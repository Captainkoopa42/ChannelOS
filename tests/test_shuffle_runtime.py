from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import MediaProbeResult
from channelos.resolve import ResolvedChannel, resolve_channel
from channelos.runtime import ChannelRuntime, ChannelRuntimeError, RuntimeStore, schedule_signature

UTC = timezone.utc


def build_shuffle_channel(
    tmp_path: Path,
    durations: list[float],
    *,
    avoid_repeat_days: int = 0,
    channel_number: int = 7,
) -> ResolvedChannel:
    media_dir = tmp_path / f"shuffle-{channel_number}"
    media_dir.mkdir(exist_ok=True)
    library = MediaLibrary(tmp_path / "library.db")

    for index, duration in enumerate(durations):
        path = media_dir / f"{index:02d}.mp4"
        payload = f"shuffle-asset-{channel_number}-{index}".encode()
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
            "name": f"Shuffle {channel_number}",
            "sources": [{"path": str(media_dir)}],
            "programming": {
                "mode": "shuffle",
                "avoid_repeat_days": avoid_repeat_days,
            },
        }
    )
    return resolve_channel(definition, library)


def test_shuffle_is_deterministic_and_exhausts_pool_before_repeat(tmp_path: Path) -> None:
    resolved = build_shuffle_channel(tmp_path, [10.0, 11.0, 12.0, 13.0, 14.0])
    epoch = datetime(2026, 1, 1, tzinfo=UTC)

    first = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime-a.db"),
        now=epoch,
    )
    second = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime-b.db"),
        now=epoch + timedelta(days=30),
    )

    first_ids = [program.media.asset.asset_id for program in first.timeline.programs]
    second_ids = [program.media.asset.asset_id for program in second.timeline.programs]
    source_ids = [item.asset.asset_id for item in resolved.media]

    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids)) == len(source_ids)
    assert set(first_ids) == set(source_ids)

    # The first repeat happens only after the entire eligible pool has aired once.
    repeated = first.broadcast_at(epoch + timedelta(seconds=first.timeline.cycle_duration_seconds))
    assert repeated.media.asset.asset_id == first_ids[0]
    assert repeated.cycle_index == 1


def test_shuffle_order_is_independent_of_resolved_input_order(tmp_path: Path) -> None:
    resolved = build_shuffle_channel(tmp_path, [20.0, 20.0, 20.0, 20.0])
    reversed_resolved = ResolvedChannel(
        definition=resolved.definition,
        media=tuple(reversed(resolved.media)),
    )
    epoch = datetime(2026, 1, 1, tzinfo=UTC)

    normal = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime-normal.db"),
        now=epoch,
    )
    reversed_runtime = ChannelRuntime.open(
        reversed_resolved,
        RuntimeStore(tmp_path / "runtime-reversed.db"),
        now=epoch,
    )

    normal_ids = [program.media.asset.asset_id for program in normal.timeline.programs]
    reversed_ids = [program.media.asset.asset_id for program in reversed_runtime.timeline.programs]

    assert normal_ids == reversed_ids
    assert schedule_signature(resolved) == schedule_signature(reversed_resolved)


def test_shuffle_repeat_day_window_rejects_impossible_pool(tmp_path: Path) -> None:
    resolved = build_shuffle_channel(
        tmp_path,
        [30.0, 45.0, 60.0],
        avoid_repeat_days=1,
    )

    with pytest.raises(ChannelRuntimeError, match="cannot guarantee 1 day"):
        ChannelRuntime.open(
            resolved,
            RuntimeStore(tmp_path / "runtime.db"),
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_shuffle_repeat_day_window_passes_when_pool_is_long_enough(tmp_path: Path) -> None:
    resolved = build_shuffle_channel(
        tmp_path,
        [43200.0, 43200.0],
        avoid_repeat_days=1,
    )

    runtime = ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime.db"),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert runtime.timeline.cycle_duration_seconds == pytest.approx(86400.0)


def test_repeat_policy_change_changes_schedule_signature(tmp_path: Path) -> None:
    resolved = build_shuffle_channel(tmp_path, [43200.0, 43200.0], avoid_repeat_days=0)
    changed_definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": resolved.definition.channel,
            "name": resolved.definition.name,
            "sources": [{"path": str(resolved.definition.sources[0].path)}],
            "programming": {
                "mode": "shuffle",
                "avoid_repeat_days": 1,
            },
        }
    )
    changed = ResolvedChannel(definition=changed_definition, media=resolved.media)

    assert schedule_signature(resolved) != schedule_signature(changed)
