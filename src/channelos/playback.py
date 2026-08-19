from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class PlaybackError(RuntimeError):
    """Base error for ChannelOS playback backends."""


class PlaybackUnavailableError(PlaybackError):
    """Raised when an optional playback backend is not installed or usable."""


VLC_RUNTIME_ENV = "CHANNELOS_VLC_DIR"
IS_WINDOWS = os.name == "nt"


def _bundled_vlc_runtime_candidates() -> tuple[Path, ...]:
    """Return ChannelOS-owned libVLC locations in product-first order."""

    executable_root = Path(sys.executable).resolve().parent
    package_root = Path(__file__).resolve().parent
    source_root = Path(__file__).resolve().parents[2]
    return (
        executable_root / "runtime" / "vlc",
        package_root / "runtime" / "vlc",
        source_root / "runtime" / "vlc",
    )


def _vlc_runtime_candidates() -> tuple[Path, ...]:
    candidates = list(_bundled_vlc_runtime_candidates())
    override = os.environ.get(VLC_RUNTIME_ENV)
    if override:
        candidates.append(Path(override).expanduser())

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        key = os.path.normcase(str(resolved))
        if key not in seen:
            unique.append(resolved)
            seen.add(key)
    return tuple(unique)


def _prepare_windows_vlc_runtime() -> tuple[Any | None, Path | None]:
    """Make a ChannelOS-owned or explicitly supplied libVLC visible to Windows."""

    if not IS_WINDOWS:
        return None, None

    for candidate in _vlc_runtime_candidates():
        if not (candidate / "libvlc.dll").is_file():
            continue

        plugins = candidate / "plugins"
        if plugins.is_dir():
            os.environ["VLC_PLUGIN_PATH"] = str(plugins)

        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is not None:
            return add_dll_directory(str(candidate)), candidate

        current_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(candidate) + os.pathsep + current_path
        return None, candidate

    return None, None


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
        self._dll_directory_handle, self._runtime_dir = _prepare_windows_vlc_runtime()

        try:
            import vlc  # type: ignore
        except (ImportError, OSError) as exc:
            raise PlaybackUnavailableError(
                "libVLC could not be loaded. Packaged ChannelOS builds should include "
                "runtime/vlc; source builds may set CHANNELOS_VLC_DIR to a directory "
                "containing libvlc.dll and its plugins."
            ) from exc

        self._vlc: Any = vlc
        try:
            self._instance = vlc.Instance(*instance_options)
            self._player = self._instance.media_player_new()
        except Exception as exc:
            location = (
                f" from {self._runtime_dir}"
                if self._runtime_dir is not None
                else ""
            )
            raise PlaybackUnavailableError(
                f"libVLC could not be initialized{location}."
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
        if hasattr(self._player, "set_pause"):
            self._player.set_pause(1)
        else:
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
        if not 0 <= percent <= 100:
            raise ValueError("volume must be from 0 through 100 percent")
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
