from __future__ import annotations

from dataclasses import dataclass, replace, field
from datetime import datetime, timedelta
from pathlib import Path

from .playback import PlaybackBackend, PlaybackError
from .runtime import (
    ChannelRuntimeError,
    TelevisionRuntime,
    TuneDecision,
    require_aware_utc,
    utc_now,
)

_START_BOUNDARY_PROBE = timedelta(microseconds=1)
_START_ALIGNMENT_TOLERANCE_SECONDS = 0.001


@dataclass(slots=True)
class _AdViewingProgress:
    channel_number: int
    plan_id: str
    segment_index: int
    asset_id: str
    duration_seconds: float
    event_id: str
    last_position: float
    consumed_seconds: float = 0.0
    consumed_ranges: list[tuple[float, float]] = field(default_factory=list)


@dataclass(slots=True)
class TelevisionSession:
    """Routes television intents through ChannelOS before touching the playback backend."""

    runtime: TelevisionRuntime
    backend: PlaybackBackend
    loaded_asset_id: str | None = None
    loaded_program_started_at: datetime | None = None
    paused: bool = False
    _ad_viewing: _AdViewingProgress | None = None
    _loaded_segment_id: str | None = None
    _transition_level: float = 1.0
    _holding: bool = False
    viewer_id: str = "default"

    def _update_transition(self, decision: TuneDecision) -> None:
        selected = decision.viewer_selection
        event = selected.event
        runtime = self.runtime.channels[decision.channel_number]
        level = 1.0
        plans = runtime.break_plans_for_event(selected)
        if event.break_id and runtime.break_store:
            plan = runtime.break_store.load_plan(event.break_id)
            plans = (plan,) if plan else plans
        for plan in plans:
            if plan.transition_behavior != "fade" or plan.transition_seconds <= 0:
                continue
            edge = plan.transition_seconds
            if event.event_type == "advertisement" and event.break_id == plan.plan_id:
                edge = min(edge, (event.end_utc - event.start_utc).total_seconds() / 2)
                if edge > 0:
                    level = min(level, max(0.0, min(1.0,
                        (decision.viewer_time_utc - event.start_utc).total_seconds() / edge,
                        (event.end_utc - decision.viewer_time_utc).total_seconds() / edge)))
            elif event.event_type == "program":
                before = (plan.scheduled_at - decision.viewer_time_utc).total_seconds()
                after = (decision.viewer_time_utc - plan.scheduled_at).total_seconds() - plan.duration_seconds
                if 0 <= before < edge:
                    level = min(level, before / edge)
                if 0 <= after < edge:
                    level = min(level, after / edge)
        if abs(level - self._transition_level) > .001:
            self.backend.set_transition_level(level)
            self._transition_level = level

    def _clear_transition(self) -> None:
        if self._transition_level != 1.0:
            self.backend.set_transition_level(1.0)
            self._transition_level = 1.0
        self._holding = False

    def _sample_ad_viewing(self) -> None:
        progress = self._ad_viewing
        if progress is None or self.paused:
            return
        try:
            position = float(self.backend.get_position())
        except (TypeError, ValueError, PlaybackError):
            return
        delta = position - progress.last_position
        # Large jumps are seeks, not actual continuous viewer consumption.
        if 0.0 < delta <= 3.0:
            ranges = progress.consumed_ranges + [(
                max(0.0, progress.last_position), min(position, progress.duration_seconds)
            )]
            merged = []
            for start, end in sorted(ranges):
                if end <= start:
                    continue
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            progress.consumed_ranges = merged
            progress.consumed_seconds = sum(end - start for start, end in merged)
        progress.last_position = position

    def _finish_ad_viewing(self, at: datetime) -> None:
        progress = self._ad_viewing
        self._ad_viewing = None
        if progress is None:
            return
        runtime = self.runtime.channels.get(progress.channel_number)
        if runtime is None or runtime.break_store is None:
            return
        consumed = runtime.break_store.save_viewing_progress(
            progress.plan_id, progress.segment_index, viewer_id=self.viewer_id,
            ranges=progress.consumed_ranges, watched_at=at,
        ) if progress.consumed_ranges else progress.consumed_seconds
        if consumed + 0.5 < progress.duration_seconds:
            return
        runtime.break_store.record_viewed(
            progress.plan_id,
            progress.segment_index,
            progress.asset_id,
            consumed_seconds=min(consumed, progress.duration_seconds),
            viewer_id=self.viewer_id,
            completed_at=at,
        )

    def _apply_selection(self, decision: TuneDecision, *, play: bool) -> Path:
        self._sample_ad_viewing()
        selected = decision.viewer_selection.media
        asset_id = selected.asset.asset_id
        path = selected.location.path

        program_started_at = decision.viewer_selection.program_started_at
        event = decision.viewer_selection.event
        if self._ad_viewing is not None and self._ad_viewing.event_id != event.event_id:
            self._finish_ad_viewing(decision.observed_at_utc or utc_now())
        if (
            self.loaded_asset_id != asset_id
            or (self.loaded_program_started_at != program_started_at
                and event.event_type != "transition")
        ):
            self.backend.load(path)
        self.loaded_asset_id = asset_id
        self.loaded_program_started_at = program_started_at

        if play:
            self.backend.play()
            self.paused = False

        self.backend.seek(decision.viewer_selection.offset_seconds)
        self._loaded_segment_id = event.segment_id
        self._holding = event.event_type == "transition"
        if self._holding:
            self.backend.pause()
        self._update_transition(decision)
        if event.event_type == "advertisement" and event.break_id:
            runtime = self.runtime.channels.get(decision.channel_number)
            plan = (
                runtime.break_store.load_plan(event.break_id)
                if runtime is not None and runtime.break_store is not None else None
            )
            if plan is not None:
                for index, segment in enumerate(plan.segments):
                    segment_at = plan.scheduled_at + timedelta(
                        seconds=segment.start_offset_seconds
                    )
                    if (segment.asset_id == asset_id
                            and abs((segment_at - program_started_at).total_seconds()) < 0.01):
                        if self._ad_viewing is None or self._ad_viewing.event_id != event.event_id:
                            self._ad_viewing = _AdViewingProgress(
                                decision.channel_number, plan.plan_id, index,
                                asset_id, segment.duration_seconds,
                                event.event_id, decision.viewer_selection.offset_seconds,
                            )
                            saved_ranges = runtime.break_store.viewing_ranges(plan.plan_id, index, self.viewer_id)
                            self._ad_viewing.consumed_ranges = saved_ranges
                            self._ad_viewing.consumed_seconds = sum(end - start for start, end in saved_ranges)
                        else:
                            self._ad_viewing.last_position = decision.viewer_selection.offset_seconds
                        break
        if not play and self.paused:
            self.backend.pause()
        return path

    def tune(
        self,
        channel_number: int,
        *,
        now: datetime | None = None,
        return_behavior: str = "live",
    ) -> TuneDecision:
        decision = self.runtime.tune(
            channel_number,
            now=now,
            return_behavior=return_behavior,
        )
        self._apply_selection(decision, play=True)
        return decision

    def watch_from_beginning(
        self,
        channel_number: int,
        program_started_at: datetime,
        *,
        now: datetime | None = None,
    ) -> TuneDecision:
        """Tune a channel and place its Viewer Clock at one scheduled program's exact start."""
        current_time = require_aware_utc(now or utc_now())
        started_at = require_aware_utc(program_started_at)
        if started_at > current_time:
            raise ChannelRuntimeError("cannot Watch from Beginning before the program has started")

        # Establish the target channel and set the Viewer Clock to the exact
        # scheduled start. At a fractional-duration boundary, floating-point
        # timeline math can classify that exact instant as the final microsecond
        # of the previous occurrence. Preserve the exact Viewer Clock, but probe
        # one microsecond inside the occurrence only to resolve which asset owns
        # the boundary. Then normalize playback back to offset 0.000s.
        self.runtime.tune(channel_number, now=current_time, return_behavior="live")
        self.runtime.go_live(now=current_time)
        decision = self.runtime.seek(
            (started_at - current_time).total_seconds(),
            now=current_time,
        )

        channel_runtime = self.runtime.channels[channel_number]
        boundary_selection = channel_runtime.selection_for_viewer_time(
            started_at + _START_BOUNDARY_PROBE
        )
        source_start = boundary_selection.event.source_offset_seconds
        if abs(boundary_selection.offset_seconds - source_start) > _START_ALIGNMENT_TOLERANCE_SECONDS:
            raise ChannelRuntimeError(
                "Watch from Beginning target does not align with a scheduled program start"
            )

        normalized_selection = replace(
            boundary_selection,
            offset_seconds=source_start,
            program_started_at=started_at,
            # Calendar filler can be clipped by the next fixed block. Preserve
            # that authoritative occurrence boundary instead of restoring the
            # source asset's full duration.
            program_ends_at=boundary_selection.program_ends_at,
        )
        decision = replace(
            decision,
            viewer_time_utc=started_at,
            viewer_selection=normalized_selection,
            lag_seconds=max(0.0, (current_time - started_at).total_seconds()),
        )
        self._apply_selection(decision, play=True)
        return decision

    def channel_up(self, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.channel_up(now=now)
        self._apply_selection(decision, play=True)
        return decision

    def channel_down(self, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.channel_down(now=now)
        self._apply_selection(decision, play=True)
        return decision

    def previous_channel(self, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.previous(now=now)
        self._apply_selection(decision, play=True)
        return decision

    def continue_watching(
        self,
        *,
        now: datetime | None = None,
        default_channel: int = 1,
    ) -> TuneDecision:
        decision = self.runtime.continue_watching(
            now=now,
            default_channel=default_channel,
        )
        self._apply_selection(decision, play=True)
        return decision

    def restore_after_lineup_change(
        self,
        channel_number: int,
        *,
        paused: bool,
        now: datetime | None = None,
    ) -> TuneDecision:
        """Recreate decoder output without discarding Viewer Clock continuity."""

        current_time = require_aware_utc(now or utc_now())
        target = int(channel_number)
        if self.runtime.current_channel == target:
            # Reapply the persisted running/paused intent to the newly-created
            # session. ViewerClock.play/pause preserve its scheduled position.
            decision = (
                self.runtime.pause(now=current_time)
                if paused
                else self.runtime.play(now=current_time)
            )
        else:
            # The prior channel was removed. A surviving replacement starts at
            # its live Broadcast Clock instead of inheriting deleted continuity.
            decision = self.runtime.tune(
                target,
                now=current_time,
                return_behavior="live",
            )
            paused = False

        # A freshly-created native decoder must play at least once to build its
        # video output. For paused continuity, establish the picture/seek first
        # and then pause it on the same frame.
        self._apply_selection(decision, play=True)
        if paused:
            self.backend.pause()
            self.paused = True
        return decision

    def pause(self, *, now: datetime | None = None) -> TuneDecision:
        self._sample_ad_viewing()
        decision = self.runtime.pause(now=now)
        self.backend.pause()
        self.paused = True
        return decision

    def play(self, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.play(now=now)
        if not self._holding:
            self.backend.play()
        self.paused = False
        return decision

    def skip(self, delta_seconds: float, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.seek(delta_seconds, now=now)
        self._apply_selection(decision, play=not self.paused)
        return decision

    def go_live(self, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.go_live(now=now)
        self._apply_selection(decision, play=True)
        return decision

    def sync(self, *, now: datetime | None = None) -> TuneDecision:
        """Keep decoder playback aligned when the Viewer Clock crosses a program boundary."""

        decision = self.runtime.status(now=now)
        error_probe = getattr(self.backend, "playback_error", None)
        error = error_probe() if callable(error_probe) else None
        if error:
            if self._loaded_segment_id != decision.viewer_selection.event.segment_id:
                # An unavailable commercial must not latch the following show
                # off air. Retry the newly authoritative event at its boundary.
                self.loaded_asset_id = None
                self.loaded_program_started_at = None
                self._ad_viewing = None
                self._clear_transition()
                self._apply_selection(decision, play=not self.paused)
                return decision
            # Make an explicit user retry reload the media instead of retaining
            # the failed decoder selection as though it were still active.
            self.loaded_asset_id = None
            self.loaded_program_started_at = None
            self._clear_transition()
            self._ad_viewing = None
            raise PlaybackError(error)

        self._sample_ad_viewing()
        selected = decision.viewer_selection

        if (
            self.loaded_asset_id != selected.media.asset.asset_id
            or self.loaded_program_started_at != selected.program_started_at
            or self._loaded_segment_id != selected.event.segment_id
        ):
            self._apply_selection(decision, play=not self.paused)
        else:
            self._update_transition(decision)

        return decision

    def suspend_decoder(self, *, persist_history: bool = True) -> None:
        """Release active decoder output without changing television clock state."""

        self._sample_ad_viewing()
        if persist_history:
            self._finish_ad_viewing(utc_now())
        self._clear_transition()
        self.backend.stop()
        self.loaded_asset_id = None
        self.loaded_program_started_at = None

    def stop(self) -> None:
        self._sample_ad_viewing()
        self._finish_ad_viewing(utc_now())
        self._clear_transition()
        self.backend.stop()

    @staticmethod
    def describe(decision: TuneDecision) -> str:
        selected = decision.viewer_selection
        state = (
            "LIVE" if decision.is_live else
            f"+{decision.ahead_seconds:.1f}s AHEAD" if decision.is_ahead else
            f"-{decision.lag_seconds:.1f}s"
        )
        return (
            f"Channel {decision.channel_number:03d} — {decision.channel_name} | "
            f"{selected.media.location.path.name} @ {selected.offset_seconds:.3f}s | {state}"
        )

    def execute(
        self,
        intent: str,
        *,
        now: datetime | None = None,
        return_behavior: str = "live",
    ) -> str:
        """Execute one Phase 1 control intent using the future remote-protocol vocabulary."""

        parts = intent.strip().upper().split()
        if not parts:
            return ""

        command = parts[0]
        if command == "TUNE" and len(parts) == 2:
            try:
                channel_number = int(parts[1])
            except ValueError as exc:
                raise ValueError("TUNE requires a numeric channel") from exc
            return self.describe(
                self.tune(channel_number, now=now, return_behavior=return_behavior)
            )
        if command == "CHANNEL_UP" and len(parts) == 1:
            return self.describe(self.channel_up(now=now))
        if command == "CHANNEL_DOWN" and len(parts) == 1:
            return self.describe(self.channel_down(now=now))
        if command in {"PREVIOUS", "PREVIOUS_CHANNEL"} and len(parts) == 1:
            return self.describe(self.previous_channel(now=now))
        if command == "PAUSE" and len(parts) == 1:
            return self.describe(self.pause(now=now))
        if command == "PLAY" and len(parts) == 1:
            return self.describe(self.play(now=now))
        if command == "GO_LIVE" and len(parts) == 1:
            return self.describe(self.go_live(now=now))
        if command == "SKIP_FORWARD" and len(parts) in {1, 2}:
            seconds = float(parts[1]) if len(parts) == 2 else 30.0
            return self.describe(self.skip(abs(seconds), now=now))
        if command == "SKIP_BACK" and len(parts) in {1, 2}:
            seconds = float(parts[1]) if len(parts) == 2 else 10.0
            return self.describe(self.skip(-abs(seconds), now=now))
        if command == "STATUS" and len(parts) == 1:
            return self.describe(self.runtime.status(now=now))
        if command == "STOP" and len(parts) == 1:
            self.stop()
            return "stopped"

        raise ChannelRuntimeError(f"unknown television intent: {intent!r}")
