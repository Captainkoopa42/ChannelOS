from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QEvent, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog

from .couch_actions import CouchActions
from .couch_model import build_couch_snapshot
from .guide import GuideError, GuideService
from .library import MediaLibrary
from .playback import NativeVideoSurface, PlaybackError
from .runtime import ChannelRuntimeError, TelevisionRuntime, TuneDecision
from .scanner import MediaScanner, ScanProgress, ScanSummary
from .television import TelevisionSession


class CouchController(QObject):
    """Qt-facing adapter over ChannelOS Guide data and television control intents."""

    snapshotChanged = Signal()
    playbackChanged = Signal()

    def __init__(
        self,
        service: GuideService,
        television: TelevisionRuntime,
        library: MediaLibrary,
    ) -> None:
        super().__init__()
        self._service = service
        self._library = library
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

    def scan_media_folder(
        self,
        path: str | Path,
        *,
        on_progress: Callable[[ScanProgress], None] | None = None,
    ) -> ScanSummary:
        """Index one user-selected media source into the existing local library."""

        scanner = MediaScanner(self._library)
        return scanner.scan(path, on_progress=on_progress)

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

    def activate_selection(self, row_index: int, program_index: int) -> dict[str, object]:
        rows = self._snapshot.get("rows", [])
        if not isinstance(rows, list) or not 0 <= row_index < len(rows):
            return {"ok": False, "message": "Guide selection is no longer available; refresh the Guide"}
        row = rows[row_index]
        programs = row.get("programs", []) if isinstance(row, dict) else []
        if not isinstance(programs, list) or not 0 <= program_index < len(programs):
            return {"ok": False, "message": "Guide program is no longer available; refresh the Guide"}
        program = programs[program_index]
        if not isinstance(program, dict):
            return {"ok": False, "message": "Guide program data is invalid"}
        return self.activateProgram(
            str(program.get("scheduleId", "")),
            int(program.get("channelNumber", row.get("channelNumber", 0))),
            float(program.get("startMs", 0.0)),
        )

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


