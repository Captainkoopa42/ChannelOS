from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.guide import GuideController, GuideError, GuideService
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


def make_resolved(tmp_path: Path) -> ResolvedChannel:
    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": 7,
            "name": "Channel 7",
            "sources": [{"path": str(tmp_path / "7")}],
            "programming": {"mode": "sequential"},
            "presentation": {"number_width": 3},
        }
    )

    media: list[IndexedMedia] = []
    for index in range(2):
        path = tmp_path / "7" / f"{index:02d}.mp4"
        asset = MediaAsset(
            asset_id=f"sha256:7-{index}",
            content_sha256=f"7-{index}",
            size_bytes=1,
            duration_seconds=30.0,
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


def make_controller(
    tmp_path: Path,
    epoch: datetime,
) -> tuple[GuideController, GuideService, FakeBackend]:
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime = ChannelRuntime.open(make_resolved(tmp_path), store, now=epoch)
    service = GuideService((runtime,))
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((runtime,), store), backend)
    return GuideController(service, session), service, backend


def guide_programs(service: GuideService, epoch: datetime):
    generated_at = epoch + timedelta(seconds=45)
    horizon = service.horizon(
        epoch,
        epoch + timedelta(seconds=90),
        generated_at=generated_at,
    )
    programs = horizon.rows[0].programs
    assert len(programs) == 3
    return programs


def test_tune_from_guide_routes_current_program_through_television_session(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    controller, service, backend = make_controller(tmp_path, epoch)
    _, current, _ = guide_programs(service, epoch)

    decision = controller.tune(current, at=epoch + timedelta(seconds=45))

    assert decision.is_live
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(15.0)
    assert backend.events == ["load", "play", "seek"]


def test_tune_from_guide_rejects_program_that_is_not_current(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    controller, service, backend = make_controller(tmp_path, epoch)
    _, _, future = guide_programs(service, epoch)

    with pytest.raises(GuideError, match="currently airing"):
        controller.tune(future, at=epoch + timedelta(seconds=45))

    assert backend.events == []


def test_watch_from_beginning_starts_current_program_at_offset_zero(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    controller, service, backend = make_controller(tmp_path, epoch)
    _, current, _ = guide_programs(service, epoch)

    decision = controller.watch_from_beginning(current, at=epoch + timedelta(seconds=45))

    assert decision.viewer_time_utc == current.start_utc
    assert decision.lag_seconds == pytest.approx(15.0)
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(0.0)
    assert backend.events == ["load", "play", "seek"]


def test_watch_from_beginning_can_reconstruct_a_past_scheduled_program(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    controller, service, backend = make_controller(tmp_path, epoch)
    past, _, _ = guide_programs(service, epoch)

    decision = controller.watch_from_beginning(past, at=epoch + timedelta(seconds=45))

    assert decision.viewer_time_utc == past.start_utc
    assert decision.lag_seconds == pytest.approx(45.0)
    assert backend.loaded == tmp_path / "7" / "00.mp4"
    assert backend.position == pytest.approx(0.0)


def test_guide_actions_reject_stale_or_future_occurrences(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    controller, service, backend = make_controller(tmp_path, epoch)
    _, current, future = guide_programs(service, epoch)

    stale = replace(current, schedule_id="stale-schedule-id")
    with pytest.raises(GuideError, match="stale"):
        controller.tune(stale, at=epoch + timedelta(seconds=45))

    with pytest.raises(GuideError, match="before the scheduled program has started"):
        controller.watch_from_beginning(future, at=epoch + timedelta(seconds=45))

    assert backend.events == []
