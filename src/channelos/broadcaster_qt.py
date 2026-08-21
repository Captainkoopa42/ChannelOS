from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QEvent, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QColor, QPalette, QWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from .broadcaster import BroadcasterError, BroadcasterService
from .couch_actions import CouchActions
from .couch_model import build_couch_snapshot
from .couch_qt import CouchController, CouchKeyFilter, _native_video_platform
from .guide import GuideService
from .library import MediaLibrary
from .models import ChannelValidationError
from .playback import NativeVideoSurface
from .resolve import resolve_channel
from .runtime import ChannelRuntime, ChannelRuntimeError, RuntimeStore, TelevisionRuntime


def _apply_channelos_control_theme(app: QApplication) -> None:
    # Give Qt Quick Controls the same high-contrast dark palette as ChannelOS.
    #
    # The platform-native Windows control style was producing light edit boxes
    # while ChannelOS supplied light text colors, making typed values almost
    # invisible. Fusion respects the application palette consistently across
    # Windows/Linux and still provides normal mouse/keyboard behavior.
    QQuickStyle.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#050c15"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f4f7fb"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0d2035"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#10283f"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f4f7fb"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#10283f"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f4f7fb"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1a91ff"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7f93a8"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#0d2035"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f4f7fb"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#42adff"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#1a3550"))
    palette.setColor(QPalette.ColorRole.Midlight, QColor("#17324a"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#10283f"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#06111e"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#02070d"))

    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#6f8194"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#6f8194"),
    )

    app.setPalette(palette)

    # Controls in Broadcaster mode use the application font unless a screen
    # deliberately specifies a larger size. Raise the floor so form values,
    # combo boxes, buttons and checkboxes are readable at 1080p couch/desk use.
    font = app.font()
    if font.pointSizeF() < 11.0:
        font.setPointSizeF(11.0)
        app.setFont(font)


class BroadcasterCouchController(CouchController):
    """Couch controller extended with safe channel-management operations."""

    broadcasterChanged = Signal()

    def __init__(
        self,
        service: GuideService,
        television: TelevisionRuntime,
        library: MediaLibrary,
        broadcaster: BroadcasterService,
        runtime_store: RuntimeStore,
    ) -> None:
        super().__init__(service, television, library)
        self._broadcaster = broadcaster
        self._runtime_store = runtime_store
        self._broadcaster_snapshot = self._build_broadcaster_snapshot()
        self._video_surface: NativeVideoSurface | None = None

    def _build_broadcaster_snapshot(self) -> dict[str, object]:
        snapshot = self._broadcaster.snapshot()
        channels = snapshot.get("channels", [])
        if isinstance(channels, list):
            for channel in channels:
                if not isinstance(channel, dict):
                    continue
                number = int(channel.get("channelNumber", 0))
                try:
                    now_next = self._service.now_next(number)
                except Exception:
                    channel["nowTitle"] = ""
                    channel["nextTitle"] = ""
                    continue
                channel["nowTitle"] = now_next.now.display_label
                channel["nextTitle"] = now_next.next.display_label
        return snapshot

    @Property("QVariantMap", notify=broadcasterChanged)
    def broadcasterSnapshot(self) -> dict[str, object]:
        return self._broadcaster_snapshot

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self._video_surface = surface
        super().attach_video_surface(surface)

    @Slot()
    def refreshBroadcaster(self) -> None:
        self._broadcaster.refresh()
        self._broadcaster_snapshot = self._build_broadcaster_snapshot()
        self.broadcasterChanged.emit()

    def _reload_lineup(self) -> None:
        """Rebuild Guide/TV objects from saved portable definitions."""

        runtimes: list[ChannelRuntime] = []
        for record in self._broadcaster.records:
            resolved = resolve_channel(record.definition, self._library)
            if not resolved.media:
                raise BroadcasterError(
                    f"Channel {record.definition.display_number} - "
                    f"{record.definition.name} no longer resolves indexed media"
                )
            runtimes.append(ChannelRuntime.open(resolved, self._runtime_store))

        if not runtimes:
            raise BroadcasterError("the active television lineup cannot be empty")

        previous_actions = self._actions
        previous_actions.stop()

        service = GuideService(tuple(runtimes))
        television = TelevisionRuntime(tuple(runtimes), self._runtime_store)

        # A changed schedule signature intentionally discards stale Viewer
        # continuity. If that edited channel was current, re-establish LIVE.
        if television.current_channel is not None:
            try:
                television.status()
            except ChannelRuntimeError:
                television.tune(television.current_channel, return_behavior="live")

        actions = CouchActions(service, television)
        if self._video_surface is not None:
            actions.attach_video_surface(self._video_surface)

        self._service = service
        self._actions = actions
        self._snapshot = build_couch_snapshot(service)
        self.snapshotChanged.emit()

        self._playback = {"active": False}
        self.playbackChanged.emit()

    @staticmethod
    def _editor_mapping(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ChannelValidationError("channel editor data must be a mapping")
        return dict(value)

    @Slot("QVariantMap", result="QVariantMap")
    def previewChannel(self, editor: dict[str, object]) -> dict[str, object]:
        try:
            return self._broadcaster.preview(self._editor_mapping(editor))
        except (
            BroadcasterError,
            ChannelRuntimeError,
            ChannelValidationError,
            OSError,
            ValueError,
        ) as exc:
            return self._error(exc)

    @Slot("QVariantMap", result="QVariantMap")
    def createChannel(self, editor: dict[str, object]) -> dict[str, object]:
        try:
            result = self._broadcaster.create(self._editor_mapping(editor))
            self._reload_lineup()
            self.refreshBroadcaster()
            definition = result.record.definition
            return {
                "ok": True,
                "message": (
                    f"Created Channel {definition.display_number} - "
                    f"{definition.name}. It is live in the Guide now."
                ),
                "channelNumber": definition.channel,
                "path": str(result.record.path),
            }
        except (
            BroadcasterError,
            ChannelRuntimeError,
            ChannelValidationError,
            OSError,
            ValueError,
        ) as exc:
            return self._error(exc)

    @Slot(int, "QVariantMap", result="QVariantMap")
    def updateChannel(
        self,
        original_channel_number: int,
        editor: dict[str, object],
    ) -> dict[str, object]:
        try:
            result = self._broadcaster.update(
                int(original_channel_number),
                self._editor_mapping(editor),
            )
            self._reload_lineup()
            self.refreshBroadcaster()
            definition = result.record.definition
            message = (
                f"Updated Channel {definition.display_number} - "
                f"{definition.name}. The Guide is using the new definition."
            )
            if result.backup_path is not None:
                message += f" Backup: {result.backup_path.name}"
            return {
                "ok": True,
                "message": message,
                "channelNumber": definition.channel,
                "path": str(result.record.path),
                "backupPath": (
                    "" if result.backup_path is None else str(result.backup_path)
                ),
            }
        except (
            BroadcasterError,
            ChannelRuntimeError,
            ChannelValidationError,
            OSError,
            ValueError,
        ) as exc:
            return self._error(exc)


class BroadcasterKeyFilter(CouchKeyFilter):
    """Add Broadcaster navigation without stealing editor text input."""

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            screen = str(self._window.property("screen"))
            key = event.key()

            if screen == "home":
                if (
                    int(self._window.property("homeSelection")) == 3
                    and key
                    in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}
                ):
                    self._controller.refreshBroadcaster()
                    self._window.setProperty("screen", "broadcaster")
                    return True

                if key == Qt.Key.Key_B:
                    self._controller.refreshBroadcaster()
                    self._window.setProperty("screen", "broadcaster")
                    return True

            if screen == "broadcaster":
                return False

        return super().eventFilter(watched, event)


def _attach_broadcaster_overlay(engine: QQmlApplicationEngine, window):
    """Create BroadcasterScreen.qml as a child of the existing couch UI."""

    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parent / "qml" / "BroadcasterScreen.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))

    if component.isError():
        messages = "; ".join(error.toString() for error in component.errors())
        raise RuntimeError(f"Broadcaster UI could not be loaded: {messages}")

    item = component.create(engine.rootContext())
    if item is None:
        raise RuntimeError("Broadcaster UI could not be created")
    if not isinstance(item, QQuickItem):
        item.deleteLater()
        raise RuntimeError("BroadcasterScreen.qml root must be a QQuickItem")

    item.setProperty("hostWindow", window)
    item.setParent(window)
    item.setParentItem(window.contentItem())
    item.setZ(90)
    return item


def run_qt(
    service: GuideService,
    television: TelevisionRuntime,
    library: MediaLibrary,
    broadcaster: BroadcasterService,
    runtime_store: RuntimeStore,
    *,
    windowed: bool = False,
) -> int:
    """Launch the couch shell with the first Broadcaster/Channel Builder slice."""

    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    app.setApplicationName("ChannelOS")
    app.setOrganizationName("ChannelOS")
    _apply_channelos_control_theme(app)

    controller = BroadcasterCouchController(
        service,
        television,
        library,
        broadcaster,
        runtime_store,
    )
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    video_window = QWindow()
    video_window.setFlag(Qt.WindowType.FramelessWindowHint, True)
    video_window.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    engine.rootContext().setContextProperty("channelOSVideoWindow", video_window)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    roots = engine.rootObjects()
    if not roots:
        return 7

    window = roots[0]

    try:
        surface = NativeVideoSurface(
            _native_video_platform(),
            int(video_window.winId()),
        )
        controller.attach_video_surface(surface)
    except (RuntimeError, ValueError) as exc:
        controller.set_video_surface_error(str(exc))

    broadcaster_item = _attach_broadcaster_overlay(engine, window)

    key_filter = BroadcasterKeyFilter(controller, window)
    app.installEventFilter(key_filter)

    window._channelos_key_filter = key_filter
    window._channelos_video_window = video_window
    window._channelos_broadcaster_item = broadcaster_item
    window._channelos_broadcaster_component_engine = engine

    playback_timer = QTimer(window)
    playback_timer.setInterval(250)
    playback_timer.timeout.connect(controller.refreshPlayback)
    playback_timer.timeout.connect(controller.refreshOnDemand)
    playback_timer.start()
    window._channelos_playback_timer = playback_timer

    app.aboutToQuit.connect(controller.stop)

    if windowed:
        window.showNormal()
    else:
        window.showFullScreen()

    if not owns_application:
        return 0
    return int(app.exec())
