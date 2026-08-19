from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.couch_actions import CouchActions
from channelos.guide import GuideError, GuideService
from channelos.library import IndexedMedia, MediaAsset, MediaLocation
from channelos.models import ChannelDefinition
from channelos.playback import NativeVideoSurface
from channelos.resolve import ResolvedChannel
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime

UTC = timezone.utc


class FakeBackend:
    def __init__(self) -> None:
        self.surface: NativeVideoSurface | None = None
        self.loaded: Path | None = None
        self.position = 0.0
        self.events: list[str] = []

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self.surface = surface
        self.events.append("surface")

    def load(self, path) -> None:
        self.loaded = Path(path)
        self.events.append("load")

    def play(self) -> None:
        self.events.append("play")

    def pause(self) -> None:
        self.events.append("pause")

    def stop(self) -> None:
        self.events.append("stop")

    def seek(self, seconds: float) -> None:
        self.position = float(seconds)
        self.events.append("seek")

    def get_position(self) -> float:
        return self.position

    def set_volume(self, percent: int) -> None:
        return None

    def get_volume(self) -> int:
        return 50

    def set_muted(self, muted: bool) -> None:
        return None

    def get_muted(self) -> bool:
        return False

    def set_rate(self, rate: float) -> None:
        return None


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


def make_actions(tmp_path: Path, epoch: datetime) -> tuple[CouchActions, GuideService, FakeBackend]:
    store = RuntimeStore(tmp_path / "runtime.db")
    runtimes = (
        ChannelRuntime.open(make_resolved(tmp_path, 7, (30.0, 30.0)), store, now=epoch),
        ChannelRuntime.open(make_resolved(tmp_path, 12, (20.0, 20.0, 20.0)), store, now=epoch),
    )
    service = GuideService(runtimes)
    television = TelevisionRuntime(runtimes, store)
    backend = FakeBackend()
    actions = CouchActions(service, television, backend_factory=lambda: backend)
    return actions, service, backend


def test_current_guide_selection_attaches_surface_and_tunes(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    now = epoch + timedelta(seconds=5)
    actions, service, backend = make_actions(tmp_path, epoch)
    program = service.now_next(7, at=now).now
    surface = NativeVideoSurface("windows", 4242)

    actions.attach_video_surface(surface)
    decision = actions.activate_program(
        program.schedule_id,
        program.channel_number,
        program.start_utc.timestamp() * 1000,
        at=now,
    )

    assert decision.channel_number == 7
    assert decision.is_live
    assert backend.surface == surface
    assert backend.loaded == program.start_utc and False  # type guard; replaced below
