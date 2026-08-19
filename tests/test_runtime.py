from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import MediaProbeResult
from channelos.resolve import ResolvedChannel, resolve_channel
from channelos.runtime import ChannelRuntime, ChannelRuntimeError, RuntimeStore

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
