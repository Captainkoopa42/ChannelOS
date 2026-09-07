from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Q_ARG, QEvent, QMetaObject, QObject, Property, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

import channelos
from channelos.broadcaster_qt import BroadcasterKeyFilter


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
            "channelCount": 2,
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
                    "managed": True,
                    "nowTitle": "Current Program",
                    "nextTitle": "Next Program",
                },
                {
                    "channelNumber": 8,
                    "displayNumber": "008",
                    "name": "Second Channel",
                    "description": "Deletion leaves this channel active",
                    "mode": "calendar",
                    "preserveEpisodeOrder": False,
                    "avoidRepeatDays": 0,
                    "numberWidth": 3,
                    "sources": ["C:/Owned Media"],
                    "sourceCount": 1,
                    "path": "channels/channel-0008.yaml",
                    "managed": True,
                    "nowTitle": "Second Program",
                    "nextTitle": "Later Program",
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

    @Slot(int, result="QVariantMap")
    def deleteChannel(self, channel_number):
        assert channel_number == 7
        self._snapshot = dict(self._snapshot)
        self._snapshot["channels"] = [
            channel
            for channel in self._snapshot["channels"]
            if channel["channelNumber"] != channel_number
        ]
        self._snapshot["channelCount"] = len(self._snapshot["channels"])
        self._snapshot["suggestedChannel"] = 1
        self.broadcasterChanged.emit()
        return {
            "ok": True,
            "message": "deleted with recovery backup",
            "channelNumber": channel_number,
            "backupPath": "channels/channel-0007.yaml.deleted.bak",
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

    invoked = QMetaObject.invokeMethod(
        item,
        "handleControllerIntent",
        Qt.ConnectionType.DirectConnection,
        Q_ARG(str, "SELECT"),
    )
    assert invoked
    assert item.property("editorMode") == "edit"
    assert item.property("selectedChannelIndex") == 0
    assert item.property("feedbackMessage") == ""

    invoked = QMetaObject.invokeMethod(
        item,
        "requestDeleteChannel",
        Qt.ConnectionType.DirectConnection,
    )
    assert invoked
    assert item.property("pendingDeleteChannelNumber") == 7

    invoked = QMetaObject.invokeMethod(
        item,
        "deleteSelectedChannel",
        Qt.ConnectionType.DirectConnection,
    )
    assert invoked
    app.processEvents()
    assert item.property("editorMode") == "list"
    assert item.property("editingChannelNumber") == 0
    assert item.property("feedbackMessage") == "deleted with recovery backup"
    assert item.property("pendingDeleteChannelNumber") == 0

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
    assert 'text: "Delete Channel"' in text
    assert "channelOS.deleteChannel(pendingDeleteChannelNumber)" in text
    assert "DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole" in text
    assert "function canDeleteSelectedChannel()" in text
    assert "event.key === Qt.Key_Delete" in text
    assert 'text: "DEL  Delete"' in text


def test_home_shortcut_escapes_library_navigation() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    window = QWindow()
    window.setProperty("screen", "library")
    router = BroadcasterKeyFilter(controller, window)  # type: ignore[arg-type]
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_H,
        Qt.KeyboardModifier.NoModifier,
        "h",
    )

    assert router.eventFilter(window, event)
    assert window.property("screen") == "home"

    window.close()
    app.processEvents()


def test_home_letter_remains_text_while_an_editor_has_focus(monkeypatch) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    window = QWindow()
    window.setProperty("screen", "library")
    router = BroadcasterKeyFilter(controller, window)  # type: ignore[arg-type]
    monkeypatch.setattr(
        BroadcasterKeyFilter,
        "_text_entry_has_focus",
        staticmethod(lambda: True),
    )
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_H,
        Qt.KeyboardModifier.NoModifier,
        "h",
    )

    assert not router.eventFilter(window, event)
    assert window.property("screen") == "library"

    window.close()
    app.processEvents()


def test_info_letter_opens_library_info_outside_text_entry() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    window = QWindow()
    window.setProperty("screen", "library")
    window.setProperty("infoVisible", False)
    router = BroadcasterKeyFilter(controller, window)  # type: ignore[arg-type]
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_I,
        Qt.KeyboardModifier.NoModifier,
        "i",
    )

    assert router.eventFilter(window, event)
    assert window.property("infoVisible") is True

    window.close()
    app.processEvents()
