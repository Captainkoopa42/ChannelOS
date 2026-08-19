from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class PlaybackError(RuntimeError):
    """Base error for ChannelOS playback backends."""


class PlaybackUnavailableError(PlaybackError):
    """Raised when an optional playback backend is not installed or usable."""


class PlaybackBackend(ABC):
    """Backend-neutral playback contract used by ChannelOS runtime code."""

    @abstractmethod
    def load(self, path: str | Path) -> None: ...

    @abstractmethod
    def play(self) -> None: ...

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def seek(self, seconds: float) -> None:
        """Seek to an absolute media time in seconds."""

    @abstractmethod
    def get_position(self) -> float:
        """Return the current absolute media time in seconds."""

    @abstractmethod
    def set_volume(self, percent: int) -> None: ...

    @abstractmethod
    def get_volume(self) -> int: ...

    @abstractmethod
    def set_muted(self, muted: bool) -> None: ...

    @abstractmethod
    def get_muted(self) -> bool: ...

    @abstractmethod
    def set_rate(self, rate: float) -> None: ...


class LibVLCBackend(PlaybackBackend):
    """Reference playback backend using python-vlc over the native libVLC library."""

    def __init__(self, *instance_options: str) -> None:
        try:
            import vlc  # type: ignore
        except ImportError as exc:
            raise PlaybackUnavailableError(
                "python-vlc is not installed. Install ChannelOS with the 'playback' extra."
            ) from exc

        self._vlc: Any = vlc
        try:
            self._instance = vlc.Instance(*instance_options)
            self._player = self._instance.media_player_new()
        except Exception as exc:
            raise PlaybackUnavailableError(
                "libVLC could not be initialized. Install VLC/libVLC for this operating system."
            ) from exc

    def load(self, path: str | Path) -> None:
        media_path = Path(path).expanduser().resolve(strict=False)
        media = self._instance.media_new_path(str(media_path))
        self._player.set_media(media)

    def play(self) -> None:
        result = self._player.play()
        if isinstance(result, int) and result < 0:
            raise PlaybackError("libVLC could not start playback")

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def seek(self, seconds: float) -> None:
        milliseconds = max(0, int(seconds * 1000))
        result = self._player.set_time(milliseconds)
        if isinstance(result, int) and result < 0:
            raise PlaybackError(f"libVLC could not seek to {seconds:.3f}s")

    def get_position(self) -> float:
        milliseconds = self._player.get_time()
        if milliseconds is None or milliseconds < 0:
            return 0.0
        return float(milliseconds) / 1000.0

    def set_volume(self, percent: int) -> None:
        if not 0 <= percent <= 200:
            raise ValueError("volume must be from 0 through 200 percent")
        result = self._player.audio_set_volume(percent)
        if isinstance(result, int) and result < 0:
            raise PlaybackError(f"libVLC rejected volume {percent}")

    def get_volume(self) -> int:
        value = self._player.audio_get_volume()
        return max(0, int(value))

    def set_muted(self, muted: bool) -> None:
        self._player.audio_set_mute(bool(muted))

    def get_muted(self) -> bool:
        return bool(self._player.audio_get_mute())

    def set_rate(self, rate: float) -> None:
        if rate <= 0:
            raise ValueError("playback rate must be positive")
        result = self._player.set_rate(float(rate))
        if isinstance(result, int) and result < 0:
            raise PlaybackError(f"libVLC rejected playback rate {rate}")
