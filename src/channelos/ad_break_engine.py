from __future__ import annotations

"""Deterministic, persistent ad-break planning primitives.

These primitives deliberately do not own playback. ChannelRuntime remains the
single authority that maps a broadcast instant to a segment. A caller supplies
a stable program-occurrence ID and commits the resulting plan before exposing
it to viewers.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

Strategy = Literal[
    "best_fit", "largest", "smallest", "sequential",
    "least_played", "complete_rotation",
]
Trigger = Literal["breakpoint", "interval", "between_programs", "calendar_boundary"]
TimingPolicy = Literal["strict_fit", "smoosh", "expand"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("break timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stable(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BreakPolicy:
    enabled: bool = False
    interval_seconds: float | None = None
    breakpoints_seconds: tuple[float, ...] = ()
    duration_seconds: float = 120.0
    priority: int = 0
    strategy: Strategy = "best_fit"
    timing_policy: TimingPolicy = "strict_fit"
    smoosh_minimum_seconds: float = 5.0
    smoosh_max_trim_seconds: float = 15.0
    expand_max_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.strategy not in {
            "best_fit", "largest", "smallest", "sequential",
            "least_played", "complete_rotation",
        }:
            raise ValueError(f"unsupported ad strategy: {self.strategy}")
        if self.timing_policy not in {"strict_fit", "smoosh", "expand"}:
            raise ValueError(f"unsupported timing policy: {self.timing_policy}")
        if self.duration_seconds <= 0:
            raise ValueError("break duration must be positive")
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("break interval must be positive")
        if any(point <= 0 for point in self.breakpoints_seconds):
            raise ValueError("breakpoints must be positive offsets")
        if self.smoosh_minimum_seconds <= 0 or self.smoosh_max_trim_seconds < 0:
            raise ValueError("invalid Smoosh limits")
        if self.expand_max_seconds < 0:
            raise ValueError("Expand limit cannot be negative")


@dataclass(frozen=True, slots=True)
class ProgramOccurrence:
    occurrence_id: str
    channel_number: int
    asset_id: str
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        start, end = _utc(self.starts_at), _utc(self.ends_at)
        if not self.occurrence_id or not self.asset_id:
            raise ValueError("program occurrence and asset IDs are required")
        if end <= start:
            raise ValueError("program occurrence end must follow its start")
        object.__setattr__(self, "starts_at", start)
        object.__setattr__(self, "ends_at", end)


@dataclass(frozen=True, slots=True)
class BreakOpportunity:
    opportunity_id: str
    occurrence_id: str
    channel_number: int
    trigger: Trigger
    scheduled_at: datetime
    duration_seconds: float
    priority: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheduled_at", _utc(self.scheduled_at))
        if self.duration_seconds <= 0:
            raise ValueError("opportunity duration must be positive")


@dataclass(frozen=True, slots=True)
class AdCandidate:
    asset_id: str
    duration_seconds: float

    def __post_init__(self) -> None:
        if not self.asset_id or self.duration_seconds <= 0:
            raise ValueError("ad candidate requires an ID and positive duration")


@dataclass(frozen=True, slots=True)
class PlannedSegment:
    asset_id: str
    start_offset_seconds: float
    source_offset_seconds: float
    duration_seconds: float
    trimmed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class BreakPlan:
    plan_id: str
    opportunity_id: str
    occurrence_id: str
    channel_number: int
    scheduled_at: datetime
    reserved_seconds: float
    segments: tuple[PlannedSegment, ...]
    strategy: str
    timing_policy: str


class BreakOpportunityScheduler:
    """Derive stable explicit/interval opportunities and arbitrate collisions."""

    @staticmethod
    def for_occurrence(
        occurrence: ProgramOccurrence, policy: BreakPolicy
    ) -> tuple[BreakOpportunity, ...]:
        if not policy.enabled:
            return ()
        offsets: dict[float, Trigger] = {
            float(point): "breakpoint" for point in policy.breakpoints_seconds
            if point < (occurrence.ends_at - occurrence.starts_at).total_seconds()
        }
        if policy.interval_seconds is not None:
            step = policy.interval_seconds
            offset = step
            duration = (occurrence.ends_at - occurrence.starts_at).total_seconds()
            while offset < duration:
                # Explicit breakpoints win when they coincide with intervals.
                offsets.setdefault(float(offset), "interval")
                offset += step
        result = []
        for offset, trigger in sorted(offsets.items()):
            at = occurrence.starts_at + timedelta(seconds=offset)
            identity = _stable(occurrence.occurrence_id, trigger, f"{offset:.6f}")
            result.append(BreakOpportunity(
                identity, occurrence.occurrence_id, occurrence.channel_number,
                trigger, at, policy.duration_seconds, policy.priority,
            ))
        return tuple(result)

    @staticmethod
    def arbitrate(
        opportunities: tuple[BreakOpportunity, ...],
    ) -> tuple[BreakOpportunity, ...]:
        """At an identical instant, keep highest priority then stable ID."""
        chosen: dict[datetime, BreakOpportunity] = {}
        for item in sorted(
            opportunities,
            key=lambda x: (-x.priority, x.channel_number, x.opportunity_id),
        ):
            chosen.setdefault(item.scheduled_at, item)
        return tuple(chosen[key] for key in sorted(chosen))


class AdSelectionEngine:
    def select(
        self,
        candidates: tuple[AdCandidate, ...],
        budget_seconds: float,
        *,
        strategy: Strategy = "best_fit",
        seed: str = "",
        play_counts: dict[str, int] | None = None,
        previously_selected: frozenset[str] = frozenset(),
        timing_policy: TimingPolicy = "strict_fit",
        smoosh_minimum_seconds: float = 5.0,
        smoosh_max_trim_seconds: float = 15.0,
    ) -> tuple[PlannedSegment, ...]:
        if budget_seconds <= 0:
            return ()
        if strategy not in {
            "best_fit", "largest", "smallest", "sequential",
            "least_played", "complete_rotation",
        }:
            raise ValueError(f"unsupported ad strategy: {strategy}")
        counts = play_counts or {}
        pool = [x for x in candidates if x.asset_id not in previously_selected]
        if strategy == "least_played":
            pool.sort(key=lambda x: (counts.get(x.asset_id, 0), x.duration_seconds,
                                     _stable(seed, x.asset_id), x.asset_id))
        elif strategy == "complete_rotation":
            pool.sort(key=lambda x: (counts.get(x.asset_id, 0),
                                     _stable(seed, x.asset_id), x.asset_id))
        elif strategy == "smallest":
            pool.sort(key=lambda x: (x.duration_seconds, _stable(seed, x.asset_id)))
        elif strategy in {"largest", "best_fit"}:
            pool.sort(key=lambda x: (-x.duration_seconds, _stable(seed, x.asset_id)))
        else:
            pool.sort(key=lambda x: (_stable(seed, x.asset_id), x.asset_id))

        selected: list[PlannedSegment] = []
        elapsed = 0.0
        used: set[str] = set()
        while pool and budget_seconds - elapsed > 0.001:
            remaining = budget_seconds - elapsed
            fitting = [x for x in pool if x.duration_seconds <= remaining + 0.001]
            if not fitting and timing_policy == "smoosh":
                fitting = [
                    x for x in pool
                    if x.duration_seconds - remaining <= smoosh_max_trim_seconds
                    and remaining >= smoosh_minimum_seconds
                ]
            if not fitting:
                break
            if strategy == "best_fit":
                item = min(fitting, key=lambda x: (
                    remaining - min(x.duration_seconds, remaining),
                    -x.duration_seconds, _stable(seed, x.asset_id)))
            else:
                item = fitting[0]
            trimmed = max(0.0, item.duration_seconds - remaining)
            if trimmed and (timing_policy != "smoosh"
                            or item.duration_seconds - trimmed < smoosh_minimum_seconds):
                break
            duration = item.duration_seconds - trimmed
            selected.append(PlannedSegment(
                item.asset_id, elapsed, 0.0, duration, trimmed
            ))
            elapsed += duration
            used.add(item.asset_id)
            pool.remove(item)
            if trimmed:
                break
        return tuple(selected)


class BreakPlanStore:
    """SQLite persistence for immutable plans and idempotent airing history."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = str(database_path)
        self.connection = sqlite3.connect(self.path, timeout=5.0)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS ad_break_plans (
                plan_id TEXT PRIMARY KEY,
                opportunity_id TEXT NOT NULL UNIQUE,
                occurrence_id TEXT NOT NULL,
                channel_number INTEGER NOT NULL,
                scheduled_at TEXT NOT NULL,
                reserved_seconds REAL NOT NULL,
                strategy TEXT NOT NULL,
                timing_policy TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ad_break_history (
                plan_id TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                asset_id TEXT NOT NULL,
                aired_at TEXT NOT NULL,
                PRIMARY KEY (plan_id, segment_index),
                FOREIGN KEY (plan_id) REFERENCES ad_break_plans(plan_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ad_break_history_asset
                ON ad_break_history(asset_id);
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def commit(self, plan: BreakPlan) -> BreakPlan:
        payload = json.dumps([asdict(s) for s in plan.segments], sort_keys=True)
        created = datetime.now(timezone.utc).isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("""
                INSERT OR IGNORE INTO ad_break_plans
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan.plan_id, plan.opportunity_id, plan.occurrence_id,
                plan.channel_number, _utc(plan.scheduled_at).isoformat(),
                plan.reserved_seconds, plan.strategy, plan.timing_policy,
                payload, created,
            ))
            row = self.connection.execute("""
                SELECT plan_id, occurrence_id, channel_number, scheduled_at,
                       reserved_seconds, strategy, timing_policy, payload
                FROM ad_break_plans WHERE opportunity_id = ?
            """, (plan.opportunity_id,)).fetchone()
            if row is None:
                raise RuntimeError("committed break plan could not be read back")
            stored = BreakPlan(
                row[0], plan.opportunity_id, row[1], row[2],
                datetime.fromisoformat(row[3]), row[4],
                tuple(PlannedSegment(**x) for x in json.loads(row[7])),
                row[5], row[6],
            )
            self.connection.commit()
            return stored
        except Exception:
            self.connection.rollback()
            raise

    def record_aired(
        self, plan_id: str, segment_index: int, asset_id: str,
        *, aired_at: datetime,
    ) -> bool:
        cursor = self.connection.execute("""
            INSERT OR IGNORE INTO ad_break_history
            (plan_id, segment_index, asset_id, aired_at) VALUES (?, ?, ?, ?)
        """, (plan_id, segment_index, asset_id, _utc(aired_at).isoformat()))
        self.connection.commit()
        return cursor.rowcount == 1

    def play_counts(self) -> dict[str, int]:
        rows = self.connection.execute("""
            SELECT asset_id, COUNT(*) FROM ad_break_history GROUP BY asset_id
        """).fetchall()
        return {str(asset): int(count) for asset, count in rows}
