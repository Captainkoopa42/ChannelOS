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
        self.volume = 50
        self.muted = False
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
        self.volume = int(percent)

    def get_volume(self) -> int:
        return self.volume

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)

    def get_muted(self) -> bool:
        return self.muted

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
    assert backend.loaded == decision.viewer_selection.media.location.path
    assert backend.position == pytest.approx(5.0)
    assert backend.events[:4] == ["surface", "load", "play", "seek"]


def test_past_guide_selection_watches_exactly_from_beginning(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    now = epoch + timedelta(seconds=35)
    actions, service, backend = make_actions(tmp_path, epoch)
    horizon = service.horizon(epoch, now + timedelta(seconds=5), generated_at=now)
    program = next(
        program
        for row in horizon.rows
        if row.channel_number == 7
        for program in row.programs
        if program.is_past
    )

    decision = actions.activate_program(
        program.schedule_id,
        program.channel_number,
        program.start_utc.timestamp() * 1000,
        at=now,
    )

    assert decision.channel_number == 7
    assert decision.viewer_time_utc == program.start_utc
    assert decision.viewer_selection.media.asset.asset_id == program.asset_id
    assert backend.loaded == decision.viewer_selection.media.location.path
    assert backend.position == pytest.approx(0.0)
    assert not decision.is_live


def test_future_guide_selection_is_rejected_before_backend_is_created(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    now = epoch + timedelta(seconds=5)
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = ChannelRuntime.open(make_resolved(tmp_path, 7, (30.0, 30.0)), store, now=epoch)
    service = GuideService((runtime,))
    television = TelevisionRuntime((runtime,), store)
    created = 0

    def make_backend() -> FakeBackend:
        nonlocal created
        created += 1
        return FakeBackend()

    actions = CouchActions(service, television, backend_factory=make_backend)
    program = service.now_next(7, at=now).next

    with pytest.raises(GuideError, match="future Guide programs"):
        actions.activate_program(
            program.schedule_id,
            program.channel_number,
            program.start_utc.timestamp() * 1000,
            at=now,
        )

    assert created == 0


def test_transport_actions_reuse_the_same_session(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    now = epoch + timedelta(seconds=5)
    actions, service, backend = make_actions(tmp_path, epoch)
    program = service.now_next(7, at=now).now
    actions.activate_program(
        program.schedule_id,
        program.channel_number,
        program.start_utc.timestamp() * 1000,
        at=now,
    )

    paused = actions.pause(at=now + timedelta(seconds=1))
    assert actions.paused
    assert paused.channel_number == 7

    resumed = actions.play(at=now + timedelta(seconds=2))
    assert not actions.paused
    assert resumed.channel_number == 7

    live = actions.go_live(at=now + timedelta(seconds=3))
    assert live.is_live
    assert backend.events.count("load") == 1


def test_reuse_current_playback_does_not_touch_decoder_or_clock(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    actions, _, backend = make_actions(tmp_path, epoch)

    decision = actions.continue_watching(at=epoch + timedelta(seconds=5), default_channel=7)
    backend.events.clear()

    reused = actions.reuse_current_playback()

    assert reused is decision
    assert backend.events == []


def test_stale_schedule_identity_is_rejected(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    actions, _, _ = make_actions(tmp_path, epoch)

    with pytest.raises(GuideError, match="stale"):
        actions.resolve_program(
            "not-a-real-schedule-id",
            7,
            epoch.timestamp() * 1000,
            at=epoch,
        )


def test_sync_advances_decoder_at_scheduled_program_boundary(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    actions, service, backend = make_actions(tmp_path, epoch)

    first_now = epoch + timedelta(seconds=5)
    program = service.now_next(7, at=first_now).now
    actions.activate_program(
        program.schedule_id,
        program.channel_number,
        program.start_utc.timestamp() * 1000,
        at=first_now,
    )

    first_path = backend.loaded

    decision = actions.sync(at=epoch + timedelta(seconds=35))

    assert decision.channel_number == 7
    assert backend.loaded is not None
    assert backend.loaded != first_path
    assert backend.loaded.name == "01.mp4"
    assert backend.position == pytest.approx(5.0)
    assert backend.events.count("load") == 2


def test_suspend_decoder_reloads_live_media(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    now = epoch + timedelta(seconds=5)

    actions, service, backend = make_actions(
        tmp_path,
        epoch,
    )

    program = service.now_next(7, at=now).now

    actions.activate_program(
        program.schedule_id,
        program.channel_number,
        program.start_utc.timestamp() * 1000,
        at=now,
    )

    assert backend.events.count("load") == 1

    actions.suspend_decoder()

    assert backend.events[-1] == "stop"

    actions.sync(
        at=now + timedelta(seconds=2)
    )

    assert backend.events.count("load") == 2



def test_numeric_tune_previous_channel_and_audio_controls(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)
    actions, _, backend = make_actions(tmp_path, epoch)

    first = actions.tune(
        7,
        at=epoch + timedelta(seconds=2),
    )
    second = actions.tune(
        12,
        at=epoch + timedelta(seconds=3),
    )
    previous = actions.previous_channel(
        at=epoch + timedelta(seconds=4),
    )

    assert first.channel_number == 7
    assert second.channel_number == 12
    assert previous.channel_number == 7

    assert actions.set_volume(65) == 65
    assert backend.volume == 65

    assert actions.set_muted(True)
    assert backend.muted
