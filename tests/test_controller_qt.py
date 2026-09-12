from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication, QWindow

from channelos.control import ControlCommand, ControlIntent
from channelos.controller_input import (
    ControllerReading,
    GamepadButton,
    GamepadSnapshot,
)
from channelos.controller_qt import QtControllerInput


class FakeBackend:
    def __init__(self) -> None:
        self.read_count = 0
        self.reading: ControllerReading | None = ControllerReading(
            "test:0",
            "Living Room Controller",
            GamepadSnapshot(),
        )

    def read_first(self) -> ControllerReading | None:
        self.read_count += 1
        return self.reading


def test_qt_bridge_reports_hotplug_and_dispatches_through_shared_router() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    window = QWindow()
    window.setProperty("statusMessage", "")
    backend = FakeBackend()
    commands: list[ControlCommand] = []
    adapter = QtControllerInput(
        window,
        commands.append,
        backend=backend,
        application_active=lambda: True,
    )

    adapter.poll()
    assert adapter.connected
    assert window.property("controllerConnected") is True
    assert window.property("controllerName") == "Living Room Controller"
    assert "connected" in str(window.property("statusMessage"))

    backend.reading = ControllerReading(
        "test:0",
        "Living Room Controller",
        GamepadSnapshot(buttons=frozenset({GamepadButton.NORTH})),
    )
    adapter.poll()
    assert commands == [ControlCommand(ControlIntent.INFO)]

    backend.reading = None
    adapter.poll()
    assert not adapter.connected
    assert window.property("controllerConnected") is False
    assert window.property("controllerName") == ""

    adapter.stop()
    window.close()
    app.processEvents()


def test_qt_bridge_suspends_background_input_and_primes_on_focus_return() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    window = QWindow()
    window.setProperty("statusMessage", "")
    backend = FakeBackend()
    commands: list[ControlCommand] = []
    active = [True]
    adapter = QtControllerInput(
        window,
        commands.append,
        backend=backend,
        application_active=lambda: active[0],
    )

    adapter.poll()
    assert adapter.connected
    reads_before_blur = backend.read_count

    active[0] = False
    backend.reading = ControllerReading(
        "test:0",
        "Living Room Controller",
        GamepadSnapshot(buttons=frozenset({GamepadButton.NORTH})),
    )
    adapter.poll()

    assert backend.read_count == reads_before_blur
    assert commands == []
    assert not adapter.connected
    assert window.property("controllerConnected") is False

    active[0] = True
    adapter.poll()
    assert commands == []
    assert adapter.connected

    backend.reading = ControllerReading(
        "test:0",
        "Living Room Controller",
        GamepadSnapshot(),
    )
    adapter.poll()
    backend.reading = ControllerReading(
        "test:0",
        "Living Room Controller",
        GamepadSnapshot(buttons=frozenset({GamepadButton.NORTH})),
    )
    adapter.poll()
    assert commands == [ControlCommand(ControlIntent.INFO)]

    adapter.stop()
    window.close()
    app.processEvents()


def test_qt_bridge_respects_persistent_controller_switch() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    window = QWindow()
    window.setProperty("statusMessage", "")
    backend = FakeBackend()
    enabled = [False]
    adapter = QtControllerInput(
        window,
        lambda _command: None,
        backend=backend,
        enabled=lambda: enabled[0],
        application_active=lambda: True,
    )

    adapter.poll()
    assert backend.read_count == 0
    assert not adapter.connected

    enabled[0] = True
    adapter.poll()
    assert backend.read_count == 1
    assert adapter.connected

    enabled[0] = False
    adapter.poll()
    assert not adapter.connected
    assert window.property("controllerConnected") is False

    adapter.stop()
    window.close()
    app.processEvents()
