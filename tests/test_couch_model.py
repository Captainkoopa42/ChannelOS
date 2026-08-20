from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.couch_model import build_couch_snapshot
from channelos.guide import GuideService
from channelos.library import IndexedMedia, MediaAsset, MediaLocation
from channelos.models import ChannelDefinition
from channelos.resolve import ResolvedChannel
from channelos.runtime import ChannelRuntime, RuntimeStore

UTC = timezone.utc


def make_resolved(tmp_path: Path, number: int, durations: tuple[float, ...]) -> ResolvedChannel:
    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": number,
            "name": f"Channel {number}",
            "sources": [{"path": str(tmp_path / str(number))}],
            "programming": {"mode": "sequential"},
            "presentation": {"number_width": 3},
        }
    )
    media: list[IndexedMedia] = []
    for index, duration in enumerate(durations):
        path = tmp_path / str(number) / f"{index:02d}.mp4"
        asset = MediaAsset(
            asset_id=f"sha256:{number}-{index}",
            content_sha256=f"{number}-{index}",
            size_bytes=1,
            duration_seconds=duration,
            container_format="mp4",
        )
        location = MediaLocation(
            path=path,
            path_key=str(path),
            asset_id=asset.asset_id,
            source_root=path.parent,
            online=True,
        )
        media.append(IndexedMedia(asset, location))
    return ResolvedChannel(definition, tuple(media))


def make_service(tmp_path: Path, epoch: datetime) -> GuideService:
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime_12 = ChannelRuntime.open(make_resolved(tmp_path, 12, (1200.0, 1200.0)), store, now=epoch)
    runtime_7 = ChannelRuntime.open(make_resolved(tmp_path, 7, (1800.0, 1800.0)), store, now=epoch)
    return GuideService((runtime_12, runtime_7))


def test_couch_snapshot_is_three_hour_half_hour_aligned_numeric_guide(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    reference = epoch + timedelta(minutes=7, seconds=15)
    snapshot = build_couch_snapshot(make_service(tmp_path, epoch), at=reference)

    assert snapshot["generatedAtMs"] == int(reference.timestamp() * 1000)
    assert snapshot["horizonStartMs"] == int(epoch.timestamp() * 1000)
    assert snapshot["horizonEndMs"] == int((epoch + timedelta(hours=3)).timestamp() * 1000)

    rows = snapshot["rows"]
    assert [row["channelNumber"] for row in rows] == [7, 12]
    assert [row["displayNumber"] for row in rows] == ["007", "012"]


def test_couch_snapshot_preserves_authoritative_current_program(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    reference = epoch + timedelta(minutes=7)
    snapshot = build_couch_snapshot(make_service(tmp_path, epoch), at=reference)

    channel_7 = snapshot["rows"][0]
    current = next(program for program in channel_7["programs"] if program["isCurrent"])

    assert current["title"] == "00"
    assert current["startMs"] == int(epoch.timestamp() * 1000)
    assert current["endMs"] == int((epoch + timedelta(minutes=30)).timestamp() * 1000)
    assert current["isPast"] is False
    assert current["isFuture"] is False


def test_couch_snapshot_rejects_non_positive_horizon(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    service = make_service(tmp_path, epoch)

    with pytest.raises(ValueError, match="guide_hours must be greater than zero"):
        build_couch_snapshot(service, at=epoch, guide_hours=0)


def test_couch_qml_asset_is_present() -> None:
    qml = Path(__file__).resolve().parents[1] / "src" / "channelos" / "qml" / "Main.qml"

    assert qml.is_file()
    text = qml.read_text(encoding="utf-8")
    assert "UNASSIGNED" in text
    assert "GUIDE" in text
    assert "WindowContainer" in text
    assert "channelOSVideoWindow" in text
