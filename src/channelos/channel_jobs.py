"""Serialized background channel mutations with a GUI checkpoint before commit."""
from __future__ import annotations

import copy
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .broadcaster import BroadcasterError, ChannelConflictError
from .loader import load_channel
from .media_resilience import _resolved_runtime
from .performance import operation
from .runtime import RuntimeStore
from .runtime_jobs import release_runtime
from .runtime_snapshot import channel_snapshot, restore_channel_snapshot


class MutationCancelled(Exception):
    pass


def catalog_revision(catalog):
    path = Path(catalog.database)
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


class ChannelMutationWorker(QObject):
    phase = Signal(str, object)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, service, kind, channel_number, editor, cancel_event):
        super().__init__()
        self.service = copy.copy(service)
        self.service._records = dict(service._records)
        self.service._definition_cache = dict(service._definition_cache)
        self.kind = kind
        self.number = int(channel_number)
        self.editor = dict(editor)
        self.cancel_event = cancel_event
        self.library_revision = service.library.revision()
        self.catalog_revision = catalog_revision(service.ad_catalog)
        self.committed = False
        self.result = None

    def _checkpoint(self, phase):
        if self.cancel_event.is_set():
            if not self.committed:
                raise MutationCancelled()
            return
        accepted = threading.Event()
        self.phase.emit(phase, accepted)
        while not accepted.wait(.05):
            if self.cancel_event.is_set():
                if not self.committed:
                    raise MutationCancelled()
                return
        if self.cancel_event.is_set() and not self.committed:
            raise MutationCancelled()

    def _before_commit(self, definition):
        self._checkpoint('verifying')
        # The GUI has saved actual viewing and suspended the affected decoder.
        # Recheck protected reservations using that final checkpoint.
        if definition is not None:
            self.service._resolve_and_validate(definition)
        if self.service.library.revision() != self.library_revision:
            raise ChannelConflictError('The Library changed during preparation. Retry the channel operation.')
        if catalog_revision(self.service.ad_catalog) != self.catalog_revision:
            raise ChannelConflictError('Ad settings changed during preparation. Retry the channel operation.')
        self.state_backup = channel_snapshot(self.service.runtime_database_path,
                                            self.temporary / 'before.db', self.number)
        self._checkpoint('committing')
        previous = self.service._records.get(self.number)
        if previous is not None and previous.path.read_text(encoding='utf-8') != self.old_text:
            raise ChannelConflictError('The channel changed during preparation. Refresh it before saving.')
        if self.kind == 'create' and self.service._managed_path_for(definition).exists():
            raise ChannelConflictError('The channel file was created during preparation. Refresh before retrying.')

    def _rollback(self):
        if self.result is None or not hasattr(self, 'state_backup'):
            return
        if self.kind == 'delete':
            self.service.restore_deleted(self.result)
        else:
            path = self.result.record.path
            if self.old_text is None:
                path.unlink(missing_ok=True)
            else:
                self.service._atomic_write(path, self.old_text)
            if self.old_assignment is None:
                self.service.ad_catalog.clear_channel_assignment(self.number)
            else:
                self.service.ad_catalog.assign_channel(self.old_assignment)
            restore_channel_snapshot(self.state_backup.database_path, self.service.runtime_database_path, self.number)
            self.service.refresh()

    @Slot()
    def run(self):
        prepared = None
        try:
            with operation('channel.' + self.kind, channel=self.number), tempfile.TemporaryDirectory(prefix='channelos-mutation-') as temporary:
                self.temporary = Path(temporary)
                previous = self.service._records.get(self.number)
                self.old_text = previous.path.read_text(encoding='utf-8') if previous is not None else None
                if previous is not None and load_channel(previous.path) != previous.definition:
                    raise ChannelConflictError('The channel changed on disk. Refresh it before saving.')
                self.old_assignment = self.service.ad_catalog.get_assignment(self.number)
                self.service._commit_callback = self._before_commit
                try:
                    if self.kind == 'create':
                        self.result = self.service.create(self.editor)
                    elif self.kind == 'update':
                        self.result = self.service.update(self.number, self.editor)
                    elif self.kind == 'delete':
                        self.result = self.service.delete(self.number)
                    elif self.kind == 'add_library_item':
                        self.result = self.service.add_library_item(self.number, str(self.editor['assetId']), str(self.editor['path']))
                    else:
                        raise BroadcasterError('Unknown channel operation')
                    self.committed = True
                    unchanged = not hasattr(self, 'state_backup')
                    self._checkpoint('runtime')
                    if self.kind != 'delete' and not unchanged:
                        runtime = _resolved_runtime(self.result.record.definition, self.service.library,
                            RuntimeStore(self.service.runtime_database_path), persistent_when_complete=True, verify_files=True)
                        prepared = release_runtime(runtime)
                except Exception:
                    self._rollback()
                    raise
                accepted = threading.Event()
                publication = {'kind': self.kind, 'number': self.number, 'result': self.result,
                    'records': self.service._records, 'definitionCache': self.service._definition_cache,
                    'prepared': prepared, 'unchanged': unchanged, 'accepted': accepted, 'error': None}
                self.completed.emit(publication)
                while not accepted.wait(.05):
                    if self.cancel_event.is_set():
                        break
                if publication['error']:
                    self._rollback()
                    raise BroadcasterError(publication['error'])
        except MutationCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


