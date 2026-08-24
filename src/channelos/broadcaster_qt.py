from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QObject,
    Property,
    Q_ARG,
    QEvent,
    QMetaObject,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
    Qt,
)
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QFileDialog

from .broadcaster import BroadcasterError, BroadcasterService
from .control import ControlCommand, ControlIntent
from .controller_qt import QtControllerInput
from .couch_actions import CouchActions
from .couch_model import build_couch_snapshot
from .couch_qt import (
    CouchController,
    CouchKeyFilter,
    _start_home_video_when_ready,
)
from .guide import GuideService
from .library import MediaLibrary, normalize_path
from .models import ChannelValidationError
from .playback import NativeVideoSurface
from .resolve import resolve_channel
from .runtime import ChannelRuntime, ChannelRuntimeError, RuntimeStore, TelevisionRuntime
from .scanner import MediaScanner, ScanCancelled, ScanProgress, ScanSummary


def _apply_channelos_control_theme(app: QApplication) -> None:
    # Give Qt Quick Controls the same high-contrast dark palette as ChannelOS.
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

    font = app.font()
    if font.pointSizeF() < 11.0:
        font.setPointSizeF(11.0)
        app.setFont(font)


class _LibraryScanWorker(QObject):
    """Run expensive hashing/probing off the Qt GUI thread."""

    progress = Signal(int, int, str)
    completed = Signal(object)
    cancelled = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        library: MediaLibrary,
        source: Path,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self._library = library
        self._source = source
        self._cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        scanner = MediaScanner(self._library)

        def publish(progress: ScanProgress) -> None:
            self.progress.emit(
                int(progress.current),
                int(progress.total),
                "" if progress.path is None else str(progress.path),
            )

        try:
            summary = scanner.scan(
                self._source,
                on_progress=publish,
                should_cancel=self._cancel_event.is_set,
            )
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.completed.emit(summary)
        finally:
            self.finished.emit()


