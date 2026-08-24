from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class NativeWindowSnapshot:
    """Observable window state required before native video playback starts."""

    host_visible: bool
    host_exposed: bool
    video_visible: bool
    video_exposed: bool
    video_width: int
    video_height: int
    video_required: bool = True

    @property
    def ready(self) -> bool:
        if not self.host_visible or not self.host_exposed:
            return False
        if not self.video_required:
            return True
        return (
            self.video_visible
            and self.video_exposed
            and self.video_width > 0
            and self.video_height > 0
        )

    def describe(self) -> str:
        return (
            f"host visible={self.host_visible} exposed={self.host_exposed}; "
            f"video required={self.video_required} visible={self.video_visible} "
            f"exposed={self.video_exposed} "
            f"size={self.video_width}x{self.video_height}"
        )


class NativeWindowStartupGate:
    """Start native playback after the embedded window is stably realizable.

    The gate deliberately knows nothing about Qt. Callers provide a state sample,
    a scheduler, and the final start callback so the readiness policy remains
    deterministic and testable without a graphical environment.
    """

    def __init__(
        self,
        *,
        sample: Callable[[], NativeWindowSnapshot],
        schedule: Callable[[int, Callable[[], None]], None],
        start: Callable[[], None],
        report: Callable[[str], None],
        interval_ms: int = 50,
        stable_samples: int = 3,
        timeout_ms: int = 5000,
    ) -> None:
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        if stable_samples <= 0:
            raise ValueError("stable_samples must be positive")
        if timeout_ms < interval_ms:
            raise ValueError("timeout_ms must be at least interval_ms")

        self._sample = sample
        self._schedule = schedule
        self._start = start
        self._report = report
        self._interval_ms = interval_ms
        self._stable_samples_required = stable_samples
        self._maximum_attempts = max(1, timeout_ms // interval_ms)
        self._attempts = 0
        self._stable_samples = 0
        self._started = False
        self._last_snapshot: NativeWindowSnapshot | None = None

    @property
    def started(self) -> bool:
        return self._started

    def begin(self) -> None:
        if self._started or self._attempts:
            return
        self._report("waiting for native Home video surface")
        self._check()

    def _check(self) -> None:
        if self._started:
            return

        snapshot = self._sample()
        self._attempts += 1

        if snapshot != self._last_snapshot:
            self._report(snapshot.describe())
            self._last_snapshot = snapshot

        if snapshot.ready:
            self._stable_samples += 1
        else:
            self._stable_samples = 0

        if self._stable_samples >= self._stable_samples_required:
            self._finish(
                "native Home video surface remained ready for "
                f"{self._stable_samples_required} checks; starting playback"
            )
            return

        if self._attempts >= self._maximum_attempts:
            self._finish(
                "native Home video surface readiness timed out; "
                "making one fallback playback attempt"
            )
            return

        self._schedule(self._interval_ms, self._check)

    def _finish(self, message: str) -> None:
        if self._started:
            return
        self._started = True
        self._report(message)
        self._start()