class CouchKeyFilter(QObject):
    """Translate couch/keyboard controls independently of QML focus ownership."""

    def __init__(self, controller: CouchController, window: QObject) -> None:
        super().__init__(window)
        self._controller = controller
        self._window = window

    def _notify(self, result: dict[str, object]) -> None:
        message = str(result.get("message", ""))
        if not message:
            return
        self._window.setProperty("statusMessage", message)
        QTimer.singleShot(4200, lambda: self._window.setProperty("statusMessage", ""))

    def _rows(self) -> list[dict[str, object]]:
        rows = self._controller.snapshot.get("rows", [])
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _current_program_index(self, row_index: int) -> int:
        rows = self._rows()
        if not 0 <= row_index < len(rows):
            return -1
        programs = rows[row_index].get("programs", [])
        if not isinstance(programs, list):
            return -1
        for index, program in enumerate(programs):
            if isinstance(program, dict) and bool(program.get("isCurrent")):
                return index
        return 0 if programs else -1

    def _select_row(self, row_index: int) -> None:
        rows = self._rows()
        if not rows:
            return
        selected = max(0, min(len(rows) - 1, row_index))
        self._window.setProperty("selectedRow", selected)
        self._window.setProperty("selectedProgram", self._current_program_index(selected))

    def _select_program_delta(self, delta: int) -> None:
        rows = self._rows()
        row_index = int(self._window.property("selectedRow"))
        if not 0 <= row_index < len(rows):
            return
        programs = rows[row_index].get("programs", [])
        if not isinstance(programs, list) or not programs:
            return
        current = int(self._window.property("selectedProgram"))
        selected = max(0, min(len(programs) - 1, current + delta))
        self._window.setProperty("selectedProgram", selected)

    def _choose_and_scan_media_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            None,
            "Choose a ChannelOS media folder",
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return

        progress_dialog = QProgressDialog()
        progress_dialog.setWindowTitle("ChannelOS — Index Media")
        progress_dialog.setLabelText("Discovering supported media files…")
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setRange(0, 1)
        progress_dialog.setValue(0)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dialog.show()
        QApplication.processEvents()

        def on_progress(progress: ScanProgress) -> None:
            maximum = max(1, progress.total)
            progress_dialog.setRange(0, maximum)
            progress_dialog.setValue(min(progress.current, maximum))
            if progress.path is None:
                progress_dialog.setLabelText(
                    f"Found {progress.total} supported media file(s). Preparing index…"
                )
            else:
                progress_dialog.setLabelText(
                    f"Indexing {progress.current} of {progress.total}\n{progress.path.name}"
                )
            QApplication.processEvents()

        try:
            summary = self._controller.scan_media_folder(folder, on_progress=on_progress)
        except (FileNotFoundError, OSError, ValueError) as exc:
            progress_dialog.close()
            self._notify({"message": f"Media scan failed — {exc}"})
            return

        progress_dialog.setValue(max(1, summary.discovered))
        progress_dialog.close()
        total_assets = self._controller._library.count_assets()
        self._notify(
            {
                "message": (
                    f"Library scan complete — {summary.discovered} files • "
                    f"{summary.new_assets} new • {summary.cache_hits} unchanged • "
                    f"{total_assets} total assets"
                )
            }
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False

        key = event.key()
        screen = str(self._window.property("screen"))

        if screen == "home":
            if key == Qt.Key.Key_G:
                self._controller.refresh()
                self._window.setProperty("screen", "guide")
                self._select_row(int(self._window.property("selectedRow")))
                return True
            if key in {Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
                QGuiApplication.quit()
                return True
            if key == Qt.Key.Key_Up:
                current = int(self._window.property("homeSelection"))
                self._window.setProperty("homeSelection", max(0, current - 1))
                return True
            if key == Qt.Key.Key_Down:
                current = int(self._window.property("homeSelection"))
                self._window.setProperty("homeSelection", min(4, current + 1))
                return True
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                selection = int(self._window.property("homeSelection"))
                if selection == 1:
                    self._controller.refresh()
                    self._window.setProperty("screen", "guide")
                    self._select_row(int(self._window.property("selectedRow")))
                elif selection == 2:
                    self._choose_and_scan_media_folder()
                elif selection == 0:
                    self._notify({"message": "Continue Watching will connect to the Viewer Clock in a later slice"})
                else:
                    self._notify({"message": "This section is reserved for a later couch UI slice"})
                return True
            return False

        if screen == "guide":
            if key == Qt.Key.Key_G:
                self._controller.refresh()
                self._select_row(int(self._window.property("selectedRow")))
                return True
            if key in {Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
                self._window.setProperty("screen", "home")
                return True
            if key == Qt.Key.Key_Up:
                self._select_row(int(self._window.property("selectedRow")) - 1)
                return True
            if key == Qt.Key.Key_Down:
                self._select_row(int(self._window.property("selectedRow")) + 1)
                return True
            if key == Qt.Key.Key_Left:
                self._select_program_delta(-1)
                return True
            if key == Qt.Key.Key_Right:
                self._select_program_delta(1)
                return True
            if key == Qt.Key.Key_Home:
                row_index = int(self._window.property("selectedRow"))
                self._window.setProperty("selectedProgram", self._current_program_index(row_index))
                return True
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                result = self._controller.activate_selection(
                    int(self._window.property("selectedRow")),
                    int(self._window.property("selectedProgram")),
                )
                self._notify(result)
                if bool(result.get("ok")):
                    self._window.setProperty("screen", "live")
                return True
            return False

        if screen != "live":
            return False

        if key in {Qt.Key.Key_G, Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
            self._controller.refresh()
            self._window.setProperty("screen", "guide")
            return True
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self._notify(self._controller.togglePause())
            return True
        if key == Qt.Key.Key_Left:
            self._notify(self._controller.skip(-10.0))
            return True
        if key == Qt.Key.Key_Right:
            self._notify(self._controller.skip(30.0))
            return True
        if key == Qt.Key.Key_Up:
            self._notify(self._controller.changeChannel(1))
            return True
        if key == Qt.Key.Key_Down:
            self._notify(self._controller.changeChannel(-1))
            return True
        if key == Qt.Key.Key_L:
            self._notify(self._controller.goLive())
            return True
        return False


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
    library: MediaLibrary,
    *,
    windowed: bool = False,
) -> int:
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    app.setApplicationName("ChannelOS")
    app.setOrganizationName("ChannelOS")

    controller = CouchController(service, television, library)
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
    video_window.setGeometry(0, 0, max(1, int(window.width())), max(1, int(window.height())))
    video_window.hide()

    try:
        surface = NativeVideoSurface(_native_video_platform(), int(video_window.winId()))
        controller.attach_video_surface(surface)
    except (RuntimeError, ValueError) as exc:
        controller.set_video_surface_error(str(exc))

    def sync_video_surface() -> None:
        width = max(1, int(window.width()))
        height = max(1, int(window.height()))
        video_window.setGeometry(0, 0, width, height)
        video_window.setVisible(window.property("screen") == "live")

    window.widthChanged.connect(sync_video_surface)
    window.heightChanged.connect(sync_video_surface)
    screen_changed = getattr(window, "screenChanged", None)
    if screen_changed is not None:
        screen_changed.connect(sync_video_surface)

    key_filter = CouchKeyFilter(controller, window)
    app.installEventFilter(key_filter)
    window._channelos_key_filter = key_filter

    app.aboutToQuit.connect(controller.stop)

    if windowed:
        window.showNormal()
    else:
        window.showFullScreen()
    sync_video_surface()

    if not owns_application:
        return 0
    return int(app.exec())
