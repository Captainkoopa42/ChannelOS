"""Staged startup: an early window, the selected station, then remaining data."""
from __future__ import annotations

import copy
import logging
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from .artwork import MediaArtworkCache
from .broadcaster import BroadcasterService
from .guide import GuideService
from .library import MediaLibrary
from .library_view import add_source_information, build_library_view
from .media_resilience import _resolved_runtime
from .performance import operation
from .resolve import MediaResolutionIndex
from .runtime import RuntimeStore, TelevisionRuntime
from .runtime_jobs import adopt_runtime, release_runtime

logger = logging.getLogger(__name__)


class SetupWorker(QObject):
    ready = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, paths, db, state_db, channels_dir, cancellation):
        super().__init__()
        self.paths, self.db, self.state_db, self.channels_dir = paths, db, state_db, channels_dir
        self.cancellation = cancellation

    @Slot()
    def run(self):
        try:
            with operation('startup.setup'):
                library = MediaLibrary(self.db)
                store = RuntimeStore(self.state_db)
                broadcaster = BroadcasterService(self.paths, self.channels_dir, library, runtime_database_path=self.state_db)
                if not self.cancellation.is_set():
                    broadcaster._deferred_startup = True
                    self.ready.emit((library, store, broadcaster))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class DataWorker(QObject):
    first = Signal(object)
    metadata = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, library, broadcaster, store_path, artwork_path, cancellation):
        super().__init__()
        self.library = library
        self.broadcaster = copy.copy(broadcaster)
        self.store_path, self.artwork_path = store_path, artwork_path
        self.cancellation = cancellation

    @Slot()
    def run(self):
        try:
            with operation('startup.data', channels=len(self.broadcaster.records)):
                store = RuntimeStore(self.store_path)
                current, previous = store.get_tuning()
                # Tuning metadata can name a replacement with no saved viewer.
                # Match Continue Watching's current / previous / default order.
                current = current if current is not None and store.load_viewer(current) is not None else None
                previous = previous if previous is not None and store.load_viewer(previous) is not None else None
                priority = {1: 2}
                if previous is not None: priority[previous] = 1
                if current is not None: priority[current] = 0
                records = sorted(self.broadcaster.records, key=lambda record:
                    (priority.get(record.channel_number, 3), record.channel_number))
                prepared, checked, availability = {}, set(), {}
                for record in records:
                    if self.cancellation.is_set(): return
                    runtime = _resolved_runtime(record.definition, self.library, store,
                        persistent_when_complete=True, verify_files=True, availability=availability)
                    checked.add(record.channel_number)
                    if runtime is not None:
                        # Prepare current policy catch-up before handing its SQL ownership to Qt.
                        GuideService((runtime,)).now_next(runtime.channel_number)
                        prepared[record.channel_number] = release_runtime(runtime)
                        self.first.emit(prepared[record.channel_number])
                        break
                else:
                    self.first.emit(None)
                if self.cancellation.is_set(): return
                index = MediaResolutionIndex(self.library)
                snapshot, media = build_library_view(self.library, store, {}, online_media=index.online)
                snapshot = add_source_information(snapshot, self.library, self.broadcaster, indexed_media=index.rows)
                self.broadcaster.studio_media(indexed_media=index.online)
                stats = MediaArtworkCache(self.artwork_path).stats()
                self.metadata.emit({'snapshot': snapshot, 'media': media,
                    'studioCache': self.broadcaster._studio_media_cache, 'cacheStats': stats})
                remaining = []
                for record in records:
                    if self.cancellation.is_set(): return
                    if record.channel_number in checked: continue
                    runtime = _resolved_runtime(record.definition, self.library, store,
                        persistent_when_complete=True, verify_files=True, index=index, availability=availability)
                    if runtime is not None:
                        GuideService((runtime,)).now_next(runtime.channel_number)
                        remaining.append(release_runtime(runtime))
                self.completed.emit(remaining)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


