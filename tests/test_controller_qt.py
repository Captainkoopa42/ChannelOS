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
        self.reading: ControllerReading | None = ControllerReading(
            "test:0",
            "Living Room Controller",
            GamepadSnapshot(),
        )

    def read_first(self) -> ControllerReading | None:
        return self.reading


def test_qt_bridge_reports_hotplug_and_dispatches_through_shared_router() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    window = QWindow()
    window.setProperty("statusMessage", "")
    backend = FakeBackend()
    commands: list[ControlCommand] = []
    adapter = QtControllerInput(window, commands.append, backend=backend)

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
