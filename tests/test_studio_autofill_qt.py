from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication

from channelos import couch_qt
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
from channelos.scanner import MediaScanner, ScanCancelled


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


def test_stop_cancels_and_joins_active_library_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller, media_root = _controller(tmp_path)
    started = threading.Event()
    cancelled = threading.Event()

    def wait_for_cancel(
        _scanner,
        _source,
        *,
        on_progress=None,
        should_cancel=None,
    ):
        started.set()
        while should_cancel is not None and not should_cancel():
            time.sleep(0.005)
        cancelled.set()
        raise ScanCancelled()

    monkeypatch.setattr(MediaScanner, "scan", wait_for_cancel)
    assert controller.startMediaScan(str(media_root))["ok"] is True
    _process_until(started.is_set)
    thread = controller._scan_thread
    assert thread is not None and thread.isRunning()

    controller.stop()

    assert cancelled.is_set()
    assert not thread.isRunning()
    assert app is not None


def test_stop_cancels_and_joins_active_studio_auto_fill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller, media_root = _controller(tmp_path)
    started = threading.Event()
    cancelled = threading.Event()

    def wait_for_cancel(
        _editor,
        _start,
        _end,
        *,
        on_progress,
        should_cancel,
    ):
        started.set()
        while not should_cancel():
            time.sleep(0.005)
        cancelled.set()
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
    assert controller.startStudioAutoFill(
        editor,
        "2026-09-07T00:00:00+00:00",
        "2026-09-08T00:00:00+00:00",
    )["ok"] is True
    _process_until(started.is_set)
    thread = controller._studio_auto_fill_thread
    assert thread is not None and thread.isRunning()

    controller.stop()

    assert cancelled.is_set()
    assert not thread.isRunning()
    assert app is not None


def test_settings_can_open_the_diagnostic_log_folder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller, _media_root = _controller(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        couch_qt.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    result = controller.openDiagnosticLogs()

    assert result["ok"] is True
    assert len(opened) == 1
    assert Path(opened[0]) == tmp_path / "logs"
    assert (tmp_path / "logs").is_dir()
    controller.stop()
    assert app is not None


def test_qml_ad_settings_survive_real_autofill_preview_and_apply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exercise the actual JavaScript -> QVariantMap -> Python service path."""
    import json

    import channelos
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression

    app = QGuiApplication.instance() or QGuiApplication([])
    controller, _media_root = _controller(tmp_path)
    ads = tmp_path / "ads"
    ads.mkdir()
    (ads / "short.mp4").write_bytes(b"owned-advertisement")
    MediaScanner(controller._library, FixedProbe()).scan(ads)

    received = []
    original_auto_fill = controller._broadcaster.auto_fill_studio

    def capture(editor, *args, **kwargs):
        received.append(editor)
        return original_auto_fill(editor, *args, **kwargs)

    monkeypatch.setattr(controller._broadcaster, "auto_fill_studio", capture)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    host_component = QQmlComponent(engine)
    host_component.setData(
        b'import QtQuick; QtObject { property string screen: "studio"; '
        b'property int studioChannelNumber: 7 }', QUrl())
    host = host_component.create()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(
        Path(channelos.__file__).resolve().parent / "qml" / "ChannelStudioScreen.qml")))
    while component.isLoading():
        app.processEvents()
    assert component.isReady(), [error.toString() for error in component.errors()]
    item = component.create()
    item.setProperty("hostWindow", host)
    app.processEvents()

    def evaluate(code):
        expression = QQmlExpression(engine.contextForObject(item), item, code)
        result, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        app.processEvents()
        return result.toVariant() if hasattr(result, "toVariant") else result

    try:
        evaluate("adBreaksEnabledCheck.checked = true; adSourcesArea.text = " + json.dumps(str(ads))
                 + '; adTriggersField.text = "calendar_boundary"; adPriorityField.text = "0"')
        started = evaluate('channelOS.startStudioAutoFill(editorObject(), '
                           '"2026-09-07T00:00:00+00:00", "2026-09-07T00:02:00+00:00")')
        assert started["ok"] is True
        _process_until(lambda: controller._studio_auto_fill_thread is None)
        _process_until(lambda: not item.property("autoFillApplying"))
        assert controller.studioAutoFill["phase"] == "ready", controller.studioAutoFill["message"]
        assert received[0]["adPriority"] == 0
        assert type(received[0]["adPriority"]) is float  # Qt's whole-number double
        assert item.property("calendarBlockCount") == 4
        preview = evaluate("channelOS.previewChannel(editorObject())")
        assert preview["ok"] is True, preview
        profile = evaluate('channelOS.saveAdBreakProfile({profileId: "p", name: "Profile", '
                           'defaults: {priority: 2}})')
        assert profile["ok"] is True, profile
        evaluate("applyDraft()")
        assert item.property("feedbackIsError") is False, item.property("feedbackMessage")
        saved = controller._broadcaster.records[0].definition
        assert saved.advertising.enabled is True
        assert saved.advertising.priority == 0
        assert type(saved.advertising.priority) is int
    finally:
        controller.stop()
        item.setProperty("hostWindow", None)
        item.deleteLater()
        host.deleteLater()
        engine.deleteLater()
        app.processEvents()

