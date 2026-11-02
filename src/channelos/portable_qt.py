"""Qt workflow for portable setup copies and explicit profile switching."""
from __future__ import annotations

import logging
import sqlite3
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from .playback import PlaybackError
from .portable import (SetupLock, load_setup,
                       recent_setups, remember_setup)
from .portable_copy import (CopyCancelled, inspect_setup, plan_copy,
                            publish_snapshot, snapshot_setup)

logger = logging.getLogger(__name__)


class _CopyWorker(QObject):
    progress = Signal(object, object, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, snapshot, cancellation):
        super().__init__()
        self.snapshot = snapshot
        self.cancellation = cancellation

    @Slot()
    def run(self):
        try:
            result = publish_snapshot(self.snapshot, on_progress=self.progress.emit,
                                      should_cancel=self.cancellation.is_set)
        except CopyCancelled:
            self.cancelled.emit()
        except Exception as exc:
            logger.exception('Portable setup copy failed')
            self.failed.emit(str(exc))
        else:
            self.completed.emit(result)
        finally:
            self.finished.emit()


def install_portable_support(module):
    base = module.BroadcasterCouchController
    if getattr(base, '_channelos_portable_enabled', False):
        return

    class PortableController(base):
        _channelos_portable_enabled = True
        portableSetupChanged = Signal()
        portableCopyChanged = Signal()

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._portable_thread = None
            self._portable_worker = None
            self._portable_cancellation = None
            self._portable_available = True
            self._portable_pending_watch = None
            self._portable_message = ''
            self._portable_copy = {'active': False, 'phase': 'idle', 'percent': 0, 'message': '', 'destination': ''}
            self._portable_monitor = QTimer(self)
            self._portable_monitor.setInterval(500)
            self._portable_monitor.timeout.connect(self.checkPortableDrive)
            self._portable_monitor.start()

        @Property('QVariantMap', notify=portableSetupChanged)
        def portableSetup(self):
            paths = self._library.portable
            return {'active': paths is not None, 'root': str(paths.root) if paths else '',
                    'name': paths.root.name if paths else 'This PC',
                    'setupId': paths.setup_id if paths else '',
                    'dataDirectory': str(self._library.database_path.parent),
                    'available': self._portable_available, 'message': self._portable_message,
                    'applicationCopyAvailable': bool(getattr(sys, 'frozen', False)),
                    'recent': recent_setups()}

        @Property('QVariantMap', notify=portableCopyChanged)
        def portableCopy(self):
            return self._portable_copy

        def _set_copy(self, **values):
            self._portable_copy = {**self._portable_copy, **values}
            self.portableCopyChanged.emit()

        def _copy_blocker(self):
            if self._portable_thread is not None:
                return 'A portable copy is already running or finishing.'
            if self._scan_thread is not None or self._studio_auto_fill_thread is not None:
                return 'Wait for the current Library scan or Studio Auto Fill to finish before copying.'
            return ''

        @Slot(result='QVariantMap')
        def choosePortableDestination(self):
            path = QFileDialog.getExistingDirectory(None, 'Copy ChannelOS Setup to Drive / Folder')
            return {'ok': bool(path), 'cancelled': not bool(path), 'path': path}

        @Slot(str, bool, bool, bool, result='QVariantMap')
        def previewPortableCopy(self, destination, copy_media, include_app, include_artwork):
            try:
                blocker = self._copy_blocker()
                if blocker:
                    return {'ok': False, 'message': blocker}
                if include_app and not getattr(sys, 'frozen', False):
                    return {'ok': False, 'message': 'This source checkout has no standalone app to copy. A packaged build can include its executable.'}
                plan = plan_copy(self._library, self._broadcaster.paths, destination,
                    copy_media=copy_media, include_artwork=include_artwork,
                    runtime_database=self._runtime_store.database_path,
                    application_directory=Path(sys.executable).parent if include_app else None)
                return {'ok': True, **plan.summary(), 'message': 'Review this copy, then choose Copy Setup.'}
            except (OSError, ValueError, sqlite3.Error) as exc:
                return self._error(exc)

        @Slot(str, bool, bool, bool, result='QVariantMap')
        def startPortableCopy(self, destination, copy_media, include_app, include_artwork):
            review = self.previewPortableCopy(destination, copy_media, include_app, include_artwork)
            if not review.get('ok'):
                return review
            try:
                plan = plan_copy(self._library, self._broadcaster.paths, destination,
                    copy_media=copy_media, include_artwork=include_artwork,
                    runtime_database=self._runtime_store.database_path,
                    application_directory=Path(sys.executable).parent if include_app else None)
                if self._on_demand.active:
                    self._persist_on_demand_state(self._on_demand.state(), force=True)
                snapshot = snapshot_setup(plan, self._library, self._runtime_store.database_path,
                                          self._broadcaster.managed_directory)
            except (OSError, ValueError, sqlite3.Error) as exc:
                return self._error(exc)
            cancellation = threading.Event()
            thread = QThread(self)
            thread.setObjectName('portable-setup-copy')
            worker = _CopyWorker(snapshot, cancellation)
            worker.moveToThread(thread)
            worker.progress.connect(self._portable_progress)
            worker.completed.connect(self._portable_completed)
            worker.failed.connect(self._portable_failed)
            worker.cancelled.connect(self._portable_cancelled)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(self._portable_finished)
            thread.started.connect(worker.run)
            self._portable_thread, self._portable_worker = thread, worker
            self._portable_cancellation = cancellation
            self._set_copy(active=True, phase='copying', percent=0,
                           message='Copying the setup snapshot…', destination='', setupId='')
            thread.start()
            return {'ok': True, 'message': 'Portable copy started. You can keep using the current setup.'}

        @Slot(object, object, str)
        def _portable_progress(self, current, total, message):
            self._set_copy(percent=min(100, int(current * 100 / max(1, total))), message=message)

        @Slot(object)
        def _portable_completed(self, result):
            self._set_copy(active=False, phase='ready', percent=100,
                           destination=result['destination'], setupId=result['setupId'], message=result['message'])
            try:
                remember_setup(load_setup(result['destination']))
            except (OSError, ValueError):
                logger.warning('Could not save the recent portable setup shortcut')
            self.portableSetupChanged.emit()

        @Slot(str)
        def _portable_failed(self, message):
            self._set_copy(active=False, phase='error', message=message)

        @Slot()
        def _portable_cancelled(self):
            self._set_copy(active=False, phase='cancelled', message='Copy cancelled. Your current setup and media were kept.')

        @Slot()
        def _portable_finished(self):
            thread = self._portable_thread
            self._portable_thread = self._portable_worker = self._portable_cancellation = None
            if thread:
                thread.deleteLater()

        @Slot(result='QVariantMap')
        def cancelPortableCopy(self):
            if self._portable_cancellation is None:
                return {'ok': False, 'message': 'No portable copy is running.'}
            self._portable_cancellation.set()
            self._set_copy(phase='cancelling', message='Cancelling the copy…')
            return {'ok': True, 'message': 'Cancelling the copy…'}

        @Slot(result='QVariantMap')
        def chooseExistingPortableSetup(self):
            path = QFileDialog.getExistingDirectory(None, 'Open Existing ChannelOS Setup')
            return self.openPortableSetup(path) if path else {'ok': False, 'cancelled': True, 'message': ''}

        @Slot(str, result='QVariantMap')
        @Slot(str, str, result='QVariantMap')
        def openPortableSetup(self, root, expected_setup_id=''):
            try:
                blocker = self._copy_blocker()
                if blocker:
                    return {'ok': False, 'message': blocker}
                if expected_setup_id and load_setup(root).setup_id != expected_setup_id:
                    return {'ok': False, 'message': 'A different setup is now at this location. Reconnect the intended drive, or use Open Existing Setup to choose it.'}
                summary = inspect_setup(root)
                paths = load_setup(summary['root'])
                if expected_setup_id and paths.setup_id != expected_setup_id:
                    return {'ok': False, 'message': 'A different setup is now at this location. Reconnect the intended drive, or use Open Existing Setup to choose it.'}
                if self._library.portable and paths.root == self._library.portable.root:
                    return {'ok': True, 'message': 'This setup is already active.'}
                with SetupLock(paths):
                    pass
                executable = sys.executable
                arguments = ['--portable-setup', str(paths.root)]
                if not getattr(sys, 'frozen', False):
                    arguments = ['-m', 'channelos.windows_app', *arguments]
                launched = QProcess.startDetached(executable, arguments)
                success = launched[0] if isinstance(launched, tuple) else launched
                if not success:
                    return {'ok': False, 'message': 'The setup is valid, but ChannelOS could not restart. Open the copied executable or try again.'}
                try:
                    remember_setup(paths)
                except OSError:
                    logger.warning('Could not remember the portable setup location')
                QTimer.singleShot(0, QGuiApplication.quit)
                return {'ok': True, 'message': 'Opening the setup from this drive. Changes will be saved there.'}
            except (OSError, ValueError, sqlite3.Error) as exc:
                return self._error(exc)

        @Slot(result=bool)
        def checkPortableDrive(self):
            paths = self._library.portable
            if paths is None:
                return True
            try:
                paths.check_available()
            except OSError as exc:
                if getattr(self, '_portable_available', True):
                    self._portable_available = False
                    self._portable_message = str(exc)
                    # Stop decoders without attempting to persist to the missing drive.
                    try:
                        if self._on_demand.active:
                            self._portable_pending_watch = self._on_demand.state()
                        self._actions.suspend_decoder(persist_history=False)
                    except PlaybackError:
                        logger.warning('Decoder could not be suspended after drive disconnect')
                    finally:
                        self._on_demand.stop()
                    for runtime in self._actions.runtime.channels.values():
                        if runtime.break_store:
                            runtime.break_store.close()
                    for cancellation in (self._scan_cancel_event, self._studio_auto_fill_cancel_event):
                        if cancellation:
                            cancellation.set()
                    self._playback = {'active': False}
                    self._on_demand_view = {'active': False}
                    self.playbackChanged.emit()
                    self.onDemandChanged.emit()
                    self.portableSetupChanged.emit()
                return False
            if not getattr(self, '_portable_available', True):
                try:
                    # Discard SQLite handles from the disconnected mount. Flush
                    # sampled viewing progress through fresh, guarded handles.
                    inspect_setup(paths.root)
                    for runtime in self._actions.runtime.channels.values():
                        if runtime.break_store:
                            runtime.break_store.reopen()
                    self._actions.stop()
                    for runtime in self._actions.runtime.channels.values():
                        if runtime.break_store:
                            runtime.break_store.close()
                    if self._portable_pending_watch is not None:
                        self._persist_on_demand_state(self._portable_pending_watch, force=True)
                        self._portable_pending_watch = None
                    self._broadcaster.refresh()
                    self._reload_lineup()
                    self._portable_available = True
                    self.refreshLibrary()
                    self.refreshBroadcaster()
                    self._portable_message = 'Portable drive reconnected. Your saved setup is available again.'
                except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
                    self._portable_available = False
                    self._portable_message = 'The drive is visible, but the setup could not reopen: ' + str(exc)
                self.portableSetupChanged.emit()
            return getattr(self, '_portable_available', True)

        @Slot()
        def refresh(self):
            if self.checkPortableDrive():
                super().refresh()

        @Slot()
        def refreshPlayback(self):
            if self.checkPortableDrive():
                super().refreshPlayback()

        @Slot()
        def refreshOnDemand(self):
            if self.checkPortableDrive():
                super().refreshOnDemand()

        @Slot()
        def refreshLibrary(self):
            if self.checkPortableDrive():
                super().refreshLibrary()

        @Slot()
        def refreshBroadcaster(self):
            if self.checkPortableDrive():
                super().refreshBroadcaster()

        @Slot()
        def stop(self):
            self._portable_monitor.stop()
            if self._portable_cancellation:
                self._portable_cancellation.set()
            thread = self._portable_thread
            if thread and thread.isRunning():
                thread.quit()
                thread.wait()
            try:
                if self._library.portable:
                    self._library.portable.check_available()
                if not self._portable_available:
                    raise OSError('Drive was disconnected')
                super().stop()
            except OSError:
                for cancellation in (self._scan_cancel_event, self._studio_auto_fill_cancel_event):
                    if cancellation:
                        cancellation.set()
                for background in (self._scan_thread, self._studio_auto_fill_thread):
                    if background and background.isRunning():
                        background.quit()
                        background.wait()
                self._on_demand.stop()
                self._actions.suspend_decoder(persist_history=False)
                logger.warning('Portable drive unavailable during shutdown; its files were not recreated')
            finally:
                for runtime in self._actions.runtime.channels.values():
                    if runtime.break_store:
                        runtime.break_store.close()

    module.BroadcasterCouchController = PortableController
