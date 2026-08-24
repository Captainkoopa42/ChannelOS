from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

import channelos


class FakeHost(QObject):
    screenChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._screen = "library"

    @Property(str, notify=screenChanged)
    def screen(self) -> str:
        return self._screen

    @screen.setter
    def screen(self, value: str) -> None:
        if value == self._screen:
            return
        self._screen = value
        self.screenChanged.emit()


class FakeChannelOS(QObject):
    libraryChanged = Signal()
    libraryScanChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._library = {
            "count": 1,
            "locationCount": 1,
            "sourceCount": 1,
            "items": [
                {
                    "assetId": "sha256:test",
                    "title": "Owned Clip",
                    "fileName": "owned.mp4",
                    "path": "C:/Owned Media/owned.mp4",
                    "sourceRoot": "C:/Owned Media",
                    "sourceName": "Owned Media",
                    "durationSeconds": 30.0,
                    "sizeBytes": 1234,
                    "containerFormat": "MP4",
                    "artworkUrl": "",
                }
            ],
            "sources": [
                {
                    "path": "C:/Owned Media",
                    "name": "Owned Media",
                    "status": "ready",
                    "available": True,
                    "discoveredCount": 1,
                    "locationCount": 1,
                    "onlineLocationCount": 1,
                    "assetCount": 1,
                    "lastScanStartedAt": "",
                    "lastScanFinishedAt": "",
                    "lastError": "",
                    "usedByChannels": [],
                }
            ],
        }
        self._scan = {
            "active": False,
            "phase": "idle",
            "sourcePath": "",
            "current": 0,
            "total": 0,
            "fileName": "",
            "message": "",
        }

    @Property("QVariantMap", notify=libraryChanged)
    def librarySnapshot(self):
        return self._library

    @Property("QVariantMap", notify=libraryScanChanged)
    def libraryScan(self):
        return self._scan

    @Slot()
    def refreshLibrary(self) -> None:
        self.libraryChanged.emit()

    @Slot(result="QVariantMap")
    def chooseMediaFolder(self):
        return {"ok": False, "cancelled": True, "message": ""}

    @Slot(str, result="QVariantMap")
    def preflightMediaSource(self, path):
        return {
            "ok": True,
            "path": path,
            "name": "Owned Media",
            "supportedCount": 1,
            "alreadyIndexed": True,
            "message": "preflight",
        }

    @Slot(str, result="QVariantMap")
    def startMediaScan(self, path):
        return {"ok": True, "message": "started"}

    @Slot(result="QVariantMap")
    def cancelMediaScan(self):
        return {"ok": True, "message": "cancelled"}

    @Slot(str, result="QVariantMap")
    def removeLibrarySource(self, path):
        return {"ok": True, "message": "removed"}

    @Slot(str, result="QVariantMap")
    def playLibraryAsset(self, asset_id):
        return {"ok": True, "message": "playing"}

    @Slot(str, result=str)
    def requestLibraryArtwork(self, asset_id):
        return ""


def test_library_qml_instantiates_headlessly() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    host = FakeHost()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    qml_path = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "LibraryScreen.qml"
    )
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))

    if component.isLoading():
        app.processEvents()

    errors = "\n".join(error.toString() for error in component.errors())
    assert component.isReady(), errors

    item = component.create(engine.rootContext())
    assert item is not None, errors
    item.setProperty("hostWindow", host)
    app.processEvents()

    assert item.property("selectedShelf") == 0
    assert item.property("selectedColumn") == 0
    assert item.property("expandedShelfId") == "all"
    assert item.property("managerVisible") is False
    assert item.property("shelfCount") >= 2

    host.screen = "home"
    app.processEvents()
    assert host.screen == "home"

    item.deleteLater()
    app.processEvents()


def test_library_manager_qml_instantiates_headlessly() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    host = FakeHost()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    qml_path = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "LibraryManagerScreen.qml"
    )
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))

    if component.isLoading():
        app.processEvents()

    errors = "\n".join(error.toString() for error in component.errors())
    assert component.isReady(), errors

    item = component.create(engine.rootContext())
    assert item is not None, errors
    item.setProperty("hostWindow", host)
    item.setProperty("active", True)
    app.processEvents()

    assert item.property("selectedMedia") == 0
    assert item.property("selectedSource") == 0
    assert item.property("feedbackMessage") == ""

    item.deleteLater()
    app.processEvents()
