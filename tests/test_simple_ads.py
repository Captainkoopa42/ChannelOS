from datetime import datetime, timedelta, timezone

import pytest

from channelos.broadcaster import BroadcasterService, definition_from_editor, channel_to_mapping
from channelos.models import ChannelDefinition
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore
from test_ad_portable import indexed
from test_broadcaster import editor

START = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def setup(tmp_path, mode="after_show", order="sequential"):
    library, programs, ads = indexed(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    raw = editor(7, programs)
    raw.update(adBreaksEnabled=True, adSources=[str(ads)], adConfigVersion="0.6",
               adSetupMode=mode, adPlayOrder=order, adClockIntervalSeconds=120)
    return library, service, raw


@pytest.mark.parametrize("order", ["sequential", "shuffle"])
def test_one_whole_ad_between_shows_rotation_survives_restart(tmp_path, order):
    library, _, raw = setup(tmp_path, order=order)
    resolved = resolve_channel(definition_from_editor(raw), library)
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = ChannelRuntime.open(resolved, store, now=START)
    events = runtime.events_between(START, START + timedelta(seconds=450))
    ads = [event for event in events if event.event_type == "advertisement"]
    assert [event.event_type for event in events[:6]] == ["program", "advertisement"] * 3
    assert len({event.asset_id for event in ads[:2]}) == 2
    assert all(first.asset_id != second.asset_id for first, second in zip(ads, ads[1:]))
    assert {(event.end_utc-event.start_utc).total_seconds() for event in ads} == {10, 15}
    runtime.break_store.close()
    reopened = ChannelRuntime.open(resolved, store, now=START + timedelta(seconds=200))
    try:
        assert reopened.events_between(START, START + timedelta(seconds=450)) == events
    finally:
        reopened.break_store.close()


@pytest.mark.parametrize("mode", ["after_show", "timed", "aligned"])
def test_autofill_exact_ads_match_runtime_and_roundtrip(tmp_path, mode):
    library, service, raw = setup(tmp_path, mode)
    raw["mode"] = "calendar"
    result = service.auto_fill_studio(raw, START.isoformat(), (START+timedelta(seconds=600)).isoformat())
    assert result["adSlotCount"]
    assert result["blocks"][0]["adPlan"]["breaks"]
    raw["calendarBlocks"] = result["blocks"]
    definition = definition_from_editor(raw)
    assert definition.schema_version == "0.6"
    assert ChannelDefinition.from_mapping(channel_to_mapping(definition)) == definition
    runtime = ChannelRuntime.open(resolve_channel(definition, library), RuntimeStore(tmp_path / "runtime.db"), now=START)
    try:
        for block in result["blocks"]:
            for plan in block["adPlan"]["breaks"]:
                at = datetime.fromisoformat(plan["scheduled_at"])
                for segment in plan["segments"]:
                    selection = runtime.project_at(at + timedelta(seconds=segment["start_offset_seconds"]+.01))
                    assert selection.origin == segment["event_type"]
                    assert selection.media.asset.asset_id == segment["asset_id"]
            if mode == "aligned":
                assert datetime.fromisoformat(block["startUtc"]).timestamp() % 120 == 0
        assert not runtime.break_store.play_counts()
    finally:
        runtime.break_store.close()


def test_clock_breaks_use_wall_time_and_resume_exactly(tmp_path):
    from dataclasses import replace
    library, _, raw = setup(tmp_path, "timed")
    resolved = resolve_channel(definition_from_editor(raw), library)
    program = replace(resolved.media[0], asset=replace(resolved.media[0].asset, duration_seconds=300))
    resolved = replace(resolved, media=(program,))
    runtime = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / "runtime.db"), now=START)
    try:
        first = runtime.project_at(START + timedelta(seconds=120))
        assert first.origin == "advertisement"
        resume = runtime.project_at(first.program_ends_at)
        assert resume.offset_seconds == 120
        second = runtime.project_at(START + timedelta(seconds=240))
        assert second.origin == "advertisement"
        assert second.media.asset.asset_id != first.media.asset.asset_id
        assert not runtime.break_store.play_counts()
    finally:
        runtime.break_store.close()


def test_aligned_classic_channel_uses_filler_until_first_clock_mark(tmp_path):
    library, _, raw = setup(tmp_path, "aligned")
    resolved = resolve_channel(definition_from_editor(raw), library)
    begins = START + timedelta(seconds=17)
    runtime = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / "runtime.db"), now=begins)
    try:
        assert runtime.project_at(begins).origin == "filler"
        show = runtime.project_at(START + timedelta(seconds=120))
        assert show.event.event_type == "program"
        assert show.offset_seconds == 0
    finally:
        runtime.break_store.close()


def test_portable_copy_keeps_selected_clips_and_queue_state(tmp_path):
    import shutil
    from channelos.library import MediaLibrary
    from channelos.portable import load_setup
    from channelos.runtime import advertising_signature
    from test_portable_copy import copy_setup

    local = tmp_path / "local"
    local.mkdir()
    library, service, raw = setup(local)
    raw["mode"] = "calendar"
    result = service.auto_fill_studio(raw, START.isoformat(), (START+timedelta(seconds=600)).isoformat())
    raw["calendarBlocks"] = result["blocks"]
    definition = service.create(raw).record.definition
    store = RuntimeStore(local / "runtime.db")
    runtime = ChannelRuntime.open(resolve_channel(definition, library), store, now=START)
    expected = runtime.events_between(START, START+timedelta(seconds=300))
    try:
        destination = tmp_path / "drive"
        copy_setup(library, service, store, destination, copy_media=True)
        moved = tmp_path / "new-mount"
        shutil.move(destination, moved)
        paths = load_setup(moved)
        copied_library = MediaLibrary(paths.data_directory / "library.db")
        copied_service = BroadcasterService((), paths.data_directory / "channels", copied_library)
        copied = resolve_channel(copied_service.records[0].definition, copied_library)
        assert copied.definition.programming.calendar[0].ad_plan["revision"] == advertising_signature(copied)
        reopened = ChannelRuntime.open(copied, RuntimeStore(paths.data_directory / "runtime.db"), now=START)
        try:
            assert reopened.events_between(START, START+timedelta(seconds=300)) == expected
        finally:
            reopened.break_store.close()
    finally:
        runtime.break_store.close()


def test_simple_ads_reject_a_packed_fixed_schedule_before_saving(tmp_path):
    library, service, raw = setup(tmp_path)
    asset = library.list_online_media_for_source(raw["sources"][0])[0].asset.asset_id
    raw.update(mode="calendar", calendarBlocks=[
        {"assetId": asset, "startUtc": START.isoformat()},
        {"assetId": asset, "startUtc": (START+timedelta(seconds=60)).isoformat()},
    ])
    with pytest.raises(ValueError, match="complete ad|fixed show"):
        service.create(raw)
    assert not service.records
