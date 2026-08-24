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
    assert [row["channelNumber"] for row in rows] == [1, 7, 12]
    assert [row["displayNumber"] for row in rows] == ["001", "007", "012"]

    reserved = rows[0]
    assert reserved["channelName"] == "ChannelOS"
    assert reserved["isUnassigned"] is True
    assert reserved["programs"][0]["title"] == "UNASSIGNED"
    assert reserved["programs"][0]["isUnassigned"] is True
    assert reserved["displaySegments"][0]["title"] == "NO PROGRAMMING"


def test_couch_snapshot_preserves_authoritative_current_program(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    reference = epoch + timedelta(minutes=7)
    snapshot = build_couch_snapshot(make_service(tmp_path, epoch), at=reference)

    channel_7 = next(
        row for row in snapshot["rows"]
        if row["channelNumber"] == 7
    )
    current = next(program for program in channel_7["programs"] if program["isCurrent"])

    assert current["title"] == "00"
    assert current["startMs"] == int(epoch.timestamp() * 1000)
    assert current["endMs"] == int((epoch + timedelta(minutes=30)).timestamp() * 1000)
    assert current["isPast"] is False
    assert current["isFuture"] is False



def test_real_channel_001_replaces_reserved_static_slot(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    store = RuntimeStore(tmp_path / "channel-001-runtime.db")
    runtime_1 = ChannelRuntime.open(
        make_resolved(tmp_path, 1, (1800.0, 1800.0)),
        store,
        now=epoch,
    )
    runtime_7 = ChannelRuntime.open(
        make_resolved(tmp_path, 7, (1800.0, 1800.0)),
        store,
        now=epoch,
    )

    snapshot = build_couch_snapshot(
        GuideService((runtime_1, runtime_7)),
        at=epoch + timedelta(minutes=5),
    )

    channel_1_rows = [
        row for row in snapshot["rows"]
        if row["channelNumber"] == 1
    ]
    assert len(channel_1_rows) == 1
    assert channel_1_rows[0]["channelName"] == "Channel 1"
    assert channel_1_rows[0]["isUnassigned"] is False
    assert channel_1_rows[0]["programs"][0]["isUnassigned"] is False


def test_short_form_guide_segments_compress_visual_density_without_losing_programs(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    store = RuntimeStore(tmp_path / "short-runtime.db")

    runtime = ChannelRuntime.open(
        make_resolved(tmp_path, 55, (30.0, 30.0, 30.0)),
        store,
        now=epoch,
    )

    service = GuideService((runtime,))

    snapshot = build_couch_snapshot(
        service,
        at=epoch + timedelta(seconds=5),
        guide_hours=0.5,
    )

    row = next(
        row for row in snapshot["rows"]
        if row["channelNumber"] == 55
    )
    programs = row["programs"]
    segments = row["displaySegments"]

    # Exact schedule remains untouched.
    assert len(programs) == 60

    # Presentation is substantially less dense.
    assert len(segments) < len(programs)
    assert sum(segment["programCount"] for segment in segments) == len(programs)

    assert segments[0]["isCluster"] is True
    assert segments[0]["firstProgramIndex"] == 0
    assert segments[0]["startMs"] == programs[0]["startMs"]

    # Every exact program is still represented by a selectable segment.
    for index, program in enumerate(programs):
        assert any(
            segment["firstProgramIndex"] <= index <= segment["lastProgramIndex"]
            for segment in segments
        )

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
    assert "guideStaticCanvas" in text
    assert 'root.homeTelevision.mode === "static"' in text
    assert "STATIC / NO PROGRAMMING" in text
    assert "WATCHING" in text
    assert "homeVideoSlot" in text
    assert "guideVideoSlot" in text
    assert "guidePreviewPanel" in text
    assert "homeLeft.width + 24" in text
    assert "guideScreen.x + guideHeader.x" in text
    assert "homePreview.width - 12" in text
    assert "id: liveVideoHost" not in text
    assert "anchors.right: guidePreviewPanel.left" in text
    assert 'root.screen === "guide" && Boolean(root.playback.active)' in text
    assert 'root.homeTelevision.mode !== "static"' in text
    assert 'root.screen === "home"' in text
    assert "readonly property bool showHomePreview" in text
    assert "readonly property bool showGuidePreview" in text
    assert "anchors.fill: parent" in text
    assert "id: liveVideoContainer" in text
    assert "readonly property bool homePreview:" not in text
    assert "WATCHING CH " in text
    assert "GUIDE" in text
    assert "WindowContainer" in text
    assert "channelOSVideoWindow" in text
    # Production HUD architecture: preserve the original video container,
    # keep native overlays bounded, and never recreate the full-screen native
    # HUD sibling that broke Windows maximize/restore presentation.
    assert "Windows-safe television HUD architecture" in text
    assert "liveVideoContainer" in text
    assert "liveClockContainer" in text
    assert "bottomHudOverlay" in text
    assert "bottomHudContainer" not in text
    assert "bottomHudMode" in text
    assert 'hudMode === "live"' in text
    assert 'hudMode === "ondemand"' in text
    assert 'property bool liveHudVisible: false' in text
    assert 'root.bottomHudMode !== "live"' in text
    assert 'root.screen === "live" && root.liveHudVisible' in text
    assert "channelEntryContainer" in text
    assert "audioHudContainer" in text
    assert "liveHudContainer" not in text
    assert "channelOS ? channelOS.playback" in text
    assert "channelOS ? channelOS.onDemand" in text
    assert "BEHIND LIVE" in text
    assert "NEXT" in text
    assert "Broadcast Clock" in text
    assert "displaySegments" in text
    assert "modelData.isCluster" in text
    assert 'modelData.programCount + " clips"' in text
    assert "LIBRARY / ON DEMAND" in text
    assert "PLAY ON DEMAND" in text
    assert "ADD MEDIA FOLDER" in text
    assert "libraryItems" in text

    couch_qt = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "channelos"
        / "couch_qt.py"
    ).read_text(encoding="utf-8")
    assert "QTimer.singleShot(10000, hide)" in couch_qt
    assert 'setProperty("liveHudVisible", False)' in couch_qt
    assert "Channel 001 is unassigned" in couch_qt
    assert "_select_guide_anchor" in couch_qt
    assert "_build_home_television_view" in couch_qt
    assert 'view["mode"] = "current"' in couch_qt
    assert '"mode": "static"' in couch_qt
    assert '"mode"] = "previous"' in couch_qt
    assert "def continueWatching" in couch_qt
    assert "def startHomePlayback" in couch_qt
    assert "NativeWindowStartupGate" in couch_qt
    assert "def _start_home_video_when_ready" in couch_qt
    assert "sample_native_windows" in couch_qt
    assert "attach_surface_and_start_home" in couch_qt
    assert "int(video_window.winId())" in couch_qt
    assert "QTimer.singleShot(500, controller.startHomePlayback)" not in couch_qt
    assert "not self._surface_ready" in couch_qt
    assert "continue_watching(default_channel=1)" in couch_qt
    assert "Continue Watching will connect" not in couch_qt
    assert "continueLabel" in text

    couch_model = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "channelos"
        / "couch_model.py"
    ).read_text(encoding="utf-8")
    assert "RESERVED_DEFAULT_CHANNEL = 1" in couch_model
    assert "channelos:unassigned:001" in couch_model
    assert "_unassigned_default_row" in couch_model


def test_active_couch_launcher_uses_home_video_startup_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    couch_entrypoint = (root / "src" / "channelos" / "couch.py").read_text(
        encoding="utf-8"
    )
    broadcaster_qt = (
        root / "src" / "channelos" / "broadcaster_qt.py"
    ).read_text(encoding="utf-8")

    assert "from .broadcaster_qt import run_qt" in couch_entrypoint
    assert "_start_home_video_when_ready" in broadcaster_qt
    assert "window._channelos_home_startup_gate" in broadcaster_qt
    assert broadcaster_qt.index("window.showFullScreen()") < broadcaster_qt.index(
        "window._channelos_home_startup_gate"
    )