class BroadcasterCouchController(CouchController):
    """Couch controller extended with management and Library 2.0 operations."""

    broadcasterChanged = Signal()
    libraryScanChanged = Signal()

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

        self._scan_thread: QThread | None = None
        self._scan_worker: _LibraryScanWorker | None = None
        self._scan_cancel_event: threading.Event | None = None
        self._library_scan: dict[str, object] = {
            "active": False,
            "phase": "idle",
            "sourcePath": "",
            "current": 0,
            "total": 0,
            "fileName": "",
            "message": "",
        }

        # CouchController builds an initial library view before the broadcaster
        # service is attached. Rebuild once so source rows can expose channel use.
        self._library_snapshot = self._build_library_snapshot()

    def _channels_using_source(self, source_path: str | Path) -> list[dict[str, object]]:
        broadcaster = getattr(self, "_broadcaster", None)
        if broadcaster is None:
            return []

        _, requested_key = normalize_path(source_path)
        matches: list[dict[str, object]] = []
        for record in broadcaster.records:
            for source in record.definition.sources:
                _, source_key = normalize_path(source.path)
                if source_key != requested_key:
                    continue
                matches.append(
                    {
                        "channelNumber": record.definition.channel,
                        "displayNumber": record.definition.display_number,
                        "name": record.definition.name,
                    }
                )
                break
        return matches

    def _build_library_snapshot(self) -> dict[str, object]:
        snapshot = super()._build_library_snapshot()
        sources: list[dict[str, object]] = []
        for source in self._library.list_sources():
            root = source.source_root
            sources.append(
                {
                    "path": str(root),
                    "name": root.name or str(root),
                    "status": source.status,
                    "available": root.exists(),
                    "discoveredCount": source.discovered_count,
                    "locationCount": source.location_count,
                    "onlineLocationCount": source.online_location_count,
                    "assetCount": source.asset_count,
                    "lastScanStartedAt": source.last_scan_started_at or "",
                    "lastScanFinishedAt": source.last_scan_finished_at or "",
                    "lastError": source.last_error or "",
                    "usedByChannels": self._channels_using_source(root),
                }
            )

        snapshot["sources"] = sources
        snapshot["sourceCount"] = len(sources)
        return snapshot

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

    @Property("QVariantMap", notify=libraryScanChanged)
    def libraryScan(self) -> dict[str, object]:
        return self._library_scan

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self._video_surface = surface
        super().attach_video_surface(surface)

    @Slot()
    def refreshBroadcaster(self) -> None:
        self._broadcaster.refresh()
        self._broadcaster_snapshot = self._build_broadcaster_snapshot()
        self.broadcasterChanged.emit()
        self.refreshLibrary()

    @Slot(str, result="QVariantMap")
    def playLibraryAsset(self, asset_id: str) -> dict[str, object]:
        target = str(asset_id)
        for index, media in enumerate(self._library_media):
            if media.asset.asset_id == target:
                return self.playLibraryIndex(index)
        return {
            "ok": False,
            "message": "Library selection is no longer available; refresh the Library",
        }

    @Slot(result="QVariantMap")
    def chooseMediaFolder(self) -> dict[str, object]:
        folder = QFileDialog.getExistingDirectory(
            None,
            "Choose a ChannelOS media folder",
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return {"ok": False, "cancelled": True, "message": ""}
        return self.preflightMediaSource(folder)

    @Slot(str, result="QVariantMap")
    def preflightMediaSource(self, source_path: str) -> dict[str, object]:
        try:
            source = Path(source_path).expanduser().resolve(strict=False)
            discovered = MediaScanner(self._library).discover(source)
            existing_keys = {
                item.source_root_key
                for item in self._library.list_sources()
            }
            _, source_key = normalize_path(source)
            return {
                "ok": True,
                "path": str(source),
                "name": source.name or str(source),
                "supportedCount": len(discovered),
                "alreadyIndexed": source_key in existing_keys,
                "message": (
                    f"Found {len(discovered)} supported media file(s) in {source}"
                ),
            }
        except (FileNotFoundError, OSError, ValueError) as exc:
            return self._error(exc)

    def _set_library_scan(self, **changes: object) -> None:
        updated = dict(self._library_scan)
        updated.update(changes)
        self._library_scan = updated
        self.libraryScanChanged.emit()

    @Slot(str, result="QVariantMap")
    def startMediaScan(self, source_path: str) -> dict[str, object]:
        if self._scan_thread is not None:
            return {
                "ok": False,
                "message": "A Library scan is already finishing; wait for it to close",
            }

        source = Path(source_path).expanduser().resolve(strict=False)
        if not source.exists():
            return {
                "ok": False,
                "message": f"media source does not exist: {source}",
            }

        cancel_event = threading.Event()
        thread = QThread(self)
        worker = _LibraryScanWorker(self._library, source, cancel_event)
        worker.moveToThread(thread)

        worker.progress.connect(self._on_library_scan_progress)
        worker.completed.connect(self._on_library_scan_completed)
        worker.cancelled.connect(self._on_library_scan_cancelled)
        worker.failed.connect(self._on_library_scan_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_library_scan_thread_finished)
        thread.started.connect(worker.run)

        self._scan_thread = thread
        self._scan_worker = worker
        self._scan_cancel_event = cancel_event
        self._set_library_scan(
            active=True,
            phase="discovering",
            sourcePath=str(source),
            current=0,
            total=0,
            fileName="",
            message="Discovering supported media files…",
        )
        thread.start()
        return {
            "ok": True,
            "message": f"Started Library scan for {source}",
        }

    @Slot(int, int, str)
    def _on_library_scan_progress(
        self,
        current: int,
        total: int,
        path: str,
    ) -> None:
        filename = Path(path).name if path else ""
        if int(current) <= 0:
            message = f"Found {int(total)} supported media file(s). Preparing index…"
            phase = "indexing"
        else:
            message = f"Indexing {int(current)} of {int(total)}"
            phase = "indexing"
        self._set_library_scan(
            active=True,
            phase=phase,
            current=int(current),
            total=int(total),
            fileName=filename,
            message=message,
        )

    @Slot(object)
    def _on_library_scan_completed(self, summary: ScanSummary) -> None:
        self.refreshLibrary()
        self._set_library_scan(
            active=False,
            phase="ready",
            current=int(summary.discovered),
            total=int(summary.discovered),
            fileName="",
            message=(
                f"Scan complete — {summary.discovered} files • "
                f"{summary.new_assets} new • {summary.cache_hits} unchanged"
            ),
        )

    @Slot()
    def _on_library_scan_cancelled(self) -> None:
        self.refreshLibrary()
        self._set_library_scan(
            active=False,
            phase="cancelled",
            fileName="",
            message="Library scan cancelled. The last successful index was preserved.",
        )

    @Slot(str)
    def _on_library_scan_failed(self, message: str) -> None:
        self.refreshLibrary()
        self._set_library_scan(
            active=False,
            phase="error",
            fileName="",
            message=f"Library scan failed — {message}",
        )

    @Slot()
    def _on_library_scan_thread_finished(self) -> None:
        thread = self._scan_thread
        self._scan_worker = None
        self._scan_cancel_event = None
        self._scan_thread = None
        if thread is not None:
            thread.deleteLater()

    @Slot(result="QVariantMap")
    def cancelMediaScan(self) -> dict[str, object]:
        if self._scan_cancel_event is None or not bool(self._library_scan.get("active")):
            return {"ok": False, "message": "No Library scan is active"}
        self._scan_cancel_event.set()
        self._set_library_scan(
            phase="cancelling",
            message="Cancelling after the current file operation…",
        )
        return {"ok": True, "message": "Cancelling Library scan"}

    @Slot(str, result="QVariantMap")
    def removeLibrarySource(self, source_path: str) -> dict[str, object]:
        if self._scan_thread is not None:
            return {
                "ok": False,
                "message": "Wait for the active Library scan to finish before removing a source",
            }

        used_by = self._channels_using_source(source_path)
        if used_by:
            labels = ", ".join(
                f"{item['displayNumber']} {item['name']}"
                for item in used_by
            )
            return {
                "ok": False,
                "message": (
                    "This source is still used by channel definition(s): "
                    f"{labels}. Edit those channels before removing the source "
                    "from the Library."
                ),
            }

        try:
            result = self._library.remove_source_from_index(source_path)
            self.refreshLibrary()
            self.refreshBroadcaster()
            return {
                "ok": True,
                "message": (
                    f"Removed {result.removed_locations} indexed location(s) from "
                    "ChannelOS. Original media files were not changed."
                ),
                "removedLocations": result.removed_locations,
                "prunedAssets": result.pruned_assets,
            }
        except (OSError, ValueError) as exc:
            return self._error(exc)

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
        self._home_television = self._build_home_television_view()
        self.snapshotChanged.emit()
        self.homeTelevisionChanged.emit()

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
    """Add management navigation without stealing editor/search text input."""

    def __init__(self, controller, window) -> None:
        super().__init__(controller, window)
        self._library_item: QQuickItem | None = None
        self._broadcaster_item: QQuickItem | None = None

    def bind_management_overlays(
        self,
        *,
        library_item: QQuickItem,
        broadcaster_item: QQuickItem,
    ) -> None:
        self._library_item = library_item
        self._broadcaster_item = broadcaster_item

    @staticmethod
    def _invoke_overlay(item: QQuickItem | None, intent: ControlIntent) -> bool:
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
        if command.intent is ControlIntent.CHANNELS:
            self._window.setProperty("infoVisible", False)
            self._controller.refreshBroadcaster()
            self._window.setProperty("screen", "broadcaster")
            return True
        screen = str(self._window.property("screen"))
        overlay_intents = {
            ControlIntent.UP,
            ControlIntent.DOWN,
            ControlIntent.LEFT,
            ControlIntent.RIGHT,
            ControlIntent.SELECT,
            ControlIntent.BACK,
            ControlIntent.ADD_MEDIA_SOURCE,
        }
        if screen == "library" and command.intent in overlay_intents:
            return self._invoke_overlay(self._library_item, command.intent)
        if screen == "broadcaster" and command.intent in overlay_intents:
            return self._invoke_overlay(self._broadcaster_item, command.intent)
        return super().dispatch_command(command)

    @staticmethod
    def _text_entry_has_focus() -> bool:
        focus = QGuiApplication.focusObject()
        if focus is None:
            return False
        class_name = focus.metaObject().className().lower()
        return any(
            marker in class_name
            for marker in (
                "textinput",
                "textfield",
                "textedit",
                "textarea",
                "lineedit",
                "spinbox",
                "combobox",
            )
        )

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and str(self._window.property("screen")) in {"broadcaster", "library"}
        ):
            command = self.command_for_key(event.key())
            if (
                command is not None
                and command.intent
                in (
                    {ControlIntent.HOME, ControlIntent.SETTINGS}
                    | (
                        {ControlIntent.INFO}
                        if str(self._window.property("screen")) == "library"
                        else set()
                    )
                    | (
                        {ControlIntent.BACK}
                        if bool(self._window.property("infoVisible"))
                        else set()
                    )
                )
                and (
                    not event.text()
                    or not self._text_entry_has_focus()
                )
            ):
                return self.dispatch_command(command)
            # These management overlays own their keyboard/focus model. In
            # particular, Library search must be allowed to receive ordinary A-Z
            # keypresses instead of global couch shortcuts. H/S remain ordinary
            # text while an editor has focus, but act as Home/Settings during
            # couch navigation.
            return False
        return super().eventFilter(watched, event)


