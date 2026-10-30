from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from channelos.ad_catalog import (
    AdCatalogStore, AdCollection, BreakProfile, ChannelAdAssignment,
    export_portable_channel,
)
from channelos.ad_break_engine import BreakPlanStore
from channelos.broadcaster import channel_to_mapping
from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition, ChannelValidationError
from channelos.probe import MediaProbeResult
from channelos.resolve import ChannelResolutionError, resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, advertising_signature, schedule_signature


UTC = timezone.utc


def indexed(tmp_path):
    program_root = tmp_path / "programs"
    ad_root = tmp_path / "commercials"
    program_root.mkdir()
    ad_root.mkdir()
    library = MediaLibrary(tmp_path / "media.sqlite")

    def add(folder, name, duration):
        path = folder / name
        data = name.encode("utf-8")
        path.write_bytes(data)
        return library.upsert_file(
            path, folder,
            content_sha256=hashlib.sha256(data).hexdigest(),
            probe=MediaProbeResult(duration_seconds=duration, container_format="mp4"),
        )

    add(program_root, "show.mp4", 60.0)
    add(ad_root, "short-ad.mp4", 10.0)
    add(ad_root, "long-ad.mp4", 15.0)
    return library, program_root, ad_root


def config(program_root, ad_ids, *, number=7, mode="sequential",
           calendar=None, triggers=None, enabled=True):
    advertising = {
        "enabled": enabled, "asset_ids": list(ad_ids),
        "breakpoints_seconds": [20], "break_duration_seconds": 20,
        "selection_strategy": "best_fit",
    }
    if triggers is not None:
        advertising["triggers"] = list(triggers)
    programming = {"mode": mode}
    if calendar is not None:
        programming["calendar"] = calendar
    return ChannelDefinition.from_mapping({
        "schema_version": "0.5", "channel": number, "name": "Portable Ads",
        "sources": [{"path": str(program_root)}],
        "programming": programming, "advertising": advertising,
    })


def test_portable_catalog_export_survives_catalog_disappearance(tmp_path):
    library, root, ads = indexed(tmp_path)
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(ads))
    base = ChannelDefinition.from_mapping({
        "schema_version": "0.1", "channel": 7, "name": "TV",
        "sources": [{"path": str(root)}], "programming": {"mode": "sequential"},
    })
    store = AdCatalogStore(tmp_path / "catalog.sqlite")
    store.save_collection(AdCollection("ads", "Ads", ids))
    store.save_profile(BreakProfile("p", "Profile", {
        "enabled": True, "strategy": "smallest", "duration_seconds": 20,
        "breakpoints_seconds": [20], "timing_policy": "smoosh",
        "triggers": ["breakpoint"], "transition_behavior": "cut",
    }))
    store.assign_channel(ChannelAdAssignment(7, "ads", "p", {"priority": 5}))
    exported = export_portable_channel(base, store, library)
    assert exported.schema_version == "0.5"
    assert exported.advertising.priority == 5
    assert exported.advertising.selection_strategy == "smallest"
    assert exported.advertising.asset_ids == ids
    roundtrip = ChannelDefinition.from_mapping(channel_to_mapping(exported))
    assert roundtrip == exported
    resolved = resolve_channel(roundtrip, library)  # no catalog store required
    assert tuple(item.asset.asset_id for item in resolved.ad_media) == ids


def test_mid_program_break_and_resume_are_restart_stable(tmp_path):
    library, root, ads = indexed(tmp_path)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    resolved = resolve_channel(config(root, ids), library)
    epoch = datetime(2026, 10, 30, 12, tzinfo=UTC)
    state = RuntimeStore(tmp_path / "runtime.sqlite")
    runtime = ChannelRuntime.open(resolved, state, now=epoch)
    inside = runtime.broadcast_at(epoch + timedelta(seconds=23))
    after = runtime.broadcast_at(epoch + timedelta(seconds=38))
    assert inside.origin == "advertisement"
    assert inside.offset_seconds == pytest.approx(3.0)
    assert after.media.asset.asset_id == resolved.media[0].asset.asset_id
    assert after.offset_seconds == pytest.approx(23.0)
    restarted = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / "runtime.sqlite"), now=epoch)
    again = restarted.broadcast_at(epoch + timedelta(seconds=23))
    assert again.media.asset.asset_id == inside.media.asset.asset_id
    assert again.offset_seconds == pytest.approx(inside.offset_seconds)
    assert restarted.broadcast_at(epoch + timedelta(seconds=38)).offset_seconds == pytest.approx(23.0)


