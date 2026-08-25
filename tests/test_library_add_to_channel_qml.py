from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Property, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

import channelos
from channelos.broadcaster_qt import BroadcasterKeyFilter
from channelos.control import ControlCommand, ControlIntent


class FakeHost(QObject):
    screenChanged = Signal()
    libraryInfoItemChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._screen = "library"
        self._library_info_item: dict[str, object] = {}

    @Property(str, notify=screenChanged)
    def screen(self) -> str:
        return self._screen

    @screen.setter
    def screen(self, value: str) -> None:
        if value == self._screen:
            return
        self._screen = value
        self.screenChanged.emit()

    @Property("QVariantMap", notify=libraryInfoItemChanged)
    def libraryInfoItem(self):
        return self._library_info_item

    @libraryInfoItem.setter
    def libraryInfoItem(self, value) -> None:
        self._library_info_item = dict(value or {})
        self.libraryInfoItemChanged.emit()


class FakeChannelOS(QObject):
    libraryChanged = Signal()
    libraryScanChanged = Signal()
    broadcasterChanged = Signal()
    settingsChanged = Signal()

    def __init__(self, *, selected_already_covered: bool = False) -> None:
        super().__init__()
        self.last_update_original: int | None = None
        self.last_update_editor: dict[str, object] | None = None
        self._settings = {
            "reducedMotion": True,
            "thumbnailWidth": 320,
        }
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
                    "continueWatching": False,
                    "watchPositionSeconds": 0.0,
                    "watchProgress": 0.0,
                    "lastWatchedAt": "",
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
        first_sources = (
            ["C:/Owned Media"]
            if selected_already_covered
            else ["C:/Cartoons"]
        )
        self._broadcaster = {
            "channelCount": 2,
            "suggestedChannel": 1,
            "managedDirectory": "channels",
            "sourceOptions": ["C:/Owned Media", "C:/Cartoons", "C:/Second Media"],
            "channels": [
                {
                    "channelNumber": 7,
                    "displayNumber": "007",
                    "name": "Cartoons",
                    "description": "Morning animation",
                    "mode": "sequential",
                    "preserveEpisodeOrder": True,
                    "avoidRepeatDays": 0,
                    "numberWidth": 3,
                    "sources": first_sources,
                    "sourceCount": len(first_sources),
                    "path": "channels/channel-0007.yaml",
                    "managed": True,
                    "nowTitle": "Current Cartoon",
                    "nextTitle": "Next Cartoon",
                },
                {
                    "channelNumber": 12,
                    "displayNumber": "012",
                    "name": "Movies",
                    "description": "Feature rotation",
                    "mode": "shuffle",
                    "preserveEpisodeOrder": False,
                    "avoidRepeatDays": 4,
                    "numberWidth": 3,
                    "sources": ["C:/Second Media"],
                    "sourceCount": 1,
                    "path": "channels/channel-0012.yaml",
                    "managed": True,
                    "nowTitle": "Current Movie",
                    "nextTitle": "Next Movie",
                },
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

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self._settings

    @Property("QVariantMap", notify=libraryChanged)
    def librarySnapshot(self):
        return self._library

    @Property("QVariantMap", notify=libraryScanChanged)
    def libraryScan(self):
        return self._scan

    @Property("QVariantMap", notify=broadcasterChanged)
    def broadcasterSnapshot(self):
        return self._broadcaster

    @Slot()
    def refreshLibrary(self) -> None:
        self.libraryChanged.emit()

    @Slot()
    def refreshBroadcaster(self) -> None:
        self.broadcasterChanged.emit()

    @Slot()
    def refresh(self) -> None:
        pass

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

    @Slot(int, "QVariantMap", result="QVariantMap")
    def updateChannel(self, original, editor):
        self.last_update_original = int(original)
        self.last_update_editor = dict(editor or {})
        for channel in self._broadcaster["channels"]:
            if int(channel["channelNumber"]) != int(original):
                continue
            channel["sources"] = list(self.last_update_editor.get("sources", []))
            channel["sourceCount"] = len(channel["sources"])
            break
        self.broadcasterChanged.emit()
        return {
            "ok": True,
            "message": "updated",
            "channelNumber": int(original),
            "path": f"channels/channel-{int(original):04d}.yaml",
            "backupPath": f"channels/channel-{int(original):04d}.yaml.bak",
        }


def make_library_item(controller: FakeChannelOS, host: FakeHost):
    app = QGuiApplication.instance() or QGuiApplication([])
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
    # Keep the QQmlComponent alive for as long as the object it created. PySide
    # may otherwise collect the component at helper return and delete the item.
    return app, engine, component, item


def invoke(item, intent: str) -> None:
    invoked = QMetaObject.invokeMethod(
        item,
        "handleControllerIntent",
        Qt.ConnectionType.DirectConnection,
        Q_ARG(str, intent),
    )
    assert invoked


def test_controller_x_opens_add_to_channel_and_select_updates_existing_channel() -> None:
    controller = FakeChannelOS()
    host = FakeHost()
    app, engine, component, item = make_library_item(controller, host)

    window = QWindow()
    window.setProperty("screen", "library")
    router = BroadcasterKeyFilter(controller, window)  # type: ignore[arg-type]
    router.bind_management_overlays(library_item=item, broadcaster_item=item)

    assert router.dispatch_command(ControlCommand(ControlIntent.PLAY_PAUSE))
    app.processEvents()
    assert item.property("addToChannelVisible") is True
    assert item.property("addToChannelChannelCount") == 2
    assert item.property("addToChannelSelection") == 0

    invoke(item, "DOWN")
    assert item.property("addToChannelSelection") == 1

    invoke(item, "SELECT")
    app.processEvents()

    assert controller.last_update_original == 12
    assert controller.last_update_editor is not None
    assert controller.last_update_editor["channel"] == 12
    assert controller.last_update_editor["name"] == "Movies"
    assert controller.last_update_editor["mode"] == "shuffle"
    assert controller.last_update_editor["avoidRepeatDays"] == 4
    assert controller.last_update_editor["sources"] == [
        "C:/Second Media",
        "C:/Owned Media/owned.mp4",
    ]
    assert "Added Owned Clip to Channel 012 - Movies." in str(
        item.property("addToChannelMessage")
    )

    invoke(item, "BACK")
    assert item.property("addToChannelVisible") is False

    window.close()
    item.deleteLater()
    app.processEvents()
    del component
    del engine


def test_add_to_channel_does_not_duplicate_media_already_covered_by_parent_source() -> None:
    controller = FakeChannelOS(selected_already_covered=True)
    host = FakeHost()
    app, engine, component, item = make_library_item(controller, host)

    invoke(item, "PLAY_PAUSE")
    assert item.property("addToChannelVisible") is True
    invoke(item, "SELECT")
    app.processEvents()

    assert controller.last_update_original is None
    assert controller.last_update_editor is None
    assert "already includes Owned Clip" in str(item.property("addToChannelMessage"))

    item.deleteLater()
    app.processEvents()
    del component
    del engine
