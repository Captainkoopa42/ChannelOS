from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ad_breaks import PlannedAd
from .ad_break_engine import (
    BreakPlan, BreakPlanStore, PlannedSegment, ProgramOccurrence,
)
from .ad_scheduling import calendar_gap_policy, eligible_media, program_opportunities, snapshot_segments, select_segments, indexed_media_for_segment
from .library import IndexedMedia
from .models import AdvertisingDefinition, CalendarBlockDefinition
from .resolve import ResolvedChannel
from .storage import (
    SQLITE_BUSY_TIMEOUT_MS,
    configure_sqlite_connection,
    prepare_database,
)

RUNTIME_SCHEMA_VERSION = 2
SECONDS_PER_DAY = 86400.0
DEFAULT_VIEWER_ID = "default"


class _ClosingSQLiteConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


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
class BroadcastEvent:
    """One typed segment occupying a bounded interval on the broadcast clock."""

    event_id: str
    event_type: str
    asset_id: str
    start_utc: datetime
    end_utc: datetime
    source_offset_seconds: float
    parent_program_id: str | None = None
    break_id: str | None = None
    parent_program_asset_id: str | None = None
    parent_program_started_at: datetime | None = None
    parent_program_ends_at: datetime | None = None
    program_occurrence_id: str | None = None
    break_occurrence_id: str | None = None
    source_offset_end_seconds: float = 0.0
    segment_id: str = ""


@dataclass(frozen=True, slots=True)
class BroadcastSelection:
    program: ScheduledProgram
    offset_seconds: float
    program_started_at: datetime
    program_ends_at: datetime
    cycle_index: int
    origin: str = "cycle"
    parent_program_id: str | None = None
    break_id: str | None = None
    parent_program_asset_id: str | None = None
    parent_program_started_at: datetime | None = None
    parent_program_ends_at: datetime | None = None
    program_occurrence_id: str | None = None
    break_occurrence_id: str | None = None
    segment_started_at: datetime | None = None
    segment_ends_at: datetime | None = None
    segment_source_offset_seconds: float = 0.0

    @property
    def media(self) -> IndexedMedia:
        return self.program.media

    @property
    def event(self) -> BroadcastEvent:
        event_type = self.origin if self.origin in {"advertisement", "transition"} else (
            "filler" if self.origin in {"filler", "show-filler"} else "program"
        )
        identity = hashlib.sha256("|".join((
            event_type,
            self.media.asset.asset_id,
            (
                self.program_occurrence_id
                if event_type != "advertisement" and self.program_occurrence_id
                else self.program_started_at.isoformat(timespec="microseconds")
            ),
            self.break_id or "",
        )).encode("utf-8")).hexdigest()
        return BroadcastEvent(
            event_id=identity,
            event_type=event_type,
            asset_id=self.media.asset.asset_id,
            start_utc=self.segment_started_at or self.program_started_at,
            end_utc=self.segment_ends_at or self.program_ends_at,
            source_offset_seconds=self.segment_source_offset_seconds,
            source_offset_end_seconds=self.segment_source_offset_seconds + (0.0 if event_type == "transition" else (
                (self.segment_ends_at or self.program_ends_at) -
                (self.segment_started_at or self.program_started_at)
            ).total_seconds()),
            segment_id=hashlib.sha256((identity + ":" + (
                self.segment_started_at or self.program_started_at
            ).isoformat()).encode()).hexdigest(),
            parent_program_id=self.parent_program_id,
            break_id=self.break_id,
            parent_program_asset_id=self.parent_program_asset_id,
            parent_program_started_at=self.parent_program_started_at,
            parent_program_ends_at=self.parent_program_ends_at,
            program_occurrence_id=self.program_occurrence_id,
            break_occurrence_id=self.break_occurrence_id,
        )


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