def test_calendar_gap_is_persistent_and_does_not_move_fixed_start(tmp_path):
    library, root, ads = indexed(tmp_path)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    show = library.list_online_media_for_source(root)[0]
    epoch = datetime(2026, 10, 30, 12, tzinfo=UTC)
    blocks = [
        {"asset_id": show.asset.asset_id, "start_utc": epoch.isoformat()},
        {"asset_id": show.asset.asset_id,
         "start_utc": (epoch + timedelta(seconds=90)).isoformat()},
    ]
    resolved = resolve_channel(config(root, ids, mode="calendar",
                                      calendar=blocks, triggers=["calendar_boundary"]), library)
    state = RuntimeStore(tmp_path / "runtime.sqlite")
    runtime = ChannelRuntime.open(resolved, state, now=epoch)
    during = runtime.broadcast_at(epoch + timedelta(seconds=65))
    assert during.origin == "advertisement"
    next_show = runtime.broadcast_at(epoch + timedelta(seconds=91))
    assert next_show.origin == "calendar"
    assert next_show.offset_seconds == pytest.approx(1.0)
    plans = BreakPlanStore(tmp_path / "runtime.sqlite").plans_for_channel(
        7, start=epoch, end=epoch + timedelta(seconds=100))
    assert len(plans) == 1
    restarted = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / "runtime.sqlite"), now=epoch)
    assert restarted.broadcast_at(epoch + timedelta(seconds=65)).media.asset.asset_id == during.media.asset.asset_id


def test_missing_offline_ad_asset_is_not_silently_replaced(tmp_path):
    library, root, ads = indexed(tmp_path)
    missing = config(root, ["sha256:missing"])
    with pytest.raises(ChannelResolutionError, match="missing or offline"):
        resolve_channel(missing, library)


def test_invalid_v05_assets_and_policies_fail_validation(tmp_path):
    library, root, ads = indexed(tmp_path)
    indexed_ads = library.list_online_media_for_source(ads)
    asset_id = indexed_ads[0].asset.asset_id
    original = channel_to_mapping(config(root, [asset_id]))
    original["advertising"]["asset_ids"] = [asset_id, asset_id]
    with pytest.raises(ChannelValidationError, match="duplicates"):
        ChannelDefinition.from_mapping(original)
    original["advertising"]["asset_ids"] = [asset_id]
    original["advertising"]["expand_max_seconds"] = -4
    with pytest.raises(ChannelValidationError, match="limits"):
        ChannelDefinition.from_mapping(original)


def test_policy_revisions_keep_program_schedule_signature(tmp_path):
    library, root, ads = indexed(tmp_path)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    a = resolve_channel(config(root, ids), library)
    braw = channel_to_mapping(a.definition)
    braw["advertising"]["selection_strategy"] = "smallest"
    b = resolve_channel(ChannelDefinition.from_mapping(braw), library)
    assert schedule_signature(a) == schedule_signature(b)
    assert advertising_signature(a) != advertising_signature(b)


def test_legacy_channel_has_no_ad_media_unless_enabled(tmp_path):
    library, root, ads = indexed(tmp_path)
    legacy = ChannelDefinition.from_mapping({
        "schema_version": "0.1", "channel": 8, "name": "Legacy",
        "sources": [{"path": str(root)}], "programming": {"mode": "sequential"},
    })
    assert resolve_channel(legacy, library).ad_media == ()
    disabled = config(root, ["sha256:missing"], enabled=False)
    assert resolve_channel(disabled, library).ad_media == ()


def test_dynamic_collection_follows_indexed_folder_and_snapshots_membership(tmp_path):
    library, root, ads = indexed(tmp_path)
    store = AdCatalogStore(tmp_path / "catalog.sqlite")
    store.save_collection(AdCollection(
        "dynamic", "Dynamic Ads", (), (str(ads),), (), "dynamic",
    ))
    store.save_profile(BreakProfile("standard", "Standard", {
        "enabled": True, "strategy": "least_played",
        "duration_seconds": 15, "breakpoints_seconds": [20],
    }))
    store.assign_channel(ChannelAdAssignment(7, "dynamic", "standard"))
    base = ChannelDefinition.from_mapping({
        "schema_version": "0.1", "channel": 7, "name": "TV",
        "sources": [{"path": str(root)}], "programming": {"mode": "sequential"},
    })
    first = export_portable_channel(base, store, library)
    assert len(first.advertising.asset_ids) == 2
    new_path = ads / "new-promo.mp4"
    payload = b"new-promo"
    new_path.write_bytes(payload)
    library.upsert_file(
        new_path, ads, content_sha256=hashlib.sha256(payload).hexdigest(),
        probe=MediaProbeResult(duration_seconds=8, container_format="mp4"),
    )
    updated = export_portable_channel(base, AdCatalogStore(tmp_path / "catalog.sqlite"), library)
    assert len(updated.advertising.asset_ids) == 3
    # Already applied YAML remains a stable snapshot until the next apply.
    assert len(first.advertising.asset_ids) == 2


