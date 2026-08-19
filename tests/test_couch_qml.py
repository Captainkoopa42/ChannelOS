from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

import channelos


class FakeChannelOS(QObject):
    snapshotChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._snapshot = {
            "generatedAtMs": 1_777_000_000_000,
            "horizonStartMs": 1_777_000_000_000,
            "horizonEndMs": 1_777_010_800_000,
            "rows": [],
        }

    @Property("QVariantMap", notify=snapshotChanged)
    def snapshot(self):
        return self._snapshot

    @Slot()
    def refresh(self) -> None:
        self.snapshotChanged.emit()


def test_main_qml_instantiates_headlessly() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    qml_path = Path(channelos.__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    roots = engine.rootObjects()
    assert roots, "Main.qml failed to instantiate"
    assert roots[0].property("screen") == "home"
    roots[0].close()
    app.processEvents()
