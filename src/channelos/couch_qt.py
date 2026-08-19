from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine

from .couch_actions import CouchActions
from .couch_model import build_couch_snapshot
from .guide import GuideError, GuideService
from .playback import NativeVideoSurface, PlaybackError
from .runtime import ChannelRuntimeError, TelevisionRuntime, TuneDecision
from .television import TelevisionSession


class CouchController(QObject):
    """Qt-facing adapter over ChannelOS Guide data and television control intents."""

    snapshotChanged = Signal()
    playbackChanged = Signal()

    def __init__(self, service: GuideService, television: TelevisionRuntime) -> None:
        super().__init__()
        self._service = service
        self._actions = CouchActions(service, television)
        self._snapshot = build_couch_snapshot(service)
        self._playback: dict[str, object] = {"active": False}
        self._surface_ready = False
        self._surface_error = "embedded video surface has not been created"

    @Property("QVariantMap", notify=snapshotChanged)
    def snapshot(self) -> dict[str, object]:
        return self._snapshot

    @Property("QVariantMap", notify=playbackChanged)
    def playback(self) -> dict[str, object]:
        return self._playback

    @Slot()
    def refresh(self) -> None:
        self._snapshot = build_couch_snapshot(self._service)
        self.snapshotChanged.emit()

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self._actions.attach_video_surface(surface)
        self._surface_ready = True
        self._surface_error = ""

    def set_video_surface_error(self, message: str) -> None:
        self._surface_ready = False
        self._surface_error = message

    def _decision_view(self, decision: TuneDecision) -> dict[str, object]:
        selected = decision.viewer_selection
        definition = self._actions.runtime.channels[decision.channel_number].channel.definition
        return {
            "active": True,
            "channelNumber": decision.channel_number,
            "displayNumber": definition.display_number,
            "channelName": decision.channel_name,
            "title": selected.media.location.path.stem,
            "assetId": selected.media.asset.asset_id,
            "offsetSeconds": float(selected.offset_seconds),
            "lagSeconds": float(decision.lag_seconds),
            "isLive": bool(decision.is_live),
            "paused": bool(self._actions.paused),
            "viewerTimeMs": int(decision.viewer_time_utc.timestamp() * 1000),
            "programStartMs": int(selected.program_started_at.timestamp() * 1000),
            "programEndMs": int(selected.program_ends_at.timestamp() * 1000),
        }

    def _publish(self, decision: TuneDecision) -> dict[str, object]:
        self._playback = self._decision_view(decision)
        self.playbackChanged.emit()
        return {
            "ok": True,
            "message": TelevisionSession.describe(decision),
            "playback": self._playback,
        }

    @staticmethod
    def _error(exc: Exception) -> dict[str, object]:
        return {"ok": False, "message": str(exc)}

    @Slot(str, int, float, result="QVariantMap")
    def activateProgram(
        self,
        schedule_id: str,
        channel_number: int,
        approximate_start_ms: float,
    ) -> dict[str, object]:
        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}
        try:
            decision = self._actions.activate_program(
                schedule_id,
                int(channel_number),
                float(approximate_start_ms),
            )
            return self._publish(decision)
        except (GuideError, ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def togglePause(self) -> dict[str, object]:
        try:
            decision = self._actions.play() if self._actions.paused else self._actions.pause()
            return self._publish(decision)
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def goLive(self) -> dict[str, object]:
        try:
            return self._publish(self._actions.go_live())
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(float, result="QVariantMap")
    def skip(self, delta_seconds: float) -> dict[str, object]:
        try:
            return self._publish(self._actions.skip(float(delta_seconds)))
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(int, result="QVariantMap")
    def changeChannel(self, direction: int) -> dict[str, object]:
        try:
            if int(direction) > 0:
                decision = self._actions.channel_up()
            elif int(direction) < 0:
                decision = self._actions.channel_down()
            else:
                raise ValueError("channel direction must be -1 or 1")
            return self._publish(decision)
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    def stop(self) -> None:
        self._actions.stop()


def _native_video_platform() -> str:
    platform_name = QGuiApplication.platformName().lower()
    if "windows" in platform_name:
        return "windows"
    if platform_name == "xcb":
        return "x11"
    if platform_name == "cocoa":
        return "macos"
    raise RuntimeError(
        f"Qt platform {platform_name!r} does not yet expose a supported native libVLC video target"
    )


def run_qt(
    service: GuideService,
    television: TelevisionRuntime,
    *,
    windowed: bool = False,
) -> int:
    app = QGuiApplication.instance()
    owns_application = app is None
    if app is None:
        app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("ChannelOS")
    app.setOrganizationName("ChannelOS")

    controller = CouchController(service, television)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    roots = engine.rootObjects()
    if not roots:
        return 7

    window = roots[0]

    # libVLC renders into a ChannelOS-owned native child window. QML remains
    # authoritative for layout/control, while the playback backend only receives
    # a platform handle. The child is visible only on the Live TV screen.
    video_window = QWindow(window)
    video_window.setFlag(Qt.WindowType.FramelessWindowHint, True)
    video_window.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    video_window.setFlag(Qt.WindowType.WindowTransparentForInput, True)
    video_window.setGeometry(0, 0, max(1, int(window.width())), max(1, int(window.height() * 0.72)))
    video_window.hide()

    try:
        surface = NativeVideoSurface(_native_video_platform(), int(video_window.winId()))
        controller.attach_video_surface(surface)
    except (RuntimeError, ValueError) as exc:
        controller.set_video_surface_error(str(exc))

    def sync_video_surface() -> None:
        width = max(1, int(window.width()))
        height = max(1, int(window.height() * 0.72))
        video_window.setGeometry(0, 0, width, height)
        video_window.setVisible(window.property("screen") == "live")

    window.widthChanged.connect(sync_video_surface)
    window.heightChanged.connect(sync_video_surface)
    screen_changed = getattr(window, "screenChanged", None)
    if screen_changed is not None:
        screen_changed.connect(sync_video_surface)

    app.aboutToQuit.connect(controller.stop)

    if windowed:
        window.showNormal()
    else:
        window.showFullScreen()
    sync_video_surface()

    if not owns_application:
        return 0
    return int(app.exec())
