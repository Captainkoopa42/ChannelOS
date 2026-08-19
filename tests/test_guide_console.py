from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.guide import GuideError, GuideService
from channelos.guide_console import GuideConsole
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


def make_console(tmp_path: Path, epoch: datetime) -> tuple[GuideConsole, FakeBackend]:
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime_7 = ChannelRuntime.open(make_resolved(tmp_path, 7, (30.0, 30.0)), store, now=epoch)
    runtime_12 = ChannelRuntime.open(make_resolved(tmp_path, 12, (20.0, 20.0, 20.0)), store, now=epoch)
    runtimes = (runtime_7, runtime_12)
    backend = FakeBackend()
    television = TelevisionSession(TelevisionRuntime(runtimes, store), backend)
    return (
        GuideConsole(
            GuideService(runtimes),
            television,
            lookback_seconds=45.0,
            horizon_seconds=90.0,
        ),
        backend,
    )


def _index_for(snapshot, *, channel: int, state: str) -> int:
    for index, program in enumerate(snapshot.programs):
        if program.channel_number != channel:
            continue
        if state == "now" and program.is_current:
            return index
        if state == "past" and program.is_past:
            return index
    raise AssertionError(f"no {state} program for channel {channel}")


def test_refresh_renders_selectable_past_now_and_future_entries(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    console, _ = make_console(tmp_path, epoch)
    reference = epoch + timedelta(seconds=42)

    snapshot = console.refresh(at=reference)
    rendered = console.render(snapshot)

    assert "[PAST" in rendered
    assert "[NOW" in rendered
    assert "[NEXT" in rendered
    assert "CH 007" in rendered
    assert "CH 012" in rendered
    assert rendered.index("CH 007") < rendered.index("CH 012")


def test_tune_selected_now_entry_routes_to_live_channel_playback(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    console, backend = make_console(tmp_path, epoch)
    reference = epoch + timedelta(seconds=42)
    snapshot = console.refresh(at=reference)
    index = _index_for(snapshot, channel=7, state="now")

    result = console.execute(f"TUNE {index}", at=reference)

    assert "Channel 007" in result
    assert "LIVE" in result
    assert backend.loaded == tmp_path / "7" / "01.mp4"
    assert backend.position == pytest.approx(12.0)


def test_tune_ch_resolves_current_guide_entry_at_command_time(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    console, backend = make_console(tmp_path, epoch)
    reference = epoch + timedelta(seconds=42)

    result = console.execute("TUNE CH 012", at=reference)

    assert "Channel 012" in result
    assert "LIVE" in result
    assert backend.loaded == tmp_path / "12" / "02.mp4"
    assert backend.position == pytest.approx(2.0)


def test_begin_selected_past_entry_starts_exact_scheduled_occurrence_at_zero(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    console, backend = make_console(tmp_path, epoch)
    reference = epoch + timedelta(seconds=42)
    snapshot = console.refresh(at=reference)
    index = next(
        index
        for index, program in enumerate(snapshot.programs)
        if program.channel_number == 7 and program.start_utc == epoch
    )

    result = console.execute(f"BEGIN {index}", at=reference)

    assert snapshot.programs[index].is_past
    assert "Channel 007" in result
    assert backend.loaded == tmp_path / "7" / "00.mp4"
    assert backend.position == pytest.approx(0.0)
    assert "-42.0s" in result


def test_console_rejects_bad_selection_index_and_future_tune(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    console, _ = make_console(tmp_path, epoch)
    reference = epoch + timedelta(seconds=42)
    snapshot = console.refresh(at=reference)

    with pytest.raises(GuideError, match="out of range"):
        console.execute("BEGIN 999", at=reference)

    future_index = next(
        index
        for index, program in enumerate(snapshot.programs)
        if program.channel_number == 7 and program.is_future
    )
    with pytest.raises(GuideError, match="currently airing"):
        console.execute(f"TUNE {future_index}", at=reference)