def install_startup_support(module):
    base = module.BroadcasterCouchController
    if getattr(base, '_channelos_staged_startup', False): return

    class StartupController(base):
        _channelos_staged_startup = True
        startupChanged = Signal()
        initialDataReady = Signal()

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._startup_state = {'active': self._defer_initial_views, 'message': 'Preparing your channels…'}
            self._startup_thread = None
            self._startup_cancel = threading.Event()
            self._startup_first_ready = False

        @Property('QVariantMap', notify=startupChanged)
        def startupState(self):
            return self._startup_state

        @Slot()
        def startDataLoading(self):
            if not self._defer_initial_views or self._startup_thread is not None: return
            self._startup_saved_tuning = self._runtime_store.get_tuning()
            worker = DataWorker(self._library, self._broadcaster, self._runtime_store.database_path,
                                self._library.database_path.parent / 'artwork', self._startup_cancel)
            thread = QThread(self)
            thread.setObjectName('ChannelOS startup')
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.first.connect(self._startup_first)
            worker.metadata.connect(self._startup_metadata)
            worker.completed.connect(self._startup_remaining)
            worker.failed.connect(self._startup_failed)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(self._startup_finished)
            thread.finished.connect(thread.deleteLater)
            self._startup_thread, self._startup_worker = thread, worker
            thread.start(QThread.Priority.LowPriority)

        def _publish_startup(self, runtimes):
            service = GuideService(tuple(runtimes), definitions=tuple(record.definition for record in self._broadcaster.records))
            if not self._startup_first_ready:
                self._actions.runtime = TelevisionRuntime(tuple(runtimes), self._runtime_store)
            self._actions.replace_lineup(service, tuple(runtimes))
            self._service = service
            self._lineup_definitions = {record.channel_number: record.definition for record in self._broadcaster.records}
            self._lineup_library_revision = self._library.revision()
            self.refresh()
            self.refreshBroadcaster()

        @Slot(object)
        def _startup_first(self, prepared):
            runtime = adopt_runtime(prepared, self._runtime_store.database_path)
            self._publish_startup((runtime,) if runtime is not None else ())
            self._startup_first_ready = True
            self._startup_state = {'active': True, 'message': 'Loading the rest of your channels…'}
            self.startupChanged.emit()
            self.initialDataReady.emit()

        @Slot(object)
        def _startup_metadata(self, payload):
            self._library_snapshot = payload['snapshot']
            self._library_media = payload['media']
            self._index_library_cards()
            self._library_revision = self._library_projection_revision()
            self._broadcaster._studio_media_cache = payload['studioCache']
            self._artwork_cache_bytes = payload['cacheStats'].size_bytes
            self._artwork_cache_files = payload['cacheStats'].file_count
            self._defer_initial_views = False
            self.libraryChanged.emit()
            self._home_television = self._build_home_television_view()
            self.homeTelevisionChanged.emit()
            self.settingsChanged.emit()

        @Slot(object)
        def _startup_remaining(self, prepared):
            self._startup_to_adopt = list(prepared)
            self._startup_runtimes = dict(self._actions.runtime.channels)
            self._adopt_startup_batch()

        @Slot()
        def _adopt_startup_batch(self):
            deadline = time.perf_counter() + .004
            while self._startup_to_adopt and time.perf_counter() < deadline:
                runtime = adopt_runtime(self._startup_to_adopt.pop(), self._runtime_store.database_path)
                self._startup_runtimes[runtime.channel_number] = runtime
            if self._startup_to_adopt:
                QTimer.singleShot(0, self._adopt_startup_batch)
                return
            self._startup_state = {'active': False, 'message': ''}
            self._publish_startup(tuple(self._startup_runtimes.values()))
            previous = self._startup_saved_tuning[1]
            television = self._actions.runtime
            if television.previous_channel is None and previous in television.channels and previous != television.current_channel:
                television.previous_channel = previous
            self.startupChanged.emit()

        @Slot(str)
        def _startup_failed(self, message):
            logger.error('Startup data could not finish: %s', message)
            self._defer_initial_views = False
            self._startup_state = {'active': False, 'message': 'Setup recovery: ' + message}
            self.startupChanged.emit()
            if not self._startup_first_ready:
                self._startup_first_ready = True
                self.initialDataReady.emit()

        @Slot()
        def _startup_finished(self):
            self._startup_thread = self._startup_worker = None

        @Slot()
        def refreshLibrary(self):
            if self._startup_state.get('active'):
                return
            super().refreshLibrary()

        @Slot(str, result='QVariantMap')
        def startMediaScan(self, source_path):
            if self._startup_state.get('active'):
                return {'ok': False, 'message': 'Your setup is still loading. Try again in a moment.'}
            return super().startMediaScan(source_path)

        @Slot(str, result='QVariantMap')
        def removeLibrarySource(self, source_path):
            if self._startup_state.get('active'):
                return {'ok': False, 'message': 'Your setup is still loading. Try again in a moment.'}
            return super().removeLibrarySource(source_path)

        @Slot('QVariantMap', str, str, result='QVariantMap')
        def startStudioAutoFill(self, editor, start_utc, end_utc):
            if self._startup_state.get('active'):
                return {'ok': False, 'message': 'Your setup is still loading. Try again in a moment.'}
            return super().startStudioAutoFill(editor, start_utc, end_utc)

        @Slot()
        def stop(self):
            self._startup_cancel.set()
            if self._startup_thread is not None:
                self._startup_thread.quit()
                self._startup_thread.wait()
            super().stop()

    module.BroadcasterCouchController = StartupController


