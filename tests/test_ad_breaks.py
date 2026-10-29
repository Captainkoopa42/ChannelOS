from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from channelos.ad_breaks import plan_ad_break
from channelos.library import IndexedMedia, MediaAsset, MediaLocation


def media_item(tmp_path: Path, name: str, duration: float) -> IndexedMedia:
    path = tmp_path / name
    payload = name.encode("utf-8")
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    asset = MediaAsset(
        asset_id=f"sha256:{digest}",
        content_sha256=digest,
        size_bytes=len(payload),
        duration_seconds=duration,
        container_format="mp4",
    )
    location = MediaLocation(
        path=path,
        path_key=str(path),
        asset_id=asset.asset_id,
        source_root=tmp_path,
        online=True,
    )
    return IndexedMedia(asset=asset, location=location)


def test_best_fit_packs_largest_ads_that_fit_without_overrun(tmp_path: Path) -> None:
    ads = (
        media_item(tmp_path, "90.mp4", 90),
        media_item(tmp_path, "60.mp4", 60),
        media_item(tmp_path, "30.mp4", 30),
        media_item(tmp_path, "45.mp4", 45),
    )

    plan = plan_ad_break(ads, 180, strategy="best_fit", seed="gap-1")

    assert sum(segment.duration_seconds for segment in plan) == pytest.approx(180)
    assert sorted(segment.duration_seconds for segment in plan) == [30, 60, 90]
    assert len({segment.media.asset.asset_id for segment in plan}) == len(plan)


def test_plan_is_repeatable_for_same_seed_and_changes_by_opportunity(tmp_path: Path) -> None:
    ads = tuple(media_item(tmp_path, f"{index}.mp4", 10) for index in range(8))

    first = plan_ad_break(ads, 30, strategy="sequential", seed="channel-7-gap-a")
    replay = plan_ad_break(ads, 30, strategy="sequential", seed="channel-7-gap-a")
    another = plan_ad_break(ads, 30, strategy="sequential", seed="channel-7-gap-b")

    first_ids = [item.media.asset.asset_id for item in first]
    assert first_ids == [item.media.asset.asset_id for item in replay]
    assert first_ids != [item.media.asset.asset_id for item in another]


def test_smallest_strategy_prefers_short_ads(tmp_path: Path) -> None:
    ads = (
        media_item(tmp_path, "60.mp4", 60),
        media_item(tmp_path, "15.mp4", 15),
        media_item(tmp_path, "30.mp4", 30),
    )

    plan = plan_ad_break(ads, 45, strategy="smallest", seed="small")

    assert [item.duration_seconds for item in plan] == [15, 30]


def test_too_short_gap_returns_empty_plan_and_never_trims_ads(tmp_path: Path) -> None:
    ads = (media_item(tmp_path, "ad.mp4", 30),)

    assert plan_ad_break(ads, 12, strategy="best_fit") == ()


def test_invalid_strategy_is_rejected(tmp_path: Path) -> None:
    ads = (media_item(tmp_path, "ad.mp4", 30),)

    with pytest.raises(ValueError, match="unsupported ad selection strategy"):
        plan_ad_break(ads, 30, strategy="magic")


def test_calendar_runtime_plays_ads_in_gap_then_returns_to_next_fixed_program(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timedelta, timezone

    from channelos.library import MediaLibrary
    from channelos.models import ChannelDefinition
    from channelos.probe import MediaProbeResult
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore

    program_root = tmp_path / "programs"
    ad_root = tmp_path / "ads"
    program_root.mkdir()
    ad_root.mkdir()
    library = MediaLibrary(tmp_path / "library.db")

    def add(root: Path, name: str, duration: float):
        path = root / name
        payload = f"{root.name}:{name}".encode("utf-8")
        path.write_bytes(payload)
        library.upsert_file(
            path,
            root,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            probe=MediaProbeResult(
                duration_seconds=duration,
                container_format="mp4",
            ),
        )
        return path

    add(program_root, "show-one.mp4", 60)
    add(program_root, "show-two.mp4", 60)
    add(ad_root, "ad-90.mp4", 90)
    add(ad_root, "ad-60.mp4", 60)
    add(ad_root, "ad-30.mp4", 30)

    programs = library.list_online_media_for_source(program_root)
    start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.4",
            "channel": 7,
            "name": "Ad Test",
            "sources": [{"path": str(program_root)}],
            "programming": {
                "mode": "calendar",
                "calendar": [
                    {
                        "start_utc": start.isoformat(),
                        "asset_id": programs[0].asset.asset_id,
                    },
                    {
                        "start_utc": (start + timedelta(seconds=240)).isoformat(),
                        "asset_id": programs[1].asset.asset_id,
                    },
                ],
            },
            "advertising": {
                "enabled": True,
                "sources": [{"path": str(ad_root)}],
                "selection_strategy": "best_fit",
            },
        }
    )
    resolved = resolve_channel(definition, library)

    # Ads are indexed by the same library but are not ordinary channel programs.
    assert len(resolved.media) == 2
    assert len(resolved.ad_media) == 3

    runtime = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime.db"),
        now=start,
    )
    first_ad = runtime.broadcast_at(start + timedelta(seconds=70))
    second_ad = runtime.broadcast_at(start + timedelta(seconds=155))
    third_ad = runtime.broadcast_at(start + timedelta(seconds=215))
    next_program = runtime.broadcast_at(start + timedelta(seconds=240))

    assert first_ad.origin == "advertisement"
    assert first_ad.media.location.path.name == "ad-90.mp4"
    assert first_ad.offset_seconds == pytest.approx(10)
    assert second_ad.origin == "advertisement"
    assert second_ad.media.location.path.name == "ad-60.mp4"
    assert second_ad.offset_seconds == pytest.approx(5)
    assert third_ad.origin == "advertisement"
    assert third_ad.media.location.path.name == "ad-30.mp4"
    assert third_ad.offset_seconds == pytest.approx(5)
    assert next_program.origin == "calendar"
    assert next_program.media.location.path.name == "show-two.mp4"
    assert next_program.offset_seconds == pytest.approx(0)


def test_legacy_channel_schema_defaults_to_no_advertising() -> None:
    from channelos.models import ChannelDefinition

    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": 7,
            "name": "Legacy",
            "sources": [{"path": "/media/programs"}],
            "programming": {"mode": "sequential"},
        }
    )

    assert definition.advertising.enabled is False
    assert definition.advertising.sources == ()
    assert definition.advertising.selection_strategy == "best_fit"
