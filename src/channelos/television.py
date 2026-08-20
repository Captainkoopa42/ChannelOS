from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from .playback import PlaybackBackend
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
class TelevisionSession:
    """Routes television intents through ChannelOS before touching the playback backend."""

    runtime: TelevisionRuntime
    backend: PlaybackBackend
    loaded_asset_id: str | None = None
    loaded_program_started_at: datetime | None = None
    paused: bool = False

    def _apply_selection(self, decision: TuneDecision, *, play: bool) -> Path:
        selected = decision.viewer_selection.media
        asset_id = selected.asset.asset_id
        path = selected.location.path

        program_started_at = decision.viewer_selection.program_started_at
        if (
            self.loaded_asset_id != asset_id
            or self.loaded_program_started_at != program_started_at
        ):
            self.backend.load(path)
            self.loaded_asset_id = asset_id
            self.loaded_program_started_at = program_started_at

        if play:
            self.backend.play()
            self.paused = False

        self.backend.seek(decision.viewer_selection.offset_seconds)
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
        if boundary_selection.offset_seconds > _START_ALIGNMENT_TOLERANCE_SECONDS:
            raise ChannelRuntimeError(
                "Watch from Beginning target does not align with a scheduled program start"
            )

        normalized_selection = replace(
            boundary_selection,
            offset_seconds=0.0,
            program_started_at=started_at,
            program_ends_at=started_at
            + timedelta(seconds=boundary_selection.program.duration_seconds),
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

    def pause(self, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.pause(now=now)
        self.backend.pause()
        self.paused = True
        return decision

    def play(self, *, now: datetime | None = None) -> TuneDecision:
        decision = self.runtime.play(now=now)
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
        selected = decision.viewer_selection

        if (
            self.loaded_asset_id != selected.media.asset.asset_id
            or self.loaded_program_started_at != selected.program_started_at
        ):
            self._apply_selection(decision, play=not self.paused)

        return decision

    def stop(self) -> None:
        self.backend.stop()

    @staticmethod
    def describe(decision: TuneDecision) -> str:
        selected = decision.viewer_selection
        state = "LIVE" if decision.is_live else f"-{decision.lag_seconds:.1f}s"
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