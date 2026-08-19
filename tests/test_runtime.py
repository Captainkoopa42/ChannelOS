from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import MediaProbeResult
from channelos.resolve import ResolvedChannel, resolve_channel
from channelos.runtime import (
    ChannelRuntime,
    ChannelRuntimeError,
    ReturnChoiceRequired,
    RuntimeStore,
    TelevisionRuntime,
)

UTC = timezone.utc


def build_resolved_channel(
    tmp_path: Path,
    durations: list[float | None],
    *,
    channel_number: int = 7,
) -> ResolvedChannel:
    media_dir = tmp_path / f"channel-{channel_number}"
    media_dir.mkdir(exist_ok=True)
    library = MediaLibrary(tmp_path / "library.db")

    for index, duration in enumerate(durations):
        path = media_dir / f"{index:02d}.mp4"
        payload = f"asset-{channel_number}-{index}".encode()
        path.write_bytes(payload)
        library.upsert_file(
            path,
            media_dir,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            probe=MediaProbeResult(
                duration_seconds=duration,
                container_format="mp4",
            ),
        )

    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": channel_number,
            "name": f"Channel {channel_number}",
            "sources": [{"path": str(media_dir)}],
            "programming": {"mode": "sequential"},
        }
    )
    return resolve_channel(definition, library)


def open_two_channel_tv(tmp_path: Path, epoch: datetime) -> TelevisionRuntime:
    channel_7 = build_resolved_channel(tmp_path, [30.0, 30.0], channel_number=7)
    channel_12 = build_resolved_channel(tmp_path, [20.0, 20.0, 20.0], channel_number=12)
    store = RuntimeStore(tmp_path / "runtime.db")
    runtime_7 = ChannelRuntime.open(channel_7, store, now=epoch)
    runtime_12 = ChannelRuntime.open(channel_12, store, now=epoch)
    return TelevisionRuntime((runtime_7, runtime_12), store)


def test_broadcast_clock_selects_program_and_seek_offset(tmp_path: Path) -> None:
    resolved = build_resolved_channel(tmp_path, [30.0, 45.0, 60.0])
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime.db"),
        now=epoch,
    )

    selection = runtime.broadcast_at(epoch + timedelta(seconds=42))

    assert selection.media.location.path.name == "01.mp4"
    assert selection.offset_seconds == pytest.approx(12.0)
    assert selection.program_started_at == epoch + timedelta(seconds=30)
    assert selection.program_ends_at == epoch + timedelta(seconds=75)
    assert selection.cycle_index == 0


def test_broadcast_clock_advances_without_playing_and_wraps(tmp_path: Path) -> None:
    resolved = build_resolved_channel(tmp_path, [30.0, 45.0, 60.0])
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime.db"),
        now=epoch,
    )

    selection = runtime.broadcast_at(epoch + timedelta(seconds=140))

    assert selection.media.location.path.name == "00.mp4"
    assert selection.offset_seconds == pytest.approx(5.0)
    assert selection.cycle_index == 1


def test_broadcast_clock_is_defined_before_epoch_too(tmp_path: Path) -> None:
    resolved = build_resolved_channel(tmp_path, [30.0, 45.0, 60.0])
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime.db"),
        now=epoch,
    )

    selection = runtime.broadcast_at(epoch - timedelta(seconds=5))

    assert selection.media.location.path.name == "02.mp4"
    assert selection.offset_seconds == pytest.approx(55.0)
    assert selection.cycle_index == -1


def test_channel_epoch_survives_runtime_restart(tmp_path: Path) -> None:
    resolved = build_resolved_channel(tmp_path, [30.0, 45.0])
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    state_path = tmp_path / "runtime.db"

    first = ChannelRuntime.open(resolved, RuntimeStore(state_path), now=epoch)
    restarted = ChannelRuntime.open(
        resolved,
        RuntimeStore(state_path),
        now=epoch + timedelta(days=3),
    )

    assert first.epoch_utc == epoch
    assert restarted.epoch_utc == epoch
    assert restarted.signature == first.signature


def test_schedule_change_creates_new_epoch(tmp_path: Path) -> None:
    resolved = build_resolved_channel(tmp_path, [30.0, 45.0, 60.0])
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    changed_at = epoch + timedelta(hours=2)
    store = RuntimeStore(tmp_path / "runtime.db")

    first = ChannelRuntime.open(resolved, store, now=epoch)
    changed = ResolvedChannel(
        definition=resolved.definition,
        media=resolved.media[:-1],
    )
    second = ChannelRuntime.open(changed, store, now=changed_at)

    assert second.signature != first.signature
    assert second.epoch_utc == changed_at


