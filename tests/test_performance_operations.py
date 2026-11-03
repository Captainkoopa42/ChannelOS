"""Behavior and work bounds for large ChannelOS management operations."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from channelos.ad_break_engine import BreakPlanStore
from channelos.ad_catalog import AdCollection, BreakProfile, ChannelAdAssignment
from channelos.broadcaster import BroadcasterService
from channelos.broadcaster_qt import BroadcasterCouchController
from channelos.couch import _open_runtimes
from channelos.couch_actions import CouchActions
from channelos.guide import GuideService
from channelos.runtime import RuntimeStore, TelevisionRuntime
from channelos.runtime_snapshot import channel_snapshot
from channelos.studio_publication import prepare_publication
from test_broadcaster import make_library, editor
from test_couch_actions import FakeBackend


def controller_fixture(tmp_path, controller_type=BroadcasterCouchController):
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    library, root = make_library(tmp_path)
    broadcaster = BroadcasterService((), tmp_path / 'channels', library)
    broadcaster.create(editor(7, root))
    broadcaster.create(editor(8, root))
    store = RuntimeStore(tmp_path / 'runtime.db')
    runtimes = _open_runtimes(broadcaster.paths, library, store)
    guide = GuideService(runtimes)
    controller = controller_type(guide, TelevisionRuntime(runtimes, store), library, broadcaster, store)
    return app, controller, root


def test_channels_open_reuses_definitions_and_does_not_read_library_cards(tmp_path, monkeypatch):
    app, controller, root = controller_fixture(tmp_path)
    import channelos.broadcaster as module
    def unexpected(*args, **kwargs):
        pytest.fail('Opening an unchanged channel list rebuilt unrelated data')
    monkeypatch.setattr(module, 'load_channel', unexpected)
    monkeypatch.setattr(controller, 'refreshLibrary', unexpected)
    monkeypatch.setattr(controller._library, 'list_online_media', unexpected)
    controller.refreshBroadcaster()
    controller.refreshBroadcaster()
    assert [row['channelNumber'] for row in controller.broadcasterSnapshot['channels']] == [7, 8]
    controller.stop()


def test_catalog_snapshot_uses_one_connection_for_all_rows(tmp_path, monkeypatch):
    library, root = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / 'channels', library)
    catalog = service.ad_catalog
    asset_id = library.list_online_media()[0].asset.asset_id
    for index in range(12):
        catalog.save_collection(AdCollection(f'c{index}', f'Collection {index}', (asset_id,)))
        catalog.save_profile(BreakProfile(f'p{index}', f'Profile {index}', {'enabled': False}))
        catalog.assign_channel(ChannelAdAssignment(index + 1, f'c{index}', f'p{index}'))
    real_connect = catalog._connect
    connections, queries = [], []
    def counted():
        db = real_connect()
        connections.append(db)
        db.set_trace_callback(queries.append)
        return db
    monkeypatch.setattr(catalog, '_connect', counted)
    snapshot = catalog.read_snapshot()
    assert len(connections) == 1
    assert sum(sql.lstrip().startswith('SELECT') for sql in queries) == 3
    assert len(snapshot['assignments']) == len(snapshot['profiles']) == len(snapshot['collections']) == 12


def test_edit_and_delete_other_station_keep_active_decoder_and_clock(tmp_path):
    app, controller, root = controller_fixture(tmp_path)
    backend = FakeBackend()
    controller._actions = CouchActions(controller._service, controller._actions.runtime, backend_factory=lambda: backend)
    controller._publish(controller._actions.tune(7))
    controller._publish(controller._actions.pause())
    station = controller._actions.runtime.channels[7]
    session = controller._actions._session
    before = tuple(backend.events)
    assert controller.updateChannel(8, editor(8, root, name='Changed 8'))['ok']
    assert controller.deleteChannel(8)['ok']
    assert controller._actions.runtime.channels[7] is station
    assert controller._actions._session is session
    assert controller._actions.paused
    assert tuple(backend.events) == before
    assert controller._actions.runtime.current_channel == 7
    controller.stop()


def test_channel_snapshot_excludes_other_station_and_archives(tmp_path):
    source = RuntimeStore(tmp_path / 'live.db')
    source.ensure_channel(7, 'seven')
    source.ensure_channel(8, 'eight')
    source.delete_channel(8)
    snapshot = channel_snapshot(source.database_path, tmp_path / 'snapshot.db', 7)
    assert snapshot.load_channel(7).schedule_signature == 'seven'
    assert snapshot.load_channel(8) is None
    with snapshot.connect() as db:
        assert db.execute('SELECT count(*) FROM deleted_channel_archives').fetchone()[0] == 0
    with source.connect() as db:
        assert db.execute('SELECT count(*) FROM deleted_channel_archives').fetchone()[0] == 1


def test_archival_is_bounded_sql_and_retains_every_clock_row(tmp_path):
    store = RuntimeStore(tmp_path / 'runtime.db')
    breaks = BreakPlanStore(store.database_path)
    stamp = '2026-11-03T12:00:00+00:00'
    with breaks.connection:
        breaks.connection.executemany('''INSERT INTO ad_program_clock(
            occurrence_id,channel_number,content_start,content_end,broadcast_start,broadcast_end,schedule_signature)
            VALUES(?,?,?,?,?,?,?)''', [(str(i), 7, stamp, stamp, stamp, stamp, 'test') for i in range(1000)])
    breaks.close()
    queries = []
    connect = store.connect
    def counted():
        db = connect()
        db.set_trace_callback(queries.append)
        return db
    store.connect = counted
    identity = store.delete_channel(7)
    assert sum(sql.lstrip().startswith('DELETE') for sql in queries) < 20
    with store.connect() as db:
        payload = json.loads(db.execute('SELECT payload FROM deleted_channel_archives WHERE archive_id=?', (identity,)).fetchone()[0])
        assert len(payload['ad_program_clock']) == 1000
        assert db.execute('SELECT count(*) FROM ad_program_clock').fetchone()[0] == 0
    store.restore_deleted_channel(identity)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM ad_program_clock').fetchone()[0] == 1000


def test_prepared_studio_publication_preserves_fixed_starts_and_checks_overlap():
    start = datetime(2026, 11, 3, tzinfo=timezone.utc)
    media = [{'assetId': 'program', 'title': 'Show', 'path': '/owned/show.mp4',
              'sourceRoot': '/owned', 'durationSeconds': 60}]
    editor = {'calendarBlocks': [{'assetId': 'program', 'startUtc': start.isoformat()}]}
    result = {'ok': True, 'blocks': [{'assetId': 'program', 'startUtc': (start + timedelta(minutes=2)).isoformat()}]}
    prepared = prepare_publication(result, editor, media)
    assert [row['startUtc'] for row in prepared['preparedRows']] == ['2026-11-03T00:00:00.000Z', '2026-11-03T00:02:00.000Z']
    assert [row['modelIndex'] for day in prepared['preparedDays'].values() for row in day] == [0, 1]
    result['blocks'][0]['startUtc'] = (start + timedelta(seconds=30)).isoformat()
    with pytest.raises(ValueError, match='overlap'):
        prepare_publication(result, editor, media)


def managed_controller_type():
    from types import SimpleNamespace
    from channelos.broadcaster_qt import BroadcasterKeyFilter
    from channelos.channel_jobs import install_channel_operations_support
    module = SimpleNamespace(BroadcasterCouchController=BroadcasterCouchController, BroadcasterKeyFilter=BroadcasterKeyFilter)
    install_channel_operations_support(module)
    return module.BroadcasterCouchController


def finish_job(app, controller, timeout=20):
    import time
    deadline = time.monotonic() + timeout
    while controller._mutation_thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    app.processEvents()
    assert controller._mutation_thread is None
    assert not controller.channelMutation['active']


def test_async_mutation_handoff_retains_unaffected_playback(tmp_path):
    app, controller, root = controller_fixture(tmp_path, managed_controller_type())
    backend = FakeBackend()
    controller._actions = CouchActions(controller._service, controller._actions.runtime, backend_factory=lambda: backend)
    controller._publish(controller._actions.tune(7))
    controller._publish(controller._actions.pause())
    station = controller._actions.runtime.channels[7]
    before = tuple(backend.events)
    results = []
    controller.channelMutationCompleted.connect(results.append)
    for kind, number, data in [('create', 9, editor(9, root)), ('update', 8, editor(8, root, name='Updated')), ('delete', 8, {})]:
        assert controller.startChannelMutation(kind, number, data)['pending']
        finish_job(app, controller)
        assert results[-1]['ok'], results[-1]
        assert controller._actions.runtime.channels[7] is station
        assert tuple(backend.events) == before
        assert controller._actions.paused
    assert controller._actions.runtime.channels.keys() == {7, 9}
    controller.stop()


def test_cancelled_preparation_keeps_ui_running_and_writes_no_channel(tmp_path, monkeypatch):
    import threading
    import time
    from PySide6.QtCore import QTimer
    app, controller, root = controller_fixture(tmp_path, managed_controller_type())
    entered, release = threading.Event(), threading.Event()
    original = BroadcasterService._resolve_and_validate
    def delayed(service, definition):
        entered.set()
        assert release.wait(10)
        return original(service, definition)
    monkeypatch.setattr(BroadcasterService, '_resolve_and_validate', delayed)
    ticks = []
    timer = QTimer()
    timer.setInterval(2)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    assert controller.startChannelMutation('create', 9, editor(9, root))['ok']
    deadline = time.monotonic() + 5
    while (not entered.is_set() or len(ticks) < 4) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert entered.is_set() and len(ticks) >= 4
    assert controller.cancelChannelMutation()['ok']
    release.set()
    finish_job(app, controller)
    timer.stop()
    assert controller.channelMutation['phase'] == 'cancelled'
    assert 9 not in controller._broadcaster.channel_numbers
    assert not (controller._broadcaster.managed_directory / 'channel-0009.yaml').exists()
    controller.stop()


def incremental_controller_type():
    from types import SimpleNamespace
    from channelos.guide_projection import install_incremental_guide_support
    module = SimpleNamespace(BroadcasterCouchController=managed_controller_type())
    install_incremental_guide_support(module)
    return module.BroadcasterCouchController


def test_guide_is_lazy_and_discards_replaced_runtime_rows(tmp_path, monkeypatch):
    import time
    original = GuideService.iter_programs
    projected = []
    def counted(runtime, *args):
        projected.append(runtime)
        yield from original(runtime, *args)
    monkeypatch.setattr(GuideService, 'iter_programs', staticmethod(counted))
    app, controller, root = controller_fixture(tmp_path, incremental_controller_type())
    assert not projected, 'Home must not project a full three-hour lineup'
    rows = controller.snapshot['rows']
    index = next(i for i, row in enumerate(rows) if row['channelNumber'] == 7)
    controller.requestGuideRows(index, index)
    deadline = time.monotonic() + 5
    while controller.snapshot['rows'][index].get('isPending') and time.monotonic() < deadline:
        app.processEvents()
    assert not controller.snapshot['rows'][index].get('isPending')
    assert {runtime.channel_number for runtime in projected} == {7}
    old = projected[-1]
    assert controller.updateChannel(7, editor(7, root, name='New seven'))['ok']
    assert controller.snapshot['rows'][index]['isPending']
    deadline = time.monotonic() + 5
    while controller.snapshot['rows'][index].get('isPending') and time.monotonic() < deadline:
        app.processEvents()
    assert projected[-1] is not old
    assert controller.snapshot['rows'][index]['channelName'] == 'New seven'
    controller.requestGuideRows(-1, -1)
    controller.stop()


def test_startup_prepares_saved_station_before_library_and_hands_off_sql(tmp_path):
    import threading
    from channelos.startup_qt import DataWorker
    from channelos.runtime_jobs import adopt_runtime
    library, root = make_library(tmp_path)
    service = BroadcasterService((), tmp_path / 'channels', library)
    service.create(editor(7, root))
    service.create(editor(8, root))
    store = RuntimeStore(service.runtime_database_path)
    runtimes = _open_runtimes(service.paths, library, store)
    television = TelevisionRuntime(runtimes, store)
    television.tune(7)
    television.tune(8)
    for runtime in runtimes:
        if runtime.break_store:
            runtime.break_store.close()
    worker = DataWorker(library, service, store.database_path, tmp_path / 'artwork', threading.Event())
    events, errors = [], []
    worker.first.connect(lambda value: events.append(('first', value)))
    worker.metadata.connect(lambda value: events.append(('metadata', value)))
    worker.completed.connect(lambda value: events.append(('rest', value)))
    worker.failed.connect(errors.append)
    thread = threading.Thread(target=worker.run)
    thread.start()
    thread.join(20)
    # Signals from the foreign thread are delivered by Qt's event loop.
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    app.processEvents()
    assert not thread.is_alive() and not errors
    assert [event[0] for event in events] == ['first', 'metadata', 'rest']
    assert events[0][1].runtime.channel_number == 8
    assert [item.runtime.channel_number for item in events[2][1]] == [7]
    for prepared in [events[0][1], *events[2][1]]:
        runtime = adopt_runtime(prepared, store.database_path)
        GuideService((runtime,)).now_next(runtime.channel_number)
        if runtime.break_store:
            runtime.break_store.close()


def test_failed_async_publication_rolls_back_definition_and_target_state(tmp_path, monkeypatch):
    app, controller, root = controller_fixture(tmp_path, managed_controller_type())
    previous = controller._broadcaster._records[8]
    text = previous.path.read_text()
    original = controller._reload_lineup
    failed = False
    def reject_once(**kwargs):
        nonlocal failed
        if kwargs.get('prepared') is not None and not failed:
            failed = True
            raise RuntimeError('Publication interrupted for test')
        return original(**kwargs)
    monkeypatch.setattr(controller, '_reload_lineup', reject_once)
    responses = []
    controller.channelMutationCompleted.connect(responses.append)
    assert controller.startChannelMutation('update', 8, editor(8, root, name='Should roll back'))['pending']
    finish_job(app, controller)
    assert responses and not responses[-1]['ok']
    assert previous.path.read_text() == text
    assert controller._broadcaster._records[8].definition.name == previous.definition.name
    assert controller._actions.runtime.channels[8].channel.definition.name == previous.definition.name
    controller.stop()
