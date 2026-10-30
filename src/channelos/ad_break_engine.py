from __future__ import annotations

"""Deterministic, persistent ad-break planning primitives.

These primitives deliberately do not own playback. ChannelRuntime remains the
single authority that maps a broadcast instant to a segment. A caller supplies
a stable program-occurrence ID and commits the resulting plan before exposing
it to viewers.
"""

import hashlib
import json
import math
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
        numeric_values = [self.duration_seconds, self.smoosh_minimum_seconds,
                          self.smoosh_max_trim_seconds, self.expand_max_seconds]
        if self.interval_seconds is not None:
            numeric_values.append(self.interval_seconds)
        numeric_values.extend(self.breakpoints_seconds)
        if any(not math.isfinite(float(value)) for value in numeric_values):
            raise ValueError("break policy values must be finite numbers")
        if self.duration_seconds <= 0:
            raise ValueError("break duration must be positive")
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("break interval must be positive")
        if any(point <= 0 for point in self.breakpoints_seconds):
            raise ValueError("breakpoints must be positive offsets")
        if len(set(self.breakpoints_seconds)) != len(self.breakpoints_seconds):
            raise ValueError("breakpoints must not contain duplicates")
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
        if not self.opportunity_id or not self.occurrence_id:
            raise ValueError("opportunity and occurrence IDs are required")
        if not math.isfinite(float(self.duration_seconds)) or self.duration_seconds <= 0:
            raise ValueError("opportunity duration must be finite and positive")


@dataclass(frozen=True, slots=True)
class AdCandidate:
    asset_id: str
    duration_seconds: float

    def __post_init__(self) -> None:
        if (not self.asset_id or not math.isfinite(float(self.duration_seconds))
                or self.duration_seconds <= 0):
            raise ValueError("ad candidate requires an ID and finite positive duration")


@dataclass(frozen=True, slots=True)
class PlannedSegment:
    asset_id: str
    start_offset_seconds: float
    source_offset_seconds: float
    duration_seconds: float
    trimmed_seconds: float = 0.0

    def __post_init__(self) -> None:
        values = (self.start_offset_seconds, self.source_offset_seconds,
                  self.duration_seconds, self.trimmed_seconds)
        if not self.asset_id or any(not math.isfinite(float(x)) for x in values):
            raise ValueError("planned segment requires an ID and finite timing values")
        if self.start_offset_seconds < 0 or self.source_offset_seconds < 0:
            raise ValueError("planned segment offsets cannot be negative")
        if self.duration_seconds <= 0 or self.trimmed_seconds < 0:
            raise ValueError("planned segment duration must be positive and trim non-negative")


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

    @property
    def duration_seconds(self) -> float:
        """Actual scheduled media duration, excluding unused reserved capacity."""
        return max(
            (segment.start_offset_seconds + segment.duration_seconds
             for segment in self.segments),
            default=0.0,
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "scheduled_at", _utc(self.scheduled_at))
        if not self.plan_id or not self.opportunity_id or not self.occurrence_id:
            raise ValueError("break plan, opportunity, and occurrence IDs are required")
        if self.channel_number < 1:
            raise ValueError("break plan channel number must be positive")
        if not math.isfinite(float(self.reserved_seconds)) or self.reserved_seconds <= 0:
            raise ValueError("reserved break duration must be finite and positive")
        if self.strategy not in {"best_fit", "largest", "smallest", "sequential",
                                 "least_played", "complete_rotation"}:
            raise ValueError(f"unsupported plan strategy: {self.strategy}")
        if self.timing_policy not in {"strict_fit", "smoosh", "expand"}:
            raise ValueError(f"unsupported plan timing policy: {self.timing_policy}")
        cursor = 0.0
        for segment in self.segments:
            if segment.start_offset_seconds < cursor - 0.001:
                raise ValueError("planned ad segments cannot overlap or move backwards")
            cursor = segment.start_offset_seconds + segment.duration_seconds
        if cursor > self.reserved_seconds + 0.001:
            raise ValueError("planned segments exceed the reserved break duration")


