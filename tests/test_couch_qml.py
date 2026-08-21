from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine

import channelos


class FakeChannelOS(QObject):
    snapshotChanged = Signal()
    playbackChanged = Signal()
    libraryChanged = Signal()
    onDemandChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._playback = {"active": False}
        self._on_demand = {"active": False}
        self._library_snapshot = {
            "count": 0,
            "locationCount": 0,
            "sourceCount": 0,
            "items": [],
        }
        self._snapshot = {
            "generatedAtMs": 1_777_000_000_000,
            "horizonStartMs": 1_777_000_000_000,
            "horizonEndMs": 1_777_010_800_000,
            "rows": [],
        }

    @Property("QVariantMap", notify=snapshotChanged)
    def snapshot(self):
        return self._snapshot

    @Property("QVariantMap", notify=playbackChanged)
    def playback(self):
        return self._playback

    @Property("QVariantMap", notify=libraryChanged)
    def librarySnapshot(self):
        return self._library_snapshot

    @Property("QVariantMap", notify=onDemandChanged)
    def onDemand(self):
        return self._on_demand

    @Slot()
    def refresh(self) -> None:
        self.snapshotChanged.emit()


def test_main_qml_instantiates_headlessly() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    video_window = QWindow()
    engine.rootContext().setContextProperty(
        "channelOSVideoWindow",
        video_window,
    )

    qml_path = Path(channelos.__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    roots = engine.rootObjects()
    assert roots, "Main.qml failed to instantiate"
    assert roots[0].property("screen") == "home"
    assert roots[0].property("channelEntry") == ""
    roots[0].setProperty("screen", "ondemand")
    roots[0].setProperty("channelEntry", "007")
    assert roots[0].property("channelEntry") == "007"
    roots[0].setProperty("channelEntry", "")
    roots[0].setProperty("screen", "home")
    assert roots[0].property("volumePercent") == 100
    assert roots[0].property("muted") is False
    roots[0].close()
    app.processEvents()
