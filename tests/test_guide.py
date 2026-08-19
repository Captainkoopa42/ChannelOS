from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.guide import GuideError, GuideService
from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import MediaProbeResult
from channelos.resolve import ResolvedChannel, resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore

UTC = timezone.utc


def build_resolved_channel(
    tmp_path: Path,
    durations: list[float],
    *,
    channel_number: int,
    mode: str = "sequential",
) -> ResolvedChannel:
    media_dir = tmp_path / f"guide-channel-{channel_number}"
    media_dir.mkdir(exist_ok=True)
    library = MediaLibrary(tmp_path / "guide-library.db")

    for index, duration in enumerate(durations):
        path = media_dir / f"{index:02d}.mp4"
        payload = f"guide-{channel_number}-{index}".encode()
        path.write_bytes(payload)
        library.upsert_file(
            path,
            media_dir,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            probe=MediaProbeResult(duration_seconds=duration, container_format="mp4"),
        )

    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": channel_number,
            "name": f"Channel {channel_number}",
            "sources": [{"path": str(media_dir)}],
            "programming": {"mode": mode},
        }
    )
    return resolve_channel(definition, library)


def open_runtime(
    tmp_path: Path,
    durations: list[float],
    *,
    channel_number: int,
    epoch: datetime,
    mode: str = "sequential",
) -> ChannelRuntime:
    resolved = build_resolved_channel(
        tmp_path,
        durations,
        channel_number=channel_number,
        mode=mode,
    )
    return ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "guide-runtime.db"),
        now=epoch,
    )


def test_horizon_matches_broadcast_clock_and_includes_overlapping_program(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = open_runtime(tmp_path, [30.0, 45.0, 60.0], channel_number=7, epoch=epoch)
    service = GuideService((runtime,))

    start = epoch + timedelta(seconds=42)
    end = epoch + timedelta(seconds=100)
    guide = service.horizon(start, end, generated_at=start)

    row = guide.rows[0]
    direct = runtime.broadcast_at(start)
    assert row.programs[0].asset_id == direct.media.asset.asset_id
    assert row.programs[0].start_utc == direct.program_started_at
    assert row.programs[0].end_utc == direct.program_ends_at
    assert [program.display_label for program in row.programs] == ["01", "02"]
    assert row.programs[0].is_current


def test_horizon_crosses_cycle_wrap_with_exact_schedule_boundaries(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = open_runtime(tmp_path, [30.0, 45.0], channel_number=7, epoch=epoch)
    service = GuideService((runtime,))

    guide = service.horizon(
        epoch + timedelta(seconds=65),
        epoch + timedelta(seconds=110),
        generated_at=epoch + timedelta(seconds=65),
    )
    programs = guide.rows[0].programs

    assert [program.display_label for program in programs] == ["01", "00", "01"]
    assert programs[0].start_utc == epoch + timedelta(seconds=30)
    assert programs[0].end_utc == epoch + timedelta(seconds=75)
    assert programs[1].start_utc == epoch + timedelta(seconds=75)
    assert programs[1].end_utc == epoch + timedelta(seconds=105)


def test_now_next_crosses_program_boundary(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = open_runtime(tmp_path, [30.0, 45.0], channel_number=7, epoch=epoch)
    service = GuideService((runtime,))

    result = service.now_next(7, at=epoch + timedelta(seconds=29))

    assert result.now.display_label == "00"
    assert result.now.start_utc == epoch
    assert result.now.end_utc == epoch + timedelta(seconds=30)
    assert result.next.display_label == "01"
    assert result.next.start_utc == epoch + timedelta(seconds=30)
    assert result.next.end_utc == epoch + timedelta(seconds=75)
    assert result.now.is_current
    assert result.next.is_future


def test_rows_are_numeric_and_shuffle_horizon_is_restart_stable(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime_12 = open_runtime(
        tmp_path,
        [20.0, 20.0, 20.0],
        channel_number=12,
        epoch=epoch,
        mode="shuffle",
    )
    runtime_7 = open_runtime(tmp_path, [30.0, 30.0], channel_number=7, epoch=epoch)
    first = GuideService((runtime_12, runtime_7)).horizon(
        epoch,
        epoch + timedelta(seconds=60),
        generated_at=epoch,
    )

    restarted_12 = ChannelRuntime.open(
        runtime_12.channel,
        RuntimeStore(tmp_path / "guide-runtime.db"),
        now=epoch + timedelta(days=1),
    )
    second = GuideService((restarted_12,)).horizon(
        epoch,
        epoch + timedelta(seconds=60),
        generated_at=epoch,
    )

    assert [row.channel_number for row in first.rows] == [7, 12]
    first_shuffle = next(row for row in first.rows if row.channel_number == 12)
    assert [program.asset_id for program in first_shuffle.programs] == [
        program.asset_id for program in second.rows[0].programs
    ]
    assert [program.schedule_id for program in first_shuffle.programs] == [
        program.schedule_id for program in second.rows[0].programs
    ]
    assert "deterministic shuffle programming" in first_shuffle.programs[0].explanation


def test_guide_rejects_invalid_horizons_and_unknown_channels(tmp_path: Path) -> None:
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    runtime = open_runtime(tmp_path, [30.0], channel_number=7, epoch=epoch)
    service = GuideService((runtime,))

    with pytest.raises(GuideError, match="end must be after start"):
        service.horizon(epoch, epoch, generated_at=epoch)

    with pytest.raises(GuideError, match="unknown channel"):
        service.now_next(99, at=epoch)
