from __future__ import annotations

from collections.abc import Callable

from channelos.window_startup import (
    NativeWindowSnapshot,
    NativeWindowStartupGate,
)


def snapshot(
    *,
    host_visible: bool = True,
    host_exposed: bool = True,
    video_visible: bool = True,
    video_exposed: bool = True,
    video_width: int = 640,
    video_height: int = 360,
    video_required: bool = True,
) -> NativeWindowSnapshot:
    return NativeWindowSnapshot(
        host_visible=host_visible,
        host_exposed=host_exposed,
        video_visible=video_visible,
        video_exposed=video_exposed,
        video_width=video_width,
        video_height=video_height,
        video_required=video_required,
    )


class ManualScheduler:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, _delay_ms: int, callback: Callable[[], None]) -> None:
        self.pending.append(callback)

    def run_next(self) -> None:
        self.pending.pop(0)()


def test_gate_waits_for_three_stable_ready_samples() -> None:
    samples = iter(
        (
            snapshot(host_exposed=False, video_exposed=False),
            snapshot(),
            snapshot(),
            snapshot(),
        )
    )
    scheduler = ManualScheduler()
    starts: list[str] = []
    reports: list[str] = []
    gate = NativeWindowStartupGate(
        sample=lambda: next(samples),
        schedule=scheduler,
        start=lambda: starts.append("started"),
        report=reports.append,
    )

    gate.begin()
    assert starts == []
    scheduler.run_next()
    scheduler.run_next()
    assert starts == []
    scheduler.run_next()

    assert starts == ["started"]
    assert gate.started is True
    assert "remained ready for 3 checks" in reports[-1]


def test_gate_resets_stability_when_readiness_is_lost() -> None:
    samples = iter(
        (
            snapshot(),
            snapshot(),
            snapshot(video_exposed=False),
            snapshot(),
            snapshot(),
            snapshot(),
        )
    )
    scheduler = ManualScheduler()
    starts: list[str] = []
    gate = NativeWindowStartupGate(
        sample=lambda: next(samples),
        schedule=scheduler,
        start=lambda: starts.append("started"),
        report=lambda _message: None,
    )

    gate.begin()
    for _ in range(4):
        scheduler.run_next()
    assert starts == []
    scheduler.run_next()

    assert starts == ["started"]


def test_gate_uses_one_fallback_attempt_after_timeout() -> None:
    scheduler = ManualScheduler()
    starts: list[str] = []
    reports: list[str] = []
    gate = NativeWindowStartupGate(
        sample=lambda: snapshot(
            host_exposed=False,
            video_visible=False,
            video_exposed=False,
            video_width=0,
            video_height=0,
        ),
        schedule=scheduler,
        start=lambda: starts.append("started"),
        report=reports.append,
        interval_ms=50,
        timeout_ms=150,
    )

    gate.begin()
    scheduler.run_next()
    scheduler.run_next()

    assert starts == ["started"]
    assert gate.started is True
    assert "timed out" in reports[-1]
    assert scheduler.pending == []


def test_gate_does_not_require_video_exposure_for_static_home() -> None:
    scheduler = ManualScheduler()
    starts: list[str] = []
    hidden_video = snapshot(
        video_visible=False,
        video_exposed=False,
        video_width=0,
        video_height=0,
        video_required=False,
    )
    gate = NativeWindowStartupGate(
        sample=lambda: hidden_video,
        schedule=scheduler,
        start=lambda: starts.append("started"),
        report=lambda _message: None,
    )

    gate.begin()
    scheduler.run_next()
    scheduler.run_next()

    assert starts == ["started"]


def test_gate_begin_is_idempotent() -> None:
    scheduler = ManualScheduler()
    gate = NativeWindowStartupGate(
        sample=lambda: snapshot(),
        schedule=scheduler,
        start=lambda: None,
        report=lambda _message: None,
    )

    gate.begin()
    gate.begin()

    assert len(scheduler.pending) == 1
