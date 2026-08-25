from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Property, Q_ARG, QEvent, QMetaObject, Signal, Slot, Qt

from .control import ControlCommand, ControlIntent


def install_display_mode_support(broadcaster_qt) -> None:
    """Extend the integrated couch shell with persisted display-mode behavior.

    Keeping this small adapter separate lets the setting use the existing
    SettingsStore without duplicating the larger couch controller. The module
    globals are replaced before ``run_qt`` constructs either object, so PySide
    sees normal subclasses with complete Qt meta-objects.
    """

    base_controller = broadcaster_qt.BroadcasterCouchController
    base_filter = broadcaster_qt.BroadcasterKeyFilter

    if getattr(base_controller, "_channelos_display_mode_enabled", False):
        return

    class DisplayModeController(base_controller):
        displayModeChanged = Signal()
        _channelos_display_mode_enabled = True

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.settingsChanged.connect(self.displayModeChanged)

        @Property(str, notify=displayModeChanged)
        def displayMode(self) -> str:
            return self._settings.display_mode

        @Slot(int, result="QVariantMap")
        def changeDisplayMode(self, direction: int) -> dict[str, object]:
            _ = direction
            value = (
                "windowed"
                if self._settings.display_mode == "fullscreen"
                else "fullscreen"
            )
            try:
                self._save_settings(
                    replace(self._settings, display_mode=value)
                )
                return {
                    "ok": True,
                    "message": (
                        "Display mode: Windowed"
                        if value == "windowed"
                        else "Display mode: Fullscreen"
                    ),
                    "displayMode": value,
                    "settings": self.settings,
                }
            except (OSError, ValueError) as exc:
                return self._error(exc)

    class DisplayModeKeyFilter(base_filter):
        _SETTINGS_INTENTS = {
            ControlIntent.UP,
            ControlIntent.DOWN,
            ControlIntent.LEFT,
            ControlIntent.RIGHT,
            ControlIntent.SELECT,
            ControlIntent.BACK,
            ControlIntent.HOME,
        }

        @staticmethod
        def _invoke_settings_overlay(window, intent: ControlIntent) -> bool:
            item = getattr(window, "_channelos_settings_item", None)
            if item is None:
                return False
            return bool(
                QMetaObject.invokeMethod(
                    item,
                    "handleControllerIntent",
                    Qt.ConnectionType.DirectConnection,
                    Q_ARG(str, intent.value),
                )
            )

        def dispatch_command(self, command: ControlCommand) -> bool:
            if (
                str(self._window.property("screen")) == "settings"
                and command.intent in self._SETTINGS_INTENTS
            ):
                return self._invoke_settings_overlay(
                    self._window,
                    command.intent,
                )
            return super().dispatch_command(command)

        def eventFilter(self, watched, event) -> bool:
            if (
                event.type() == QEvent.Type.KeyPress
                and str(self._window.property("screen")) == "settings"
            ):
                command = self.command_for_key(event.key())
                if (
                    command is not None
                    and command.intent in self._SETTINGS_INTENTS
                ):
                    return self.dispatch_command(command)
                # F11 and any unrecognized key continue to QML/global shortcuts.
                return False
            return super().eventFilter(watched, event)

    broadcaster_qt.BroadcasterCouchController = DisplayModeController
    broadcaster_qt.BroadcasterKeyFilter = DisplayModeKeyFilter
