from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from .guide import GuideController, GuideError, GuideProgram, GuideService
from .playback import LibVLCBackend, NativeVideoSurface, PlaybackBackend
from .runtime import TelevisionRuntime, TuneDecision, require_aware_utc, utc_now
from .television import TelevisionSession

UTC = timezone.utc
BackendFactory = Callable[[], PlaybackBackend]


class CouchActions:
    """Pure-Python action layer between the couch UI and television runtime."""

    def __init__(
        self,
        service: GuideService,
        runtime: TelevisionRuntime,
        *,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.service = service
        self.runtime = runtime
        self._backend_factory = backend_factory or LibVLCBackend
        self._backend: PlaybackBackend | None = None
        self._session: TelevisionSession | None = None
        self._guide: GuideController | None = None
        self._surface: NativeVideoSurface | None = None
        self._last_decision: TuneDecision | None = None

    @property
    def last_decision(self) -> TuneDecision | None:
        return self._last_decision

    @property
    def paused(self) -> bool:
        return bool(self._session and self._session.paused)

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        """Remember the UI's native video target and attach it to an active backend."""

        self._surface = surface
        if self._backend is not None:
            self._backend.attach_video_surface(surface)

    def _ensure_session(self) -> TelevisionSession:
        if self._session is not None:
            return self._session

        backend = self._backend_factory()
        if self._surface is not None:
            backend.attach_video_surface(self._surface)

        session = TelevisionSession(self.runtime, backend)
        self._backend = backend
        self._session = session
        self._guide = GuideController(self.service, session)
        return session

    def _ensure_guide(self) -> GuideController:
        self._ensure_session()
        assert self._guide is not None
        return self._guide

    def resolve_program(
        self,
        schedule_id: str,
        channel_number: int,
        approximate_start_ms: float,
        *,
        at: datetime | None = None,
    ) -> GuideProgram:
        """Resolve one QML schedule identity back to the authoritative Guide occurrence."""

        if not schedule_id:
            raise GuideError("Guide selection is missing its schedule identity")
        reference = require_aware_utc(at or utc_now())
        approximate_start = datetime.fromtimestamp(
            float(approximate_start_ms) / 1000.0,
            tz=UTC,
        )
        # QML transports epoch milliseconds while runtime schedule boundaries can
        # retain microseconds. Search a narrow window around the displayed start
        # and recover the authoritative GuideProgram by stable schedule ID.
        horizon = self.service.horizon(
            approximate_start - timedelta(seconds=1),
            approximate_start + timedelta(seconds=1),
            generated_at=reference,
        )
        for row in horizon.rows:
            if row.channel_number != channel_number:
                continue
            for program in row.programs:
                if program.schedule_id == schedule_id:
                    return program
        raise GuideError(
            "Guide program is stale or no longer belongs to the current channel schedule; refresh the Guide"
        )

    def activate_program(
        self,
        schedule_id: str,
        channel_number: int,
        approximate_start_ms: float,
        *,
        at: datetime | None = None,
    ) -> TuneDecision:
        """Tune current Guide selections or start past owned programs from the beginning."""

        reference = require_aware_utc(at or utc_now())
        program = self.resolve_program(
            schedule_id,
            channel_number,
            approximate_start_ms,
            at=reference,
        )
        if program.start_utc > reference:
            raise GuideError("future Guide programs cannot be played before they air")

        guide = self._ensure_guide()
        if program.start_utc <= reference < program.end_utc:
            decision = guide.tune(program, at=reference)
        else:
            decision = guide.watch_from_beginning(program, at=reference)
        self._last_decision = decision
        return decision

    def pause(self, *, at: datetime | None = None) -> TuneDecision:
        decision = self._ensure_session().pause(now=at)
        self._last_decision = decision
        return decision

    def play(self, *, at: datetime | None = None) -> TuneDecision:
        decision = self._ensure_session().play(now=at)
        self._last_decision = decision
        return decision

    def skip(self, delta_seconds: float, *, at: datetime | None = None) -> TuneDecision:
        decision = self._ensure_session().skip(delta_seconds, now=at)
        self._last_decision = decision
        return decision

    def go_live(self, *, at: datetime | None = None) -> TuneDecision:
        decision = self._ensure_session().go_live(now=at)
        self._last_decision = decision
        return decision

    def channel_up(self, *, at: datetime | None = None) -> TuneDecision:
        decision = self._ensure_session().channel_up(now=at)
        self._last_decision = decision
        return decision

    def channel_down(self, *, at: datetime | None = None) -> TuneDecision:
        decision = self._ensure_session().channel_down(now=at)
        self._last_decision = decision
        return decision

    def sync(self, *, at: datetime | None = None) -> TuneDecision:
        """Synchronize decoder playback with the authoritative Viewer Clock."""

        decision = self._ensure_session().sync(now=at)
        self._last_decision = decision
        return decision

    def suspend_decoder(self) -> None:
        """Release live-TV decoder output while preserving runtime clock state."""

        if self._session is not None:
            self._session.suspend_decoder()

    def stop(self) -> None:
        if self._session is not None:
            self._session.stop()
