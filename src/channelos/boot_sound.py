"""The boot jig: "Poppie" plays softly while ChannelOS starts.

The track (assets/sound/boot_poppie.ogg) is the jig repeated in passes of
exactly 3.0 s (8 beats at 160 BPM), already softened, with a fade-in at the
start. The first note of every pass doubles as the jig's final "na", so when
start-up finishes the sound runs on to the next pass boundary and fades out on
that note: a quick boot hears the jig once, a slow boot hears it loop.

Playback goes through libVLC on its own thread (starting libVLC can take a
moment); the user's volume is applied as libVLC gain from the very first
sample, and nothing plays while muted.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)

BOOT_SOUND_PATH = Path(__file__).resolve().parent / "assets" / "sound" / "boot_poppie.ogg"
PASS_SECONDS = 3.0
TRACK_SECONDS = 60.45
FADE_OUT_SECONDS = 0.45


def finish_delay(elapsed: float) -> float:
    """Seconds until the next pass boundary (never before the first pass ends)."""
    elapsed = max(0.0, float(elapsed))
    boundary = max(PASS_SECONDS, math.ceil((elapsed + 0.05) / PASS_SECONDS) * PASS_SECONDS)
    return max(0.0, boundary - elapsed)


def _default_backend(volume_percent: int):
    from .playback import LibVLCBackend
    gain = max(0.0, min(1.0, volume_percent / 100.0))
    return LibVLCBackend("--quiet", "--no-video", f"--gain={gain:.2f}")


class BootSound(QObject):
    def __init__(self, volume_percent: int, muted: bool, *, path: Path = BOOT_SOUND_PATH,
                 backend_factory: Callable[[int], object] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._volume = max(0, min(100, int(volume_percent)))
        self._muted = bool(muted)
        self._path = Path(path)
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
        return True

    def _open(self) -> None:
        try:
            backend = self._factory(self._volume)
            backend.load(self._path)
            backend.play()
            # The user's level is already libVLC gain; 100 here keeps the fade
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

    def elapsed(self) -> float:
        backend, started = self._backend, self._started_at
        if backend is None or started is None:
            return 0.0
        try:
            position = float(backend.get_position())
        except Exception:
            position = 0.0
        return position if position > 0 else time.monotonic() - started

    def finish(self) -> None:
        """Start-up is done: end on the next "na" with a fade."""
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
        QTimer.singleShot(int(finish_delay(self.elapsed()) * 1000), self.fade_out)

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
        if backend is not None:
            threading.Thread(target=self._stop_backend, args=(backend,), daemon=True).start()

    @staticmethod
    def _stop_backend(backend) -> None:
        try:
            backend.stop()
        except Exception:
            logger.debug("Boot sound did not stop cleanly", exc_info=True)
