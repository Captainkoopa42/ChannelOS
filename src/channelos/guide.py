from __future__ import annotations

import hashlib
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
    payload = "|".join(
        (
            str(runtime.channel_number),
            runtime.signature,
            selection.media.asset.asset_id,
            selection.program_started_at.isoformat(timespec="microseconds"),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _explanation(runtime: ChannelRuntime, selection: BroadcastSelection) -> tuple[str, ...]:
    programming = runtime.channel.definition.programming
    position = selection.program.index + 1
    count = len(runtime.timeline.programs)
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
        duration_seconds=selection.program.duration_seconds,
        programming_mode=runtime.channel.definition.programming.mode,
        explanation=_explanation(runtime, selection),
        is_current=start <= reference < end,
        is_past=end <= reference,
        is_future=start > reference,
    )


def _selection_after_boundary(runtime: ChannelRuntime, boundary: datetime) -> BroadcastSelection:
    """Select the program beginning at a known end boundary without float-edge ambiguity."""
    return runtime.broadcast_at(require_aware_utc(boundary) + _BOUNDARY_EPSILON)


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
        current_selection = runtime.broadcast_at(reference)
        next_selection = _selection_after_boundary(runtime, current_selection.program_ends_at)
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
        selection = runtime.broadcast_at(program.start_utc + _BOUNDARY_EPSILON)
        current = _program_from_selection(runtime, selection, relative_to=program.start_utc)
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
        selection = runtime.broadcast_at(start)

        while selection.program_started_at < end:
            programs.append(
                _program_from_selection(runtime, selection, relative_to=reference)
            )
            selection = _selection_after_boundary(runtime, selection.program_ends_at)

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

        # The Guide already uses a one-microsecond boundary probe when walking
        # from one scheduled occurrence to the next. Use the same boundary-safe
        # instant here. Without it, converting an absolute program start to a
        # relative float seek and back can land one microsecond on the previous
        # occurrence for fractional media durations. Playback still begins at
        # effectively zero, but most importantly it resolves the selected asset.
        boundary_safe_start = program.start_utc + _BOUNDARY_EPSILON
        return self.television.watch_from_beginning(
            program.channel_number,
            boundary_safe_start,
            now=reference,
        )