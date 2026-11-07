from __future__ import annotations

import logging
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QObject,
    Property,
    Q_ARG,
    QCoreApplication,
    QEvent,
    QMetaObject,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
    Qt,
)
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QKeyEvent, QPalette, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QFileDialog

from .broadcaster import (
    BroadcasterError,
    BroadcasterService,
    StudioAutoFillCancelled,
)
from .control import ControlCommand, ControlIntent
from .controller_qt import QtControllerInput
from .couch_actions import CouchActions
from .couch_qt import (
    CouchController,
    CouchKeyFilter,
    _start_home_video_when_ready,
)
from .guide import GuideError, GuideService
from .library import MediaLibrary, normalize_path
from .models import ChannelValidationError
from .playback import NativeVideoSurface, PlaybackError
from .runtime import ChannelRuntimeError, RuntimeStore, TelevisionRuntime
from .scanner import MediaScanner, ScanCancelled, ScanProgress, ScanSummary

logger = logging.getLogger(__name__)


def _apply_channelos_control_theme(app: QApplication) -> None:
    # Give Qt Quick Controls the same high-contrast dark palette as ChannelOS.
    if getattr(app, '_channelos_theme_applied', False):
        return
    app._channelos_theme_applied = True
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
        logger.info("Library scan worker started source=%s", self._source.name)

        last_publication = [0.0]
        def publish(progress: ScanProgress) -> None:
            now = time.monotonic()
            if progress.current not in {0,progress.total} and now - last_publication[0] < .1:
                return
            last_publication[0] = now
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
            logger.info("Library scan worker cancelled")
            self.cancelled.emit()
        except Exception as exc:
            logger.exception("Library scan worker failed")
            self.failed.emit(str(exc))
        else:
            logger.info(
                "Library scan worker completed discovered=%d new=%d cached=%d probe_errors=%d",
                summary.discovered,
                summary.new_assets,
                summary.cache_hits,
                summary.probe_errors,
            )
            self.completed.emit(summary)
        finally:
            self.finished.emit()


class _StudioAutoFillWorker(QObject):
    """Build a detached Studio schedule without blocking the QML GUI thread."""

    progress = Signal(int, int, str)
    completed = Signal(object)
    cancelled = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        broadcaster: BroadcasterService,
        editor: dict[str, Any],
        start_utc: str,
        end_utc: str,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self._broadcaster = broadcaster
        self._editor = dict(editor)
        self._start_utc = str(start_utc)
        self._end_utc = str(end_utc)
        self._cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        logger.info("Studio Auto Fill worker started")
        try:
            result = self._broadcaster.auto_fill_studio(
                self._editor,
                self._start_utc,
                self._end_utc,
                on_progress=self.progress.emit,
                should_cancel=self._cancel_event.is_set,
            )
            if result.get('ok'):
                from .studio_publication import prepare_publication
                media = self._broadcaster.studio_media()
                result = prepare_publication(result, self._editor, media,
                    self._broadcaster.studio_groups(available_asset_ids={item['assetId'] for item in media}))
            if self._cancel_event.is_set():
                raise StudioAutoFillCancelled("Studio Auto Fill was cancelled")
        except StudioAutoFillCancelled:
            logger.info("Studio Auto Fill worker cancelled")
            self.cancelled.emit()
        except Exception as exc:
            logger.exception("Studio Auto Fill worker failed")
            self.failed.emit(str(exc))
        else:
            summary = result if isinstance(result, dict) else {}
            logger.info(
                "Studio Auto Fill worker completed blocks=%d ad_windows=%d ad_seconds=%s warnings=%d",
                len(summary.get("blocks", ())), summary.get("adSlotCount", 0),
                summary.get("adReservedSeconds", 0), len(summary.get("adWarnings", ())),
            )
            self.completed.emit(result)
        finally:
            self.finished.emit()


