from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .library import IndexedMedia
from .playback import (
    LibVLCBackend,
    NativeVideoSurface,
    PlaybackBackend,
)

BackendFactory = Callable[[], PlaybackBackend]


class OnDemandError(ValueError):
    """Raised when an On Demand action has no valid media target."""


@dataclass(frozen=True, slots=True)
class OnDemandState:
    active: bool
    asset_id: str = ""
    title: str = ""
    path: Path | None = None
    duration_seconds: float = 0.0
    position_seconds: float = 0.0
    paused: bool = False
    ended: bool = False


class OnDemandSession:
    """Playback state for Library media, independent of channel scheduling."""

    def __init__(
        self,
        *,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self._backend_factory = backend_factory or LibVLCBackend
        self._backend: PlaybackBackend | None = None
        self._surface: NativeVideoSurface | None = None
        self._current: IndexedMedia | None = None
        self._paused = False

    @property
    def active(self) -> bool:
        return self._current is not None

    @property
    def paused(self) -> bool:
        return self._paused

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self._surface = surface
        if self._backend is not None:
            self._backend.attach_video_surface(surface)

    def _ensure_backend(self) -> PlaybackBackend:
        if self._backend is not None:
            return self._backend

        backend = self._backend_factory()
        if self._surface is not None:
            backend.attach_video_surface(self._surface)

        self._backend = backend
        return backend

    def _restart_current_media_at(
        self,
        seconds: float,
    ) -> OnDemandState:
        """Rebuild playback after a backend reaches natural EOF.

        Some native decoders cannot reliably leave their ENDED state through
        play()/seek() alone. Re-loading the current media gives the backend a
        fresh decoder/vout pipeline while preserving the On Demand selection.
        """

        if self._current is None:
            raise OnDemandError(
                "no On Demand media is currently playing"
            )

        backend = self._ensure_backend()

        duration = float(
            self._current.asset.duration_seconds or 0.0
        )

        target = max(0.0, float(seconds))
        if duration > 0:
            target = min(target, duration)

        backend.stop()
        backend.load(self._current.location.path)
        backend.play()

        if target > 0:
            backend.seek(target)

        self._paused = False
        return self.state()

    def play_media(self, media: IndexedMedia) -> OnDemandState:
        backend = self._ensure_backend()
        backend.load(media.location.path)
        backend.play()
        backend.seek(0.0)

        self._current = media
        self._paused = False
        return self.state()

    def state(self) -> OnDemandState:
        if self._current is None:
            return OnDemandState(active=False)

        position = 0.0
        ended = False

        if self._backend is not None:
            ended = bool(self._backend.has_ended())
            position = max(
                0.0,
                float(self._backend.get_position()),
            )

        duration = float(
            self._current.asset.duration_seconds or 0.0
        )

        # Some playback engines reset their reported timestamp to zero after
        # entering ENDED. The television UI should still show the playhead at
        # the actual end of the media.
        if ended and duration > 0:
            position = duration
        elif duration > 0:
            position = min(position, duration)

        return OnDemandState(
            active=True,
            asset_id=self._current.asset.asset_id,
            title=self._current.location.path.stem,
            path=self._current.location.path,
            duration_seconds=duration,
            position_seconds=position,
            paused=self._paused,
            ended=ended,
        )

    def toggle_pause(self) -> OnDemandState:
        if self._current is None or self._backend is None:
            raise OnDemandError("no On Demand media is currently playing")

        # ENDED is not PAUSED. libVLC must be explicitly restarted before
        # playback can continue.
        if self._backend.has_ended():
            return self._restart_current_media_at(0.0)

        if self._paused:
            self._backend.play()
            self._paused = False
        else:
            self._backend.pause()
            self._paused = True

        return self.state()

    def skip(self, delta_seconds: float) -> OnDemandState:
        if self._current is None or self._backend is None:
            raise OnDemandError("no On Demand media is currently playing")

        duration = float(
            self._current.asset.duration_seconds or 0.0
        )
        ended = bool(self._backend.has_ended())

        # Several playback engines report zero after media enters ENDED.
        # Semantically the playhead is at duration, so seek relative to that.
        if ended and duration > 0:
            current = duration
        else:
            current = max(
                0.0,
                float(self._backend.get_position()),
            )

        target = max(
            0.0,
            current + float(delta_seconds),
        )

        if duration > 0:
            target = min(target, duration)

        if ended and target < duration:
            # ENDED is a terminal decoder state for some native backends.
            # Rebuild the media pipeline instead of trying to revive it.
            return self._restart_current_media_at(target)

        self._backend.seek(target)
        return self.state()

    def stop(self) -> None:
        if self._backend is not None:
            self._backend.stop()

        self._current = None
        self._paused = False