def _attach_overlay(
    engine: QQmlApplicationEngine,
    window,
    filename: str,
    *,
    z: int,
):
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parent / "qml" / filename
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))

    if component.isError():
        messages = "; ".join(error.toString() for error in component.errors())
        raise RuntimeError(f"{filename} could not be loaded: {messages}")

    item = component.create(engine.rootContext())
    if item is None:
        raise RuntimeError(f"{filename} could not be created")
    if not isinstance(item, QQuickItem):
        item.deleteLater()
        raise RuntimeError(f"{filename} root must be a QQuickItem")

    item.setProperty("hostWindow", window)
    item.setParent(window)
    item.setParentItem(window.contentItem())
    item.setZ(z)
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
    """Launch the couch shell with Broadcaster and Library management overlays."""

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

    library_item = _attach_overlay(
        engine,
        window,
        "LibraryScreen.qml",
        z=85,
    )
    broadcaster_item = _attach_overlay(
        engine,
        window,
        "BroadcasterScreen.qml",
        z=90,
    )
    settings_item = _attach_overlay(
        engine,
        window,
        "SettingsScreen.qml",
        z=95,
    )

    key_filter = BroadcasterKeyFilter(controller, window)
    key_filter.bind_management_overlays(
        library_item=library_item,
        broadcaster_item=broadcaster_item,
    )
    app.installEventFilter(key_filter)
    window.homeMenuActivated.connect(key_filter.activateHomeMenu)
    window.homeCardActivated.connect(key_filter.activateHomeCard)

    window._channelos_key_filter = key_filter
    window._channelos_video_window = video_window
    window._channelos_library_item = library_item
    window._channelos_broadcaster_item = broadcaster_item
    window._channelos_settings_item = settings_item
    window._channelos_component_engine = engine

    controller_input = QtControllerInput(window, key_filter.dispatch_command)
    window._channelos_controller_input = controller_input

    playback_timer = QTimer(window)
    playback_timer.setInterval(250)
    playback_timer.timeout.connect(controller.refreshPlayback)
    playback_timer.timeout.connect(controller.refreshOnDemand)
    playback_timer.start()
    window._channelos_playback_timer = playback_timer

    app.aboutToQuit.connect(controller.stop)
    app.aboutToQuit.connect(controller_input.stop)

    if windowed:
        window.showNormal()
    else:
        window.showFullScreen()

    controller_input.start()

    # channelos.couch launches this Broadcaster-integrated Qt path. Keep Home
    # startup on the same native-surface gate as the narrower couch launcher so
    # a future integration cannot silently omit the playback request again.
    window._channelos_home_startup_gate = _start_home_video_when_ready(
        controller,
        window,
        video_window,
    )

    if not owns_application:
        return 0
    return int(app.exec())
