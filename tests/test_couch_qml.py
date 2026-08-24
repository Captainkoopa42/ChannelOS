from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine

import channelos
from channelos.control import ControlCommand, ControlIntent
from channelos.couch_qt import CouchKeyFilter


class FakeChannelOS(QObject):
    snapshotChanged = Signal()
    playbackChanged = Signal()
    homeTelevisionChanged = Signal()
    libraryChanged = Signal()
    onDemandChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._playback = {"active": False}
        self._home_television = {
            "mode": "static",
            "isUnassigned": True,
            "displayNumber": "001",
            "channelName": "ChannelOS",
            "title": "NO PROGRAMMING",
        }
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

    @Property("QVariantMap", notify=homeTelevisionChanged)
    def homeTelevision(self):
        return self._home_television

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
    assert roots[0].property("homeFocusArea") == 0
    assert roots[0].property("homeCardSelection") == 0
    assert roots[0].property("settingsSelection") == 0
    assert roots[0].property("infoVisible") is False
    assert roots[0].property("controllerConnected") is False
    assert roots[0].property("controllerName") == ""
    assert roots[0].property("channelEntry") == ""
    roots[0].setProperty("screen", "ondemand")
    roots[0].setProperty("channelEntry", "007")
    assert roots[0].property("channelEntry") == "007"
    roots[0].setProperty("channelEntry", "")
    roots[0].setProperty("screen", "home")
    assert roots[0].property("volumePercent") == 100
    assert roots[0].property("muted") is False
    roots[0].setProperty("infoVisible", True)
    assert roots[0].property("infoVisible") is True
    roots[0].setProperty("infoVisible", False)
    roots[0].close()
    app.processEvents()


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (Qt.Key.Key_7, ControlCommand.digit(7)),
        (Qt.Key.Key_Up, ControlCommand(ControlIntent.UP)),
        (Qt.Key.Key_Return, ControlCommand(ControlIntent.SELECT)),
        (Qt.Key.Key_G, ControlCommand(ControlIntent.GUIDE)),
        (Qt.Key.Key_H, ControlCommand(ControlIntent.HOME)),
        (Qt.Key.Key_I, ControlCommand(ControlIntent.INFO)),
        (Qt.Key.Key_VolumeUp, ControlCommand(ControlIntent.VOLUME_UP)),
        (
            Qt.Key.Key_MediaTogglePlayPause,
            ControlCommand(ControlIntent.PLAY_PAUSE),
        ),
    ],
)
def test_keyboard_adapter_emits_control_commands(key, expected) -> None:
    assert CouchKeyFilter.command_for_key(key) == expected


def test_keyboard_adapter_leaves_unbound_text_keys_alone() -> None:
    assert CouchKeyFilter.command_for_key(Qt.Key.Key_X) is None


def test_consumer_remote_channel_key_uses_the_same_intent_boundary() -> None:
    channel_up = getattr(Qt.Key, "Key_ChannelUp", None)
    if channel_up is None:
        pytest.skip("this Qt build does not expose the consumer ChannelUp key")
    assert CouchKeyFilter.command_for_key(channel_up) == ControlCommand(
        ControlIntent.CHANNEL_UP
    )


def test_normalized_navigation_intent_moves_home_selection() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    window = QWindow()
    window.setProperty("screen", "home")
    window.setProperty("homeSelection", 0)
    window.setProperty("homeFocusArea", 0)
    window.setProperty("homeCardSelection", 0)
    window.setProperty("settingsSelection", 0)

    router = CouchKeyFilter(controller, window)  # type: ignore[arg-type]

    assert router.dispatch_command(ControlCommand(ControlIntent.DOWN))
    assert window.property("homeSelection") == 1
    assert router.dispatch_command(ControlCommand(ControlIntent.UP))
    assert window.property("homeSelection") == 0

    window.setProperty("homeSelection", 4)
    assert router.dispatch_command(ControlCommand(ControlIntent.DOWN))
    assert window.property("homeFocusArea") == 1
    assert router.dispatch_command(ControlCommand(ControlIntent.RIGHT))
    assert window.property("homeCardSelection") == 1
    assert router.dispatch_command(ControlCommand(ControlIntent.UP))
    assert window.property("homeFocusArea") == 0
    assert window.property("homeSelection") == 4

    assert router.dispatch_command(ControlCommand(ControlIntent.SETTINGS))
    assert window.property("screen") == "settings"
    assert router.dispatch_command(ControlCommand(ControlIntent.BACK))
    assert window.property("screen") == "home"

    window.setProperty("screen", "guide")
    assert router.dispatch_command(ControlCommand(ControlIntent.HOME))
    assert window.property("screen") == "home"

    window.close()
    app.processEvents()


def test_transport_intents_keep_toggle_and_idempotent_semantics() -> None:
    assert CouchKeyFilter._transport_should_toggle(
        ControlIntent.SELECT,
        paused=False,
    )
    assert CouchKeyFilter._transport_should_toggle(
        ControlIntent.PLAY_PAUSE,
        paused=True,
    )
    assert not CouchKeyFilter._transport_should_toggle(
        ControlIntent.PLAY,
        paused=False,
    )
    assert CouchKeyFilter._transport_should_toggle(
        ControlIntent.PLAY,
        paused=True,
    )
    assert CouchKeyFilter._transport_should_toggle(
        ControlIntent.PAUSE,
        paused=False,
    )
    assert not CouchKeyFilter._transport_should_toggle(
        ControlIntent.PAUSE,
        paused=True,
    )


def test_info_intent_toggles_context_drawer_and_back_closes_it() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    window = QWindow()
    window.setProperty("screen", "guide")
    window.setProperty("infoVisible", False)
    window.setProperty("liveHudVisible", True)

    router = CouchKeyFilter(controller, window)  # type: ignore[arg-type]

    assert router.dispatch_command(ControlCommand(ControlIntent.INFO))
    assert window.property("infoVisible") is True

    # Info owns the couch surface, so browsing cannot move content behind it.
    assert router.dispatch_command(ControlCommand(ControlIntent.RIGHT))
    assert window.property("infoVisible") is True

    assert router.dispatch_command(ControlCommand(ControlIntent.BACK))
    assert window.property("infoVisible") is False

    window.setProperty("screen", "live")
    window.setProperty("liveHudVisible", True)
    assert router.dispatch_command(ControlCommand(ControlIntent.INFO))
    assert window.property("infoVisible") is True
    assert window.property("liveHudVisible") is False
    assert router.dispatch_command(ControlCommand(ControlIntent.INFO))
    assert window.property("infoVisible") is False

    window.close()
    app.processEvents()
