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