class CalendarTimeline:
    """Fixed Studio calendar blocks with the normal channel cycle as filler."""

    def __init__(
        self,
        media: tuple[IndexedMedia, ...],
        filler_media: tuple[IndexedMedia, ...],
        calendar: tuple[CalendarBlockDefinition, ...],
        *,
        channel_number: int,
        ad_media: tuple[IndexedMedia, ...] = (),
        advertising: AdvertisingDefinition | None = None,
        library=None,
    ) -> None:
        self.filler = SequentialTimeline(filler_media)
        self.cycle_duration_seconds = self.filler.cycle_duration_seconds
        self.ad_media = tuple(
            item for item in ad_media
            if item.asset.duration_seconds is not None
            and float(item.asset.duration_seconds) > 0.0
        )
        self.advertising = advertising or AdvertisingDefinition()
        self.library = library
        self.channel_number = int(channel_number)
        self.break_store: BreakPlanStore | None = None
        self.ad_revision = ""
        self._ad_plan_cache: dict[tuple[datetime, datetime], tuple] = {}
        self._ad_plan_ids: dict[tuple[datetime, datetime], str] = {}
        self._mid_plan_cache: dict[int, tuple[BreakPlan, ...]] = {}
        by_asset = {item.asset.asset_id: item for item in media}

        programs: list[ScheduledProgram] = []
        gap_fillers: list[SequentialTimeline | None] = []
        starts: list[datetime] = []
        ends: list[datetime] = []
        previous_end: datetime | None = None
        for index, block in enumerate(calendar):
            try:
                item = by_asset[block.asset_id]
            except KeyError as exc:
                raise ChannelRuntimeError(
                    "calendar block references media that is not online or is "
                    f"outside the channel sources: {block.asset_id}"
                ) from exc
            duration = item.asset.duration_seconds
            if duration is None or duration <= 0:
                raise ChannelRuntimeError(
                    "Broadcast Clock requires positive media durations. "
                    f"Re-scan before scheduling: {item.location.path}"
                )
            start = require_aware_utc(block.start_utc)
            end = start + timedelta(seconds=float(duration))
            if previous_end is not None and start < previous_end:
                raise ChannelRuntimeError(
                    "calendar blocks overlap; move or remove the block beginning "
                    f"at {start.isoformat()}"
                )
            programs.append(
                ScheduledProgram(
                    media=item,
                    index=index,
                    duration_seconds=float(duration),
                )
            )
            if block.filler is None:
                gap_fillers.append(None)
            else:
                filler_items: list[IndexedMedia] = []
                for asset_id in block.filler.asset_ids:
                    try:
                        filler_items.append(by_asset[asset_id])
                    except KeyError as exc:
                        raise ChannelRuntimeError(
                            "show-specific filler references media that is not "
                            "online or is outside the channel sources: "
                            f"{asset_id}"
                        ) from exc
                ordered_filler = tuple(filler_items)
                if block.filler.mode == "shuffle":
                    ordered_filler = deterministic_media_order(
                        channel_number=channel_number,
                        media=ordered_filler,
                        namespace=(
                            "show-filler:"
                            + block.start_utc.isoformat(timespec="microseconds")
                        ),
                    )
                gap_fillers.append(SequentialTimeline(ordered_filler))
            starts.append(start)
            ends.append(end)
            previous_end = end

        if not programs:
            raise ChannelRuntimeError(
                "calendar programming requires at least one fixed block"
            )
        self.programs = tuple(programs)
        self._gap_fillers = tuple(gap_fillers)
        self._starts = tuple(starts)
        self._ends = tuple(ends)

    def _calendar_occurrence_id(self, index: int) -> str:
        return hashlib.sha256(f"calendar:{self.channel_number}:{self.programs[index].media.asset.asset_id}:{self._starts[index].isoformat()}".encode()).hexdigest()

    def _calendar_program_end(self, index: int, plans) -> datetime:
        cuts = sum(self.break_store.content_cuts(self._calendar_occurrence_id(index))) if self.break_store else 0.0
        return self._ends[index] + timedelta(seconds=sum(p.duration_seconds for p in plans) - cuts)

    def _calendar_mid_plans(self, index: int) -> tuple[BreakPlan, ...]:
        if index in self._mid_plan_cache:
            return self._mid_plan_cache[index]
        start, natural_end = self._starts[index], self._ends[index]
        asset_id = self.programs[index].media.asset.asset_id
        occurrence_id = hashlib.sha256(
            f"calendar:{self.channel_number}:{asset_id}:{start.isoformat()}".encode()
        ).hexdigest()
        existing = list(self.break_store.plans_for_occurrence(occurrence_id)) if self.break_store else []
        next_start = self._starts[index + 1] if index + 1 < len(self._starts) else None
        slack = max(0.0, (next_start - natural_end).total_seconds()) if next_start else float("inf")
        inserted = 0.0
        opportunities = program_opportunities(self.advertising, ProgramOccurrence(
            occurrence_id, self.channel_number, asset_id, start, natural_end,
        ), self.ad_revision)
        for opportunity, settings in opportunities:
            if opportunity.trigger not in {"breakpoint", "interval"}:
                continue
            content_offset = (opportunity.scheduled_at - start).total_seconds()
            inserted = 0.0
            elapsed = 0.0
            previous = None
            for saved in sorted(existing, key=lambda p: p.scheduled_at):
                saved_offset = (saved.scheduled_at - start).total_seconds() - elapsed
                if saved_offset < content_offset - .001:
                    inserted += saved.duration_seconds
                elif abs(saved_offset - content_offset) < .001:
                    previous = saved
                elapsed += saved.duration_seconds
            expected = opportunity.scheduled_at + timedelta(seconds=inserted)
            if previous is not None:
                continue
            activation = self.break_store.policy_activation(self.channel_number) if self.break_store else None
            if activation is not None and expected < activation:
                continue
            cuts = sum(self.break_store.content_cuts(occurrence_id)) if self.break_store else sum(p.content_cut_seconds for p in existing)
            source_position = (opportunity.scheduled_at - start).total_seconds()
            available_content = (natural_end - start).total_seconds() - source_position - cuts - .001
            if available_content <= 0:
                continue
            budget = min(opportunity.duration_seconds, max(0.0, slack - inserted + cuts))
            extra = 0.0
            if settings.timing_policy == "expand" and settings.schedule_priority != "fixed":
                if settings.expand_source == "current_program" and settings.schedule_priority == "advertising":
                    extra = min(settings.expand_max_seconds, available_content)
                else:
                    budget = min(opportunity.duration_seconds + settings.expand_max_seconds,
                                 max(0.0, slack - inserted + cuts))
            if budget <= .001 and extra <= .001:
                continue
            media = eligible_media(self.ad_media, settings)
            effective_timing = "expand" if extra > 0 else ("smoosh" if settings.timing_policy == "smoosh" else "strict_fit")
            segments = select_segments(media, budget, replace(settings, timing_policy=effective_timing),
                expand_max_seconds=extra, seed=opportunity.opportunity_id,
                counts=self.break_store.rotation_counts(self.channel_number, before=expected) if self.break_store else None,
            )
            actual = max((part.start_offset_seconds + part.duration_seconds for part in segments), default=0.0)
            cut = max(0.0, actual - budget) if extra else 0.0
            plan = BreakPlan(
                hashlib.sha256(opportunity.opportunity_id.encode()).hexdigest(),
                opportunity.opportunity_id, occurrence_id, self.channel_number,
                expected, max(budget, actual, .001), segments, settings.selection_strategy, effective_timing,
                content_cut_seconds=cut, cut_target_occurrence_id=occurrence_id if cut else "",
                cut_source="current_program" if cut else "none",
                transition_behavior=settings.transition_behavior, transition_seconds=settings.transition_seconds,
                trigger=opportunity.trigger, profile_id=settings.profile_id, policy_revision=self.ad_revision,
            )
            if self.break_store:
                plan = self.break_store.commit(plan)
            existing.append(plan)
            inserted += plan.duration_seconds
        result = tuple(sorted(existing, key=lambda p: p.scheduled_at))
        if sum(p.duration_seconds - p.content_cut_seconds for p in result) > slack + .001:
            raise ChannelRuntimeError("persisted calendar break crosses a protected program start")
        self._mid_plan_cache[index] = result
        return result

    def catch_up_through(self, epoch: datetime, instant: datetime) -> None:
        """Generate calendar decisions in airing order, including untuned gaps."""
        if self.break_store is None:
            return
        activation = self.break_store.policy_activation(self.channel_number) or epoch
        cursor = self.break_store.catchup_cursor(self.channel_number) or activation
        first = max(0, bisect_right(self._starts, cursor) - 1)
        last = min(len(self._starts), bisect_right(self._starts, instant))
        if last - first > 10000:
            raise ChannelRuntimeError("calendar catch-up exceeds 10000 occurrences")
        for index in range(first, last):
            plans = self._calendar_mid_plans(index)
            end = self._calendar_program_end(index, plans)
            if index + 1 < len(self._starts) and end < self._starts[index + 1] and end <= instant:
                key = (end, self._starts[index + 1])
                if key not in self._ad_plan_cache and self._gap_settings() is not None:
                    self._ad_plan_cache[key] = self._calendar_ad_plan(*key)
            if index + 1 < len(self._starts) and self._starts[index + 1] <= instant:
                self.break_store.advance_catchup_cursor(self.channel_number, self._starts[index + 1])

    def _gap_settings(self):
        return calendar_gap_policy(self.advertising)

    def _calendar_ad_plan(self, gap_anchor: datetime, next_start: datetime) -> tuple[PlannedAd, ...]:
        """Persist fixed-gap decisions before projecting them onto the broadcast clock."""
        gap_settings = self._gap_settings() or ("default", "calendar_boundary", self.advertising)
        identity, trigger, settings = gap_settings
        budget = (next_start - gap_anchor).total_seconds()
        if self.advertising.placements and trigger == "between_programs":
            budget = min(budget, settings.break_duration_seconds)
        if trigger == "fixed_slot" and settings.slot_seconds:
            import math
            edge = math.ceil((gap_anchor.timestamp() + 1e-6) / settings.slot_seconds) * settings.slot_seconds
            budget = min(budget, edge - gap_anchor.timestamp())
        seed = (
            f"channel:{self.channel_number}:"
            f"{gap_anchor.isoformat(timespec='microseconds')}:"
            f"{next_start.isoformat(timespec='microseconds')}"
        )
        opportunity_id = hashlib.sha256(
            f"{seed}:{self.ad_revision}".encode("utf-8")
        ).hexdigest()
        stored = (
            self.break_store.load_opportunity(opportunity_id)
            if self.break_store is not None else None
        )
        if stored is None and self.break_store is not None:
            # A changed policy must not replace the plan of a gap that has
            # already started. The occurrence ID is independent of revision.
            occurrence_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
            for previous in self.break_store.plans_for_occurrence(occurrence_id):
                if previous.scheduled_at == gap_anchor:
                    stored = previous
                    break
        if stored is None:
            if not self.advertising.enabled:
                return ()
            activation = self.break_store.policy_activation(self.channel_number) if self.break_store else None
            if activation is not None and gap_anchor < activation:
                return ()
            media = eligible_media(self.ad_media, settings)
            selected = select_segments(media, budget, replace(settings,
                timing_policy="smoosh" if settings.timing_policy == "smoosh" else "strict_fit"),
                seed=seed,
                counts=self.break_store.rotation_counts(self.channel_number, before=gap_anchor) if self.break_store else None,
            )
            if self.break_store is None:
                segments = selected
            else:
                stored = self.break_store.commit(BreakPlan(
                    plan_id=opportunity_id,
                    opportunity_id=opportunity_id,
                    occurrence_id=hashlib.sha256(seed.encode("utf-8")).hexdigest(),
                    channel_number=self.channel_number,
                    scheduled_at=gap_anchor,
                    reserved_seconds=budget,
                    segments=selected,
                    transition_behavior=settings.transition_behavior, transition_seconds=settings.transition_seconds,
                    trigger=trigger, profile_id=settings.profile_id, policy_revision=self.ad_revision,
                    strategy=settings.selection_strategy,
                    timing_policy=(
                        "smoosh" if settings.timing_policy == "smoosh"
                        else "strict_fit"
                    ),
                ))
                segments = stored.segments
        else:
            segments = stored.segments
        self._ad_plan_ids[(gap_anchor, next_start)] = (
            stored.plan_id if stored is not None else opportunity_id
        )
        return tuple(
            PlannedAd(
                media=indexed_media_for_segment(segment, self.ad_media, self.library),
                start_offset_seconds=segment.start_offset_seconds,
                duration_seconds=segment.duration_seconds,
                event_type=segment.event_type, source_offset_seconds=segment.source_offset_seconds,
            )
            for segment in segments
        )

    def selection_at(self, epoch: datetime, at: datetime) -> BroadcastSelection:
        epoch_utc = require_aware_utc(epoch)
        at_utc = require_aware_utc(at)
        insertion = bisect_right(self._starts, at_utc)
        previous_index = insertion - 1

        mid_plans = (
            self._calendar_mid_plans(previous_index)
            if previous_index >= 0 else ()
        )
        calendar_end = (
            self._calendar_program_end(previous_index, mid_plans)
            if previous_index >= 0 else epoch_utc
        )
        if previous_index >= 0 and at_utc < calendar_end:
            program = self.programs[previous_index]
            start = self._starts[previous_index]
            elapsed_in_breaks = 0.0
            for plan in mid_plans:
                plan_end = plan.scheduled_at + timedelta(seconds=plan.duration_seconds)
                if plan.scheduled_at <= at_utc < plan_end:
                    position = (at_utc - plan.scheduled_at).total_seconds()
                    segment_index = next((
                        number for number, segment in enumerate(plan.segments)
                        if segment.start_offset_seconds <= position
                        < segment.start_offset_seconds + segment.duration_seconds
                    ), None)
                    if segment_index is not None:
                        segment = plan.segments[segment_index]
                        item = indexed_media_for_segment(segment, self.ad_media, self.library)
                        segment_start = plan.scheduled_at + timedelta(
                            seconds=segment.start_offset_seconds
                        )
                        return BroadcastSelection(
                            program=ScheduledProgram(
                                media=item, index=len(self.programs) + segment_index,
                                duration_seconds=segment.duration_seconds,
                            ),
                            offset_seconds=(segment.source_offset_seconds if segment.event_type == "transition" else (at_utc - segment_start).total_seconds()),
                            program_started_at=segment_start,
                            program_ends_at=segment_start + timedelta(
                                seconds=segment.duration_seconds
                            ),
                            cycle_index=previous_index,
                            origin=segment.event_type,
                            segment_source_offset_seconds=segment.source_offset_seconds,
                            break_id=plan.plan_id,
                            parent_program_asset_id=program.media.asset.asset_id,
                            parent_program_started_at=start,
                            parent_program_ends_at=calendar_end,
                            program_occurrence_id=plan.occurrence_id,
                            parent_program_id=BroadcastSelection(
                                program, 0, start, calendar_end, previous_index,
                                program_occurrence_id=plan.occurrence_id,
                            ).event.event_id,
                        )
                if plan_end <= at_utc:
                    elapsed_in_breaks += plan.duration_seconds
            return BroadcastSelection(
                program=program,
                offset_seconds=(at_utc - start).total_seconds() - elapsed_in_breaks,
                program_started_at=start,
                program_ends_at=calendar_end,
                cycle_index=previous_index,
                origin="calendar",
                program_occurrence_id=hashlib.sha256(
                    f"calendar:{self.channel_number}:{program.media.asset.asset_id}:{start.isoformat()}".encode()
                ).hexdigest(),
                segment_started_at=max((p.scheduled_at + timedelta(seconds=p.duration_seconds)
                                        for p in mid_plans if p.scheduled_at + timedelta(seconds=p.duration_seconds) <= at_utc), default=start),
                segment_ends_at=min((p.scheduled_at for p in mid_plans if p.scheduled_at > at_utc and p.duration_seconds > 0), default=calendar_end),
                segment_source_offset_seconds=max((
                    (p.scheduled_at - start).total_seconds() - sum(
                        previous.duration_seconds for previous in mid_plans if previous.scheduled_at < p.scheduled_at
                    ) for p in mid_plans if p.scheduled_at + timedelta(seconds=p.duration_seconds) <= at_utc
                ), default=0.0),
            )

        gap_anchor = calendar_end
        next_start = (
            self._starts[insertion]
            if insertion < len(self._starts)
            else None
        )

        # Advertising is a separate media scope. It only fills a bounded
        # calendar gap in this first integration slice; ordinary channel media
        # remains the fallback for any time the ad pool cannot cover.
        filler_anchor = gap_anchor
        if (
            (self.advertising.enabled or self.break_store is not None)
            and next_start is not None
            and next_start > gap_anchor
            and (
                self._gap_settings() is not None or self.break_store is not None
            )
        ):
            cache_key = (gap_anchor, next_start)
            if cache_key not in self._ad_plan_cache:
                self._ad_plan_cache[cache_key] = self._calendar_ad_plan(gap_anchor, next_start)
            ad_plan = self._ad_plan_cache[cache_key]
            for ad_index, segment in enumerate(ad_plan):
                segment_start = gap_anchor + timedelta(
                    seconds=segment.start_offset_seconds
                )
                segment_end = segment_start + timedelta(
                    seconds=segment.duration_seconds
                )
                if segment_start <= at_utc < segment_end:
                    ad_program = ScheduledProgram(
                        media=segment.media,
                        index=len(self.programs) + ad_index,
                        duration_seconds=segment.duration_seconds,
                    )
                    return BroadcastSelection(
                        program=ad_program,
                        offset_seconds=(segment.source_offset_seconds if segment.event_type == "transition" else (at_utc - segment_start).total_seconds()),
                        program_started_at=segment_start,
                        program_ends_at=segment_end,
                        cycle_index=previous_index,
                        origin=segment.event_type,
                        segment_source_offset_seconds=segment.source_offset_seconds,
                        break_id=self._ad_plan_ids.get(cache_key),
                        parent_program_id=(BroadcastSelection(
                            self.programs[previous_index], 0, self._starts[previous_index],
                            calendar_end, previous_index,
                            program_occurrence_id=hashlib.sha256(
                                f"calendar:{self.channel_number}:{self.programs[previous_index].media.asset.asset_id}:{self._starts[previous_index].isoformat()}".encode()
                            ).hexdigest(),
                        ).event.event_id if previous_index >= 0 else None),
                        parent_program_asset_id=(
                            self.programs[previous_index].media.asset.asset_id
                            if previous_index >= 0 else None
                        ),
                        parent_program_started_at=(
                            self._starts[previous_index]
                            if previous_index >= 0 else None
                        ),
                        parent_program_ends_at=(
                            self._ends[previous_index]
                            if previous_index >= 0 else None
                        ),
                    )
            if ad_plan:
                final_segment = ad_plan[-1]
                filler_anchor = gap_anchor + timedelta(
                    seconds=final_segment.end_offset_seconds
                )

        filler_timeline = (
            self._gap_fillers[previous_index]
            if previous_index >= 0
            and self._gap_fillers[previous_index] is not None
            else self.filler
        )
        filler = filler_timeline.selection_at(filler_anchor, at_utc)
        filler_end = filler.program_ends_at
        if next_start is not None and filler_end > next_start:
            filler_end = next_start
        return BroadcastSelection(
            program=filler.program,
            offset_seconds=filler.offset_seconds,
            program_started_at=filler.program_started_at,
            program_ends_at=filler_end,
            cycle_index=filler.cycle_index,
            origin=(
                "show-filler"
                if previous_index >= 0
                and self._gap_fillers[previous_index] is not None
                else "filler"
            ),
        )


