from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .couch_model import build_couch_snapshot
from .guide import GuideService


class CouchController(QObject):
    """Small Qt-facing adapter over the read-only ChannelOS Guide service."""

    snapshotChanged = Signal()

    def __init__(self, service: GuideService) -> None:
        super().__init__()
        self._service = service
        self._snapshot = build_couch_snapshot(service)

    @Property("QVariantMap", notify=snapshotChanged)
    def snapshot(self) -> dict[str, object]:
        return self._snapshot

    @Slot()
    def refresh(self) -> None:
        self._snapshot = build_couch_snapshot(self._service)
        self.snapshotChanged.emit()


def run_qt(service: GuideService, *, windowed: bool = False) -> int:
    app = QGuiApplication.instance()
    owns_application = app is None
    if app is None:
        app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("ChannelOS")
    app.setOrganizationName("ChannelOS")

    controller = CouchController(service)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    roots = engine.rootObjects()
    if not roots:
        return 7

    window = roots[0]
    if windowed:
        window.showNormal()
    else:
        window.showFullScreen()

    if not owns_application:
        return 0
    return int(app.exec())
