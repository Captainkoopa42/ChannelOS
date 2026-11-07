"""Staged startup: an early window, the selected station, then remaining data."""
from __future__ import annotations

import copy
import logging
import sys
import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Property, Qt, QThread, QTimer, QUrl, Signal, Slot

# Worker results must reach the GUI thread. Queued explicitly: an automatic
# connection to a Python slot ran `ready` on the setup thread on Windows, which
# then built the main window off the GUI thread and deadlocked.
QUEUED = Qt.ConnectionType.QueuedConnection


class MainThreadRelay(QObject):
    """Run callables on the GUI thread, posted from any thread.

    On Windows CI, signal connections from a worker QThread to these Python
    methods ran on the worker thread even when queued, which built the main
    window off the GUI thread and deadlocked. A thread-safe queue drained by a
    GUI-thread timer cannot do that.
    """

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._pending: queue.SimpleQueue = queue.SimpleQueue()
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    def post(self, function, *args) -> None:
        self._pending.put((function, args))

    def _drain(self) -> None:
        while True:
            try:
                function, args = self._pending.get_nowait()
            except queue.Empty:
                return
            try:
                function(*args)
            except Exception:
                logger.exception("Startup step failed on the GUI thread")
from PySide6.QtGui import QWindow
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

BOOT_VIDEO_LIMIT_SECONDS = 120


class BootSkipFilter(QObject):
    """Any key, click or controller button skips the boot video.

    Installed on the application while the video plays: the native video
    child window may hold input focus, so a QML key handler alone is not enough.
    """

    def __init__(self, skip, parent=None):
        super().__init__(parent)
        self._skip = skip

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin):
            self._skip()
            return True
        return False


def boot_preferences(state_db) -> dict:
    """Boot look from the saved settings, read before anything else opens."""
    from .settings import SettingsStore
    try:
        settings = SettingsStore(Path(state_db).with_name("settings.json")).load()
    except Exception:  # an unreadable settings file must never block boot
        logger.exception("Boot preferences could not be read")
        from .settings import CouchSettings
        settings = CouchSettings()
    setup = Path(state_db).parent
    video = settings.boot_video
    video_path = setup / "boot" / settings.boot_video_file if settings.boot_video_file else None
    if video == "custom" and (video_path is None or not video_path.is_file()):
        video = "static"
    spec = {"name": "channelos", "palette": {}, "wallpaper": "", "wallpaperFit": "fill", "wallpaperOpacity": 100}
    if settings.theme == "chromespace":
        spec["name"] = "chromespace"
    elif settings.theme.startswith("custom-"):
        try:
            from .themes import ThemeStore, derive_palette
            store = ThemeStore(setup / "themes")
            theme = store.get(settings.theme)
            if theme is not None:
                image = store.image_path(theme.wallpaper)
                spec = {"name": theme.theme_id,
                        "palette": derive_palette(theme.roles, panel_opacity=theme.panel_opacity if theme.wallpaper else 100),
                        "wallpaper": QUrl.fromLocalFile(str(image)).toString() if image else "",
                        "wallpaperFit": theme.wallpaper_fit, "wallpaperOpacity": theme.wallpaper_opacity}
        except Exception:
            logger.exception("Boot theme could not be prepared")
    return {"video": video, "videoPath": str(video_path) if video == "custom" else "",
            "sound": settings.boot_video_sound, "loadingStyle": settings.loading_style,
            "bootSound": settings.boot_sound and video != "custom",
            "volume": 0 if settings.muted else settings.volume_percent,
            "reducedMotion": settings.reduced_motion, "themeSpec": spec}


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
            self._startup_state = {'active': self._defer_initial_views, 'message': 'Preparing your channels…',
                                   'progress': 0.5, 'firstReady': not self._defer_initial_views}
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
            relay = self._startup_relay = MainThreadRelay(self)
            direct = Qt.ConnectionType.DirectConnection
            worker.first.connect(lambda value: relay.post(self._startup_first, value), direct)
            worker.metadata.connect(lambda value: relay.post(self._startup_metadata, value), direct)
            worker.completed.connect(lambda value: relay.post(self._startup_remaining, value), direct)
            worker.failed.connect(lambda message: relay.post(self._startup_failed, message), direct)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(self._startup_finished)
            thread.finished.connect(thread.deleteLater)
            self._startup_thread, self._startup_worker = thread, worker
            # Normal priority: during boot the animated loading screen keeps the
            # GUI thread busy, and a low-priority loader was starved for many
            # seconds on CPUs without a GPU (Windows CI).
            thread.start(QThread.Priority.NormalPriority)

        def _publish_startup(self, runtimes):
            service = GuideService(tuple(runtimes), definitions=tuple(record.definition for record in self._broadcaster.records))
            if not self._startup_first_ready:
                self._actions.runtime = TelevisionRuntime(tuple(runtimes), self._runtime_store)
            self._actions.replace_lineup(service, tuple(runtimes))
            self._service = self._actions.service  # profile-filtered
            self._lineup_definitions = {record.channel_number: record.definition for record in self._broadcaster.records}
            self._lineup_library_revision = self._library.revision()
            self.refresh()
            self.refreshBroadcaster()

        @Slot(object)
        def _startup_first(self, prepared):
            runtime = adopt_runtime(prepared, self._runtime_store.database_path)
            self._publish_startup((runtime,) if runtime is not None else ())
            self._startup_first_ready = True
            self._startup_state = {'active': True, 'message': 'Loading the rest of your channels…',
                                   'progress': 0.8, 'firstReady': True}
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
            self._startup_state = {'active': False, 'message': '', 'progress': 1.0, 'firstReady': True}
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
            self._startup_state = {'active': False, 'message': 'Setup recovery: ' + message,
                                   'progress': 1.0, 'firstReady': True}
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