def launch(module, paths, db, state_db, channels_dir, *, windowed=False):
    started = time.perf_counter()
    app = QApplication.instance()
    owns_application = app is None
    app = app or QApplication(sys.argv[:1])
    app.setApplicationName('ChannelOS')
    app.setOrganizationName('ChannelOS')
    module._apply_channelos_control_theme(app)

    class Bootstrap(QObject):
        changed = Signal()
        def __init__(self):
            super().__init__()
            self.text = 'Opening your ChannelOS setup…'
            self.can_close = False
            self.cancel = threading.Event()
            self.result = 0

        @Property(str, notify=changed)
        def message(self): return self.text

        @Property(bool, notify=changed)
        def canClose(self): return self.can_close

        @Slot()
        def closeRequested(self):
            self.cancel.set()
            self.text = 'Finishing the current setup check…'
            self.changed.emit()

        @Slot(object)
        def ready(self, data):
            if self.cancel.is_set(): return
            library, store, broadcaster = data
            try:
                service = GuideService((), definitions=tuple(record.definition for record in broadcaster.records))
                module.run_qt(service, TelevisionRuntime((), store), library, broadcaster, store, windowed=windowed)
                self.can_close = True
                self.changed.emit()
                window.close()
            except Exception as exc:
                self.failed(str(exc))

        @Slot(str)
        def failed(self, message):
            self.result = 6
            self.text = 'ChannelOS could not open this setup.\n' + message
            self.can_close = True
            self.changed.emit()

        @Slot()
        def finished(self):
            if self.cancel.is_set():
                self.can_close = True
                window.close()

    control = Bootstrap()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('startupControl', control)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / 'qml' / 'StartupWindow.qml')))
    if not engine.rootObjects(): return 7
    window = engine.rootObjects()[0]
    if windowed: window.showNormal()
    else: window.showFullScreen()
    logger.info('operation=startup.window elapsed_ms=%.3f', (time.perf_counter() - started) * 1000)
    worker = SetupWorker(paths, db, state_db, channels_dir, control.cancel)
    thread = QThread(app)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.ready.connect(control.ready)
    worker.failed.connect(control.failed)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(control.finished)
    app._channelos_bootstrap = (engine, window, control, worker, thread)
    thread.start(QThread.Priority.LowPriority)
    if not owns_application: return 0
    result = int(app.exec())
    control.cancel.set()
    thread.quit()
    thread.wait()
    return control.result or result
