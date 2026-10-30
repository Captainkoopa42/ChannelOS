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
Trigger = Literal["breakpoint", "interval", "between_programs", "calendar_boundary", "fixed_slot"]
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
    media_path: str = ""
    original_duration_seconds: float | None = None
    event_type: str = "advertisement"

    def __post_init__(self) -> None:
        values = (self.start_offset_seconds, self.source_offset_seconds,
                  self.duration_seconds, self.trimmed_seconds)
        if not self.asset_id or any(not math.isfinite(float(x)) for x in values):
            raise ValueError("planned segment requires an ID and finite timing values")
        if self.start_offset_seconds < 0 or self.source_offset_seconds < 0:
            raise ValueError("planned segment offsets cannot be negative")
        if self.duration_seconds <= 0 or self.trimmed_seconds < 0:
            raise ValueError("planned segment duration must be positive and trim non-negative")
        if self.event_type not in {"advertisement", "transition", "filler"}:
            raise ValueError("unsupported planned segment type")


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
    transition_behavior: str = "cut"
    transition_seconds: float = 0.5
    trigger: str = "breakpoint"
    profile_id: str | None = None
    policy_revision: str = ""
    content_cut_seconds: float = 0.0
    cut_target_occurrence_id: str = ""
    cut_source: str = "none"

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
        if self.transition_behavior not in {"cut", "fade", "hold"}:
            raise ValueError("unsupported plan transition behavior")
        if not math.isfinite(self.transition_seconds) or not 0 <= self.transition_seconds <= 10:
            raise ValueError("invalid plan transition duration")
        if not math.isfinite(self.content_cut_seconds) or self.content_cut_seconds < 0:
            raise ValueError("invalid plan content cut")
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
                if len(offsets) >= 10000:
                    raise ValueError("a program cannot generate more than 10000 break opportunities")
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
        if budget_seconds <= 0 and not (timing_policy == "expand" and expand_max_seconds > 0):
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

        if strategy == "best_fit" and timing_policy == "strict_fit" and len(pool) <= 14:
            # Exact bounded subset search. A greedy longest-first decision can
            # waste a gap even when a perfect combination is available.
            # Above the bound, use the existing deterministic greedy fallback.
            best_mask = 0
            best_total = 0.0
            best_count = 0
            sizes = [item.duration_seconds for item in pool]
            for mask in range(1, 1 << len(pool)):
                total = sum(size for index, size in enumerate(sizes) if mask & (1 << index))
                if total > selection_budget + 0.001:
                    continue
                count = mask.bit_count()
                if (total > best_total + 0.001
                        or (abs(total - best_total) <= 0.001
                            and (count < best_count or best_mask == 0))
                        or (abs(total - best_total) <= 0.001
                            and count == best_count and mask < best_mask)):
                    best_mask = mask
                    best_total = total
                    best_count = count
            selected_pool = [
                item for index, item in enumerate(pool)
                if best_mask & (1 << index)
            ]
            start_offset = 0.0
            result: list[PlannedSegment] = []
            for item in selected_pool:
                result.append(PlannedSegment(
                    item.asset_id, start_offset, 0.0, item.duration_seconds,
                ))
                start_offset += item.duration_seconds
            return tuple(result)

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
            CREATE TABLE IF NOT EXISTS ad_plan_metadata (
                plan_id TEXT PRIMARY KEY REFERENCES ad_break_plans(plan_id) ON DELETE CASCADE,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ad_break_history_asset
                ON ad_break_history(asset_id);
            CREATE TABLE IF NOT EXISTS ad_view_history (
                plan_id TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                viewer_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                consumed_seconds REAL NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (plan_id, segment_index, viewer_id),
                FOREIGN KEY (plan_id) REFERENCES ad_break_plans(plan_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ad_view_history_asset
                ON ad_view_history(asset_id);
            CREATE TABLE IF NOT EXISTS ad_view_progress (
                plan_id TEXT NOT NULL REFERENCES ad_break_plans(plan_id),
                segment_index INTEGER NOT NULL,
                viewer_id TEXT NOT NULL,
                ranges_json TEXT NOT NULL,
                consumed_seconds REAL NOT NULL,
                last_watched_at TEXT NOT NULL,
                PRIMARY KEY(plan_id, segment_index, viewer_id)
            );
            CREATE TABLE IF NOT EXISTS ad_break_policy_state (
                channel_number INTEGER PRIMARY KEY,
                policy_revision TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ad_break_catchup_state (
                channel_number INTEGER PRIMARY KEY,
                policy_revision TEXT NOT NULL,
                content_cursor_utc TEXT NOT NULL,
                activated_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ad_program_clock (
                occurrence_id TEXT PRIMARY KEY,
                channel_number INTEGER NOT NULL,
                content_start TEXT NOT NULL,
                content_end TEXT NOT NULL,
                broadcast_start TEXT NOT NULL,
                broadcast_end TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ad_program_clock_channel
                ON ad_program_clock(channel_number, broadcast_start);
            CREATE TABLE IF NOT EXISTS ad_retired_plans (
                plan_id TEXT PRIMARY KEY REFERENCES ad_break_plans(plan_id),
                retired_at TEXT NOT NULL
            );
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def reset_program_clock(self, channel_number: int, *, at: datetime) -> None:
        """Archive old-schedule decisions while retaining their existing ledgers."""
        with self.connection:
            self.connection.execute("""
                INSERT OR IGNORE INTO ad_retired_plans
                SELECT plan_id, ? FROM ad_break_plans WHERE channel_number = ?
            """, (_utc(at).isoformat(), channel_number))
            self.connection.execute("DELETE FROM ad_program_clock WHERE channel_number = ?", (channel_number,))
            self.connection.execute("DELETE FROM ad_break_catchup_state WHERE channel_number = ?", (channel_number,))


    def ensure_catchup_cursor(
        self, channel_number: int, revision: str, *,
        start_at: datetime, activated_at: datetime,
    ) -> datetime:
        """Maintain a durable content-clock checkpoint for missed programs.

        A profile revision begins at its activation date rather than
        retroactively generating advertisements before the policy existed.
        """
        content = _utc(start_at).isoformat()
        activated = _utc(activated_at).isoformat()
        row = self.connection.execute(
            "SELECT policy_revision, content_cursor_utc FROM ad_break_catchup_state "
            "WHERE channel_number = ?", (int(channel_number),),
        ).fetchone()
        if row is not None and str(row[0]) == revision:
            return _utc(datetime.fromisoformat(str(row[1])))
        self.connection.execute("""
            INSERT INTO ad_break_catchup_state (
                channel_number, policy_revision, content_cursor_utc, activated_at_utc
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_number) DO UPDATE SET
                policy_revision = excluded.policy_revision,
                content_cursor_utc = excluded.content_cursor_utc,
                activated_at_utc = excluded.activated_at_utc
        """, (int(channel_number), revision, content, activated))
        self.connection.commit()
        return _utc(start_at)

    def catchup_cursor(self, channel_number: int) -> datetime | None:
        row = self.connection.execute(
            "SELECT content_cursor_utc FROM ad_break_catchup_state "
            "WHERE channel_number = ?", (int(channel_number),),
        ).fetchone()
        return None if row is None else _utc(datetime.fromisoformat(str(row[0])))

    def advance_catchup_cursor(
        self, channel_number: int, cursor: datetime,
    ) -> None:
        self.connection.execute("""
            UPDATE ad_break_catchup_state
            SET content_cursor_utc = ?
            WHERE channel_number = ?
              AND content_cursor_utc < ?
        """, (
            _utc(cursor).isoformat(), int(channel_number),
            _utc(cursor).isoformat(),
        ))
        self.connection.commit()

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
                    DELETE FROM ad_program_clock
                    WHERE channel_number = ? AND broadcast_start > ?
                """, (int(channel_number), updated))
                self.connection.execute("""
                    DELETE FROM ad_break_plans
                    WHERE channel_number = ?
                      AND scheduled_at > ?
                      AND plan_id NOT IN (
                          SELECT DISTINCT plan_id FROM ad_break_history
                      )
                      AND plan_id NOT IN (
                          SELECT DISTINCT plan_id FROM ad_view_history
                      )
                      AND plan_id NOT IN (
                          SELECT DISTINCT plan_id FROM ad_view_progress
                      )
                      AND plan_id NOT IN (SELECT plan_id FROM ad_retired_plans)
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
            inserted = self.connection.execute("""
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
            self.connection.execute(
                "INSERT OR IGNORE INTO ad_plan_metadata VALUES (?, ?)",
                (stored.plan_id, json.dumps({key: getattr(plan if inserted.rowcount else stored, key) for key in (
                    "transition_behavior", "transition_seconds", "trigger", "profile_id", "policy_revision",
                    "content_cut_seconds", "cut_target_occurrence_id", "cut_source"
                )}, sort_keys=True)),
            )
            stored = self._with_metadata(stored)
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
        if segments[segment_index].get("event_type", "advertisement") != "advertisement":
            raise ValueError("transition events are not advertisement airings")
        cursor = self.connection.execute("""
            INSERT OR IGNORE INTO ad_break_history
            (plan_id, segment_index, asset_id, aired_at) VALUES (?, ?, ?, ?)
        """, (plan_id, segment_index, asset_id, _utc(aired_at).isoformat()))
        self.connection.commit()
        return cursor.rowcount == 1

    def reconcile_completed(self, channel_number: int, *, through: datetime) -> int:
        """Catch up durable completed-airing entries for already committed plans.

        Reads completed segment identities in one query, avoiding reloading the
        entire plans table and rechecking all existing rows one at a time on
        every Tune/Guide projection. No viewer count is changed by this action.
        """
        instant = _utc(through)
        rows = self.connection.execute("""
            SELECT plan_id, scheduled_at, payload FROM ad_break_plans
            WHERE channel_number = ? AND scheduled_at <= ?
              AND plan_id NOT IN (SELECT plan_id FROM ad_retired_plans)
            ORDER BY scheduled_at, plan_id
        """, (int(channel_number), instant.isoformat())).fetchall()
        if not rows:
            return 0
        completed = {
            (str(row[0]), int(row[1]))
            for row in self.connection.execute("""
                SELECT h.plan_id, h.segment_index FROM ad_break_history h
                JOIN ad_break_plans p ON p.plan_id = h.plan_id
                WHERE p.channel_number = ?
            """, (int(channel_number),))
        }
        recorded = 0
        for plan_id, start_text, payload in rows:
            starts_at = _utc(datetime.fromisoformat(str(start_text)))
            for index, segment in enumerate(json.loads(payload)):
                if segment.get("event_type", "advertisement") != "advertisement":
                    continue
                if (str(plan_id), index) in completed:
                    continue
                ended_at = starts_at + timedelta(
                    seconds=float(segment["start_offset_seconds"])
                    + float(segment["duration_seconds"])
                )
                if ended_at > instant:
                    continue
                if self.record_aired(
                    str(plan_id), index, str(segment["asset_id"]), aired_at=ended_at
                ):
                    recorded += 1
        return recorded

    def record_viewed(
        self, plan_id: str, segment_index: int, asset_id: str, *,
        viewer_id: str = "default", consumed_seconds: float,
        completed_at: datetime,
    ) -> bool:
        """Record a verified *viewer* completion, separate from logical airing.

        The caller must establish genuine playback consumption, not merely
        observe a broadcast timestamp or seek into a segment.
        """
        plan = self.load_plan(plan_id)
        if plan is None:
            raise KeyError(f"unknown ad plan: {plan_id}")
        if segment_index < 0 or segment_index >= len(plan.segments):
            raise IndexError("unknown segment index")
        segment = plan.segments[segment_index]
        if segment.event_type != "advertisement":
            raise ValueError("transition events are not viewer advertisement completions")
        if asset_id != segment.asset_id:
            raise ValueError("viewer asset must match committed plan")
        if not viewer_id:
            raise ValueError("viewer ID cannot be empty")
        if not math.isfinite(float(consumed_seconds)) or (
            consumed_seconds < segment.duration_seconds - 0.5
            or consumed_seconds > segment.duration_seconds + 0.5
        ):
            raise ValueError("viewed completion requires verified full-duration consumption")
        cursor = self.connection.execute("""
            INSERT OR IGNORE INTO ad_view_history (
                plan_id, segment_index, viewer_id, asset_id,
                consumed_seconds, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            plan_id, segment_index, viewer_id, asset_id,
            float(consumed_seconds), _utc(completed_at).isoformat(),
        ))
        self.connection.commit()
        return cursor.rowcount == 1

    def viewing_ranges(self, plan_id: str, segment_index: int, viewer_id: str = "default"):
        row = self.connection.execute(
            "SELECT ranges_json FROM ad_view_progress WHERE plan_id = ? AND segment_index = ? AND viewer_id = ?",
            (plan_id, segment_index, viewer_id),
        ).fetchone()
        return [] if row is None else [tuple(item) for item in json.loads(row[0])]

    def save_viewing_progress(self, plan_id: str, segment_index: int, *, viewer_id: str,
                             ranges, watched_at: datetime) -> float:
        plan = self.load_plan(plan_id)
        if plan is None or not 0 <= segment_index < len(plan.segments):
            raise ValueError("unknown viewing segment")
        segment = plan.segments[segment_index]
        if segment.event_type != "advertisement" or not viewer_id:
            raise ValueError("viewing progress requires an advertisement and viewer")
        merged = []
        for start, end in sorted([*self.viewing_ranges(plan_id, segment_index, viewer_id), *ranges]):
            if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start <= end <= segment.duration_seconds:
                raise ValueError("viewing coverage must be inside the advertisement")
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            elif end > start:
                merged.append((start, end))
        consumed = sum(end - start for start, end in merged)
        self.connection.execute("""
            INSERT INTO ad_view_progress VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id, segment_index, viewer_id) DO UPDATE SET
                ranges_json = excluded.ranges_json, consumed_seconds = excluded.consumed_seconds,
                last_watched_at = excluded.last_watched_at
        """, (plan_id, segment_index, viewer_id, json.dumps(merged), consumed, _utc(watched_at).isoformat()))
        self.connection.commit()
        return consumed

    def viewer_counts(self, channel_number: int | None = None) -> dict[str, int]:
        query = """
            SELECT h.asset_id, COUNT(*) FROM ad_view_history h
            JOIN ad_break_plans p ON p.plan_id = h.plan_id
        """
        params: tuple[int, ...] = ()
        if channel_number is not None:
            query += " WHERE p.channel_number = ?"
            params = (int(channel_number),)
        query += " GROUP BY h.asset_id"
        return {
            str(asset_id): int(count)
            for asset_id, count in self.connection.execute(query, params)
        }

    def diagnostics(self, channel_number: int) -> dict[str, object]:
        number = int(channel_number)
        plans = self.connection.execute(
            "SELECT COUNT(*) FROM ad_break_plans WHERE channel_number = ?",
            (number,),
        ).fetchone()[0]
        aired = self.connection.execute("""
            SELECT COUNT(*), MAX(h.aired_at) FROM ad_break_history h
            JOIN ad_break_plans p ON p.plan_id = h.plan_id
            WHERE p.channel_number = ?
        """, (number,)).fetchone()
        viewed = self.connection.execute("""
            SELECT COUNT(*) FROM ad_view_history h
            JOIN ad_break_plans p ON p.plan_id = h.plan_id
            WHERE p.channel_number = ?
        """, (number,)).fetchone()[0]
        progress = self.connection.execute("""
            SELECT v.consumed_seconds, v.segment_index, p.payload, v.last_watched_at
            FROM ad_view_progress v JOIN ad_break_plans p ON p.plan_id = v.plan_id
            WHERE p.channel_number = ?
        """, (number,)).fetchall()
        return {
            "channelNumber": number,
            "plannedBreaks": int(plans),
            "completedAirings": int(aired[0]),
            "completedViewings": int(viewed),
            "lastAiredUtc": aired[1] or "",
            "viewerCounts": self.viewer_counts(number),
            "airedCounts": self.play_counts(number),
            "lastWatchedUtc": max((row[3] for row in progress), default=""),
            "viewerCompletionRate": (sum(row[0] / json.loads(row[2])[row[1]]["duration_seconds"]
                                         for row in progress) / len(progress)) if progress else 0.0,
        }

    def play_counts(self, channel_number: int | None = None) -> dict[str, int]:
        query = """SELECT h.asset_id, COUNT(*) FROM ad_break_history h
                   JOIN ad_break_plans p ON p.plan_id = h.plan_id"""
        params = () if channel_number is None else (int(channel_number),)
        if channel_number is not None:
            query += " WHERE p.channel_number = ?"
        rows = self.connection.execute(query + " GROUP BY h.asset_id", params).fetchall()
        return {str(asset): int(count) for asset, count in rows}

    def rotation_counts(self, channel_number: int, *, before: datetime) -> dict[str, int]:
        """Count committed reservations before a new break, never viewer activity.

        A future Guide projection and a live tune must make identical rotation
        decisions. Reservations are intentionally distinct from the airing ledger.
        """
        result = {str(asset): int(count) for asset, count in self.connection.execute("""
            SELECT h.asset_id, COUNT(*) FROM ad_break_history h
            JOIN ad_retired_plans r ON h.plan_id = r.plan_id
            JOIN ad_break_plans p ON p.plan_id = h.plan_id WHERE p.channel_number = ?
            GROUP BY h.asset_id
        """, (channel_number,))}
        for (payload,) in self.connection.execute(
            "SELECT payload FROM ad_break_plans WHERE channel_number = ? "
            "AND scheduled_at < ? AND plan_id NOT IN (SELECT plan_id FROM ad_retired_plans) ORDER BY scheduled_at, plan_id",
            (int(channel_number), _utc(before).isoformat()),
        ):
            for segment in json.loads(payload):
                if segment.get("event_type", "advertisement") != "advertisement":
                    continue
                asset_id = segment["asset_id"]
                result[asset_id] = result.get(asset_id, 0) + 1
        return result

    def save_program_clock(self, occurrence_id: str, channel_number: int, *,
                           content_start: datetime, content_end: datetime,
                           broadcast_start: datetime, broadcast_end: datetime) -> None:
        self.connection.execute("""
            INSERT INTO ad_program_clock VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(occurrence_id) DO UPDATE SET
                broadcast_end = excluded.broadcast_end
        """, (occurrence_id, int(channel_number), _utc(content_start).isoformat(),
              _utc(content_end).isoformat(), _utc(broadcast_start).isoformat(),
              _utc(broadcast_end).isoformat()))
        self.connection.commit()

    def program_clock(self, occurrence_id: str) -> tuple[datetime, datetime] | None:
        row = self.connection.execute(
            "SELECT broadcast_start, broadcast_end FROM ad_program_clock WHERE occurrence_id = ?",
            (occurrence_id,),
        ).fetchone()
        return None if row is None else tuple(_utc(datetime.fromisoformat(x)) for x in row)

    def preceding_program_end(self, channel_number: int, content_start: datetime) -> datetime | None:
        row = self.connection.execute(
            "SELECT broadcast_end FROM ad_program_clock WHERE channel_number = ? "
            "AND content_end <= ? ORDER BY content_end DESC LIMIT 1",
            (int(channel_number), _utc(content_start).isoformat()),
        ).fetchone()
        return None if row is None else _utc(datetime.fromisoformat(row[0]))

    def clock_at(self, channel_number: int, at: datetime):
        row = self.connection.execute(
            "SELECT occurrence_id, content_start, content_end, broadcast_start, broadcast_end "
            "FROM ad_program_clock WHERE channel_number = ? AND broadcast_start <= ? "
            "AND broadcast_end > ? ORDER BY broadcast_start DESC LIMIT 1",
            (int(channel_number), _utc(at).isoformat(), _utc(at).isoformat()),
        ).fetchone()
        return None if row is None else (str(row[0]), *(_utc(datetime.fromisoformat(x)) for x in row[1:]))

    def content_cuts(self, occurrence_id: str) -> tuple[float, float]:
        head = tail = 0.0
        for (payload,) in self.connection.execute(
            "SELECT payload FROM ad_plan_metadata WHERE json_extract(payload, '$.cut_target_occurrence_id') = ?",
            (occurrence_id,),
        ):
            item = json.loads(payload)
            if item.get("cut_source") == "next_event":
                head += float(item.get("content_cut_seconds", 0))
            else:
                tail += float(item.get("content_cut_seconds", 0))
        return head, tail

    def policy_activation(self, channel_number: int) -> datetime | None:
        row = self.connection.execute(
            "SELECT activated_at_utc FROM ad_break_catchup_state WHERE channel_number = ?",
            (int(channel_number),),
        ).fetchone()
        return None if row is None else _utc(datetime.fromisoformat(row[0]))

    def load_opportunity(self, opportunity_id: str) -> BreakPlan | None:
        """Recover the immutable committed plan for an opportunity after restart."""
        row = self.connection.execute("""
            SELECT plan_id, opportunity_id, occurrence_id, channel_number,
                   scheduled_at, reserved_seconds, strategy, timing_policy, payload
            FROM ad_break_plans WHERE opportunity_id = ?
        """, (str(opportunity_id),)).fetchone()
        if row is None:
            return None
        return self._with_metadata(BreakPlan(
            str(row[0]), str(row[1]), str(row[2]), int(row[3]),
            datetime.fromisoformat(str(row[4])), float(row[5]),
            tuple(PlannedSegment(**item) for item in json.loads(row[8])),
            str(row[6]), str(row[7]),
        ))

    def load_plan(self, plan_id: str) -> BreakPlan | None:
        """Recover a plan by its stable plan ID."""
        row = self.connection.execute("""
            SELECT plan_id, opportunity_id, occurrence_id, channel_number,
                   scheduled_at, reserved_seconds, strategy, timing_policy, payload
            FROM ad_break_plans WHERE plan_id = ?
        """, (str(plan_id),)).fetchone()
        if row is None:
            return None
        return self._with_metadata(BreakPlan(
            str(row[0]), str(row[1]), str(row[2]), int(row[3]),
            datetime.fromisoformat(str(row[4])), float(row[5]),
            tuple(PlannedSegment(**item) for item in json.loads(row[8])),
            str(row[6]), str(row[7]),
        ))

    def _with_metadata(self, plan: BreakPlan) -> BreakPlan:
        from dataclasses import replace
        row = self.connection.execute(
            "SELECT payload FROM ad_plan_metadata WHERE plan_id = ?", (plan.plan_id,)
        ).fetchone()
        return plan if row is None else replace(plan, **json.loads(row[0]))

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
              AND plan_id NOT IN (SELECT plan_id FROM ad_retired_plans)
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
              AND plan_id NOT IN (SELECT plan_id FROM ad_retired_plans)
            ORDER BY scheduled_at DESC, plan_id
        """, (int(channel_number), instant.isoformat())).fetchall()
        for row in rows:
            plan = self.load_plan(str(row[0]))
            if plan is not None and instant < (
                plan.scheduled_at + timedelta(seconds=plan.duration_seconds)
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