def _finish_boot_sound_when_ready(app) -> None:
    """End the boot jig (on its next "na") once the first channel is ready."""
    sound = getattr(app, "_channelos_boot_sound", None)
    if sound is None:
        return
    window = getattr(app, "_channelos_window", None)
    controller = getattr(window, "_channelos_controller", None) if window is not None else None
    state = getattr(controller, "startupState", None) if controller is not None else None
    if not isinstance(state, dict) or not state.get("active") or state.get("firstReady") is not False:
        sound.finish()
        return

    def changed():
        current = controller.startupState
        if not current.get("active") or current.get("firstReady") is not False:
            controller.startupChanged.disconnect(changed)
            sound.finish()

    controller.startupChanged.connect(changed)


def launch(module, paths, db, state_db, channels_dir, *, windowed=False):
    started = time.perf_counter()
    app = QApplication.instance()
    owns_application = app is None
    app = app or QApplication(sys.argv[:1])
    app.setApplicationName('ChannelOS')
    app.setOrganizationName('ChannelOS')
    module._apply_channelos_control_theme(app)

    preferences = boot_preferences(state_db)

    class Bootstrap(QObject):
        changed = Signal()
        def __init__(self):
            super().__init__()
            self.text = 'Opening your ChannelOS setup…'
            self.can_close = False
            self.cancel = threading.Event()
            self.result = 0
            self.amount = 0.08
            self.video_playing = False
            self.backend = None
            self.pending = None
            self.video_timer = QTimer(self)
            self.video_timer.setInterval(200)
            self.video_timer.timeout.connect(self._poll_video)
            self.video_started = 0.0

        @Property(str, notify=changed)
        def message(self): return self.text

        @Property(bool, notify=changed)
        def canClose(self): return self.can_close

        @Property(float, notify=changed)
        def progress(self): return self.amount

        @Property(bool, notify=changed)
        def videoPlaying(self): return self.video_playing

        @Property('QVariantMap', constant=True)
        def boot(self): return {k: v for k, v in preferences.items() if k != 'themeSpec'}

        @Property('QVariantMap', constant=True)
        def themeSpec(self): return preferences['themeSpec']

        def start_video(self, surface_window):
            if preferences['video'] != 'custom':
                return
            # Show the native child first; libVLC needs a realized, visible target.
            self.skip_filter = BootSkipFilter(self.skipBootVideo, self)
            app.installEventFilter(self.skip_filter)
            self.video_playing = True
            self.video_started = time.monotonic()
            self.changed.emit()
            QTimer.singleShot(150, lambda: self._attach_and_play(surface_window))

        def _attach_and_play(self, surface_window):
            if not self.video_playing:
                return  # skipped before it started
            try:
                from .playback import LibVLCBackend, NativeVideoSurface
                from .couch_qt import _native_video_platform
                backend = LibVLCBackend()
                backend.attach_video_surface(NativeVideoSurface(_native_video_platform(), int(surface_window.winId())))
                backend.set_muted(not preferences['sound'])
                backend.load(Path(preferences['videoPath']))
                backend.play()
            except Exception as exc:  # no libVLC or a broken file: fall back to static
                logger.warning('Boot video could not play: %s', exc)
                self.video_playing = False
                if getattr(self, 'skip_filter', None) is not None:
                    app.removeEventFilter(self.skip_filter)
                    self.skip_filter = None
                self.changed.emit()
                if self.pending is not None:
                    data, self.pending = self.pending, None
                    QTimer.singleShot(0, lambda: self.ready(data))
                return
            self.backend = backend
            self.video_timer.start()

        def _poll_video(self):
            backend = self.backend
            done = time.monotonic() - self.video_started > BOOT_VIDEO_LIMIT_SECONDS
            if not done and backend is not None:
                try:
                    done = bool(backend.has_ended()) or backend.playback_error() is not None
                except Exception:
                    done = True
            if done:
                self.skipBootVideo()

        @Slot()
        def skipBootVideo(self):
            if not self.video_playing:
                return
            self.video_timer.stop()
            self.video_playing = False
            if getattr(self, 'skip_filter', None) is not None:
                app.removeEventFilter(self.skip_filter)
                self.skip_filter = None
            backend, self.backend = self.backend, None
            try:
                if backend is not None:
                    backend.stop()
            except Exception:
                logger.exception('Boot video did not stop cleanly')
            self.changed.emit()
            if self.pending is not None:
                data, self.pending = self.pending, None
                QTimer.singleShot(0, lambda: self.ready(data))

        @Slot()
        def closeRequested(self):
            self.cancel.set()
            self.text = 'Finishing the current setup check…'
            self.changed.emit()

        @Slot(object)
        def ready(self, data):
            if self.cancel.is_set(): return
            self.amount = 0.4
            self.text = 'Tuning in…'
            self.changed.emit()
            if self.video_playing:
                # Hand off to the main window once the boot video ends.
                self.pending = data
                return
            library, store, broadcaster = data
            try:
                service = GuideService((), definitions=tuple(record.definition for record in broadcaster.records))
                module.run_qt(service, TelevisionRuntime((), store), library, broadcaster, store, windowed=windowed)
                _finish_boot_sound_when_ready(app)
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
    # The boot jig plays from the first frame until the first channel is ready.
    boot_sound = None
    if preferences.get("bootSound"):
        from .boot_sound import BootSound
        boot_sound = BootSound(int(preferences.get("volume", 0)), False, parent=app)
        boot_sound.start()
        app._channelos_boot_sound = boot_sound
        app.aboutToQuit.connect(boot_sound.stop)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('startupControl', control)
    boot_video_window = QWindow()
    engine.rootContext().setContextProperty('bootVideoWindow', boot_video_window)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / 'qml' / 'StartupWindow.qml')))
    if not engine.rootObjects(): return 7
    window = engine.rootObjects()[0]
    if windowed: window.showNormal()
    else: window.showFullScreen()
    # Attach libVLC after the native child exists (same rule as the Home video).
    QTimer.singleShot(120, lambda: control.start_video(boot_video_window))
    logger.info('operation=startup.window elapsed_ms=%.3f', (time.perf_counter() - started) * 1000)
    worker = SetupWorker(paths, db, state_db, channels_dir, control.cancel)
    thread = QThread(app)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    # Results reach the GUI thread through MainThreadRelay (see its note).
    relay = MainThreadRelay(app)
    worker.ready.connect(lambda data: relay.post(control.ready, data), Qt.ConnectionType.DirectConnection)
    worker.failed.connect(lambda message: relay.post(control.failed, message), Qt.ConnectionType.DirectConnection)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(lambda: relay.post(control.finished), Qt.ConnectionType.DirectConnection)
    app._channelos_bootstrap = (engine, window, control, worker, thread, boot_video_window, relay)
    thread.start(QThread.Priority.NormalPriority)  # see StartupController.startDataLoading
    if not owns_application: return 0
    result = int(app.exec())
    control.cancel.set()
    thread.quit()
    thread.wait()
    return control.result or result
