from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.library import IndexedMedia, MediaAsset, MediaLocation
from channelos.models import ChannelDefinition
from channelos.resolve import ResolvedChannel
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
from channelos.television import TelevisionSession

UTC = timezone.utc


class FakeBackend:
    def __init__(self) -> None:
        self.loaded: Path | None = None
        self.position = 0.0
        self.events: list[str] = []

    def load(self, path):
        self.loaded = Path(path)
        self.events.append("load")

    def play(self):
        self.events.append("play")

    def pause(self):
        self.events.append("pause")

    def stop(self):
        self.events.append("stop")

    def seek(self, seconds):
        self.position = float(seconds)
        self.events.append("seek")

    def get_position(self):
        return self.position

    def set_volume(self, percent):
        return None

    def get_volume(self):
        return 50

    def set_muted(self, muted):
        return None

    def get_muted(self):
        return False

    def set_rate(self, rate):
        return None


def make_resolved(tmp_path: Path, number: int, durations: list[float]) -> ResolvedChannel:
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


def make_session(tmp_path: Path, epoch: datetime) -> tuple[TelevisionSession, FakeBackend]:
    store = RuntimeStore(tmp_path / "runtime.db")
    channel_7 = ChannelRuntime.open(
        make_resolved(tmp_path, 7, [30.0, 30.0]),
        store,
        now=epoch,
    )
    channel_12 = ChannelRuntime.open(
        make_resolved(tmp_path, 12, [20.0, 20.0, 20.0]),
        store,
        now=epoch,
    )
    backend = FakeBackend()
    return TelevisionSession(TelevisionRuntime((channel_7, channel_12), store), backend), backend


def test_tune_intent_loads_broadcast_asset_and_seeks_to_live_offset(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    result = session.execute("TUNE 007", now=epoch + timedelta(seconds=42))

    assert "Channel 007" in result
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(12.0)
    assert backend.events == ["load", "play", "seek"]


def test_channel_up_and_previous_follow_independent_broadcast_clocks(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    session.execute("TUNE 007", now=epoch)
    session.execute("CHANNEL_UP", now=epoch + timedelta(seconds=25))

    assert backend.loaded == tmp_path / "12" / "01.mp4"
    assert backend.position == pytest.approx(5.0)

    result = session.execute("PREVIOUS_CHANNEL", now=epoch + timedelta(seconds=50))
    assert "Channel 007" in result
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(20.0)


def test_pause_skip_and_go_live_keep_viewer_clock_authoritative(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    session.execute("TUNE 007", now=epoch)
    session.execute("PAUSE", now=epoch + timedelta(seconds=10))
    paused_event_count = len(backend.events)

    session.execute("SKIP_BACK 5", now=epoch + timedelta(seconds=20))
    assert backend.position == pytest.approx(5.0)
    assert backend.events[-1] == "pause"
    assert len(backend.events) > paused_event_count

    result = session.execute("GO_LIVE", now=epoch + timedelta(seconds=50))
    assert "LIVE" in result
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(20.0)


def test_resume_tuning_uses_saved_viewer_position(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    session, backend = make_session(tmp_path, epoch)

    session.tune(7, now=epoch)
    session.tune(12, now=epoch + timedelta(seconds=20))
    decision = session.tune(7, now=epoch + timedelta(seconds=50), return_behavior="resume")

    assert decision.lag_seconds == pytest.approx(30.0)
    assert backend.loaded == tmp_path / "7" / "00.mp4"
    assert backend.position == pytest.approx(20.0)
