from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication

from .control import ControlCommand
from .controller_input import (
    ControllerBackend,
    ControllerInputHub,
    create_controller_backend,
)


class QtControllerInput(QObject):
    """Qt timer bridge from a native gamepad backend to the couch router."""

    CONNECTED_POLL_MS = 16
    DISCONNECTED_POLL_MS = 1500

    def __init__(
        self,
        window: QObject,
        dispatch: Callable[[ControlCommand], object],
        *,
        backend: ControllerBackend | None = None,
        enabled: Callable[[], bool] | None = None,
        application_active: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._enabled = enabled or (lambda: True)
        self._application_active = (
            application_active or self._default_application_active
        )
        self._accepting_input = False
        self._backend = (
            backend if backend is not None else create_controller_backend()
        )
        self._hub = (
            None
            if self._backend is None
            else ControllerInputHub(
                self._backend,
                dispatch,
                connection_changed=self._connection_changed,
            )
        )
        self._message_generation = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.DISCONNECTED_POLL_MS)
        self._timer.timeout.connect(self.poll)

        self._window.setProperty("controllerConnected", False)
        self._window.setProperty("controllerName", "")

        app = QGuiApplication.instance()
        if application_active is None and app is not None:
            app.applicationStateChanged.connect(self._application_state_changed)

    @property
    def available(self) -> bool:
        return self._hub is not None

    @property
    def connected(self) -> bool:
        return self._hub is not None and self._hub.connected

    def start(self) -> None:
        if self._hub is None or self._timer.isActive():
            return
        self.poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @staticmethod
    def _default_application_active() -> bool:
        app = QGuiApplication.instance()
        return (
            app is None
            or app.applicationState() == Qt.ApplicationState.ApplicationActive
        )

    def _application_state_changed(self, _state: Qt.ApplicationState) -> None:
        # Resume immediately on focus return instead of waiting for the backed-
        # off timer. The first active sample is primed and cannot fire a held
        # button into ChannelOS.
        if self._timer.isActive():
            self.poll()

    def _suspend_input(self) -> None:
        if self._hub is None:
            return
        if self._accepting_input or self._hub.connected:
            self._hub.reset()
        self._accepting_input = False
        self._window.setProperty("controllerConnected", False)
        self._window.setProperty("controllerName", "")
        if self._timer.interval() != self.DISCONNECTED_POLL_MS:
            self._timer.setInterval(self.DISCONNECTED_POLL_MS)

    def poll(self) -> None:
        if self._hub is None:
            return
        if not bool(self._enabled()) or not bool(self._application_active()):
            self._suspend_input()
            return
        self._accepting_input = True
        self._hub.poll()
        interval = (
            self.CONNECTED_POLL_MS
            if self._hub.connected
            else self.DISCONNECTED_POLL_MS
        )
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _connection_changed(self, connected: bool, name: str) -> None:
        self._window.setProperty("controllerConnected", connected)
        self._window.setProperty("controllerName", name if connected else "")
        message = (
            f"{name} connected"
            if connected
            else "Controller disconnected - keyboard controls remain available"
        )
        self._window.setProperty("statusMessage", message)
        self._message_generation += 1
        generation = self._message_generation

        def clear_message() -> None:
            if (
                generation == self._message_generation
                and str(self._window.property("statusMessage")) == message
            ):
                self._window.setProperty("statusMessage", "")

        QTimer.singleShot(4200, clear_message)
