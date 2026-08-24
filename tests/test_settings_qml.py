from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import (
    QObject,
    Property,
    QUrl,
    Signal,
    Slot,
    qInstallMessageHandler,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow

import channelos


class FakeSettingsHost(QObject):
    screenChanged = Signal()
    settingsSelectionChanged = Signal()
    statusMessageChanged = Signal()
    volumePercentChanged = Signal()
    mutedChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._screen = "settings"
        self._settings_selection = 0
        self._status_message = ""
        self._volume_percent = 100
        self._muted = False

    @Property(str, notify=screenChanged)
    def screen(self) -> str:
        return self._screen

    @screen.setter
    def screen(self, value: str) -> None:
        if value != self._screen:
            self._screen = value
            self.screenChanged.emit()

    @Property(int, notify=settingsSelectionChanged)
    def settingsSelection(self) -> int:
        return self._settings_selection

    @settingsSelection.setter
    def settingsSelection(self, value: int) -> None:
        self._settings_selection = int(value)
        self.settingsSelectionChanged.emit()

    @Property(str, notify=statusMessageChanged)
    def statusMessage(self) -> str:
        return self._status_message

    @statusMessage.setter
    def statusMessage(self, value: str) -> None:
        self._status_message = str(value)
        self.statusMessageChanged.emit()

    @Property(int, notify=volumePercentChanged)
    def volumePercent(self) -> int:
        return self._volume_percent

    @volumePercent.setter
    def volumePercent(self, value: int) -> None:
        self._volume_percent = int(value)
        self.volumePercentChanged.emit()

    @Property(bool, notify=mutedChanged)
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool) -> None:
        self._muted = bool(value)
        self.mutedChanged.emit()


class FakeSettingsController(QObject):
    settingsChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = {
            "volumePercent": 100,
            "muted": False,
            "skipBackSeconds": 10,
            "skipForwardSeconds": 30,
            "performanceProfile": "standard",
            "generateVideoThumbnails": True,
            "artworkCacheLimitMb": 0,
            "backgroundArtworkDuringPlayback": True,
            "reducedMotion": False,
            "thumbnailWidth": 640,
            "ffmpegThreads": 0,
            "artworkCacheBytes": 0,
            "artworkCacheFiles": 0,
        }

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self._settings

    @Slot(str, int, result="QVariantMap")
    def adjustSetting(self, name, direction):
        return {
            "ok": True,
            "message": f"adjusted {name} {direction}",
            "settings": self._settings,
        }

    @Slot(result="QVariantMap")
    def resetSettings(self):
        return {
            "ok": True,
            "message": "reset",
            "volume": 100,
            "muted": False,
            "settings": self._settings,
        }

    @Slot(result="QVariantMap")
    def clearArtworkCache(self):
        return {
            "ok": True,
            "message": "cleared",
            "removedFiles": 0,
            "removedBytes": 0,
            "settings": self._settings,
        }


def test_settings_qml_instantiates_headlessly() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeSettingsController()
    host = FakeSettingsHost()
    surface = QQuickWindow()
    surface.resize(1280, 720)
    surface.show()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    qml_path = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "SettingsScreen.qml"
    )
    messages: list[str] = []
    previous_handler = qInstallMessageHandler(
        lambda _mode, _context, message: messages.append(message)
    )
    try:
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
        if component.isLoading():
            app.processEvents()

        errors = "\n".join(error.toString() for error in component.errors())
        assert component.isReady(), errors

        item = component.create(engine.rootContext())
        assert item is not None, errors
        item.setProperty("hostWindow", host)
        item.setParent(surface)
        item.setParentItem(surface.contentItem())
        app.processEvents()
        assert item.property("visible") is True

        host.screen = "home"
        app.processEvents()
        assert item.property("visible") is False

        item.deleteLater()
        surface.close()
        app.processEvents()
    finally:
        qInstallMessageHandler(previous_handler)

    settings_warnings = [
        message
        for message in messages
        if "SettingsScreen.qml" in message
    ]
    assert settings_warnings == []


def test_settings_qml_exposes_all_persistent_controls() -> None:
    qml_path = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "SettingsScreen.qml"
    )
    text = qml_path.read_text(encoding="utf-8")

    assert "preferences.volumePercent" in text
    assert "preferences.muted" in text
    assert "preferences.skipBackSeconds" in text
    assert "preferences.skipForwardSeconds" in text
    assert "preferences.performanceProfile" in text
    assert "preferences.generateVideoThumbnails" in text
    assert "preferences.artworkCacheLimitMb" in text
    assert "preferences.backgroundArtworkDuringPlayback" in text
    assert "preferences.reducedMotion" in text
    assert "preferences.artworkCacheBytes" in text
    assert "channelOS.clearArtworkCache()" in text
    assert "channelOS.resetSettings()" in text