def test_dynamic_collection_excludes_assets(tmp_path):
    library, root, ads = indexed(tmp_path)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    store = AdCatalogStore(tmp_path / "catalog.sqlite")
    store.save_collection(AdCollection(
        "x", "Exclude", (), (str(ads),), (ids[0],), "dynamic",
    ))
    store.save_profile(BreakProfile("p", "P", {"enabled": True}))
    store.assign_channel(ChannelAdAssignment(7, "x", "p"))
    resolved = store.resolve_channel(7, library)
    assert len(resolved.ad_media) == 1
    assert resolved.ad_media[0].asset_id == ids[1]


def test_broadcaster_embeds_catalog_assignment_on_apply(tmp_path):
    from channelos.broadcaster import BroadcasterService
    from channelos.loader import load_channel

    library, root, ads = indexed(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    service.save_ad_collection({
        "collectionId": "ads", "name": "Ads", "assetIds": ids,
    })
    service.save_ad_profile({
        "profileId": "p", "name": "Profile",
        "defaults": {
            "enabled": True, "strategy": "smallest",
            "breakpoints_seconds": [20], "duration_seconds": 20,
        },
    })
    service.assign_ad_profile({
        "channelNumber": 7, "collectionId": "ads", "profileId": "p",
        "overrides": {"priority": 11},
    })
    result = service.create({
        "channel": 7, "name": "Catalog TV", "sources": [str(root)],
        "mode": "sequential",
    })
    applied = load_channel(result.record.path)
    assert applied.schema_version == "0.5"
    assert applied.advertising.enabled
    assert applied.advertising.asset_ids == tuple(ids)
    assert applied.advertising.priority == 11
    assert len(resolve_channel(applied, library).ad_media) == 2


def test_editor_advanced_configuration_roundtrip(tmp_path):
    from channelos.broadcaster import definition_from_editor

    library, root, ads = indexed(tmp_path)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    definition = definition_from_editor({
        "channel": 7, "name": "Ad TV", "sources": [str(root)],
        "mode": "sequential", "adBreaksEnabled": True,
        "adAssetIds": ids, "adConfigVersion": "0.5",
        "adSelectionStrategy": "complete_rotation",
        "adBreakpointsSeconds": ["20"],
        "adBreakDurationSeconds": 25,
        "adTimingPolicy": "smoosh",
        "adSmooshMaxTrimSeconds": 10,
        "adTriggers": ["breakpoint"],
    })
    assert definition.advertising.selection_strategy == "complete_rotation"
    assert definition.advertising.smoosh_max_trim_seconds == 10
    assert ChannelDefinition.from_mapping(channel_to_mapping(definition)) == definition


def test_studio_preview_is_isolated_and_reports_ad_events(tmp_path):
    from channelos.broadcaster import BroadcasterService

    library, root, ads = indexed(tmp_path)
    service = BroadcasterService((), tmp_path / "channels", library)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    editor = {
        "channel": 9, "name": "Preview", "sources": [str(root)],
        "mode": "sequential", "adBreaksEnabled": True,
        "adConfigVersion": "0.5", "adAssetIds": ids,
        "adBreakpointsSeconds": [20], "adBreakDurationSeconds": 20,
    }
    preview = service.preview(editor)
    assert preview["ok"]
    assert preview["adPreview"]
    assert preview["adPreview"][0]["eventType"] == "advertisement"
    assert preview["adPreview"][0]["breakId"]
    # Preview never applies a channel to the live lineup.
    assert not (tmp_path / "channels").exists()



@pytest.mark.parametrize("behavior", ["fade", "hold"])
def test_unimplemented_transitions_are_rejected_before_apply(tmp_path, behavior):
    from channelos.runtime import ChannelRuntimeError

    library, root, ads = indexed(tmp_path)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    raw = channel_to_mapping(config(root, ids))
    raw["advertising"]["transition_behavior"] = behavior
    resolved = resolve_channel(ChannelDefinition.from_mapping(raw), library)
    with pytest.raises(ChannelRuntimeError, match="not supported"):
        ChannelRuntime.open(
            resolved, RuntimeStore(tmp_path / "runtime.sqlite"),
            now=datetime(2026, 10, 30, tzinfo=UTC),
        )



def test_active_calendar_ad_plan_survives_policy_revision(tmp_path):
    library, root, ads = indexed(tmp_path)
    ad_ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    show = library.list_online_media_for_source(root)[0]
    epoch = datetime(2026, 10, 30, 12, tzinfo=UTC)
    blocks = [
        {"asset_id": show.asset.asset_id, "start_utc": epoch.isoformat()},
        {"asset_id": show.asset.asset_id,
         "start_utc": (epoch + timedelta(seconds=90)).isoformat()},
    ]
    first = config(root, ad_ids, mode="calendar", calendar=blocks,
                   triggers=["calendar_boundary"])
    db_path = tmp_path / "runtime.sqlite"
    runtime = ChannelRuntime.open(resolve_channel(first, library),
                                  RuntimeStore(db_path), now=epoch)
    playing = runtime.broadcast_at(epoch + timedelta(seconds=66))
    assert playing.origin == "advertisement"
    previous_id = playing.event.break_id
    assert previous_id
    runtime.break_store.close()

    revised = channel_to_mapping(first)
    revised["advertising"]["selection_strategy"] = "smallest"
    runtime2 = ChannelRuntime.open(
        resolve_channel(ChannelDefinition.from_mapping(revised), library),
        RuntimeStore(db_path), now=epoch + timedelta(seconds=67),
    )
    unchanged = runtime2.broadcast_at(epoch + timedelta(seconds=67))
    assert unchanged.origin == "advertisement"
    assert unchanged.event.break_id == previous_id
    assert unchanged.media.asset.asset_id == playing.media.asset.asset_id
    assert runtime2.broadcast_at(epoch + timedelta(seconds=91)).origin == "calendar"
    runtime2.break_store.close()



def test_calendar_mid_program_break_resumes_content_without_moving_fixed_slot(tmp_path):
    library, root, ads = indexed(tmp_path)
    asset_ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    show = library.list_online_media_for_source(root)[0]
    epoch = datetime(2026, 10, 30, 12, tzinfo=UTC)
    blocks = [
        {"asset_id": show.asset.asset_id, "start_utc": epoch.isoformat()},
        {"asset_id": show.asset.asset_id,
         "start_utc": (epoch + timedelta(seconds=90)).isoformat()},
    ]
    raw = channel_to_mapping(config(
        root, asset_ids, mode="calendar", calendar=blocks, triggers=["breakpoint"],
    ))
    raw["advertising"]["breakpoints_seconds"] = [30]
    raw["advertising"]["break_duration_seconds"] = 10
    resolved = resolve_channel(ChannelDefinition.from_mapping(raw), library)
    state = RuntimeStore(tmp_path / "calendar-mid.db")
    runtime = ChannelRuntime.open(resolved, state, now=epoch)
    before = runtime.broadcast_at(epoch + timedelta(seconds=29))
    middle = runtime.broadcast_at(epoch + timedelta(seconds=35))
    resumed = runtime.broadcast_at(epoch + timedelta(seconds=43))
    next_fixed = runtime.broadcast_at(epoch + timedelta(seconds=91))
    assert before.origin == "calendar"
    assert before.offset_seconds == pytest.approx(29)
    assert middle.origin == "advertisement"
    assert middle.offset_seconds == pytest.approx(5)
    assert middle.event.break_id
    assert middle.event.parent_program_asset_id == show.asset.asset_id
    assert resumed.origin == "calendar"
    assert resumed.offset_seconds == pytest.approx(33)
    assert resumed.program_ends_at == epoch + timedelta(seconds=70)
    assert next_fixed.origin == "calendar"
    assert next_fixed.offset_seconds == pytest.approx(1)
    runtime.break_store.close()
    restarted = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / "calendar-mid.db"),
                                    now=epoch)
    again = restarted.broadcast_at(epoch + timedelta(seconds=35))
    assert again.event.break_id == middle.event.break_id
    assert again.media.asset.asset_id == middle.media.asset.asset_id
    restarted.break_store.close()


def test_calendar_mid_program_break_skips_when_no_slack(tmp_path):
    library, root, ads = indexed(tmp_path)
    asset_ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    show = library.list_online_media_for_source(root)[0]
    epoch = datetime(2026, 10, 30, 12, tzinfo=UTC)
    blocks = [
        {"asset_id": show.asset.asset_id, "start_utc": epoch.isoformat()},
        {"asset_id": show.asset.asset_id,
         "start_utc": (epoch + timedelta(seconds=60)).isoformat()},
    ]
    raw = channel_to_mapping(config(
        root, asset_ids, mode="calendar", calendar=blocks, triggers=["breakpoint"],
    ))
    raw["advertising"]["breakpoints_seconds"] = [30]
    raw["advertising"]["break_duration_seconds"] = 10
    resolved = resolve_channel(ChannelDefinition.from_mapping(raw), library)
    runtime = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / "no-slack.db"),
                                  now=epoch)
    assert runtime.broadcast_at(epoch + timedelta(seconds=35)).origin == "calendar"
    assert runtime.broadcast_at(epoch + timedelta(seconds=61)).origin == "calendar"
    assert runtime.broadcast_at(epoch + timedelta(seconds=61)).offset_seconds == pytest.approx(1)
    runtime.break_store.close()
