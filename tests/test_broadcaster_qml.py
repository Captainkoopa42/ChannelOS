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
        self._screen = "broadcaster"

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
    broadcasterChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._snapshot = {
            "channelCount": 1,
            "suggestedChannel": 25,
            "managedDirectory": "channels",
            "sourceOptions": ["C:/Owned Media"],
            "channels": [
                {
                    "channelNumber": 7,
                    "displayNumber": "007",
                    "name": "Test Channel",
                    "description": "Owned television",
                    "mode": "sequential",
                    "preserveEpisodeOrder": False,
                    "avoidRepeatDays": 0,
                    "numberWidth": 3,
                    "sources": ["C:/Owned Media"],
                    "sourceCount": 1,
                    "path": "test-channel-07.yaml",
                    "managed": False,
                    "nowTitle": "Current Program",
                    "nextTitle": "Next Program",
                }
            ],
        }

    @Property("QVariantMap", notify=broadcasterChanged)
    def broadcasterSnapshot(self):
        return self._snapshot

    @Slot()
    def refreshBroadcaster(self) -> None:
        self.broadcasterChanged.emit()

    @Slot("QVariantMap", result="QVariantMap")
    def previewChannel(self, editor):
        return {
            "ok": True,
            "message": "preview",
            "resolvedCount": 1,
            "items": [
                {
                    "title": "Current Program",
                    "durationSeconds": 30.0,
                    "assetId": "sha256:test",
                    "path": "C:/Owned Media/test.mp4",
                }
            ],
        }

    @Slot("QVariantMap", result="QVariantMap")
    def createChannel(self, editor):
        return {
            "ok": True,
            "message": "created",
            "channelNumber": 25,
            "path": "channels/channel-0025.yaml",
        }

    @Slot(int, "QVariantMap", result="QVariantMap")
    def updateChannel(self, original, editor):
        return {
            "ok": True,
            "message": "updated",
            "channelNumber": original,
            "path": "test-channel-07.yaml",
            "backupPath": "test-channel-07.yaml.bak",
        }


def test_broadcaster_qml_instantiates_headlessly() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    host = FakeHost()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    qml_path = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "BroadcasterScreen.qml"
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

    assert item.property("editorMode") == "list"
    assert item.property("selectedChannelIndex") == 0
    assert item.property("feedbackMessage") == ""

    host.screen = "home"
    app.processEvents()
    assert host.screen == "home"

    item.deleteLater()
    app.processEvents()


def test_broadcaster_paths_always_bind_as_strings() -> None:
    qml_path = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "BroadcasterScreen.qml"
    )
    text = qml_path.read_text(encoding="utf-8")

    assert "snapshot.managedDirectory\n                                                  || \"\"" in text
