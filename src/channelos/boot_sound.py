"""The boot sound: "Poppie" (or your own sound) plays while ChannelOS starts.

The built-in track (assets/sound/boot_poppie.ogg) is Poppie's intro followed by
two cycles of its lead-in and chorus. Each cycle is 18 s, cut exactly where
the song itself repeats, so while start-up continues the player jumps from the
end of the file back to the start of the cycle (18.03 s) and the music carries
on without a seam. It is stored softened at full level; the Boot Sound Volume
setting (25% by default) and the main volume set how loud it plays.

When start-up finishes the sound plays on to the next bar line (1.5 s, four
beats at 160 BPM), after at least two bars, and fades out over one bar. Your
own boot sound repeats whole while loading and fades out the same way, without
the bar grid.

Playback goes through libVLC on its own thread (starting libVLC can take a
moment). The level is applied as libVLC gain from the first sample, and
nothing plays while muted.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)

BOOT_SOUND_PATH = Path(__file__).resolve().parent / "assets" / "sound" / "boot_poppie.ogg"
BAR_SECONDS = 1.5          # four beats at 160 BPM
MINIMUM_SECONDS = 3.0      # a quick boot still hears two bars
FADE_OUT_SECONDS = 1.5     # one bar
POPPIE_LOOP = (18.03, 54.03)   # lead-in + chorus cycles; the file ends on a cycle boundary
BOOT_SOUND_SUFFIXES = {".mp3", ".ogg", ".oga", ".opus", ".wav", ".flac", ".m4a", ".aac", ".wma"}


def finish_delay(elapsed: float, bar: float | None = BAR_SECONDS) -> float:
    """Seconds until the fade starts: the next bar line, never before two bars."""
    elapsed = max(0.0, float(elapsed))
    if not bar:
        return max(0.0, MINIMUM_SECONDS - elapsed)
    boundary = max(MINIMUM_SECONDS, math.ceil((elapsed + 0.05) / bar) * bar)
    return max(0.0, boundary - elapsed)


def boot_sound_plan(settings: Any, setup_directory: Path) -> dict[str, Any] | None:
    """What should play at start-up for these settings, or None for silence."""
    choice = getattr(settings, "boot_sound", "poppie")
    if choice == "off" or getattr(settings, "boot_video", "static") == "custom":
        return None  # a custom boot video brings its own sound
    volume = 0 if settings.muted else round(settings.volume_percent * settings.boot_sound_volume / 100)
    if volume <= 0:
        return None
    if choice == "custom":
        path = Path(setup_directory) / "boot" / settings.boot_sound_file if settings.boot_sound_file else None
        if path is not None and path.is_file():
            return {"path": path, "volume": volume, "loop": None, "bar": None}
    return {"path": BOOT_SOUND_PATH, "volume": volume, "loop": POPPIE_LOOP, "bar": BAR_SECONDS}


def _default_backend(volume_percent: int):
    from .playback import LibVLCBackend
    gain = max(0.0, min(1.0, volume_percent / 100.0))
    return LibVLCBackend("--quiet", "--no-video", f"--gain={gain:.3f}")


class BootSound(QObject):
    def __init__(self, volume_percent: int, muted: bool = False, *, path: Path = BOOT_SOUND_PATH,
                 loop: tuple[float, float] | None = POPPIE_LOOP, bar: float | None = BAR_SECONDS,
                 backend_factory: Callable[[int], object] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._volume = max(0, min(100, int(volume_percent)))
        self._muted = bool(muted)
        self._path = Path(path)
        self._loop = loop
        self._bar = bar
        self._factory = backend_factory or _default_backend
        self._backend = None
        self._started_at: float | None = None
        self._finish_requested = False
        self._finished = False
        self._lock = threading.Lock()
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(30)
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_started = 0.0
        self._ready_timer = QTimer(self)
        self._ready_timer.setInterval(50)
        self._ready_timer.timeout.connect(self._check_ready)
        self._loop_timer = QTimer(self)
        self._loop_timer.setInterval(40)
        self._loop_timer.timeout.connect(self._keep_looping)

    @classmethod
    def from_plan(cls, plan: dict[str, Any], **kwargs) -> "BootSound":
        return cls(int(plan["volume"]), False, path=plan["path"], loop=plan["loop"], bar=plan["bar"], **kwargs)

    @property
    def silent(self) -> bool:
        return self._muted or self._volume == 0 or not self._path.is_file()

    @property
    def finished(self) -> bool:
        return self._finished

    def start(self) -> bool:
        if self.silent:
            self._finished = True
            return False
        threading.Thread(target=self._open, name="ChannelOS boot sound", daemon=True).start()
        self._loop_timer.start()
        return True

    def _open(self) -> None:
        try:
            backend = self._factory(self._volume)
            backend.load(self._path)
            backend.play()
            # The level is already libVLC gain; 100 here keeps the fade
            # (transition level) working from a known volume.
            backend.set_volume(100)
        except Exception as exc:  # no libVLC or no audio device: boot stays silent
            logger.info("Boot sound unavailable: %s", exc)
            with self._lock:
                self._finished = True
            return
        with self._lock:
            if self._finished:
                self._stop_backend(backend)
                return
            self._backend = backend
            self._started_at = time.monotonic()

    def position(self) -> float:
        backend, started = self._backend, self._started_at
        if backend is None or started is None:
            return 0.0
        try:
            position = float(backend.get_position())
        except Exception:
            position = 0.0
        return position if position > 0 else time.monotonic() - started

    def _keep_looping(self) -> None:
        """Still loading at the end of the file: carry on from the loop start."""
        backend = self._backend
        if self._finished:
            self._loop_timer.stop()
            return
        if backend is None:
            return
        try:
            ended = bool(backend.has_ended())
            if self._loop is not None:
                start, end = self._loop
                position = float(backend.get_position())
                if ended:
                    backend.load(self._path)
                    backend.play()
                    backend.seek(start)
                elif position >= end - 0.045:
                    backend.seek(start + max(0.0, position - end))
            elif ended:
                backend.load(self._path)
                backend.play()
        except Exception:
            logger.debug("Boot sound loop failed", exc_info=True)

    def finish(self) -> None:
        """Start-up is done: fade out from the next bar line."""
        if self._finish_requested or self._finished:
            return
        self._finish_requested = True
        self._ready_timer.start()
        self._check_ready()

    def _check_ready(self) -> None:
        if self._finished:
            self._ready_timer.stop()
            return
        if self._backend is None:
            return  # still opening; try again shortly
        self._ready_timer.stop()
        delay = finish_delay(self.position(), self._bar)
        QTimer.singleShot(int(delay * 1000), self.fade_out)

    def fade_out(self) -> None:
        if self._finished or self._fade_timer.isActive():
            return
        self._fade_started = time.monotonic()
        self._fade_timer.start()

    def _fade_step(self) -> None:
        progress = (time.monotonic() - self._fade_started) / FADE_OUT_SECONDS
        backend = self._backend
        if backend is not None and progress < 1.0:
            try:
                backend.set_transition_level(max(0.0, 1.0 - progress))
            except Exception:
                progress = 1.0
        if progress >= 1.0:
            self._fade_timer.stop()
            self.stop()

    def stop(self) -> None:
        with self._lock:
            self._finished = True
            backend, self._backend = self._backend, None
        self._ready_timer.stop()
        self._fade_timer.stop()
        self._loop_timer.stop()
        if backend is not None:
            threading.Thread(target=self._stop_backend, args=(backend,), daemon=True).start()

    @staticmethod
    def _stop_backend(backend) -> None:
        try:
            backend.stop()
        except Exception:
            logger.debug("Boot sound did not stop cleanly", exc_info=True)