def install_channel_operations_support(module):
    """Add asynchronous UI commands while retaining the synchronous service API."""
    from PySide6.QtCore import Property, QThread, Qt
    from .control import ControlIntent
    from .runtime_jobs import adopt_runtime

    base = module.BroadcasterCouchController
    if getattr(base, '_channelos_mutation_jobs', False):
        return

    class ManagedController(base):
        _channelos_mutation_jobs = True
        channelMutationChanged = Signal()
        channelMutationCompleted = Signal('QVariantMap')

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._mutation_thread = None
            self._mutation_worker = None
            self._mutation_cancel = None
            self._mutation_suspended = False
            self._channel_mutation = {'active': False, 'phase': 'idle', 'cancellable': False}

        @Property('QVariantMap', notify=channelMutationChanged)
        def channelMutation(self):
            return self._channel_mutation

        def _mutation_state(self, **values):
            self._channel_mutation = {**self._channel_mutation, **values}
            self.channelMutationChanged.emit()

        @Slot(str, int, 'QVariantMap', result='QVariantMap')
        def startChannelMutation(self, kind, number, editor):
            if getattr(self, 'startupState', {}).get('active'):
                return {'ok': False, 'message': 'Your setup is still loading. Try again in a moment.'}
            if self._mutation_thread is not None:
                return {'ok': False, 'message': 'Wait for the current channel operation to finish.'}
            if kind not in {'create', 'update', 'delete', 'add_library_item'}:
                return {'ok': False, 'message': 'Unknown channel operation'}
            if self.libraryScan.get('active') or self.studioAutoFill.get('active'):
                return {'ok': False, 'message': 'Finish or cancel the current Library scan or Auto Fill first.'}
            try:
                target = int(editor.get('channel', number)) if kind == 'create' else int(number)
                if target <= 0:
                    raise ValueError('Enter a positive channel number')
                cancel = threading.Event()
                worker = ChannelMutationWorker(self._broadcaster, kind, target, editor, cancel)
                thread = QThread(self)
                thread.setObjectName('ChannelOS channel ' + kind)
                worker.moveToThread(thread)
                thread.started.connect(worker.run)
                worker.phase.connect(self._mutation_phase)
                worker.completed.connect(self._mutation_ready)
                worker.failed.connect(self._mutation_failed)
                worker.cancelled.connect(self._mutation_cancelled)
                worker.finished.connect(thread.quit)
                worker.finished.connect(worker.deleteLater)
                thread.finished.connect(self._mutation_finished)
                thread.finished.connect(thread.deleteLater)
                self._mutation_thread, self._mutation_worker, self._mutation_cancel = thread, worker, cancel
                self._mutation_prior = (self._actions.runtime.current_channel,
                    bool(self._playback.get('active')) and not self._on_demand.active,
                    bool(self._playback.get('paused')))
                self._mutation_suspended = False
                self._mutation_state(active=True, phase='preparing', cancellable=True,
                    kind=kind, channelNumber=target, message='Preparing channel changes…')
                thread.start(QThread.Priority.LowPriority)
                return {'ok': True, 'pending': True, 'channelNumber': target, 'message': 'Preparing channel changes…'}
            except (ValueError, OSError) as exc:
                return self._error(exc)

        @Slot(result='QVariantMap')
        def cancelChannelMutation(self):
            if not self._channel_mutation.get('cancellable') or self._mutation_cancel is None:
                return {'ok': False, 'message': 'Finishing the saved channel operation…'}
            self._mutation_cancel.set()
            self._mutation_state(message='Cancelling channel preparation…', cancellable=False)
            return {'ok': True, 'message': 'Cancelling channel preparation…'}

        @Slot(str, object)
        def _mutation_phase(self, phase, accepted):
            try:
                if self._mutation_cancel.is_set() and self._channel_mutation.get('cancellable'):
                    return
                if phase in {'verifying', 'committing'}:
                    self._checkpoint_playback_history()
                if phase == 'verifying' and self._actions.runtime.current_channel == self._channel_mutation['channelNumber']:
                    self._actions.suspend_decoder()
                    self._mutation_suspended = True
                labels = {'verifying': 'Checking the final playback and ad history…',
                          'committing': 'Saving channel changes…', 'runtime': 'Preparing the updated channel…'}
                self._mutation_state(phase=phase, message=labels[phase],
                                     cancellable=phase == 'verifying')
            except Exception:
                self._mutation_cancel.set()
                raise
            finally:
                accepted.set()

        @Slot(object)
        def _mutation_ready(self, payload):
            runtime = None
            try:
                runtime = adopt_runtime(payload['prepared'], self._runtime_store.database_path)
                self._broadcaster._records = payload['records']
                self._broadcaster._definition_cache = payload['definitionCache']
                result = payload['result']
                if not payload['unchanged']:
                    self._reload_lineup(prepared=({} if payload['kind'] == 'delete' else {payload['number']: runtime}),
                        replacement_channel_number=getattr(result, 'replacement_channel_number', None))
                self.refreshBroadcaster()
                message = ('Deleted' if payload['kind'] == 'delete' else 'Saved') + f" Channel {payload['number']:03d}."
                response = {'ok': True, 'kind': payload['kind'], 'channelNumber': payload['number'], 'message': message}
                self._mutation_state(active=False, phase='complete', cancellable=False, message=message)
                self.channelMutationCompleted.emit(response)
            except Exception as exc:
                if runtime is not None and self._actions.runtime.channels.get(runtime.channel_number) is not runtime and runtime.break_store is not None:
                    runtime.break_store.close()
                payload['error'] = str(exc)
                self._mutation_state(phase='recovery', cancellable=False, message='Restoring the previous channel…')
            finally:
                payload['accepted'].set()

        def _restore_mutation_playback(self):
            prior, active, paused = self._mutation_prior
            if self._mutation_suspended and active and prior in self._actions.runtime.channels:
                self._publish(self._actions.restore_after_lineup_change(prior, paused=paused))

        @Slot(str)
        def _mutation_failed(self, message):
            try:
                self._broadcaster.refresh()
                self._reload_lineup()
                self._restore_mutation_playback()
                self.refreshBroadcaster()
            except Exception as recovery:
                message += ' Recovery: ' + str(recovery)
            self._mutation_state(active=False, phase='failed', cancellable=False, message=message)
            self.channelMutationCompleted.emit({'ok': False, 'kind': self._channel_mutation['kind'],
                'channelNumber': self._channel_mutation['channelNumber'], 'message': message})

        @Slot()
        def _mutation_cancelled(self):
            try:
                self._restore_mutation_playback()
            except Exception as exc:
                self._publish_playback_failure(exc)
            self._mutation_state(active=False, phase='cancelled', cancellable=False, message='Channel preparation cancelled.')
            self.channelMutationCompleted.emit({'ok': False, 'cancelled': True,
                'kind': self._channel_mutation['kind'], 'message': 'Channel preparation cancelled.'})

        @Slot()
        def _mutation_finished(self):
            self._mutation_thread = self._mutation_worker = self._mutation_cancel = None

        @Slot()
        def refreshPlayback(self):
            if self._channel_mutation.get('active') and (self._mutation_suspended or self._channel_mutation.get('phase') == 'committing'):
                session = self._actions._session
                if session is not None:
                    session._sample_ad_viewing()
                return
            super().refreshPlayback()

        @Slot()
        def stop(self):
            if self._mutation_cancel is not None:
                self._mutation_cancel.set()
            if self._mutation_thread is not None:
                self._mutation_thread.quit()
                self._mutation_thread.wait()
            super().stop()

    key_base = module.BroadcasterKeyFilter
    class ManagedKeyFilter(key_base):
        def dispatch_command(self, command):
            if getattr(self._controller, 'channelMutation', {}).get('active'):
                if command.intent is ControlIntent.BACK:
                    self._controller.cancelChannelMutation()
                return True
            return super().dispatch_command(command)

    module.BroadcasterCouchController = ManagedController
    module.BroadcasterKeyFilter = ManagedKeyFilter
