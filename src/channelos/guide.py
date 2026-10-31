from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .runtime import BroadcastSelection, ChannelRuntime, TuneDecision, require_aware_utc, utc_now

if TYPE_CHECKING:
    from .television import TelevisionSession

_BOUNDARY_EPSILON = timedelta(microseconds=1)


class GuideError(ValueError):
    """Raised when a requested Guide view or action is invalid."""


@dataclass(frozen=True, slots=True)
class GuideProgram:
    """One scheduled program occurrence on a channel timeline."""

    schedule_id: str
    channel_number: int
    asset_id: str
    display_label: str
    start_utc: datetime
    end_utc: datetime
    duration_seconds: float
    programming_mode: str
    explanation: tuple[str, ...]
    is_current: bool
    is_past: bool
    is_future: bool
    is_advertisement: bool = False
    event_id: str = ""
    parent_program_id: str | None = None
    break_id: str | None = None
    break_markers: tuple["GuideBreakMarker", ...] = ()


@dataclass(frozen=True, slots=True)
class GuideBreakMarker:
    """A compact Guide marker for an ad break inside a parent program."""

    break_id: str
    start_utc: datetime
    end_utc: datetime
    advertisement_asset_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NowNext:
    channel_number: int
    channel_name: str
    now: GuideProgram
    next: GuideProgram


@dataclass(frozen=True, slots=True)
class GuideChannelRow:
    channel_number: int
    channel_name: str
    programs: tuple[GuideProgram, ...]


@dataclass(frozen=True, slots=True)
class GuideHorizon:
    start_utc: datetime
    end_utc: datetime
    generated_at_utc: datetime
    rows: tuple[GuideChannelRow, ...]


def _schedule_id(runtime: ChannelRuntime, selection: BroadcastSelection) -> str:
    return selection.event.event_id


def _explanation(runtime: ChannelRuntime, selection: BroadcastSelection) -> tuple[str, ...]:
    programming = runtime.channel.definition.programming
    position = selection.program.index + 1
    count = len(runtime.timeline.programs)
    if selection.origin == "advertisement":
        return (
            f"Channel {runtime.channel_number}",
            "advertisement break",
            "committed ad event from the ChannelRuntime broadcast timeline",
            f"asset {selection.media.asset.asset_id}",
        )
    if programming.mode == "calendar":
        if selection.origin == "calendar":
            return (
                f"Channel {runtime.channel_number}",
                "Channel Studio calendar programming",
                f"fixed calendar block {position} of {count}",
                f"asset {selection.media.asset.asset_id}",
            )
        if selection.origin == "show-filler":
            return (
                f"Channel {runtime.channel_number}",
                "show-specific automatic filler",
                "uses the reusable group attached to the preceding fixed show",
                f"asset {selection.media.asset.asset_id}",
            )
        return (
            f"Channel {runtime.channel_number}",
            f"{programming.filler_mode} automatic filler",
            "fills time not occupied by a fixed calendar block",
            f"asset {selection.media.asset.asset_id}",
        )
    if programming.mode == "shuffle":
        return (
            f"Channel {runtime.channel_number}",
            "deterministic shuffle programming",
            "stable order derived from channel number and media asset IDs",
            f"shuffle position {position} of {count}",
            f"asset {selection.media.asset.asset_id}",
        )
    return (
        f"Channel {runtime.channel_number}",
        "sequential programming",
        f"sequence position {position} of {count}",
        f"asset {selection.media.asset.asset_id}",
    )


def _program_from_selection(
    runtime: ChannelRuntime,
    selection: BroadcastSelection,
    *,
    relative_to: datetime,
) -> GuideProgram:
    reference = require_aware_utc(relative_to)
    start = selection.program_started_at
    end = selection.program_ends_at
    return GuideProgram(
        schedule_id=_schedule_id(runtime, selection),
        channel_number=runtime.channel_number,
        asset_id=selection.media.asset.asset_id,
        display_label=selection.media.location.path.stem,
        start_utc=start,
        end_utc=end,
        # A fixed calendar block may interrupt a filler asset. Guide duration
        # describes the scheduled occurrence, not the uncut source file.
        duration_seconds=max(0.0, (end - start).total_seconds()),
        programming_mode=runtime.channel.definition.programming.mode,
        explanation=_explanation(runtime, selection),
        is_current=start <= reference < end,
        is_past=end <= reference,
        is_future=start > reference,
        is_advertisement=selection.event.event_type == "advertisement",
        event_id=selection.event.event_id,
        parent_program_id=selection.event.parent_program_id,
        break_id=selection.event.break_id,
    )


