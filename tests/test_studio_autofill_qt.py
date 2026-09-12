from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication

from channelos.broadcaster import (
    BroadcasterService,
    StudioAutoFillCancelled,
)
from channelos.broadcaster_qt import BroadcasterCouchController
from channelos.guide import GuideService
from channelos.library import MediaLibrary
from channelos.probe import MediaProbeResult
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
from channelos.scanner import MediaScanner


class FixedProbe:
    def probe(self, path: Path) -> MediaProbeResult:
        return MediaProbeResult(
            duration_seconds=30.0,
            container_format=path.suffix.lstrip(".") or "mp4",
        )


def _controller(tmp_path: Path) -> tuple[BroadcasterCouchController, Path]:
    media_root = tmp_path / "media"
    media_root.mkdir()
    (media_root / "program.mp4").write_bytes(b"owned-media")
    library = MediaLibrary(tmp_path / "library.db")
    MediaScanner(library, FixedProbe()).scan(media_root)
    broadcaster = BroadcasterService((), tmp_path / "channels", library)
    broadcaster.create(
        {
            "channel": 7,
            "name": "Studio Test",
            "sources": [str(media_root)],
            "mode": "sequential",
            "preserveEpisodeOrder": False,
            "avoidRepeatDays": 0,
            "numberWidth": 3,
        }
    )
    store = RuntimeStore(tmp_path / "runtime.db")
    runtimes = tuple(
        ChannelRuntime.open(resolve_channel(record.definition, library), store)
        for record in broadcaster.records
    )
    guide = GuideService(runtimes)
    television = TelevisionRuntime(runtimes, store)
    return (
        BroadcasterCouchController(
            guide,
            television,
            library,
            broadcaster,
            store,
        ),
        media_root,
    )


def _process_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert predicate()


def test_studio_auto_fill_runs_off_thread_and_cancels_without_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller, media_root = _controller(tmp_path)
    completed: list[dict[str, object]] = []
    controller.studioAutoFillCompleted.connect(completed.append)

    def wait_for_cancel(
        _editor,
        _start,
        _end,
        *,
        on_progress,
        should_cancel,
    ):
        on_progress(1, 10, "working")
        while not should_cancel():
            time.sleep(0.005)
        raise StudioAutoFillCancelled()

    monkeypatch.setattr(
        controller._broadcaster,
        "auto_fill_studio",
        wait_for_cancel,
    )
    editor = {
        "channel": 7,
        "name": "Studio Test",
        "sources": [str(media_root)],
        "mode": "calendar",
        "fillerMode": "sequential",
        "calendarBlocks": [],
    }

    started = controller.startStudioAutoFill(
        editor,
        "2026-09-07T00:00:00+00:00",
        "2026-09-08T00:00:00+00:00",
    )

    assert started["ok"] is True
    assert controller.studioAutoFill["active"] is True
    assert controller.cancelStudioAutoFill()["ok"] is True
    _process_until(lambda: controller.studioAutoFill["phase"] == "cancelled")
    _process_until(lambda: controller._studio_auto_fill_thread is None)
    assert completed == []
    assert "draft was not changed" in str(controller.studioAutoFill["message"])
    controller.stop()
    assert app is not None


def test_studio_auto_fill_publishes_only_completed_background_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller, media_root = _controller(tmp_path)
    completed: list[dict[str, object]] = []
    controller.studioAutoFillCompleted.connect(completed.append)

    def complete(
        _editor,
        start,
        end,
        *,
        on_progress,
        should_cancel,
    ):
        assert not should_cancel()
        on_progress(5, 10, "halfway")
        return {
            "ok": True,
            "message": "ready",
            "startUtc": start,
            "endUtc": end,
            "blocks": [],
        }

    monkeypatch.setattr(controller._broadcaster, "auto_fill_studio", complete)
    editor = {
        "channel": 7,
        "name": "Studio Test",
        "sources": [str(media_root)],
        "mode": "calendar",
        "fillerMode": "sequential",
        "calendarBlocks": [],
    }

    assert controller.startStudioAutoFill(
        editor,
        "2026-09-07T00:00:00+00:00",
        "2026-09-08T00:00:00+00:00",
    )["ok"] is True

    _process_until(lambda: bool(completed))
    _process_until(lambda: controller._studio_auto_fill_thread is None)
    assert completed[0]["message"] == "ready"
    assert controller.studioAutoFill["phase"] == "ready"
    assert controller.studioAutoFill["percent"] == 100
    controller.stop()
    assert app is not None