class BreakOpportunityScheduler:
    """Derive stable explicit/interval opportunities and arbitrate collisions."""

    @staticmethod
    def for_occurrence(
        occurrence: ProgramOccurrence,
        policy: BreakPolicy,
        *,
        revision: str = "",
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
            identity = _stable(occurrence.occurrence_id, revision, trigger, f"{offset:.6f}")
            result.append(BreakOpportunity(
                identity, occurrence.occurrence_id, occurrence.channel_number,
                trigger, at, policy.duration_seconds, policy.priority,
            ))
        return tuple(result)

    @staticmethod
    def arbitrate(
        opportunities: tuple[BreakOpportunity, ...],
    ) -> tuple[BreakOpportunity, ...]:
        """Keep one deterministic winner for each overlapping break window.

        Windows are half-open [scheduled_at, scheduled_at + duration). A
        transitive overlap cluster is arbitrated as one opportunity.
        """
        ordered = sorted(opportunities, key=lambda x: (
            x.scheduled_at, -x.priority, x.channel_number, x.opportunity_id
        ))
        clusters: list[list[BreakOpportunity]] = []
        cluster_end: datetime | None = None
        for item in ordered:
            item_end = item.scheduled_at + timedelta(seconds=item.duration_seconds)
            if not clusters or cluster_end is None or item.scheduled_at >= cluster_end:
                clusters.append([item])
                cluster_end = item_end
            else:
                clusters[-1].append(item)
                cluster_end = max(cluster_end, item_end)
        winners = [
            min(cluster, key=lambda x: (
                -x.priority, x.scheduled_at, x.channel_number, x.opportunity_id
            ))
            for cluster in clusters
        ]
        return tuple(sorted(winners, key=lambda x: (
            x.scheduled_at, x.channel_number, x.opportunity_id
        )))


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
        expand_max_seconds: float = 0.0,
    ) -> tuple[PlannedSegment, ...]:
        if not math.isfinite(float(budget_seconds)):
            raise ValueError("break budget must be finite")
        if budget_seconds <= 0:
            return ()
        if not math.isfinite(float(expand_max_seconds)) or expand_max_seconds < 0:
            raise ValueError("Expand limit must be finite and non-negative")
        if not math.isfinite(float(smoosh_minimum_seconds)) or smoosh_minimum_seconds <= 0:
            raise ValueError("Smoosh minimum must be finite and positive")
        if not math.isfinite(float(smoosh_max_trim_seconds)) or smoosh_max_trim_seconds < 0:
            raise ValueError("Smoosh trim limit must be finite and non-negative")
        if timing_policy not in {"strict_fit", "smoosh", "expand"}:
            raise ValueError(f"unsupported timing policy: {timing_policy}")
        selection_budget = (
            budget_seconds + expand_max_seconds
            if timing_policy == "expand" else budget_seconds
        )
        if strategy not in {
            "best_fit", "largest", "smallest", "sequential",
            "least_played", "complete_rotation",
        }:
            raise ValueError(f"unsupported ad strategy: {strategy}")
        counts = play_counts or {}
        if any(int(value) < 0 for value in counts.values()):
            raise ValueError("play counts cannot be negative")
        if len({x.asset_id for x in candidates}) != len(candidates):
            raise ValueError("candidate asset IDs must be unique")
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
        while pool and selection_budget - elapsed > 0.001:
            remaining = selection_budget - elapsed
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
            CREATE TABLE IF NOT EXISTS ad_break_policy_state (
                channel_number INTEGER PRIMARY KEY,
                policy_revision TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


    def apply_policy_revision(
        self, channel_number: int, revision: str, *, at: datetime
    ) -> bool:
        """Invalidate unstarted plans when ad policy changes; preserve airing plans.

        Returns True when an existing policy revision changed. Plans that have
        already started or have an airing-history row remain immutable.
        """
        instant = _utc(at)
        updated = instant.isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT policy_revision FROM ad_break_policy_state WHERE channel_number = ?",
                (int(channel_number),),
            ).fetchone()
            changed = row is not None and str(row[0]) != str(revision)
            if changed:
                self.connection.execute("""
                    DELETE FROM ad_break_plans
                    WHERE channel_number = ?
                      AND scheduled_at > ?
                      AND plan_id NOT IN (
                          SELECT DISTINCT plan_id FROM ad_break_history
                      )
                """, (int(channel_number), updated))
            self.connection.execute("""
                INSERT INTO ad_break_policy_state
                    (channel_number, policy_revision, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_number) DO UPDATE SET
                    policy_revision = excluded.policy_revision,
                    updated_at = excluded.updated_at
            """, (int(channel_number), str(revision), updated))
            self.connection.commit()
            return changed
        except Exception:
            self.connection.rollback()
            raise

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
        if segment_index < 0:
            raise ValueError("segment index cannot be negative")
        row = self.connection.execute(
            "SELECT payload FROM ad_break_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown ad break plan: {plan_id}")
        segments = json.loads(row[0])
        if segment_index >= len(segments):
            raise IndexError("segment index is outside the committed break plan")
        if segments[segment_index]["asset_id"] != asset_id:
            raise ValueError("aired asset ID does not match the committed plan segment")
        cursor = self.connection.execute("""
            INSERT OR IGNORE INTO ad_break_history
            (plan_id, segment_index, asset_id, aired_at) VALUES (?, ?, ?, ?)
        """, (plan_id, segment_index, asset_id, _utc(aired_at).isoformat()))
        self.connection.commit()
        return cursor.rowcount == 1

    def reconcile_completed(self, channel_number: int, *, through: datetime) -> int:
        """Record only ads whose *scheduled* broadcast has finished.

        A viewer tuning into an advertisement does not mean it has aired to
        completion. The ledger is idempotent and independent of viewer state.
        """
        instant = _utc(through)
        rows = self.connection.execute(
            "SELECT plan_id FROM ad_break_plans WHERE channel_number = ? "
            "ORDER BY scheduled_at, plan_id",
            (int(channel_number),),
        ).fetchall()
        recorded = 0
        for row in rows:
            plan = self.load_plan(str(row[0]))
            if plan is None or plan.scheduled_at > instant:
                continue
            for index, segment in enumerate(plan.segments):
                ended_at = plan.scheduled_at + timedelta(
                    seconds=segment.start_offset_seconds + segment.duration_seconds
                )
                if ended_at <= instant:
                    if self.record_aired(plan.plan_id, index, segment.asset_id, aired_at=ended_at):
                        recorded += 1
        return recorded

    def play_counts(self) -> dict[str, int]:
        rows = self.connection.execute("""
            SELECT asset_id, COUNT(*) FROM ad_break_history GROUP BY asset_id
        """).fetchall()
        return {str(asset): int(count) for asset, count in rows}

    def load_opportunity(self, opportunity_id: str) -> BreakPlan | None:
        """Recover the immutable committed plan for an opportunity after restart."""
        row = self.connection.execute("""
            SELECT plan_id, opportunity_id, occurrence_id, channel_number,
                   scheduled_at, reserved_seconds, strategy, timing_policy, payload
            FROM ad_break_plans WHERE opportunity_id = ?
        """, (str(opportunity_id),)).fetchone()
        if row is None:
            return None
        return BreakPlan(
            str(row[0]), str(row[1]), str(row[2]), int(row[3]),
            datetime.fromisoformat(str(row[4])), float(row[5]),
            tuple(PlannedSegment(**item) for item in json.loads(row[8])),
            str(row[6]), str(row[7]),
        )

    def load_plan(self, plan_id: str) -> BreakPlan | None:
        """Recover a plan by its stable plan ID."""
        row = self.connection.execute("""
            SELECT plan_id, opportunity_id, occurrence_id, channel_number,
                   scheduled_at, reserved_seconds, strategy, timing_policy, payload
            FROM ad_break_plans WHERE plan_id = ?
        """, (str(plan_id),)).fetchone()
        if row is None:
            return None
        return BreakPlan(
            str(row[0]), str(row[1]), str(row[2]), int(row[3]),
            datetime.fromisoformat(str(row[4])), float(row[5]),
            tuple(PlannedSegment(**item) for item in json.loads(row[8])),
            str(row[6]), str(row[7]),
        )

    def plans_for_channel(
        self, channel_number: int, *, start: datetime, end: datetime
    ) -> tuple[BreakPlan, ...]:
        """Load committed plans intersecting a UTC time range for runtime projection."""
        start_utc, end_utc = _utc(start), _utc(end)
        if end_utc <= start_utc:
            raise ValueError("plan query end must follow start")
        # Compare parsed UTC instants in Python. SQLite's datetime() emits
        # a space-separated timestamp while stored values use ISO's "T";
        # lexicographic comparison across those formats is not chronologically safe.
        rows = self.connection.execute("""
            SELECT plan_id FROM ad_break_plans
            WHERE channel_number = ?
            ORDER BY scheduled_at, plan_id
        """, (int(channel_number),)).fetchall()
        matches = []
        for row in rows:
            plan = self.load_plan(str(row[0]))
            if plan is None:
                continue
            plan_end = plan.scheduled_at + timedelta(seconds=plan.reserved_seconds)
            if plan.scheduled_at < end_utc and plan_end > start_utc:
                matches.append(plan)
        return tuple(matches)

    def plans_for_occurrence(self, occurrence_id: str) -> tuple[BreakPlan, ...]:
        """Load all immutable plans belonging to one program occurrence."""
        rows = self.connection.execute("""
            SELECT plan_id FROM ad_break_plans
            WHERE occurrence_id = ?
            ORDER BY scheduled_at, plan_id
        """, (str(occurrence_id),)).fetchall()
        return tuple(
            plan for row in rows
            if (plan := self.load_plan(str(row[0]))) is not None
        )

    def active_plan_at(
        self, channel_number: int, at: datetime
    ) -> BreakPlan | None:
        """Return the already-committed break containing a broadcast instant."""
        instant = _utc(at)
        rows = self.connection.execute("""
            SELECT plan_id FROM ad_break_plans
            WHERE channel_number = ? AND scheduled_at <= ?
            ORDER BY scheduled_at DESC, plan_id
        """, (int(channel_number), instant.isoformat())).fetchall()
        for row in rows:
            plan = self.load_plan(str(row[0]))
            if plan is not None and instant < (
                plan.scheduled_at + timedelta(seconds=plan.reserved_seconds)
            ):
                return plan
        return None

    def aired_segments(self, plan_id: str) -> tuple[tuple[int, str, datetime], ...]:
        """Return the durable airing ledger for a plan in segment order."""
        rows = self.connection.execute("""
            SELECT segment_index, asset_id, aired_at
            FROM ad_break_history WHERE plan_id = ?
            ORDER BY segment_index
        """, (str(plan_id),)).fetchall()
        return tuple(
            (int(index), str(asset_id), _utc(datetime.fromisoformat(str(aired_at))))
            for index, asset_id, aired_at in rows
        )