def _parent_program_with_breaks(
    runtime: ChannelRuntime,
    selection: BroadcastSelection,
    *,
    relative_to: datetime,
) -> GuideProgram:
    """Project a program as one Guide occurrence with ad-break markers.

    When the queried instant falls inside an advertisement, the runtime event
    carries the interrupted program identity and original timing.
    """
    reference = require_aware_utc(relative_to)
    event = selection.event
    plans = runtime.break_plans_for_event(selection, at=reference)
    markers = tuple(
        GuideBreakMarker(
            break_id=plan.plan_id,
            start_utc=plan.scheduled_at,
            end_utc=plan.scheduled_at + timedelta(seconds=plan.duration_seconds),
            advertisement_asset_ids=tuple(segment.asset_id for segment in plan.segments if segment.event_type == "advertisement"),
        )
        for plan in plans if plan.duration_seconds > 0
    )

    if event.break_id:
        asset_id = event.parent_program_asset_id
        start = event.parent_program_started_at
        base_end = event.parent_program_ends_at
        parent_id = event.parent_program_id
        media = next(
            (item for item in runtime.channel.media if item.asset.asset_id == asset_id),
            None,
        )
        if media is None or start is None or base_end is None or parent_id is None:
            plan = runtime.break_store.load_plan(event.break_id) if runtime.break_store and event.break_id else None
            if plan is None:
                return _program_from_selection(runtime, selection, relative_to=reference)
            from dataclasses import replace
            return replace(_program_from_selection(runtime, selection, relative_to=reference),
                           schedule_id=plan.plan_id, event_id=plan.plan_id,
                           display_label="Advertisement break", start_utc=plan.scheduled_at,
                           end_utc=plan.scheduled_at + timedelta(seconds=plan.duration_seconds),
                           duration_seconds=plan.duration_seconds, is_advertisement=True)
        label = media.location.path.stem
        duration = float(media.asset.duration_seconds or 0.0)
        explanation = (
            f"Channel {runtime.channel_number}",
            "program interrupted by an advertisement break",
            f"asset {asset_id}",
        )
        schedule_id = parent_id
    else:
        media = selection.media
        asset_id = event.asset_id
        start = selection.program_started_at
        base_end = selection.program_ends_at
        parent_id = event.event_id
        label = media.location.path.stem
        duration = selection.program.duration_seconds
        explanation = _explanation(runtime, selection)
        schedule_id = event.event_id

    end = max(base_end, max((marker.end_utc for marker in markers), default=base_end))
    return GuideProgram(
        schedule_id=schedule_id,
        channel_number=runtime.channel_number,
        asset_id=asset_id,
        display_label=label,
        start_utc=start,
        end_utc=end,
        duration_seconds=max(0.0, (end - start).total_seconds()),
        programming_mode=runtime.channel.definition.programming.mode,
        explanation=explanation,
        is_current=start <= reference < end,
        is_past=end <= reference,
        is_future=start > reference,
        is_advertisement=False,
        event_id=schedule_id,
        break_markers=markers,
    )


def _selection_after_boundary(runtime: ChannelRuntime, boundary: datetime) -> BroadcastSelection:
    """Select the program beginning at a known end boundary without float-edge ambiguity."""
    return runtime.project_at(require_aware_utc(boundary) + _BOUNDARY_EPSILON)


