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


class ReturnChoiceRequired(ChannelRuntimeError):
    """Raised when return_behavior='ask' requires the caller to choose live or resume."""


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


@dataclass(slots=True)
class ViewerClock:
    """A viewer's personal position on a channel's schedule timeline."""

    schedule_time_utc: datetime
    observed_at_utc: datetime
    running: bool = True

    def __post_init__(self) -> None:
        self.schedule_time_utc = require_aware_utc(self.schedule_time_utc)
        self.observed_at_utc = require_aware_utc(self.observed_at_utc)

    @classmethod
    def live(cls, at: datetime) -> "ViewerClock":
        current = require_aware_utc(at)
        return cls(current, current, True)

    def current(self, at: datetime) -> datetime:
        now = require_aware_utc(at)
        if not self.running:
            return self.schedule_time_utc
        return self.schedule_time_utc + (now - self.observed_at_utc)

    def _rebase(self, at: datetime) -> datetime:
        now = require_aware_utc(at)
        current = self.current(now)
        self.schedule_time_utc = current
        self.observed_at_utc = now
        return current

    def pause(self, at: datetime) -> datetime:
        current = self._rebase(at)
        self.running = False
        return current

    def play(self, at: datetime) -> datetime:
        now = require_aware_utc(at)
        if not self.running:
            self.observed_at_utc = now
            self.running = True
        return self.current(now)

    def freeze(self, at: datetime) -> datetime:
        """Freeze continuity while the viewer is tuned to another channel."""
        return self.pause(at)

    def seek(self, delta_seconds: float, at: datetime, *, live_ceiling: datetime | None = None) -> datetime:
        now = require_aware_utc(at)
        target = self.current(now) + timedelta(seconds=float(delta_seconds))
        if live_ceiling is not None:
            ceiling = require_aware_utc(live_ceiling)
            if target > ceiling:
                target = ceiling
        self.schedule_time_utc = target
        self.observed_at_utc = now
        return target

    def go_live(self, at: datetime) -> datetime:
        now = require_aware_utc(at)
        self.schedule_time_utc = now
        self.observed_at_utc = now
        self.running = True
        return now


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

                CREATE TABLE IF NOT EXISTS viewer_runtime (
                    channel_number INTEGER PRIMARY KEY,
                    schedule_time_utc TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    running INTEGER NOT NULL,
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
                connection.execute(
                    "DELETE FROM viewer_runtime WHERE channel_number = ?",
                    (channel_number,),
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

    def save_viewer(self, channel_number: int, clock: ViewerClock, *, now: datetime | None = None) -> None:
        updated = require_aware_utc(now or utc_now())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO viewer_runtime(
                    channel_number, schedule_time_utc, observed_at_utc, running, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(channel_number) DO UPDATE SET
                    schedule_time_utc = excluded.schedule_time_utc,
                    observed_at_utc = excluded.observed_at_utc,
                    running = excluded.running,
                    updated_at = excluded.updated_at
                """,
                (
                    channel_number,
                    datetime_to_text(clock.schedule_time_utc),
                    datetime_to_text(clock.observed_at_utc),
                    int(clock.running),
                    datetime_to_text(updated),
                ),
            )

    def load_viewer(self, channel_number: int) -> ViewerClock | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM viewer_runtime WHERE channel_number = ?",
                (channel_number,),
            ).fetchone()
        if row is None:
            return None
        return ViewerClock(
            schedule_time_utc=datetime_from_text(str(row["schedule_time_utc"])),
            observed_at_utc=datetime_from_text(str(row["observed_at_utc"])),
            running=bool(row["running"]),
        )

    def _set_meta(self, key: str, value: str | None) -> None:
        with self.connect() as connection:
            if value is None:
                connection.execute("DELETE FROM runtime_meta WHERE key = ?", (key,))
            else:
                connection.execute(
                    "INSERT OR REPLACE INTO runtime_meta(key, value) VALUES(?, ?)",
                    (key, value),
                )

    def _get_meta_int(self, key: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM runtime_meta WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return None

    def set_tuning(self, current_channel: int | None, previous_channel: int | None) -> None:
        self._set_meta("current_channel", None if current_channel is None else str(current_channel))
        self._set_meta("previous_channel", None if previous_channel is None else str(previous_channel))

    def get_tuning(self) -> tuple[int | None, int | None]:
        return self._get_meta_int("current_channel"), self._get_meta_int("previous_channel")


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

    @property
    def channel_number(self) -> int:
        return self.channel.definition.channel

    def broadcast_at(self, at: datetime | None = None) -> BroadcastSelection:
        return self.timeline.selection_at(self.epoch_utc, at or utc_now())

    def selection_for_viewer_time(self, viewer_time: datetime) -> BroadcastSelection:
        return self.timeline.selection_at(self.epoch_utc, viewer_time)


@dataclass(frozen=True, slots=True)
class TuneDecision:
    channel_number: int
    channel_name: str
    viewer_time_utc: datetime
    viewer_selection: BroadcastSelection
    broadcast_selection: BroadcastSelection
    lag_seconds: float

    @property
    def is_live(self) -> bool:
        return self.lag_seconds < 0.5


class TelevisionRuntime:
    """Multi-channel television state independent of the decoder/player backend."""

    def __init__(self, channels: tuple[ChannelRuntime, ...], store: RuntimeStore) -> None:
        if not channels:
            raise ChannelRuntimeError("television runtime requires at least one channel")
        by_number: dict[int, ChannelRuntime] = {}
        for channel in channels:
            if channel.channel_number in by_number:
                raise ChannelRuntimeError(f"duplicate channel number {channel.channel_number}")
            by_number[channel.channel_number] = channel
        self.channels = by_number
        self.channel_numbers = tuple(sorted(by_number))
        self.store = store

        current, previous = store.get_tuning()
        self.current_channel = current if current in self.channels else None
        self.previous_channel = previous if previous in self.channels else None
        self._viewer: ViewerClock | None = None
        if self.current_channel is not None:
            self._viewer = self.store.load_viewer(self.current_channel)

    def _now(self, value: datetime | None) -> datetime:
        return require_aware_utc(value or utc_now())

    def _channel(self, number: int) -> ChannelRuntime:
        try:
            return self.channels[number]
        except KeyError as exc:
            raise ChannelRuntimeError(f"channel {number} is not in the active lineup") from exc

    def _decision(self, now: datetime) -> TuneDecision:
        if self.current_channel is None or self._viewer is None:
            raise ChannelRuntimeError("no channel is currently tuned")
        runtime = self._channel(self.current_channel)
        viewer_time = self._viewer.current(now)
        if viewer_time > now:
            viewer_time = self._viewer.go_live(now)
        viewer_selection = runtime.selection_for_viewer_time(viewer_time)
        broadcast_selection = runtime.broadcast_at(now)
        lag = max(0.0, (now - viewer_time).total_seconds())
        return TuneDecision(
            channel_number=runtime.channel_number,
            channel_name=runtime.channel.definition.name,
            viewer_time_utc=viewer_time,
            viewer_selection=viewer_selection,
            broadcast_selection=broadcast_selection,
            lag_seconds=lag,
        )

    def _persist_viewer(self, now: datetime) -> None:
        if self.current_channel is not None and self._viewer is not None:
            self.store.save_viewer(self.current_channel, self._viewer, now=now)

    def tune(
        self,
        channel_number: int,
        *,
        now: datetime | None = None,
        return_behavior: str = "live",
    ) -> TuneDecision:
        current_time = self._now(now)
        self._channel(channel_number)

        if self.current_channel == channel_number and self._viewer is not None:
            return self._decision(current_time)

        if return_behavior not in {"live", "resume", "ask"}:
            raise ValueError("return_behavior must be 'live', 'resume', or 'ask'")

        if self.current_channel is not None and self._viewer is not None:
            self._viewer.freeze(current_time)
            self._persist_viewer(current_time)

        old_current = self.current_channel
        saved = self.store.load_viewer(channel_number)
        if return_behavior == "ask" and saved is not None:
            raise ReturnChoiceRequired(
                f"Channel {channel_number} has saved viewer continuity; choose live or resume"
            )

        if return_behavior == "resume" and saved is not None:
            saved.observed_at_utc = current_time
            saved.running = True
            viewer = saved
        else:
            viewer = ViewerClock.live(current_time)

        self.previous_channel = old_current if old_current != channel_number else self.previous_channel
        self.current_channel = channel_number
        self._viewer = viewer
        self.store.set_tuning(self.current_channel, self.previous_channel)
        self._persist_viewer(current_time)
        return self._decision(current_time)

    def channel_up(self, *, now: datetime | None = None) -> TuneDecision:
        current_time = self._now(now)
        if self.current_channel is None:
            return self.tune(self.channel_numbers[0], now=current_time)
        index = self.channel_numbers.index(self.current_channel)
        target = self.channel_numbers[(index + 1) % len(self.channel_numbers)]
        return self.tune(target, now=current_time)

    def channel_down(self, *, now: datetime | None = None) -> TuneDecision:
        current_time = self._now(now)
        if self.current_channel is None:
            return self.tune(self.channel_numbers[-1], now=current_time)
        index = self.channel_numbers.index(self.current_channel)
        target = self.channel_numbers[(index - 1) % len(self.channel_numbers)]
        return self.tune(target, now=current_time)

    def previous(self, *, now: datetime | None = None) -> TuneDecision:
        if self.previous_channel is None:
            raise ChannelRuntimeError("there is no previous channel yet")
        return self.tune(self.previous_channel, now=self._now(now))

    def pause(self, *, now: datetime | None = None) -> TuneDecision:
        current_time = self._now(now)
        if self._viewer is None:
            raise ChannelRuntimeError("no channel is currently tuned")
        self._viewer.pause(current_time)
        self._persist_viewer(current_time)
        return self._decision(current_time)

    def play(self, *, now: datetime | None = None) -> TuneDecision:
        current_time = self._now(now)
        if self._viewer is None:
            raise ChannelRuntimeError("no channel is currently tuned")
        self._viewer.play(current_time)
        self._persist_viewer(current_time)
        return self._decision(current_time)

    def seek(self, delta_seconds: float, *, now: datetime | None = None) -> TuneDecision:
        current_time = self._now(now)
        if self._viewer is None:
            raise ChannelRuntimeError("no channel is currently tuned")
        self._viewer.seek(delta_seconds, current_time, live_ceiling=current_time)
        self._persist_viewer(current_time)
        return self._decision(current_time)

    def go_live(self, *, now: datetime | None = None) -> TuneDecision:
        current_time = self._now(now)
        if self._viewer is None:
            raise ChannelRuntimeError("no channel is currently tuned")
        self._viewer.go_live(current_time)
        self._persist_viewer(current_time)
        return self._decision(current_time)

    def status(self, *, now: datetime | None = None) -> TuneDecision:
        return self._decision(self._now(now))
