from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .library import IndexedMedia
from .resolve import ResolvedChannel

RUNTIME_SCHEMA_VERSION = 1


class ChannelRuntimeError(RuntimeError):
    """Raised when a resolved channel cannot form a valid television runtime."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def datetime_to_text(value: datetime) -> str:
    return require_aware_utc(value).isoformat(timespec="microseconds")


def datetime_from_text(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return require_aware_utc(parsed)


@dataclass(frozen=True, slots=True)
class ScheduledProgram:
    media: IndexedMedia
    index: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class BroadcastSelection:
    program: ScheduledProgram
    offset_seconds: float
    program_started_at: datetime
    program_ends_at: datetime
    cycle_index: int

    @property
    def media(self) -> IndexedMedia:
        return self.program.media


class SequentialTimeline:
    """An indefinitely repeating deterministic sequence of timed media assets."""

    def __init__(self, media: tuple[IndexedMedia, ...]) -> None:
        if not media:
            raise ChannelRuntimeError("a channel runtime requires at least one indexed media asset")

        programs: list[ScheduledProgram] = []
        cumulative: list[float] = []
        total = 0.0
        missing: list[str] = []

        for index, item in enumerate(media):
            duration = item.asset.duration_seconds
            if duration is None or duration <= 0:
                missing.append(str(item.location.path))
                continue
            duration_value = float(duration)
            programs.append(
                ScheduledProgram(
                    media=item,
                    index=index,
                    duration_seconds=duration_value,
                )
            )
            total += duration_value
            cumulative.append(total)

        if missing:
            preview = ", ".join(missing[:3])
            if len(missing) > 3:
                preview += f", ... (+{len(missing) - 3} more)"
            raise ChannelRuntimeError(
                "Broadcast Clock requires positive media durations. "
                f"Re-scan with technical probing before scheduling: {preview}"
            )

        self.programs = tuple(programs)
        self._cumulative_ends = tuple(cumulative)
        self.cycle_duration_seconds = total

    def selection_at(self, epoch: datetime, at: datetime) -> BroadcastSelection:
        epoch_utc = require_aware_utc(epoch)
        at_utc = require_aware_utc(at)
        elapsed = (at_utc - epoch_utc).total_seconds()
        cycle_duration = self.cycle_duration_seconds
        cycle_index = int(elapsed // cycle_duration)
        cycle_position = elapsed % cycle_duration

        previous_end = 0.0
        for program, end in zip(self.programs, self._cumulative_ends, strict=True):
            if cycle_position < end:
                offset = cycle_position - previous_end
                started = at_utc - timedelta(seconds=offset)
                return BroadcastSelection(
                    program=program,
                    offset_seconds=offset,
                    program_started_at=started,
                    program_ends_at=started + timedelta(seconds=program.duration_seconds),
                    cycle_index=cycle_index,
                )
            previous_end = end

        # Floating-point modulo should keep cycle_position below cycle_duration,
        # but protect the invariant if a platform ever returns the endpoint.
        first = self.programs[0]
        return BroadcastSelection(
            program=first,
            offset_seconds=0.0,
            program_started_at=at_utc,
            program_ends_at=at_utc + timedelta(seconds=first.duration_seconds),
            cycle_index=cycle_index + 1,
        )


def schedule_signature(channel: ResolvedChannel) -> str:
    """Return a deterministic fingerprint of the inputs that define a channel timeline."""

    payload = {
        "schema": 1,
        "channel": channel.definition.channel,
        "mode": channel.definition.programming.mode,
        "media": [
            {
                "asset_id": item.asset.asset_id,
                "duration_seconds": item.asset.duration_seconds,
            }
            for item in channel.media
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PersistedChannelRuntime:
    channel_number: int
    schedule_signature: str
    epoch_utc: datetime


class RuntimeStore:
    """Persistent local runtime state. Media remains in the media library, never here."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channel_runtime (
                    channel_number INTEGER PRIMARY KEY,
                    schedule_signature TEXT NOT NULL,
                    epoch_utc TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO runtime_meta(key, value) VALUES('schema_version', ?)",
                (str(RUNTIME_SCHEMA_VERSION),),
            )

    def ensure_channel(
        self,
        channel_number: int,
        signature: str,
        *,
        now: datetime | None = None,
    ) -> PersistedChannelRuntime:
        current = require_aware_utc(now or utc_now())
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM channel_runtime WHERE channel_number = ?",
                (channel_number,),
            ).fetchone()

            if row is None or row["schedule_signature"] != signature:
                epoch_text = datetime_to_text(current)
                connection.execute(
                    """
                    INSERT INTO channel_runtime(
                        channel_number, schedule_signature, epoch_utc, updated_at
                    ) VALUES(?, ?, ?, ?)
                    ON CONFLICT(channel_number) DO UPDATE SET
                        schedule_signature = excluded.schedule_signature,
                        epoch_utc = excluded.epoch_utc,
                        updated_at = excluded.updated_at
                    """,
                    (channel_number, signature, epoch_text, epoch_text),
                )
                return PersistedChannelRuntime(
                    channel_number=channel_number,
                    schedule_signature=signature,
                    epoch_utc=current,
                )

        return PersistedChannelRuntime(
            channel_number=channel_number,
            schedule_signature=str(row["schedule_signature"]),
            epoch_utc=datetime_from_text(str(row["epoch_utc"])),
        )


@dataclass(frozen=True, slots=True)
class ChannelRuntime:
    channel: ResolvedChannel
    timeline: SequentialTimeline
    epoch_utc: datetime
    signature: str

    @classmethod
    def open(
        cls,
        channel: ResolvedChannel,
        store: RuntimeStore,
        *,
        now: datetime | None = None,
    ) -> "ChannelRuntime":
        if channel.definition.programming.mode != "sequential":
            raise ChannelRuntimeError(
                "Phase 1 Broadcast Clock currently requires programming.mode='sequential'"
            )
        timeline = SequentialTimeline(channel.media)
        signature = schedule_signature(channel)
        persisted = store.ensure_channel(
            channel.definition.channel,
            signature,
            now=now,
        )
        return cls(
            channel=channel,
            timeline=timeline,
            epoch_utc=persisted.epoch_utc,
            signature=signature,
        )

    def broadcast_at(self, at: datetime | None = None) -> BroadcastSelection:
        return self.timeline.selection_at(self.epoch_utc, at or utc_now())