class GuideService:
    """Read-only Guide projection over authoritative ChannelRuntime timelines."""

    def __init__(self, runtimes: tuple[ChannelRuntime, ...]) -> None:
        if not runtimes:
            raise GuideError("Guide requires at least one channel runtime")
        by_number: dict[int, ChannelRuntime] = {}
        for runtime in runtimes:
            if runtime.channel_number in by_number:
                raise GuideError(f"duplicate channel number: {runtime.channel_number}")
            by_number[runtime.channel_number] = runtime
        self._runtimes = tuple(by_number[number] for number in sorted(by_number))

    @property
    def channel_numbers(self) -> tuple[int, ...]:
        return tuple(runtime.channel_number for runtime in self._runtimes)

    def now_next(self, channel_number: int, *, at: datetime | None = None) -> NowNext:
        reference = require_aware_utc(at or utc_now())
        runtime = self._runtime(channel_number)
        current_selection = runtime.project_at(reference)
        boundary = current_selection.program_ends_at
        if current_selection.break_id and runtime.break_store:
            plan = runtime.break_store.load_plan(current_selection.break_id)
            if plan:
                boundary = plan.scheduled_at + timedelta(seconds=plan.duration_seconds)
        next_selection = _selection_after_boundary(runtime, boundary)
        return NowNext(
            channel_number=runtime.channel_number,
            channel_name=runtime.channel.definition.name,
            now=_program_from_selection(runtime, current_selection, relative_to=reference),
            next=_program_from_selection(runtime, next_selection, relative_to=reference),
        )

    def horizon(
        self,
        start: datetime,
        end: datetime,
        *,
        generated_at: datetime | None = None,
    ) -> GuideHorizon:
        start_utc = require_aware_utc(start)
        end_utc = require_aware_utc(end)
        if end_utc <= start_utc:
            raise GuideError("Guide horizon end must be after start")
        reference = require_aware_utc(generated_at or utc_now())

        rows = tuple(
            self._row(runtime, start_utc, end_utc, reference)
            for runtime in self._runtimes
        )
        return GuideHorizon(
            start_utc=start_utc,
            end_utc=end_utc,
            generated_at_utc=reference,
            rows=rows,
        )

    def validate_program(self, program: GuideProgram) -> ChannelRuntime:
        """Verify that a Guide occurrence still belongs to the current channel schedule."""
        runtime = self._runtime(program.channel_number)
        selection = runtime.project_at(program.start_utc + _BOUNDARY_EPSILON)
        current = _parent_program_with_breaks(runtime, selection, relative_to=program.start_utc)
        if (
            current.schedule_id != program.schedule_id
            or current.asset_id != program.asset_id
            or current.start_utc != program.start_utc
            or current.end_utc != program.end_utc
        ):
            raise GuideError(
                "Guide program is stale or no longer belongs to the current channel schedule; refresh the Guide"
            )
        return runtime

    def _runtime(self, channel_number: int) -> ChannelRuntime:
        for runtime in self._runtimes:
            if runtime.channel_number == channel_number:
                return runtime
        raise GuideError(f"unknown channel: {channel_number}")

    @staticmethod
    def _row(
        runtime: ChannelRuntime,
        start: datetime,
        end: datetime,
        reference: datetime,
    ) -> GuideChannelRow:
        programs: list[GuideProgram] = []
        selection = runtime.project_at(start)

        while True:
            program = _parent_program_with_breaks(
                runtime, selection, relative_to=reference
            )
            if program.end_utc <= start:
                selection = _selection_after_boundary(runtime, program.end_utc)
                continue
            if program.start_utc >= end:
                break
            programs.append(program)
            if program.end_utc >= end:
                break
            selection = _selection_after_boundary(runtime, program.end_utc)

        return GuideChannelRow(
            channel_number=runtime.channel_number,
            channel_name=runtime.channel.definition.name,
            programs=tuple(programs),
        )


class GuideController:
    """Routes actions on Guide occurrences through the normal ChannelOS television path."""

    def __init__(self, service: GuideService, television: TelevisionSession) -> None:
        self.service = service
        self.television = television

    def tune(self, program: GuideProgram, *, at: datetime | None = None) -> TuneDecision:
        reference = require_aware_utc(at or utc_now())
        self.service.validate_program(program)
        if not (program.start_utc <= reference < program.end_utc):
            raise GuideError("Tune from Guide requires a program that is currently airing")
        return self.television.tune(program.channel_number, now=reference, return_behavior="live")

    def watch_from_beginning(
        self,
        program: GuideProgram,
        *,
        at: datetime | None = None,
    ) -> TuneDecision:
        reference = require_aware_utc(at or utc_now())
        self.service.validate_program(program)
        if program.start_utc > reference:
            raise GuideError("cannot Watch from Beginning before the scheduled program has started")
        return self.television.watch_from_beginning(
            program.channel_number,
            program.start_utc,
            now=reference,
        )