def deterministic_media_order(
    channel_number: int,
    media: tuple[IndexedMedia, ...],
    *,
    namespace: str = "channel",
) -> tuple[IndexedMedia, ...]:
    """Return a stable asset permutation independent of paths and process randomness."""

    asset_ids = sorted(item.asset.asset_id for item in media)
    seed_payload = {
        "schema": 1,
        "channel": int(channel_number),
        "asset_ids": asset_ids,
    }
    if namespace != "channel":
        seed_payload["namespace"] = str(namespace)
    encoded = json.dumps(seed_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    seed = hashlib.sha256(encoded).digest()

    def order_key(item: IndexedMedia) -> tuple[bytes, str]:
        digest = hashlib.sha256(seed + item.asset.asset_id.encode("utf-8")).digest()
        return digest, item.asset.asset_id

    return tuple(sorted(media, key=order_key))


def deterministic_shuffle_order(channel: ResolvedChannel) -> tuple[IndexedMedia, ...]:
    return deterministic_media_order(
        channel.definition.channel,
        channel.media,
    )


def _validate_shuffle_repeat_window(timeline: SequentialTimeline, avoid_repeat_days: int) -> None:
    if avoid_repeat_days <= 0:
        return

    required_seconds = float(avoid_repeat_days) * SECONDS_PER_DAY
    if timeline.cycle_duration_seconds >= required_seconds:
        return

    available_hours = timeline.cycle_duration_seconds / 3600.0
    raise ChannelRuntimeError(
        "shuffle repeat avoidance cannot guarantee "
        f"{avoid_repeat_days} day(s) without repeats: the eligible media pool spans only "
        f"{available_hours:.2f} hours. Add eligible media or reduce avoid_repeat_days."
    )


def _calendar_signature_block(block: CalendarBlockDefinition) -> dict[str, object]:
    payload: dict[str, object] = {
        "start_utc": block.start_utc.isoformat(timespec="microseconds"),
        "asset_id": block.asset_id,
    }
    if block.filler is not None:
        payload["filler"] = {
            "mode": block.filler.mode,
            "asset_ids": list(block.filler.asset_ids),
        }
    return payload


def schedule_signature(channel: ResolvedChannel) -> str:
    """Return a deterministic fingerprint of the inputs that define a channel timeline."""

    programming = channel.definition.programming
    signature_media = channel.media
    if programming.mode == "shuffle":
        signature_media = tuple(sorted(channel.media, key=lambda item: item.asset.asset_id))

    # Keep the exact schema-2 payload for legacy 0.1 channels. Adding Channel
    # Studio must not re-anchor every existing Broadcast Clock on upgrade.
    if programming.mode != "calendar":
        payload = {
            "schema": 2,
            "channel": channel.definition.channel,
            "programming": {
                "mode": programming.mode,
                "preserve_episode_order": programming.preserve_episode_order,
                "avoid_repeat_days": programming.avoid_repeat_days,
            },
            "media": [
                {
                    "asset_id": item.asset.asset_id,
                    "duration_seconds": item.asset.duration_seconds,
                }
                for item in signature_media
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    if programming.filler_mode == "shuffle":
        signature_media = tuple(
            sorted(channel.media, key=lambda item: item.asset.asset_id)
        )

    payload = {
        "schema": 3,
        "channel": channel.definition.channel,
        "programming": {
            "mode": programming.mode,
            "preserve_episode_order": programming.preserve_episode_order,
            "avoid_repeat_days": programming.avoid_repeat_days,
            "filler_mode": programming.filler_mode,
            "calendar": [
                _calendar_signature_block(block)
                for block in programming.calendar
            ],
        },
        "media": [
            {
                "asset_id": item.asset.asset_id,
                "duration_seconds": item.asset.duration_seconds,
            }
            for item in signature_media
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def advertising_signature(channel: ResolvedChannel) -> str:
    """Fingerprint ad policy independently from the program Broadcast Clock.

    Advertising edits must never change the channel epoch or viewer continuity.
    This revision is available to plan invalidation and diagnostics without
    becoming part of RuntimeStore's program-schedule signature.
    """
    advertising = channel.definition.advertising
    from .models import advertising_to_mapping
    payload = advertising_to_mapping(advertising)
    payload["ad_assets"] = sorted(item.asset.asset_id for item in channel.ad_media)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PersistedChannelRuntime:
    channel_number: int
    schedule_signature: str
    epoch_utc: datetime


@dataclass(frozen=True, slots=True)
class OnDemandWatchState:
    """One viewer's durable playhead for a stable owned-media asset."""

    viewer_id: str
    asset_id: str
    position_seconds: float
    duration_seconds: float
    completed: bool
    last_watched_at: datetime

    @property
    def progress_fraction(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return min(
            1.0,
            max(0.0, self.position_seconds / self.duration_seconds),
        )

    @property
    def resumable(self) -> bool:
        return on_demand_watch_is_resumable(
            self.position_seconds,
            self.duration_seconds,
            completed=self.completed,
        )


def on_demand_watch_is_complete(
    position_seconds: float,
    duration_seconds: float,
) -> bool:
    duration = max(0.0, float(duration_seconds))
    position = max(0.0, float(position_seconds))
    return duration > 0.0 and position >= duration * 0.95


def on_demand_watch_is_resumable(
    position_seconds: float,
    duration_seconds: float,
    *,
    completed: bool = False,
) -> bool:
    if completed:
        return False

    position = max(0.0, float(position_seconds))
    duration = max(0.0, float(duration_seconds))
    minimum_position = min(
        30.0,
        max(10.0, duration * 0.02),
    )
    if position < minimum_position:
        return False
    if duration > 0.0 and position >= duration * 0.95:
        return False
    return True


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
        prepare_database(
            self.database_path,
            meta_table="runtime_meta",
            supported_version=RUNTIME_SCHEMA_VERSION,
        )
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000,
            factory=_ClosingSQLiteConnection,
        )
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, self.database_path)
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

                CREATE TABLE IF NOT EXISTS on_demand_watch (
                    viewer_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    position_seconds REAL NOT NULL,
                    duration_seconds REAL NOT NULL,
                    completed INTEGER NOT NULL,
                    last_watched_at TEXT NOT NULL,
                    PRIMARY KEY(viewer_id, asset_id)
                );

                CREATE INDEX IF NOT EXISTS idx_on_demand_watch_recent
                    ON on_demand_watch(viewer_id, last_watched_at DESC);
                """
            )
            connection.execute(
                """
                INSERT INTO runtime_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(RUNTIME_SCHEMA_VERSION),),
            )

    def ensure_channel(
        self,
        channel_number: int,
        signature: str,
        *,
        now: datetime | None = None,
        preserve_clock_on_change: bool = False,
    ) -> PersistedChannelRuntime:
        current = require_aware_utc(now or utc_now())
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM channel_runtime WHERE channel_number = ?",
                (channel_number,),
            ).fetchone()

            if row is None or row["schedule_signature"] != signature:
                preserve_existing_clock = (
                    row is not None and preserve_clock_on_change
                )
                epoch_text = (
                    str(row["epoch_utc"])
                    if preserve_existing_clock
                    else datetime_to_text(current)
                )
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
                    (
                        channel_number,
                        signature,
                        epoch_text,
                        datetime_to_text(current),
                    ),
                )
                if not preserve_existing_clock:
                    connection.execute(
                        "DELETE FROM viewer_runtime WHERE channel_number = ?",
                        (channel_number,),
                    )
                return PersistedChannelRuntime(
                    channel_number=channel_number,
                    schedule_signature=signature,
                    epoch_utc=datetime_from_text(epoch_text),
                )

        return PersistedChannelRuntime(
            channel_number=channel_number,
            schedule_signature=str(row["schedule_signature"]),
            epoch_utc=datetime_from_text(str(row["epoch_utc"])),
        )

    def load_channel(self, channel_number: int) -> PersistedChannelRuntime | None:
        """Load saved Broadcast Clock state without changing its signature.

        Recovery runtimes use this to project a temporarily smaller media pool
        against the existing clock. A disconnected drive must not look like a
        permanent schedule edit, re-anchor the channel, or delete its viewer
        continuity merely because the app rebuilt the in-memory lineup.
        """

        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM channel_runtime WHERE channel_number = ?",
                (int(channel_number),),
            ).fetchone()
        if row is None:
            return None
        return PersistedChannelRuntime(
            channel_number=int(row["channel_number"]),
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

    def delete_channel(self, channel_number: int) -> None:
        """Forget channel-specific clocks and stale tuning references."""

        number = int(channel_number)
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM viewer_runtime WHERE channel_number = ?",
                (number,),
            )
            connection.execute(
                "DELETE FROM channel_runtime WHERE channel_number = ?",
                (number,),
            )
            for key in ("current_channel", "previous_channel"):
                connection.execute(
                    "DELETE FROM runtime_meta WHERE key = ? AND value = ?",
                    (key, str(number)),
                )

    def save_on_demand_watch(
        self,
        asset_id: str,
        position_seconds: float,
        duration_seconds: float,
        *,
        completed: bool = False,
        viewer_id: str = DEFAULT_VIEWER_ID,
        now: datetime | None = None,
    ) -> OnDemandWatchState:
        watched_at = require_aware_utc(now or utc_now())
        target_viewer = str(viewer_id).strip() or DEFAULT_VIEWER_ID
        target_asset = str(asset_id).strip()
        if not target_asset:
            raise ValueError("On Demand watch state requires an asset ID")

        position = max(0.0, float(position_seconds))
        duration = max(0.0, float(duration_seconds))
        if duration > 0.0:
            position = min(position, duration)
        finished = bool(completed) or on_demand_watch_is_complete(
            position,
            duration,
        )

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO on_demand_watch(
                    viewer_id,
                    asset_id,
                    position_seconds,
                    duration_seconds,
                    completed,
                    last_watched_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(viewer_id, asset_id) DO UPDATE SET
                    position_seconds = excluded.position_seconds,
                    duration_seconds = excluded.duration_seconds,
                    completed = excluded.completed,
                    last_watched_at = excluded.last_watched_at
                """,
                (
                    target_viewer,
                    target_asset,
                    position,
                    duration,
                    int(finished),
                    datetime_to_text(watched_at),
                ),
            )

        return OnDemandWatchState(
            viewer_id=target_viewer,
            asset_id=target_asset,
            position_seconds=position,
            duration_seconds=duration,
            completed=finished,
            last_watched_at=watched_at,
        )

    @staticmethod
    def _watch_from_row(row: sqlite3.Row) -> OnDemandWatchState:
        return OnDemandWatchState(
            viewer_id=str(row["viewer_id"]),
            asset_id=str(row["asset_id"]),
            position_seconds=max(0.0, float(row["position_seconds"])),
            duration_seconds=max(0.0, float(row["duration_seconds"])),
            completed=bool(row["completed"]),
            last_watched_at=datetime_from_text(str(row["last_watched_at"])),
        )

    def load_on_demand_watch(
        self,
        asset_id: str,
        *,
        viewer_id: str = DEFAULT_VIEWER_ID,
    ) -> OnDemandWatchState | None:
        target_viewer = str(viewer_id).strip() or DEFAULT_VIEWER_ID
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM on_demand_watch
                WHERE viewer_id = ? AND asset_id = ?
                """,
                (target_viewer, str(asset_id)),
            ).fetchone()
        return None if row is None else self._watch_from_row(row)

    def list_on_demand_watch(
        self,
        *,
        viewer_id: str = DEFAULT_VIEWER_ID,
    ) -> list[OnDemandWatchState]:
        target_viewer = str(viewer_id).strip() or DEFAULT_VIEWER_ID
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM on_demand_watch
                WHERE viewer_id = ?
                ORDER BY last_watched_at DESC, asset_id
                """,
                (target_viewer,),
            ).fetchall()
        return [self._watch_from_row(row) for row in rows]

    def _set_meta(self, key: str, value: str | None) -> None:
        with self.connect() as connection:
            self._write_meta(connection, key, value)

    @staticmethod
    def _write_meta(
        connection: sqlite3.Connection,
        key: str,
        value: str | None,
    ) -> None:
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

    def set_tuning(
        self,
        current_channel: int | None,
        previous_channel: int | None,
    ) -> None:
        with self.connect() as connection:
            self._write_meta(
                connection,
                "current_channel",
                None if current_channel is None else str(current_channel),
            )
            self._write_meta(
                connection,
                "previous_channel",
                None if previous_channel is None else str(previous_channel),
            )

    def get_tuning(self) -> tuple[int | None, int | None]:
        return self._get_meta_int("current_channel"), self._get_meta_int("previous_channel")


@dataclass(frozen=True, slots=True)
class ChannelRuntime:
    channel: ResolvedChannel
    timeline: SequentialTimeline | CalendarTimeline
    epoch_utc: datetime
    signature: str
    break_store: BreakPlanStore | None = None
    policy_revision_changed_at: datetime | None = None

    @classmethod
    def open(
        cls,
        channel: ResolvedChannel,
        store: RuntimeStore,
        *,
        now: datetime | None = None,
        transient: bool = False,
    ) -> "ChannelRuntime":
        programming = channel.definition.programming
        if channel.definition.advertising.enabled and any(
            item.asset.duration_seconds is None or not math.isfinite(float(item.asset.duration_seconds))
            or item.asset.duration_seconds <= 0 for item in channel.ad_media
        ):
            raise ChannelRuntimeError("advertising requires finite positive indexed media durations; re-scan its Library source")
        if programming.mode == "sequential":
            ordered_media = channel.media
        elif programming.mode == "shuffle":
            ordered_media = deterministic_shuffle_order(channel)
        elif programming.mode == "calendar":
            if programming.filler_mode == "shuffle":
                ordered_media = deterministic_shuffle_order(channel)
            else:
                ordered_media = channel.media
        else:
            raise ChannelRuntimeError(
                f"unsupported programming mode for Broadcast Clock: {programming.mode!r}"
            )

        if programming.mode == "calendar":
            timeline = CalendarTimeline(
                channel.media,
                ordered_media,
                programming.calendar,
                channel_number=channel.definition.channel,
                ad_media=channel.ad_media,
                advertising=channel.definition.advertising,
                library=channel.library,
            )
            if programming.filler_mode == "shuffle":
                _validate_shuffle_repeat_window(
                    timeline.filler,
                    programming.avoid_repeat_days,
                )
        else:
            timeline = SequentialTimeline(ordered_media)
            if programming.mode == "shuffle":
                _validate_shuffle_repeat_window(
                    timeline,
                    programming.avoid_repeat_days,
                )

        signature = schedule_signature(channel)
        previous_clock = store.load_channel(channel.definition.channel)
        persisted = (
            store.load_channel(channel.definition.channel)
            if transient
            else None
        )
        if persisted is None:
            persisted = store.ensure_channel(
                channel.definition.channel,
                signature,
                now=now,
                # Calendar blocks already carry absolute UTC intent. Editing a
                # future block must not restart today's filler cycle or erase the
                # viewer's paused/behind-live position.
                preserve_clock_on_change=(programming.mode == "calendar"),
            )
        break_store = BreakPlanStore(store.database_path)
        if not channel.definition.advertising.enabled and not break_store.connection.execute(
            "SELECT 1 FROM ad_break_plans WHERE channel_number = ? LIMIT 1", (channel.definition.channel,)
        ).fetchone():
            break_store.close()
            break_store = None
        if break_store is not None and not transient and previous_clock is not None and previous_clock.schedule_signature != signature and programming.mode != "calendar":
            break_store.reset_program_clock(channel.definition.channel, at=require_aware_utc(now or utc_now()))
        if programming.mode == "calendar":
            timeline.break_store = break_store
            timeline.ad_revision = advertising_signature(channel)
        policy_revision_changed_at = None
        if break_store is not None and not transient:
            revision_time = require_aware_utc(now or utc_now())
            if break_store.apply_policy_revision(
                channel.definition.channel,
                advertising_signature(channel),
                at=revision_time,
            ):
                policy_revision_changed_at = revision_time
            if programming.mode in {"sequential", "shuffle"}:
                previously_committed = break_store.plans_for_channel(
                    channel.definition.channel,
                    start=persisted.epoch_utc,
                    end=revision_time + timedelta(microseconds=1),
                )
                previously_committed = tuple(plan for plan in previously_committed if plan.scheduled_at >= persisted.epoch_utc)
                completed_duration = sum(
                    plan.duration_seconds for plan in previously_committed
                    if plan.scheduled_at + timedelta(
                        seconds=plan.duration_seconds
                    ) <= revision_time
                )
                partial = sum(max(0.0, (revision_time - p.scheduled_at).total_seconds())
                              for p in previously_committed
                              if p.scheduled_at <= revision_time < p.scheduled_at + timedelta(seconds=p.duration_seconds))
                content_now = revision_time - timedelta(seconds=completed_duration + partial)
                # A newly enabled ad policy begins at the program currently
                # airing, not months before it was enabled. A matching
                # revision recovers its prior durable checkpoint on restart.
                initial = timeline.selection_at(
                    persisted.epoch_utc, content_now,
                ).program_started_at
                break_store.ensure_catchup_cursor(
                    channel.definition.channel,
                    advertising_signature(channel),
                    start_at=initial,
                    activated_at=revision_time,
                )
            if programming.mode == "calendar":
                break_store.ensure_catchup_cursor(
                    channel.definition.channel, advertising_signature(channel),
                    start_at=revision_time, activated_at=revision_time,
                )
        return cls(
            channel=channel,
            timeline=timeline,
            epoch_utc=persisted.epoch_utc,
            signature=signature,
            break_store=break_store,
            policy_revision_changed_at=policy_revision_changed_at,
        )

    @property
    def channel_number(self) -> int:
        return self.channel.definition.channel

    @staticmethod
    def _plan_duration(plan: BreakPlan) -> float:
        return plan.duration_seconds

    def _program_occurrence_id(self, selection: BroadcastSelection) -> str:
        """Stable identity for the underlying program, independent of ad policy."""
        return hashlib.sha256("|".join((
            str(self.channel_number), self.signature,
            selection.media.asset.asset_id,
            selection.program_started_at.isoformat(timespec="microseconds"),
        )).encode("utf-8")).hexdigest()

    def _break_occurrence_id(self, selection: BroadcastSelection) -> str:
        """Revision-scoped identity for plans attached to a program occurrence."""
        return hashlib.sha256("|".join((
            self._program_occurrence_id(selection),
            advertising_signature(self.channel),
        )).encode("utf-8")).hexdigest()

    def _ensure_occurrence_plans(
        self, selection: BroadcastSelection, at: datetime
    ) -> tuple[BreakPlan, ...]:
        if self.break_store is None:
            return ()
        occurrence_id = self._program_occurrence_id(selection)
        policy_revision = advertising_signature(self.channel)
        occurrence = ProgramOccurrence(
            occurrence_id, self.channel_number, selection.media.asset.asset_id,
            selection.program_started_at, selection.program_ends_at,
        )
        opportunities = program_opportunities(self.channel.definition.advertising, occurrence, policy_revision)
        clock = self.break_store.program_clock(occurrence_id)
        previous_end = self.break_store.preceding_program_end(
            self.channel_number, selection.program_started_at
        )
        actual_start = clock[0] if clock else (previous_end or selection.program_started_at)
        prior_occurrence_duration = (actual_start - selection.program_started_at).total_seconds()
        occurrence_plans = list(
            self.break_store.plans_for_occurrence(occurrence_id)
        )
        committed: list[BreakPlan] = []
        for opportunity, settings in opportunities:
            head_cut, tail_cut = self.break_store.content_cuts(occurrence_id)
            source_offset = (opportunity.scheduled_at - selection.program_started_at).total_seconds()
            if source_offset < head_cut or (opportunity.trigger in {"breakpoint", "interval"}
                                           and source_offset >= selection.program.duration_seconds - tail_cut):
                continue
            existing = self.break_store.load_opportunity(opportunity.opportunity_id)
            if existing is not None:
                plan = existing
            else:
                opportunity_offset = (
                    opportunity.scheduled_at - occurrence.starts_at
                ).total_seconds()
                if opportunity.trigger in {"between_programs", "fixed_slot"}:
                    opportunity_offset -= tail_cut
                elapsed_in_prior = 0.0
                prior_duration = 0.0
                old = None
                for previous in sorted(occurrence_plans, key=lambda p: p.scheduled_at):
                    content_offset = (previous.scheduled_at - actual_start).total_seconds() - elapsed_in_prior + head_cut
                    if content_offset < opportunity_offset - 0.001:
                        prior_duration += previous.duration_seconds
                    elif abs(content_offset - opportunity_offset) < 0.001:
                        old = previous
                    elapsed_in_prior += previous.duration_seconds
                expected_at = actual_start + timedelta(seconds=opportunity_offset - head_cut + prior_duration)
                if old is not None:
                    committed.append(old)
                    continue
                activation = self.break_store.policy_activation(self.channel_number)
                if activation is not None and expected_at < activation:
                    continue
                counts = self.break_store.rotation_counts(self.channel_number, before=expected_at)
                budget = opportunity.duration_seconds
                if opportunity.trigger == "fixed_slot" and settings.slot_seconds:
                    import math
                    edge = math.ceil((expected_at.timestamp() - 1e-6) / settings.slot_seconds) * settings.slot_seconds
                    budget = max(0.0, edge - expected_at.timestamp())
                target_occurrence_id = ""
                cut_source = "none"
                extra = 0.0
                if settings.timing_policy == "expand" and settings.schedule_priority != "fixed":
                    if settings.expand_source == "schedule_shift":
                        extra = settings.expand_max_seconds
                    elif settings.schedule_priority == "advertising" and settings.expand_source in {"current_program", "next_event"}:
                        target = selection
                        if settings.expand_source == "next_event":
                            target = self.timeline.selection_at(self.epoch_utc, selection.program_ends_at + timedelta(microseconds=1))
                        target_occurrence_id = self._program_occurrence_id(target)
                        head, tail = self.break_store.content_cuts(target_occurrence_id)
                        available = target.program.duration_seconds - head - tail - .001
                        if settings.expand_source == "current_program":
                            available -= opportunity_offset
                        extra = min(settings.expand_max_seconds, max(0.0, available))
                        cut_source = settings.expand_source
                if opportunity.trigger == "fixed_slot":
                    extra = 0.0
                planned = select_segments(
                    eligible_media(self.channel.ad_media, settings), budget, settings,
                    seed=opportunity.opportunity_id, counts=counts, expand_max_seconds=extra,
                )
                actual_duration = max((part.start_offset_seconds + part.duration_seconds for part in planned), default=0.0)
                if opportunity.trigger == "fixed_slot" and actual_duration < budget - .001:
                    filler = self.timeline.programs[0].media
                    parts = list(planned)
                    while actual_duration < budget - .001:
                        duration = min(float(filler.asset.duration_seconds), budget - actual_duration)
                        parts.append(PlannedSegment(
                            filler.asset.asset_id, actual_duration, 0.0, duration,
                            media_path=str(filler.location.path), original_duration_seconds=filler.asset.duration_seconds,
                            event_type="filler",
                        ))
                        actual_duration += duration
                    planned = tuple(parts)
                cut = max(0.0, actual_duration - budget) if cut_source != "none" else 0.0
                plan_id = hashlib.sha256(
                    opportunity.opportunity_id.encode("utf-8")
                ).hexdigest()
                plan = BreakPlan(
                    plan_id=plan_id,
                    opportunity_id=opportunity.opportunity_id,
                    occurrence_id=occurrence_id,
                    channel_number=self.channel_number,
                    scheduled_at=(
                        selection.program_started_at
                        + timedelta(seconds=(
                            opportunity_offset - head_cut + prior_occurrence_duration + prior_duration
                        ))
                    ),
                    reserved_seconds=max(
                        max(budget, .001),
                        max((segment.start_offset_seconds + segment.duration_seconds
                             for segment in planned), default=0.0),
                    ),
                    segments=planned,
                    transition_behavior=settings.transition_behavior,
                    transition_seconds=settings.transition_seconds,
                    trigger=opportunity.trigger, profile_id=settings.profile_id,
                    policy_revision=policy_revision,
                    content_cut_seconds=cut, cut_target_occurrence_id=target_occurrence_id, cut_source=cut_source,
                    strategy=settings.selection_strategy,
                    timing_policy=settings.timing_policy,
                )
                # The immutable plan is durable before runtime can expose its first ad.
                plan = self.break_store.commit(plan)
                occurrence_plans.append(plan)
            committed.append(plan)
        self.break_store.save_program_clock(
            occurrence_id, self.channel_number,
            content_start=selection.program_started_at, content_end=selection.program_ends_at,
            broadcast_start=actual_start,
            broadcast_end=actual_start + timedelta(seconds=(
                selection.program.duration_seconds - sum(self.break_store.content_cuts(occurrence_id))
                + sum(p.duration_seconds for p in occurrence_plans)
            )),
        )
        return self.break_store.plans_for_occurrence(occurrence_id)

    def _catch_up_sequential(self, instant: datetime) -> None:
        """Reconcile missed logical program occurrences before tuning.

        The cursor advances by program *content time*, while persisted breaks
        supply the offset to each program's actual broadcast start. Each
        occurrence is planned chronologically, so Least Played sees completed
        prior airings even after a long shutdown. A crash between committing
        a plan and checkpointing safely reuses the immutable plan on retry.
        """
        if self.break_store is None or not isinstance(
            self.timeline, SequentialTimeline
        ):
            return
        cursor = self.break_store.catchup_cursor(self.channel_number)
        if cursor is None or cursor > instant:
            return
        # Fail closed rather than guess the LIVE event after an unbounded
        # backlog. A subsequent request resumes from the persisted checkpoint.
        for _ in range(10000):
            base = self.timeline.selection_at(
                self.epoch_utc, cursor + timedelta(microseconds=1)
            )
            if base.program_started_at > instant:
                return
            occurrence_id = self._program_occurrence_id(base)
            previous_end = self.break_store.preceding_program_end(self.channel_number, base.program_started_at)
            actual_start = previous_end or base.program_started_at
            if actual_start > instant:
                return
            self._ensure_occurrence_plans(base, instant)
            if base.program_ends_at <= cursor:
                raise ChannelRuntimeError(
                    "ad catch-up did not advance the program-content cursor"
                )
            cursor = base.program_ends_at
            self.break_store.advance_catchup_cursor(
                self.channel_number, cursor
            )
            if cursor > instant:
                return
        raise ChannelRuntimeError(
            "advertising catch-up has more than 10000 outstanding program "
            "occurrences; repeat the operation to advance its saved checkpoint"
        )

    def _selection_at(self, at: datetime, *, record_airings: bool = True) -> BroadcastSelection:
        instant = require_aware_utc(at)
        if self.break_store is None:
            return self.timeline.selection_at(self.epoch_utc, instant)
        if isinstance(self.timeline, CalendarTimeline):
            self.timeline.catch_up_through(self.epoch_utc, instant)
            selection = self.timeline.selection_at(self.epoch_utc, instant)
        else:
            self._catch_up_sequential(instant)
            clock_row = self.break_store.clock_at(self.channel_number, instant)
            if clock_row is None:
                base = self.timeline.selection_at(self.epoch_utc, instant)
                self._ensure_occurrence_plans(base, instant)
                clock_row = self.break_store.clock_at(self.channel_number, instant)
            if clock_row is None:
                return self.timeline.selection_at(self.epoch_utc, instant)
            occurrence_id, content_start, content_end, parent_start, parent_end = clock_row
            base = self.timeline.selection_at(self.epoch_utc, content_start + timedelta(microseconds=1))
            occurrence_plans = self._ensure_occurrence_plans(base, instant)
            parent_start, parent_end = self.break_store.program_clock(occurrence_id)
            head_cut, tail_cut = self.break_store.content_cuts(occurrence_id)
            elapsed = 0.0
            active = None
            for plan in occurrence_plans:
                if plan.scheduled_at <= instant < plan.scheduled_at + timedelta(seconds=plan.duration_seconds):
                    active = plan
                    elapsed += (instant - plan.scheduled_at).total_seconds()
                    break
                if plan.scheduled_at + timedelta(seconds=plan.duration_seconds) <= instant:
                    elapsed += plan.duration_seconds
            offset = (instant - parent_start).total_seconds() - elapsed + head_cut
            selection = replace(
                base, offset_seconds=offset, program_started_at=parent_start, program_ends_at=parent_end,
                program_occurrence_id=occurrence_id, break_occurrence_id=self._break_occurrence_id(base),
            )
            if active is None:
                earlier = [p for p in occurrence_plans if p.scheduled_at + timedelta(seconds=p.duration_seconds) <= instant]
                later = [p for p in occurrence_plans if p.scheduled_at > instant and p.duration_seconds > 0]
                segment_start = max((p.scheduled_at + timedelta(seconds=p.duration_seconds) for p in earlier), default=parent_start)
                segment_end = min((p.scheduled_at for p in later), default=parent_end)
                selection = replace(selection, segment_started_at=segment_start, segment_ends_at=segment_end,
                                    segment_source_offset_seconds=offset - (instant - segment_start).total_seconds())
            if active is not None:
                position = (instant - active.scheduled_at).total_seconds()
                for index, segment in enumerate(active.segments):
                    if segment.start_offset_seconds <= position < segment.start_offset_seconds + segment.duration_seconds:
                        media = self._media_for_segment(segment)
                        start = active.scheduled_at + timedelta(seconds=segment.start_offset_seconds)
                        selection = BroadcastSelection(
                            ScheduledProgram(media, len(self.timeline.programs) + index, segment.duration_seconds),
                            (segment.source_offset_seconds if segment.event_type == "transition" else (instant - start).total_seconds() + segment.source_offset_seconds),
                            start, start + timedelta(seconds=segment.duration_seconds), base.cycle_index,
                            origin=segment.event_type, parent_program_id=selection.event.event_id,
                            break_id=active.plan_id, parent_program_asset_id=base.media.asset.asset_id,
                            parent_program_started_at=parent_start, parent_program_ends_at=parent_end,
                            program_occurrence_id=occurrence_id,
                            segment_source_offset_seconds=segment.source_offset_seconds,
                        )
                        break
        if record_airings:
            self.break_store.reconcile_completed(self.channel_number, through=instant)
        return selection

    def _media_for_segment(self, segment: PlannedSegment) -> IndexedMedia:
        return indexed_media_for_segment(segment, self.channel.ad_media, self.channel.library)

    def project_at(self, at: datetime) -> BroadcastSelection:
        """Resolve a schedule projection without claiming future content aired."""
        return self._selection_at(at, record_airings=False)

    def events_between(self, start: datetime, end: datetime) -> tuple[BroadcastEvent, ...]:
        """Materialize the same bounded segment timeline used by playback."""
        cursor, until = require_aware_utc(start), require_aware_utc(end)
        if until <= cursor:
            raise ValueError("event horizon end must follow start")
        result = []
        for _ in range(10000):
            event = self.project_at(cursor).event
            if event.end_utc <= cursor:
                raise ChannelRuntimeError("broadcast event timeline did not advance")
            result.append(event)
            if event.end_utc >= until:
                return tuple(result)
            cursor = event.end_utc
        raise ChannelRuntimeError("event horizon exceeds 10000 segments")

    def break_plans_for_event(
        self, selection: BroadcastSelection, *, at: datetime | None = None
    ) -> tuple[BreakPlan, ...]:
        """Return the persisted break plans associated with a program selection.

        Advertisement selections carry their parent program identity, allowing
        the Guide to display one parent occurrence with break markers.
        """
        if self.break_store is None:
            return ()
        event = selection.event
        occurrence_id = event.program_occurrence_id
        if isinstance(self.timeline, CalendarTimeline):
            parent_start = event.parent_program_started_at or selection.program_started_at
            if parent_start in self.timeline._starts:
                index = self.timeline._starts.index(parent_start)
                plans = list(self.timeline._calendar_mid_plans(index))
                end = self.timeline._calendar_program_end(index, plans)
                if index + 1 < len(self.timeline._starts) and self.timeline._starts[index + 1] > end:
                    for plan in self.break_store.plans_for_channel(
                        self.channel_number, start=end, end=self.timeline._starts[index + 1]
                    ):
                        if plan.scheduled_at >= end and plan not in plans:
                            plans.append(plan)
                return tuple(plans)
        if not occurrence_id:
            return ()
        return self.break_store.plans_for_occurrence(occurrence_id)

    def broadcast_at(self, at: datetime | None = None) -> BroadcastSelection:
        return self._selection_at(at or utc_now())

    def selection_for_viewer_time(self, viewer_time: datetime) -> BroadcastSelection:
        return self.project_at(viewer_time)


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

    def saved_status(
        self,
        channel_number: int,
        *,
        now: datetime | None = None,
    ) -> TuneDecision | None:
        """Project saved Viewer Clock continuity without tuning the channel."""

        current_time = self._now(now)
        runtime = self._channel(int(channel_number))
        saved = self.store.load_viewer(runtime.channel_number)
        if saved is None:
            return None

        viewer_time = saved.current(current_time)
        if viewer_time > current_time:
            viewer_time = current_time

        viewer_selection = runtime.selection_for_viewer_time(viewer_time)
        broadcast_selection = runtime.broadcast_at(current_time)
        lag = max(0.0, (current_time - viewer_time).total_seconds())
        return TuneDecision(
            channel_number=runtime.channel_number,
            channel_name=runtime.channel.definition.name,
            viewer_time_utc=viewer_time,
            viewer_selection=viewer_selection,
            broadcast_selection=broadcast_selection,
            lag_seconds=lag,
        )

    def continue_watching(
        self,
        *,
        now: datetime | None = None,
        default_channel: int = 1,
    ) -> TuneDecision:
        """Resume meaningful television continuity, falling back to the default.

        Priority:
        1. current persisted channel / Viewer Clock,
        2. previous channel when it still has saved Viewer Clock continuity,
        3. the real default channel live.

        A presentation-only unassigned CH001 never enters the runtime.
        """

        current_time = self._now(now)

        if self.current_channel is not None and self._viewer is not None:
            self._viewer.play(current_time)
            self._persist_viewer(current_time)
            return self._decision(current_time)

        if self.previous_channel is not None:
            saved = self.store.load_viewer(self.previous_channel)
            if saved is not None:
                return self.tune(
                    self.previous_channel,
                    now=current_time,
                    return_behavior="resume",
                )

        default = int(default_channel)
        if default in self.channels:
            return self.tune(
                default,
                now=current_time,
                return_behavior="live",
            )

        raise ChannelRuntimeError(
            f"no television continuity is available and default channel "
            f"{default:03d} is unassigned"
        )

    def status(self, *, now: datetime | None = None) -> TuneDecision:
        return self._decision(self._now(now))