class BroadcasterCouchController(CouchController):
    """Couch controller extended with management and Library 2.0 operations."""

    broadcasterChanged = Signal()
    libraryScanChanged = Signal()
    mediaPreflightCompleted = Signal("QVariantMap")
    studioAutoFillChanged = Signal()
    studioAutoFillCompleted = Signal("QVariantMap")

    def __init__(
        self,
        service: GuideService,
        television: TelevisionRuntime,
        library: MediaLibrary,
        broadcaster: BroadcasterService,
        runtime_store: RuntimeStore,
    ) -> None:
        self._broadcaster = broadcaster
        self._defer_initial_views = bool(getattr(broadcaster, '_deferred_startup', False))
        super().__init__(service, television, library)
        self._runtime_store = runtime_store
        self._lineup_definitions = {record.channel_number: record.definition for record in broadcaster.records}
        self._lineup_library_revision = library.revision()
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

        self._studio_auto_fill_thread: QThread | None = None
        self._studio_auto_fill_worker: _StudioAutoFillWorker | None = None
        self._studio_auto_fill_cancel_event: threading.Event | None = None
        self._studio_auto_fill: dict[str, object] = {
            "active": False,
            "phase": "idle",
            "current": 0,
            "total": 0,
            "percent": 0,
            "message": "",
        }


    def _channels_using_source(self, source_path: str | Path, indexed_media=None) -> list[dict[str, object]]:
        broadcaster = getattr(self, "_broadcaster", None)
        if broadcaster is None:
            return []

        return broadcaster.source_dependencies(source_path, indexed_media=indexed_media)

    def _build_library_snapshot(self) -> dict[str, object]:
        snapshot = super()._build_library_snapshot()
        if self._defer_initial_views:
            return snapshot
        from .library_view import add_source_information
        return add_source_information(snapshot, self._library, self._broadcaster)

    def _build_broadcaster_snapshot(self) -> dict[str, object]:
        snapshot = self._broadcaster.snapshot()
        channels = snapshot.get("channels", [])
        if isinstance(channels, list):
            for channel in channels:
                if not isinstance(channel, dict):
                    continue
                number = int(channel.get("channelNumber", 0))
                channel["available"] = number in self._service.channel_numbers
                channel["availabilityMessage"] = "" if channel["available"] else "Media unavailable — reconnect or scan its source in Library"
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

    @Property("QVariantMap", notify=studioAutoFillChanged)
    def studioAutoFill(self) -> dict[str, object]:
        return self._studio_auto_fill

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self._video_surface = surface
        super().attach_video_surface(surface)

    @Slot()
    def stop(self) -> None:
        # Set every cancellation flag before joining either worker. Otherwise a
        # slow Library scan can delay cancellation of Studio Auto Fill (or vice
        # versa) while the GUI is closing.
        if self._scan_cancel_event is not None:
            self._scan_cancel_event.set()
        if self._studio_auto_fill_cancel_event is not None:
            self._studio_auto_fill_cancel_event.set()

        # A live QThread being destroyed is a process-fatal Qt error. Request
        # both event loops to stop, then wait until their current cooperative
        # operation returns before allowing controller destruction.
        for thread in (
            self._scan_thread,
            self._studio_auto_fill_thread,
        ):
            if thread is None or not thread.isRunning():
                continue
            logger.info("Waiting for worker shutdown name=%s", thread.objectName())
            thread.quit()
            thread.wait()
            logger.info("Worker shutdown complete name=%s", thread.objectName())
        super().stop()

    @Slot()
    def refreshBroadcaster(self) -> None:
        from .performance import operation
        with operation('channels.open', channels=len(self._broadcaster.records)):
            self._broadcaster.refresh()
            self._broadcaster_snapshot = self._build_broadcaster_snapshot()
            self.broadcasterChanged.emit()

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

    @Slot(result="QVariantMap")
    def chooseMediaFolderPath(self):
        folder = QFileDialog.getExistingDirectory(None, "Choose a ChannelOS media folder", str(Path.home()), QFileDialog.Option.ShowDirsOnly)
        return {"ok":bool(folder),"cancelled":not bool(folder),"path":folder}

    @Slot(str, result="QVariantMap")
    def startMediaPreflight(self, source_path):
        if self._scan_thread is not None:
            return {"ok":False,"message":"A Library operation is already finishing."}
        if getattr(self, 'startupState', {}).get('active') or getattr(self, 'channelMutation', {}).get('active'):
            return {"ok":False,"message":"Wait for the current setup operation to finish."}
        from .library_jobs import SourcePreflightWorker
        cancel = threading.Event()
        worker = SourcePreflightWorker(self._library, source_path, cancel)
        thread = QThread(self)
        thread.setObjectName('source-preflight')
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_preflight_completed)
        worker.failed.connect(self._on_preflight_failed)
        worker.cancelled.connect(self._on_preflight_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_library_scan_thread_finished)
        self._scan_thread, self._scan_worker, self._scan_cancel_event = thread, worker, cancel
        self._scan_kind, self._pending_preflight = 'preflight', None
        self._set_library_scan(active=True,phase='discovering',sourcePath=str(source_path),current=0,total=0,
            fileName='',message='Checking this source…')
        thread.start(QThread.Priority.LowPriority)
        return {"ok":True,"pending":True,"message":"Checking this source…"}

    @Slot(object)
    def _on_preflight_completed(self, result):
        self._pending_preflight = result

    @Slot(str)
    def _on_preflight_failed(self, message):
        self._pending_preflight = {"ok":False,"message":message}

    @Slot()
    def _on_preflight_cancelled(self):
        self._pending_preflight = {"ok":False,"cancelled":True,"message":"Source check cancelled."}

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
        thread.setObjectName("library-scan")
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

        self._scan_kind = "scan"
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
        if getattr(self, '_scan_kind', '') == 'preflight':
            result = self._pending_preflight or {"ok":False,"cancelled":True,"message":"Source check cancelled."}
            self._pending_preflight = None
            self._set_library_scan(active=False,phase='ready' if result.get('ok') else 'cancelled' if result.get('cancelled') else 'error', message=result.get('message',''))
            self.mediaPreflightCompleted.emit(result)

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
                    "This source is still used by saved channel or ad collection references: "
                    f"{labels}. Edit those references before removing the source "
                    "from the Library."
                ),
            }

        try:
            result = self._broadcaster.remove_library_source(source_path)
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
        except (BroadcasterError, OSError, ValueError) as exc:
            return self._error(exc)

    def _reload_lineup(self, *, replacement_channel_number=None, prepared=None) -> None:
        if not hasattr(self._actions, 'replace_lineup'):
            return self._reload_lineup_full(replacement_channel_number=replacement_channel_number)
        from .media_resilience import _resolved_runtime
        previous = getattr(self._actions, "full_channels", None) or self._actions.runtime.channels
        definitions = {record.channel_number: record.definition for record in self._broadcaster.records}
        changed = {number for number, definition in definitions.items()
                   if self._lineup_definitions.get(number) != definition}
        removed = set(previous) - set(definitions)
        if self._library.revision() != self._lineup_library_revision:
            changed.update(definitions)
        if prepared is not None:
            changed = set(prepared)
        current = self._actions.runtime.current_channel
        active_changed = current in changed or current in removed
        was_active = bool(self._playback.get('active')) and not self._on_demand.active
        paused = bool(self._playback.get('paused'))
        if active_changed and was_active:
            self._actions.suspend_decoder()
        replacements = {}
        try:
            for number in changed:
                if prepared is not None:
                    replacements[number] = prepared[number]
                else:
                    replacements[number] = _resolved_runtime(definitions[number], self._library, self._runtime_store,
                        persistent_when_complete=True, verify_files=True)
            combined = {number: runtime for number, runtime in previous.items() if number not in changed and number not in removed}
            combined.update({number: runtime for number, runtime in replacements.items() if runtime is not None})
            service = GuideService(tuple(combined.values()), definitions=tuple(definitions.values()))
            self._actions.replace_lineup(service, tuple(combined.values()))
            self._service = self._actions.service  # profile-filtered
            self._lineup_definitions = definitions
            self._lineup_library_revision = self._library.revision()
        except Exception:
            for runtime in replacements.values():
                if runtime is not None and runtime.break_store is not None:
                    runtime.break_store.close()
            if active_changed and was_active and current in previous:
                self._publish(self._actions.restore_after_lineup_change(current, paused=paused))
            raise
        for number in changed | removed:
            old = previous.get(number)
            if old is not None and old is not combined.get(number) and old.break_store is not None:
                old.break_store.close()
        self._snapshot = self._build_guide_snapshot()
        self._home_television = self._build_home_television_view()
        self.snapshotChanged.emit()
        self.homeTelevisionChanged.emit()
        if active_changed and was_active:
            target = current if current in combined else replacement_channel_number
            if target not in combined:
                target = next(iter(sorted(combined)), None)
            if target is None:
                self._playback = {'active': False}
                self.playbackChanged.emit()
            else:
                try:
                    self._publish(self._actions.restore_after_lineup_change(target, paused=paused if target == current else False))
                except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
                    self._publish_playback_failure(exc)

    def _reload_lineup_full(
        self,
        *,
        replacement_channel_number: int | None = None,
    ) -> None:
        """Rebuild Guide/TV objects while preserving active playback."""

        restore_playback = (
            bool(self._playback.get("active"))
            and not self._on_demand.active
        )
        prior_channel_number = int(
            self._playback.get("channelNumber", 0) or 0
        )
        prior_paused = bool(self._playback.get("paused", False))

        from .couch import _open_runtimes
        runtimes = _open_runtimes(self._broadcaster.paths, self._library, self._runtime_store,
            definitions={record.path: record.definition for record in self._broadcaster.records})

        service = GuideService(tuple(runtimes), definitions=tuple(record.definition for record in self._broadcaster.records))
        television = TelevisionRuntime(tuple(runtimes), self._runtime_store)

        if television.current_channel is not None:
            try:
                television.status()
            except ChannelRuntimeError:
                television.tune(television.current_channel, return_behavior="live")

        actions = CouchActions(service, television)
        actions.set_audio_output_device(
            self._settings.audio_output_device_id or None
        )
        actions.set_video_settings(self._settings.video)
        if getattr(self._actions, "_surface_size", None):
            actions.set_surface_size(*self._actions._surface_size)
        if self._video_surface is not None:
            actions.attach_video_surface(self._video_surface)

        restore_channel_number: int | None = None
        if restore_playback and television.channel_numbers:
            if prior_channel_number in television.channels:
                restore_channel_number = prior_channel_number
            elif replacement_channel_number in television.channels:
                restore_channel_number = replacement_channel_number
                prior_paused = False
            else:
                restore_channel_number = television.channel_numbers[0]
                prior_paused = False

        # Nothing that can invalidate the replacement lineup has touched the
        # working decoder yet. Retire it only after every definition/runtime
        # object and presentation target above has been accepted.
        previous_actions = self._actions
        previous_actions.stop()
        for runtime in getattr(previous_actions, "full_channels", previous_actions.runtime.channels).values():
            if runtime.break_store is not None:
                runtime.break_store.close()

        if hasattr(actions, "set_channel_filter"):
            actions.set_channel_filter(self._profile_channel_filter())
        self._service = actions.service
        self._actions = actions
        self._snapshot = self._build_guide_snapshot()
        self._home_television = self._build_home_television_view()
        self.snapshotChanged.emit()
        self.homeTelevisionChanged.emit()

        if restore_channel_number is None:
            self._playback = {"active": False}
            self.playbackChanged.emit()
            return

        try:
            decision = actions.restore_after_lineup_change(
                restore_channel_number,
                paused=prior_paused,
            )
            self._publish(decision)
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            # The saved lineup is valid even if the native decoder cannot be
            # recreated. Keep its runtime active and show the normal retryable
            # playback failure instead of silently leaving a blank surface.
            self._publish_playback_failure(exc)

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

    @Slot(int, result="QVariantMap")
    def loadChannelStudio(self, channel_number: int) -> dict[str, object]:
        try:
            draft = self._broadcaster.studio_draft(int(channel_number))
            return {
                "ok": True,
                "message": "Studio draft loaded. Live television is unchanged.",
                "draft": draft,
            }
        except (
            BroadcasterError,
            ChannelValidationError,
            OSError,
            ValueError,
        ) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def adCatalogSnapshot(self) -> dict[str, object]:
        try:
            return {"ok": True, **self._broadcaster.ad_catalog_snapshot()}
        except (OSError, ValueError) as exc:
            return self._error(exc)

    @Slot(int, result="QVariantMap")
    def adBreakDiagnostics(self, channel_number: int) -> dict[str, object]:
        try:
            channel = self._actions.runtime.channels.get(int(channel_number))
            if channel is None:
                return {"ok": False, "message": "Channel is not live; apply it first"}
            if channel.break_store is None:
                return {"ok": True, "channelNumber": int(channel_number),
                        "plannedBreaks": 0, "completedAirings": 0,
                        "completedViewings": 0, "lastAiredUtc": "",
                        "viewerCounts": {}}
            return {"ok": True, **channel.break_store.diagnostics(int(channel_number))}
        except (OSError, ValueError) as exc:
            return self._error(exc)

    @Slot("QVariantMap", result="QVariantMap")
    def saveAdCollection(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            return {
                "ok": True,
                "message": "Advertisement collection saved",
                **self._broadcaster.save_ad_collection(dict(payload)),
            }
        except (OSError, ValueError) as exc:
            return self._error(exc)

    @Slot("QVariantMap", result="QVariantMap")
    def saveAdBreakProfile(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            return {
                "ok": True,
                "message": "Reusable break profile saved",
                **self._broadcaster.save_ad_profile(dict(payload)),
            }
        except (OSError, ValueError) as exc:
            return self._error(exc)

    @Slot("QVariantMap", result="QVariantMap")
    def assignAdBreakProfile(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            return {
                "ok": True,
                "message": "Channel assignment saved; apply Studio draft to activate",
                **self._broadcaster.assign_ad_profile(dict(payload)),
            }
        except (OSError, ValueError) as exc:
            return self._error(exc)

    @Slot(str, "QVariantList", str, result="QVariantMap")
    def createStudioGroup(
        self,
        name: str,
        asset_ids: list[object],
        mode: str,
    ) -> dict[str, object]:
        try:
            group = self._broadcaster.create_studio_group(
                name,
                (str(value) for value in asset_ids),
                mode,
            )
            return {
                "ok": True,
                "message": (
                    f"Saved reusable group {group['name']} with "
                    f"{group['memberCount']} item(s)"
                ),
                "group": group,
                "groups": self._broadcaster.studio_groups(),
            }
        except (
            BroadcasterError,
            ChannelValidationError,
            OSError,
            ValueError,
        ) as exc:
            return self._error(exc)

    @Slot(str, result="QVariantMap")
    def deleteStudioGroup(self, group_id: str) -> dict[str, object]:
        try:
            self._broadcaster.delete_studio_group(group_id)
            return {
                "ok": True,
                "message": (
                    "Reusable group deleted. Existing draft assignments keep "
                    "their embedded media snapshot."
                ),
                "groups": self._broadcaster.studio_groups(),
            }
        except (BroadcasterError, OSError, ValueError) as exc:
            return self._error(exc)

    def _set_studio_auto_fill(self, **changes: object) -> None:
        updated = dict(self._studio_auto_fill)
        updated.update(changes)
        self._studio_auto_fill = updated
        self.studioAutoFillChanged.emit()

    @Slot("QVariantMap", str, str, result="QVariantMap")
    def startStudioAutoFill(
        self,
        editor: dict[str, object],
        start_utc: str,
        end_utc: str,
    ) -> dict[str, object]:
        try:
            if self._studio_auto_fill_thread is not None:
                return {
                    "ok": False,
                    "message": "Studio Auto Fill is already finishing",
                }
            mapped_editor = self._editor_mapping(editor)
            # Validate timestamps on the GUI thread so malformed requests fail
            # immediately, while all media resolution and schedule generation
            # remains in the worker.
            self._broadcaster._studio_timestamp(start_utc, "calendar start")
            self._broadcaster._studio_timestamp(end_utc, "calendar end")
        except (ChannelValidationError, ValueError) as exc:
            return self._error(exc)

        cancel_event = threading.Event()
        thread = QThread(self)
        thread.setObjectName("studio-auto-fill")
        worker = _StudioAutoFillWorker(
            self._broadcaster,
            mapped_editor,
            start_utc,
            end_utc,
            cancel_event,
        )
        worker.moveToThread(thread)

        worker.progress.connect(self._on_studio_auto_fill_progress)
        worker.completed.connect(self._on_studio_auto_fill_completed)
        worker.cancelled.connect(self._on_studio_auto_fill_cancelled)
        worker.failed.connect(self._on_studio_auto_fill_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_studio_auto_fill_thread_finished)
        thread.started.connect(worker.run)

        self._studio_auto_fill_thread = thread
        self._studio_auto_fill_worker = worker
        self._studio_auto_fill_cancel_event = cancel_event
        self._set_studio_auto_fill(
            active=True,
            phase="preparing",
            current=0,
            total=0,
            percent=0,
            message="Preparing detached Studio Auto Fill…",
        )
        thread.start()
        return {
            "ok": True,
            "message": "Studio Auto Fill started in the background",
        }

    @Slot(int, int, str)
    def _on_studio_auto_fill_progress(
        self,
        current: int,
        total: int,
        message: str,
    ) -> None:
        current = max(0, int(current))
        total = max(0, int(total))
        percent = (
            min(100, int(current * 100 / total))
            if total > 0
            else 0
        )
        self._set_studio_auto_fill(
            active=True,
            phase="building" if total > 0 else "preparing",
            current=current,
            total=total,
            percent=percent,
            message=str(message),
        )

    @Slot(object)
    def _on_studio_auto_fill_completed(self, result: object) -> None:
        if (
            self._studio_auto_fill_cancel_event is not None
            and self._studio_auto_fill_cancel_event.is_set()
        ):
            self._on_studio_auto_fill_cancelled()
            return
        if not isinstance(result, dict):
            self._on_studio_auto_fill_failed(
                "Studio Auto Fill returned an invalid result"
            )
            return
        self._set_studio_auto_fill(
            active=False,
            phase="ready",
            current=1,
            total=1,
            percent=100,
            message=str(result.get("message", "Studio Auto Fill is ready")),
        )
        # Transfer the large prepared model as one string; QML parses it into
        # native arrays instead of walking thousands of QVariant maps.
        publication = ({key: value for key, value in result.items()
                        if key not in {'preparedRows', 'preparedDays'}}
                       if result.get('publicationJson') else dict(result))
        self.studioAutoFillCompleted.emit(publication)

    @Slot()
    def _on_studio_auto_fill_cancelled(self) -> None:
        self._set_studio_auto_fill(
            active=False,
            phase="cancelled",
            current=0,
            total=0,
            percent=0,
            message=(
                "Studio Auto Fill cancelled. The detached draft was not changed."
            ),
        )

    @Slot(str)
    def _on_studio_auto_fill_failed(self, message: str) -> None:
        self._set_studio_auto_fill(
            active=False,
            phase="error",
            current=0,
            total=0,
            percent=0,
            message=f"Studio Auto Fill failed — {message}",
        )

    @Slot()
    def _on_studio_auto_fill_thread_finished(self) -> None:
        thread = self._studio_auto_fill_thread
        self._studio_auto_fill_worker = None
        self._studio_auto_fill_cancel_event = None
        self._studio_auto_fill_thread = None
        if thread is not None:
            thread.deleteLater()

    @Slot(result="QVariantMap")
    def cancelStudioAutoFill(self) -> dict[str, object]:
        if (
            self._studio_auto_fill_cancel_event is None
            or not bool(self._studio_auto_fill.get("active"))
        ):
            return {"ok": False, "message": "No Studio Auto Fill is active"}
        self._studio_auto_fill_cancel_event.set()
        self._set_studio_auto_fill(
            phase="cancelling",
            message="Cancelling after the current local operation…",
        )
        return {"ok": True, "message": "Cancelling Studio Auto Fill"}

    def _checkpoint_playback_history(self) -> None:
        checkpoint = getattr(self._actions, "checkpoint_viewing", None)
        if callable(checkpoint):
            checkpoint()

    @contextmanager
    def _deletion_playback_guard(self, channel_number: int):
        self._checkpoint_playback_history()
        prior_channel = self._actions.runtime.current_channel
        prior_paused = bool(self._playback.get("paused"))
        was_active = bool(self._playback.get("active")) and not self._on_demand.active
        suspend = getattr(self._actions, "suspend_decoder", None)
        suspended = False
        try:
            if prior_channel == int(channel_number) and callable(suspend):
                suspended = True
                suspend()
            yield
        except Exception:
            if suspended and was_active and prior_channel in self._actions.runtime.channels:
                try:
                    decision = self._actions.restore_after_lineup_change(prior_channel, paused=prior_paused)
                    self._publish(decision)
                except (ChannelRuntimeError, PlaybackError, ValueError) as recovery_error:
                    self._publish_playback_failure(recovery_error)
            raise

    @Slot("QVariantMap", result="QVariantMap")
    def createChannel(self, editor: dict[str, object]) -> dict[str, object]:
        try:
            self._checkpoint_playback_history()
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
    def previewAdSettings(self, channel_number: int, editor: dict[str, object]) -> dict[str, object]:
        try:
            return {"ok": True, "editor": self._broadcaster.preview_ad_settings(channel_number, editor)}
        except (BroadcasterError, ChannelValidationError, OSError, ValueError) as exc:
            return self._error(exc)

    @Slot(int, str, str, result="QVariantMap")
    def addLibraryItemToChannel(self, channel_number: int, asset_id: str, path: str) -> dict[str, object]:
        try:
            self._checkpoint_playback_history()
            result = self._broadcaster.add_library_item(channel_number, asset_id, path)
            self._reload_lineup()
            self.refreshBroadcaster()
            return {"ok": True, "channelNumber": result.record.channel_number}
        except (BroadcasterError, ChannelRuntimeError, ChannelValidationError, OSError, ValueError) as exc:
            return self._error(exc)

    @Slot(int, "QVariantMap", result="QVariantMap")
    def updateChannel(
        self,
        original_channel_number: int,
        editor: dict[str, object],
    ) -> dict[str, object]:
        try:
            self._checkpoint_playback_history()
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

    @Slot(int, result="QVariantMap")
    def deleteChannel(self, channel_number: int) -> dict[str, object]:
        try:
            with self._deletion_playback_guard(int(channel_number)):
                result = self._broadcaster.delete(int(channel_number))
                try:
                    self._reload_lineup(
                        replacement_channel_number=(
                            result.replacement_channel_number
                        )
                    )
                    self.refreshBroadcaster()
                except Exception:
                    # A deletion is not committed unless the replacement lineup
                    # can take over. Put the definition back and restore the prior
                    # Guide before returning the original error to the UI.
                    self._broadcaster.restore_deleted(result)
                    self._reload_lineup()
                    self.refreshBroadcaster()
                    raise
                definition = result.record.definition
                return {
                    "ok": True,
                    "message": (
                        f"Deleted Channel {definition.display_number} - "
                        f"{definition.name}. Its media files were not changed. "
                        f"Recovery backup: {result.backup_path.name}"
                    ),
                    "channelNumber": definition.channel,
                    "backupPath": str(result.backup_path),
                }
        except (
            BroadcasterError,
            ChannelRuntimeError,
            ChannelValidationError,
            GuideError,
            OSError,
            PlaybackError,
            ValueError,
        ) as exc:
            return self._error(exc)


class BroadcasterKeyFilter(CouchKeyFilter):
    """Add management navigation without stealing editor/search text input."""

    def __init__(self, controller, window) -> None:
        super().__init__(controller, window)
        self._library_item: QQuickItem | None = None
        self._broadcaster_item: QQuickItem | None = None
        self._studio_item: QQuickItem | None = None

    def bind_management_overlays(
        self,
        *,
        library_item: QQuickItem,
        broadcaster_item: QQuickItem,
        studio_item: QQuickItem | None = None,
    ) -> None:
        self._library_item = library_item
        self._broadcaster_item = broadcaster_item
        self._studio_item = studio_item

    @staticmethod
    def _invoke_overlay(item: QQuickItem | None, intent: ControlIntent) -> bool:
        if item is None:
            return False
        argument_type='QString' if item.metaObject().indexOfMethod('handleControllerIntent(QString)')>=0 else 'QVariant'
        return bool(
            QMetaObject.invokeMethod(
                item,
                "handleControllerIntent",
                Qt.ConnectionType.DirectConnection,
                Q_ARG(argument_type, intent.value),
            )
        )

    def dispatch_command(self, command: ControlCommand) -> bool:
        # Profile locks and the PIN pad come before any screen handling.
        if self._profile_guard(command):
            return True
        notice = getattr(self._window, '_channelos_portable_notice', None)
        if notice is not None and notice.isVisible():
            self._invoke_overlay(notice, command.intent)
            return True
        if str(self._window.property('screen'))=='planner':
            item = getattr(self._window,'_channelos_planner_item',None)
            destinations = {ControlIntent.HOME:'home',ControlIntent.GUIDE:'guide',ControlIntent.SETTINGS:'settings',ControlIntent.LIBRARY:'library',ControlIntent.CHANNELS:'broadcaster'}
            if item is not None and command.intent in destinations:
                QMetaObject.invokeMethod(item,'requestExit',Qt.ConnectionType.DirectConnection,Q_ARG('QVariant',destinations[command.intent]))
                return True
            if command.intent in {ControlIntent.UP,ControlIntent.DOWN,ControlIntent.LEFT,ControlIntent.RIGHT,ControlIntent.SELECT}:
                focus = QGuiApplication.focusObject()
                name = focus.metaObject().className().lower() if focus else ''
                direct = any(value in name for value in ('combobox','spinbox','listview')) or bool(focus and any(
                    focus.inherits(value) for value in ('QQuickComboBox','QQuickSpinBox','QQuickListView')))
                arrows = {ControlIntent.UP:Qt.Key.Key_Up,ControlIntent.DOWN:Qt.Key.Key_Down,ControlIntent.LEFT:Qt.Key.Key_Left,ControlIntent.RIGHT:Qt.Key.Key_Right}
                modifiers = Qt.KeyboardModifier.NoModifier
                if command.intent is ControlIntent.SELECT and self.open_keyboard_for_focus():
                    return True
                if command.intent is ControlIntent.SELECT:
                    key = Qt.Key.Key_Return if self._text_entry_has_focus() or direct else Qt.Key.Key_Space
                elif direct:
                    key = arrows[command.intent]
                else:
                    key = Qt.Key.Key_Tab
                    if command.intent in {ControlIntent.UP,ControlIntent.LEFT}:
                        modifiers = Qt.KeyboardModifier.ShiftModifier
                QCoreApplication.sendEvent(self._window,QKeyEvent(QEvent.Type.KeyPress,key,modifiers))
                QCoreApplication.sendEvent(self._window,QKeyEvent(QEvent.Type.KeyRelease,key,modifiers))
                return True
        notice = getattr(self._window, '_channelos_portable_notice', None)
        if notice is not None and notice.isVisible():
            self._invoke_overlay(notice, command.intent)
            return True
        if command.intent is ControlIntent.CHANNELS:
            self._window.setProperty("infoVisible", False)
            self._controller.refreshBroadcaster()
            self._window.setProperty("screen", "broadcaster")
            return True
        screen = str(self._window.property("screen"))
        if screen == "library" and command.intent is ControlIntent.PLAY_PAUSE:
            # X/West is the Library's secondary couch action. Playback screens
            # still receive PLAY_PAUSE through the normal couch dispatcher.
            return self._invoke_overlay(self._library_item, command.intent)
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
        if screen == "planner" and command.intent in overlay_intents:
            item = getattr(self._window, '_channelos_planner_item', None)
            return self._invoke_overlay(item, command.intent)
        if screen == "studio" and command.intent in overlay_intents:
            return self._invoke_overlay(self._studio_item, command.intent)
        self._profile_checked = True  # already guarded above
        try:
            return super().dispatch_command(command)
        finally:
            self._profile_checked = None

    @staticmethod
    def _text_entry_has_focus() -> bool:
        focus = QGuiApplication.focusObject()
        if focus is None:
            return False
        class_name = focus.metaObject().className().lower()
        return any(focus.inherits(value) for value in ('QQuickTextInput','QQuickTextEdit','QQuickComboBox','QQuickSpinBox')) or any(
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
        notice = getattr(self._window, '_channelos_portable_notice', None)
        if notice is not None and notice.isVisible() and event.type() == QEvent.Type.KeyPress:
            command = self.command_for_key(event.key())
            if command is not None:
                return self.dispatch_command(command)
        if (
            event.type() == QEvent.Type.KeyPress
            and str(self._window.property("screen"))
            in {"broadcaster", "library", "studio", "planner"}
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

    icon_path = Path(__file__).resolve().parent / "assets" / "ChannelOS.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

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
        logger.error("Main QML failed to create a root window")
        return 7

    window = roots[0]

    if not app.windowIcon().isNull():
        window.setIcon(app.windowIcon())

    portable_notice = _attach_overlay(engine, window, "PortableDriveNotice.qml", z=300)
    operation_notice = _attach_overlay(engine, window, "ChannelOperationOverlay.qml", z=400)
    window._channelos_operation_notice = operation_notice
    window._channelos_portable_notice = portable_notice
    key_filter = BroadcasterKeyFilter(controller, window)
    overlays = {}
    factories = {
        'library': ('LibraryScreen.qml', 85),
        'broadcaster': ('BroadcasterScreen.qml', 90),
        'studio': ('ChannelStudioScreen.qml', 92),
        'planner': ('BroadcastPlannerScreen.qml', 93),
        'settings': ('SettingsScreen.qml', 95),
    }
    def ensure_management_screen():
        screen = str(window.property('screen'))
        if screen in factories and screen not in overlays:
            filename, z = factories[screen]
            try:
                overlays[screen] = _attach_overlay(engine, window, filename, z=z)
            except Exception as exc:
                logger.exception('Management screen could not open')
                window.setProperty('statusMessage', str(exc))
                window.setProperty('screen', 'home')
                return
        for name, item in overlays.items():
            item.setVisible(screen == name)
        key_filter.bind_management_overlays(library_item=overlays.get('library'),
            broadcaster_item=overlays.get('broadcaster'), studio_item=overlays.get('studio'))
        for name in factories:
            setattr(window, '_channelos_' + name + '_item', overlays.get(name))
    from .couch_qt import connect_screen_changed
    connect_screen_changed(window, ensure_management_screen)
    ensure_management_screen()
    window.installEventFilter(key_filter)
    app.aboutToQuit.connect(lambda: window.removeEventFilter(key_filter))
    window.homeMenuActivated.connect(key_filter.activateHomeMenu)
    window.guideLiveActivated.connect(key_filter.activateGuideLive)
    window.pinSubmitted.connect(key_filter.submitPin)
    # Fill and stretch follow the video surface's shape.
    def report_video_size(*_args) -> None:
        controller.setVideoSurfaceSize(video_window.width(), video_window.height())
    video_window.widthChanged.connect(report_video_size)
    video_window.heightChanged.connect(report_video_size)
    window.homeCardActivated.connect(key_filter.activateHomeCard)
    window._channelos_key_filter = key_filter
    window._channelos_video_window = video_window
    window._channelos_component_engine = engine
    window._channelos_controller = controller
    window._channelos_overlay_factory = ensure_management_screen
    app._channelos_window = window

    controller_input = QtControllerInput(
        window,
        key_filter.dispatch_command,
        enabled=lambda: bool(
            controller.settings.get("controllerEnabled", True)
        ),
    )
    window._channelos_controller_input = controller_input
    controller.attach_controller_input(controller_input)

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
    def start_home_gate():
        window._channelos_home_startup_gate = _start_home_video_when_ready(controller, window, video_window)
    if controller._defer_initial_views and hasattr(controller, 'startDataLoading'):
        controller.initialDataReady.connect(start_home_gate)
        QTimer.singleShot(0, controller.startDataLoading)
    else:
        start_home_gate()

    if not owns_application:
        return 0
    return int(app.exec())
