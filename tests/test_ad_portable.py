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
    assert after.offset_seconds == pytest.approx(28.0)
    restarted = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / "runtime.sqlite"), now=epoch)
    again = restarted.broadcast_at(epoch + timedelta(seconds=23))
    assert again.media.asset.asset_id == inside.media.asset.asset_id
    assert again.offset_seconds == pytest.approx(inside.offset_seconds)
    assert restarted.broadcast_at(epoch + timedelta(seconds=38)).offset_seconds == pytest.approx(28.0)


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