def test_runtime_refuses_unknown_media_duration(tmp_path: Path) -> None:
    resolved = build_resolved_channel(tmp_path, [30.0, None])

    with pytest.raises(ChannelRuntimeError, match="requires positive media durations"):
        ChannelRuntime.open(
            resolved,
            RuntimeStore(tmp_path / "runtime.db"),
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_viewer_clock_pause_play_and_go_live(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    tv = open_two_channel_tv(tmp_path, epoch)

    tv.tune(7, now=epoch)
    paused = tv.pause(now=epoch + timedelta(seconds=20))
    still_paused = tv.status(now=epoch + timedelta(seconds=50))

    assert paused.viewer_selection.media.location.path.name == "00.mp4"
    assert paused.viewer_selection.offset_seconds == pytest.approx(20.0)
    assert still_paused.viewer_selection.offset_seconds == pytest.approx(20.0)
    assert still_paused.lag_seconds == pytest.approx(30.0)

    tv.play(now=epoch + timedelta(seconds=50))
    resumed = tv.status(now=epoch + timedelta(seconds=55))
    assert resumed.viewer_selection.offset_seconds == pytest.approx(25.0)
    assert resumed.lag_seconds == pytest.approx(30.0)

    live = tv.go_live(now=epoch + timedelta(seconds=55))
    assert live.is_live
    assert live.viewer_selection.media.location.path.name == "01.mp4"
    assert live.viewer_selection.offset_seconds == pytest.approx(25.0)


def test_two_channels_advance_independently_while_untuned(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    tv = open_two_channel_tv(tmp_path, epoch)

    first = tv.tune(7, now=epoch)
    channel_12 = tv.channel_up(now=epoch + timedelta(seconds=25))
    back_to_7 = tv.previous(now=epoch + timedelta(seconds=50))

    assert first.channel_number == 7
    assert first.viewer_selection.media.location.path.name == "00.mp4"
    assert channel_12.channel_number == 12
    assert channel_12.viewer_selection.media.location.path.name == "01.mp4"
    assert channel_12.viewer_selection.offset_seconds == pytest.approx(5.0)

    # Channel 7 was not decoded for 25 seconds, but its Broadcast Clock kept moving.
    assert back_to_7.channel_number == 7
    assert back_to_7.viewer_selection.media.location.path.name == "01.mp4"
    assert back_to_7.viewer_selection.offset_seconds == pytest.approx(20.0)
    assert back_to_7.is_live


def test_resume_returns_to_saved_viewer_clock_instead_of_live(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    tv = open_two_channel_tv(tmp_path, epoch)

    tv.tune(7, now=epoch)
    tv.tune(12, now=epoch + timedelta(seconds=20))
    resumed = tv.tune(7, now=epoch + timedelta(seconds=50), return_behavior="resume")

    assert resumed.viewer_selection.media.location.path.name == "00.mp4"
    assert resumed.viewer_selection.offset_seconds == pytest.approx(20.0)
    assert resumed.broadcast_selection.media.location.path.name == "01.mp4"
    assert resumed.broadcast_selection.offset_seconds == pytest.approx(20.0)
    assert resumed.lag_seconds == pytest.approx(30.0)
    assert not resumed.is_live


def test_ask_return_behavior_exposes_saved_continuity_choice(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    tv = open_two_channel_tv(tmp_path, epoch)

    tv.tune(7, now=epoch)
    tv.tune(12, now=epoch + timedelta(seconds=10))

    with pytest.raises(ReturnChoiceRequired, match="choose live or resume"):
        tv.tune(7, now=epoch + timedelta(seconds=30), return_behavior="ask")


def test_previous_channel_toggles_between_last_two_channels(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    tv = open_two_channel_tv(tmp_path, epoch)

    tv.tune(7, now=epoch)
    tv.tune(12, now=epoch + timedelta(seconds=5))
    first_previous = tv.previous(now=epoch + timedelta(seconds=10))
    second_previous = tv.previous(now=epoch + timedelta(seconds=15))

    assert first_previous.channel_number == 7
    assert second_previous.channel_number == 12


def test_tuning_and_viewer_clock_survive_runtime_restart(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    first = open_two_channel_tv(tmp_path, epoch)
    first.tune(7, now=epoch)
    first.status(now=epoch + timedelta(seconds=10))

    restarted = open_two_channel_tv(tmp_path, epoch + timedelta(seconds=40))
    restored = restarted.status(now=epoch + timedelta(seconds=40))

    assert restarted.current_channel == 7
    assert restored.viewer_time_utc == epoch + timedelta(seconds=40)
    assert restored.is_live


def test_seek_cannot_fast_forward_past_live(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    tv = open_two_channel_tv(tmp_path, epoch)
    tv.tune(7, now=epoch)
    tv.pause(now=epoch + timedelta(seconds=10))

    decision = tv.seek(999, now=epoch + timedelta(seconds=20))

    assert decision.is_live
    assert decision.viewer_time_utc == epoch + timedelta(seconds=20)
