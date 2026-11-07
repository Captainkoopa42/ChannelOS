"""Background availability checks and scoped, stale-safe runtime replacement."""
from __future__ import annotations

import copy
import logging
import threading
import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .library_view import add_source_information, build_library_view
from .resolve import MediaResolutionIndex
from .runtime import ChannelRuntimeError
from .runtime_jobs import adopt_runtime, release_runtime

logger = logging.getLogger(__name__)


class RecoveryWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, library, broadcaster, store, previous, roots, cancellation, force_channels=()):
        super().__init__()
        self.library, self.broadcaster, self.store = library, copy.copy(broadcaster), store
        self.previous, self.roots, self.cancellation = previous, roots, cancellation
        self.force_channels=set(force_channels)

    @Slot()
    def run(self):
        from .media_resilience import _usable_channel, _resolved_runtime
        try:
            index = MediaResolutionIndex(self.library)
            availability, root_availability, replacements = {}, {}, {}
            for record in self.broadcaster.records:
                if self.cancellation.is_set():
                    return
                try:
                    resolved = _usable_channel(record.definition, self.library, verify_files=True,
                        index=index, availability=availability, root_availability=root_availability)
                    if resolved == self.previous.get(record.channel_number) and record.channel_number not in self.force_channels:
                        continue
                    runtime = None if resolved is None else _resolved_runtime(record.definition,
                        self.library, self.store, prepared_channel=resolved, index=index,
                        persistent_when_complete=record.definition.programming.mode=='planner')
                except ChannelRuntimeError:
                    logger.exception('Channel %s has no usable recovery timeline', record.channel_number)
                    runtime = None
                replacements[record.channel_number] = release_runtime(runtime)
            if self.cancellation.is_set():
                return
            snapshot, media = build_library_view(self.library, self.store, {}, online_media=index.online)
            snapshot = add_source_information(snapshot, self.library, self.broadcaster, indexed_media=index.rows)
            self.completed.emit({'prepared': replacements, 'snapshot': snapshot, 'media': media,
                'returned': {root for root in self.roots if root.exists()}})
        except Exception as exc:
            logger.exception('Media recovery preparation failed')
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class RecoveryJobs:
    """Lifecycle mixin used by the Qt resilience adapter."""

    def _initialize_recovery_jobs(self):
        self._recovery_thread = self._recovery_worker = None
        self._recovery_cancel = threading.Event()
        self._recovery_result = None
        self._recovery_retry = False
        self._recovery_restore = False
        self._recovery_adopting = False
        self._recovery_stopping = False
        self._recovery_force_channels=set()
        self._recovery_inflight_forces=set()

    def _recovery_revision(self):
        return self._library.revision(), tuple((record.channel_number, record.definition)
                                               for record in self._broadcaster.records)

    def _request_media_recovery(self, *, restore_if_active):
        if self._recovery_stopping:
            return
        self._recovery_restore |= restore_if_active
        unavailable=set(self._temporarily_unavailable_roots)
        self._recovery_force_channels.update(number for number,runtime in self._actions.runtime.channels.items()
            if getattr(runtime.timeline,'actual_source_roots',frozenset()) & unavailable)
        if self._recovery_thread is not None or self._recovery_adopting:
            self._recovery_retry |= (self._recovery_input_revision != self._recovery_revision()
                or bool(self._recovery_force_channels-self._recovery_inflight_forces))
            return
        if getattr(self, 'startupState', {}).get('active') or getattr(self, 'channelMutation', {}).get('active'):
            QTimer.singleShot(200, lambda: self._request_media_recovery(restore_if_active=restore_if_active))
            return
        self._recovery_input_revision = self._recovery_revision()
        self._recovery_prior = (self._actions.runtime.current_channel, bool(self._actions.paused))
        self._recovery_cancel = threading.Event()
        self._recovery_result = None
        self._recovery_inflight_forces=set(self._recovery_force_channels)
        self._recovery_force_channels.clear()
        worker = RecoveryWorker(self._library, self._broadcaster, self._runtime_store,
            {number: runtime.channel for number, runtime in self._actions.runtime.channels.items()},
            set(self._temporarily_unavailable_roots), self._recovery_cancel,self._recovery_inflight_forces)
        thread = QThread(self)
        thread.setObjectName('ChannelOS media recovery')
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._recovery_ready)
        worker.failed.connect(self._recovery_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._recovery_finished)
        self._recovery_thread, self._recovery_worker = thread, worker
        thread.start(QThread.Priority.LowPriority)

    @Slot(object)
    def _recovery_ready(self, result):
        self._recovery_result = result

    @Slot(str)
    def _recovery_failed(self, message):
        logger.warning('Media recovery remains pending: %s', message)

    @Slot()
    def _recovery_finished(self):
        thread = self._recovery_thread
        self._recovery_thread = self._recovery_worker = None
        if thread is not None:
            thread.deleteLater()
        result = self._recovery_result
        self._recovery_result = None
        if self._recovery_stopping:
            return
        if result is not None and self._recovery_input_revision == self._recovery_revision():
            self._recovery_payload = result
            self._recovery_to_adopt = list(result['prepared'].items())
            self._recovery_adopted = {}
            self._recovery_adopting = True
            self._adopt_recovery_batch()
        else:
            self._recovery_retry |= result is not None
            self._finish_recovery_adoption()

    @Slot()
    def _adopt_recovery_batch(self):
        if not self._recovery_adopting:
            return
        try:
            deadline = time.perf_counter() + .004
            while self._recovery_to_adopt and time.perf_counter() < deadline:
                number, prepared = self._recovery_to_adopt.pop()
                self._recovery_adopted[number] = adopt_runtime(prepared, self._runtime_store.database_path)
            if self._recovery_to_adopt:
                QTimer.singleShot(0, self._adopt_recovery_batch)
                return
            if self._recovery_stopping or self._recovery_input_revision != self._recovery_revision():
                for runtime in self._recovery_adopted.values():
                    if runtime is not None and runtime.break_store is not None:
                        runtime.break_store.close()
                self._recovery_retry = not self._recovery_stopping
                self._finish_recovery_adoption()
                return
            prior, paused = self._recovery_prior
            current = self._actions.runtime.current_channel
            restore = self._recovery_restore and current == prior and not self._on_demand.active
            # The controller's delta operation retains every unaffected runtime,
            # decoder session, Guide cache row, and Viewer Clock.
            self._reload_lineup(prepared=self._recovery_adopted)
            payload = self._recovery_payload
            for item in payload['snapshot']['items']:
                asset_id = item['assetId']
                item['artworkUrl'] = self._artwork_urls.get(asset_id, '')
                previous = self._library_cards.get(asset_id)
                if previous:
                    for field in ('continueWatching', 'watchPositionSeconds', 'watchProgress', 'lastWatchedAt'):
                        item[field] = previous[field]
            self._library_snapshot, self._library_media = payload['snapshot'], payload['media']
            self._index_library_cards()
            self._library_revision = self._library_projection_revision()
            self.libraryChanged.emit()
            self._temporarily_unavailable_roots.difference_update(payload['returned'])
            if restore and not self._playback.get('active') and self._surface_ready:
                channels = self._actions.runtime.channels
                target = prior if prior in channels else next(iter(sorted(channels)), None)
                if target is not None:
                    self._publish(self._actions.restore_after_lineup_change(target, paused=paused if target == prior else False))
            self._recovery_restore = False
        except Exception as exc:
            logger.exception('Could not adopt prepared media recovery')
            self._recovery_to_adopt.clear()
            current = self._actions.runtime.channels
            for number, runtime in self._recovery_adopted.items():
                if runtime is not None and runtime is not current.get(number) and runtime.break_store is not None:
                    runtime.break_store.close()
            self._publish_temporary_unavailable(f'Media recovery is pending: {exc}')
        finally:
            if not self._recovery_to_adopt:
                self._finish_recovery_adoption()

    def _finish_recovery_adoption(self):
        self._recovery_adopting = False
        if self._recovery_retry and not self._recovery_stopping:
            self._recovery_retry = False
            QTimer.singleShot(0, lambda: self._request_media_recovery(restore_if_active=self._recovery_restore))

    @Slot()
    def stop(self):
        self._recovery_stopping = True
        self._recovery_cancel.set()
        if self._recovery_thread is not None:
            self._recovery_thread.quit()
            self._recovery_thread.wait()
        if self._recovery_adopting:
            for number, runtime in self._recovery_adopted.items():
                if runtime is not None and runtime is not self._actions.runtime.channels.get(number) and runtime.break_store is not None:
                    runtime.break_store.close()
            self._recovery_adopting = False
        super().stop()
