"""Regression checks for background work and history-preserving projections."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from channelos.ad_break_engine import BreakPlan, BreakPlanStore, PlannedSegment
from channelos.portable_copy import capture_setup, plan_copy, prepare_snapshot
from test_performance_operations import controller_fixture
from test_portable_copy import source_setup
from test_portable_qt import controller_factory, wait_for

AT = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def plan(identity='p', *, start=AT, reserved=30, duration=30):
    return BreakPlan(identity, 'opp-' + identity, 'occ-' + identity, 7, start, reserved,
        (PlannedSegment('ad-' + identity, 0, 0, duration),), 'best_fit', 'strict_fit')


def test_history_queries_are_bounded_and_forecasts_never_become_viewed(tmp_path):
    store = BreakPlanStore(tmp_path / 'runtime.db')
    old = plan('old', start=AT-timedelta(days=10))
    payload = json.dumps([asdict(part) for part in old.segments])
    with store.connection:
        store.connection.executemany('INSERT INTO ad_break_plans VALUES(?,?,?,?,?,?,?,?,?,?)',
            [(f'old-{i}',f'old-opp-{i}',f'old-occ-{i}',7,old.scheduled_at.isoformat(),30,
              'best_fit','strict_fit',payload,AT.isoformat()) for i in range(500)])
        store.connection.executemany('INSERT INTO ad_break_history VALUES(?,?,?,?)',
            [(f'old-{i}',0,old.segments[0].asset_id,AT.isoformat()) for i in range(500)])
    future = plan('future', start=AT+timedelta(hours=1))
    store.commit(future)
    store._sync_plan_index(channel_number=7)
    statements = []
    store.connection.set_trace_callback(statements.append)
    assert store.reconcile_completed(7, through=AT) == 0
    assert store.plans_for_channel(7,start=AT,end=AT+timedelta(minutes=1)) == ()
    assert len(statements) <= 12
    assert store.viewer_counts() == {}
    assert store.reconcile_completed(7, through=future.scheduled_at+timedelta(seconds=29)) == 0
    assert store.reconcile_completed(7, through=future.scheduled_at+timedelta(seconds=30)) == 1
    assert store.reconcile_completed(7, through=future.scheduled_at+timedelta(days=1)) == 0
    assert store.viewer_counts() == {}
    assert store.aired_segments(future.plan_id)[0][2] == future.scheduled_at+timedelta(seconds=30)
    assert any('USING INDEX idx_ad_break_plans_occurrence' in row[-1] for row in
        store.connection.execute('EXPLAIN QUERY PLAN SELECT plan_id FROM ad_break_plans WHERE occurrence_id=?', ('occ-future',)))
    store.close()


def test_plan_cache_observes_other_connection_after_its_index_journal_is_consumed(tmp_path):
    path = tmp_path / 'runtime.db'
    first, second = BreakPlanStore(path), BreakPlanStore(path)
    original = plan()
    first.commit(original)
    assert first.load_plan('p') == original
    metadata = json.loads(second.connection.execute('SELECT payload FROM ad_plan_metadata WHERE plan_id=?', ('p',)).fetchone()[0])
    metadata['profile_id'] = 'updated-in-another-connection'
    with second.connection:
        second.connection.execute('UPDATE ad_plan_metadata SET payload=? WHERE plan_id=?', (json.dumps(metadata),'p'))
    second._sync_plan_index(channel_number=7)
    assert not second.connection.execute('SELECT 1 FROM ad_plan_index_changes').fetchall()
    assert first.load_plan('p').profile_id == metadata['profile_id']
    # A restore may delete and recreate the same immutable identity.
    with second.connection:
        second.connection.execute('DELETE FROM ad_break_plans WHERE plan_id=?', ('p',))
    second.commit(original)
    second._sync_plan_index(channel_number=7)
    assert first.load_plan('p') == original
    first.close()
    second.close()


def test_plan_indexes_keep_reserved_and_actual_bounds_and_offsets_distinct(tmp_path):
    store = BreakPlanStore(tmp_path / 'runtime.db')
    expanded = plan('expanded', reserved=90, duration=30)
    reserved = plan('reserved', start=AT+timedelta(minutes=10), reserved=900, duration=30)
    store.commit(expanded)
    store.commit(reserved)
    assert store.active_plan_at(7, AT+timedelta(seconds=10)) == expanded
    assert store.active_plan_at(7, AT+timedelta(seconds=40)) is None
    assert store.plans_for_channel(7,start=AT+timedelta(seconds=40),end=AT+timedelta(seconds=50)) == (expanded,)
    assert store.active_plan_at(7, reserved.scheduled_at+timedelta(seconds=40)) is None
    assert store.plans_for_channel(7,start=reserved.scheduled_at+timedelta(minutes=5),end=reserved.scheduled_at+timedelta(minutes=6)) == (reserved,)
    # Imports can retain equivalent timestamps with a different UTC offset.
    with store.connection:
        store.connection.execute('UPDATE ad_break_plans SET scheduled_at=? WHERE plan_id=?',
            (expanded.scheduled_at.astimezone(timezone(timedelta(hours=-7))).isoformat(),'expanded'))
    assert store.active_plan_at(7, AT+timedelta(seconds=10)).plan_id == 'expanded'
    store.record_aired('expanded',0,'ad-expanded',aired_at=AT+timedelta(seconds=90))
    store._sync_plan_index(channel_number=7)
    with store.connection:
        store.connection.execute('DELETE FROM ad_break_history WHERE plan_id=?', ('expanded',))
    assert store.reconcile_completed(7,through=AT+timedelta(seconds=90)) == 1
    with store.connection:
        store.connection.execute('INSERT INTO ad_retired_plans VALUES(?,?)', ('reserved',AT.isoformat()))
    assert store.plans_for_channel(7,start=reserved.scheduled_at,end=reserved.scheduled_at+timedelta(seconds=30)) == ()
    assert store.reconcile_completed(7,through=AT+timedelta(days=1)) == 0
    store.close()


def test_unchanged_library_and_audio_controls_do_not_scan_cached_artwork(tmp_path, monkeypatch):
    app, controller, _ = controller_fixture(tmp_path)
    def unexpected(*args, **kwargs):
        pytest.fail('An unchanged view or audio control started a full projection/cache scan')
    monkeypatch.setattr(controller, '_build_library_snapshot', unexpected)
    monkeypatch.setattr(controller._artwork_cache, 'stats', unexpected)
    monkeypatch.setattr(controller._artwork_cache, 'prune', unexpected)
    controller.refreshLibrary()
    controller.refreshLibrary()
    assert controller.changeVolume(7)['ok']
    assert controller.toggleMute()['ok']
    controller.stop()


def test_source_preflight_is_cancellable_background_read_only_work(tmp_path, monkeypatch):
    from PySide6.QtCore import QThread, QTimer
    from channelos.scanner import MediaScanner
    app, controller, root = controller_fixture(tmp_path)
    gate, entered = threading.Event(), threading.Event()
    def discover(*args, **kwargs):
        assert QThread.currentThread() is not app.thread()
        entered.set()
        gate.wait(5)
        return [root / 'new.mp4']
    monkeypatch.setattr(MediaScanner, 'discover', discover)
    before = controller._library.revision()
    results, heartbeat = [], []
    controller.mediaPreflightCompleted.connect(results.append)
    try:
        assert controller.startMediaPreflight(str(root))['pending']
        wait_for(app, entered.is_set)
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        app.processEvents()
        assert heartbeat and not results
        assert controller.cancelMediaScan()['ok']
        gate.set()
        wait_for(app, lambda: controller._scan_thread is None)
        assert results[0]['cancelled']
        assert controller._library.revision() == before
    finally:
        gate.set()
        controller.stop()


def test_portable_capture_pins_writer_state_before_worker_conversion(tmp_path):
    library, service, store, runtime = source_setup(tmp_path)
    try:
        target = tmp_path / 'copy'
        reviewed = plan_copy(library,service.paths,target,copy_media=True)
        watch = store.list_on_demand_watch()[0]
        captured = capture_setup(reviewed,library,store.database_path,service.managed_directory)
        store.save_on_demand_watch(watch.asset_id, 45, watch.duration_seconds, now=AT)
        # A later channel edit also cannot leak into the captured copy.
        path = service.paths[0]
        path.write_text(path.read_text().replace('Travel TV','Later TV'))
        snapshot = prepare_snapshot(captured)
        try:
            with sqlite3.connect(snapshot.root / 'ChannelOS-Data' / 'runtime.db') as copied:
                position = copied.execute('SELECT position_seconds FROM on_demand_watch').fetchone()[0]
            assert position == watch.position_seconds
            text = next((snapshot.root / 'ChannelOS-Data' / 'channels').glob('*.yaml')).read_text()
            assert 'Travel TV' in text and 'Later TV' not in text
        finally:
            snapshot.close()
    finally:
        runtime.break_store.close()


def test_production_portable_review_and_conversion_leave_qt_responsive_and_reuse_plan(controller_factory, tmp_path, monkeypatch):
    from PySide6.QtCore import QThread, QTimer
    from channelos import portable_qt
    app, create, _ = controller_factory
    controller = create()
    gate, entered = threading.Event(), threading.Event()
    real_plan, real_prepare = portable_qt.plan_copy, portable_qt.prepare_snapshot
    calls, reviews = [], []
    def slow_plan(*args, **kwargs):
        assert QThread.currentThread() is not app.thread()
        calls.append('plan')
        entered.set(); gate.wait(5)
        return real_plan(*args, **kwargs)
    def slow_prepare(*args, **kwargs):
        assert QThread.currentThread() is not app.thread()
        calls.append('prepare')
        entered.set(); gate.wait(5)
        return real_prepare(*args, **kwargs)
    monkeypatch.setattr(portable_qt,'plan_copy',slow_plan)
    monkeypatch.setattr(portable_qt,'prepare_snapshot',slow_prepare)
    controller.portablePreviewCompleted.connect(reviews.append)
    options = (str(tmp_path / 'drive'),True,False,False)
    try:
        assert controller.beginPortablePreview(*options)['pending']
        wait_for(app, entered.is_set)
        heartbeat=[]
        QTimer.singleShot(0,lambda:heartbeat.append(True)); app.processEvents()
        assert heartbeat and not reviews
        gate.set(); wait_for(app,lambda:controller._portable_thread is None)
        assert reviews[0]['ok'], reviews
        gate.clear(); entered.clear()
        assert controller.startPortableCopy(*options)['ok']
        wait_for(app,entered.is_set)
        QTimer.singleShot(0,lambda:heartbeat.append(True)); app.processEvents()
        assert len(heartbeat)==2 and controller.portableCopy['active']
        gate.set(); wait_for(app,lambda:controller._portable_thread is None)
        assert controller.portableCopy['phase']=='ready',controller.portableCopy
        assert calls == ['plan','prepare']
    finally:
        gate.set()
        controller.stop()


def test_recovery_reuses_healthy_playback_and_adopts_only_changed_channels(tmp_path, monkeypatch):
    from PySide6.QtCore import QThread, QTimer
    from channelos import broadcaster_qt, media_resilience
    from channelos.guide_projection import install_incremental_guide_support
    from channelos.couch_actions import CouchActions
    from channelos.scanner import MediaScanner
    from test_broadcaster import editor
    from test_couch_actions import FakeBackend
    from test_media_resilience import FixedProbe
    module=SimpleNamespace(BroadcasterCouchController=broadcaster_qt.BroadcasterCouchController)
    media_resilience.install_media_resilience_support(module)
    install_incremental_guide_support(module)
    app, controller, root = controller_fixture(tmp_path,module.BroadcasterCouchController)
    other=tmp_path/'other'; other.mkdir(); (other/'healthy.mp4').write_bytes(b'healthy independent file')
    MediaScanner(controller._library,FixedProbe()).scan(other)
    assert controller.createChannel(editor(9,other))['ok']
    backend=FakeBackend()
    controller._actions=CouchActions(controller._service,controller._actions.runtime,backend_factory=lambda:backend)
    controller._publish(controller._actions.tune(9))
    session, station = controller._actions._session, controller._actions.runtime.channels[9]
    events, viewer = list(backend.events), controller._runtime_store.load_viewer(9)
    missing=controller._actions.runtime.channels[7].channel.media[0]
    missing.location.path.unlink()
    media_resilience._mark_location_offline(controller._library,missing.location.path)
    gate, entered = threading.Event(),threading.Event()
    real_usable=media_resilience._usable_channel
    def blocked(*args,**kwargs):
        assert QThread.currentThread() is not app.thread()
        entered.set(); gate.wait(5)
        return real_usable(*args,**kwargs)
    monkeypatch.setattr(media_resilience,'_usable_channel',blocked)
    try:
        assert not controller._reload_resilient_lineup(restore_if_active=True)
        wait_for(app,entered.is_set)
        heartbeat=[]; QTimer.singleShot(0,lambda:heartbeat.append(True));app.processEvents()
        assert heartbeat
        gate.set()
        wait_for(app,lambda:controller._recovery_thread is None and not controller._recovery_adopting)
        assert controller._actions.runtime.channels[9] is station
        assert controller._actions._session is session
        assert backend.events == events
        assert controller._runtime_store.load_viewer(9)==viewer
        assert all(item.location.path != missing.location.path for item in controller._actions.runtime.channels[7].channel.media)
        assert controller.playback['channelNumber']==9
    finally:
        gate.set(); controller.stop()


def test_channel_operation_blocks_editor_typing_and_allows_keyboard_cancel(tmp_path, monkeypatch):
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtQuick import QQuickWindow
    from channelos import broadcaster_qt
    from channelos.channel_jobs import install_channel_operations_support
    module=SimpleNamespace(BroadcasterCouchController=broadcaster_qt.BroadcasterCouchController,
                           BroadcasterKeyFilter=broadcaster_qt.BroadcasterKeyFilter)
    install_channel_operations_support(module)
    app,controller,_=controller_fixture(tmp_path,module.BroadcasterCouchController)
    window=QQuickWindow()
    keyfilter=module.BroadcasterKeyFilter(controller,window)
    cancellations=[]
    monkeypatch.setattr(controller,'cancelChannelMutation',lambda:cancellations.append(True))
    controller._mutation_state(active=True,cancellable=True)
    try:
        assert keyfilter.eventFilter(window,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_A,Qt.KeyboardModifier.NoModifier,'a'))
        override=QKeyEvent(QEvent.Type.ShortcutOverride,Qt.Key.Key_F11,Qt.KeyboardModifier.NoModifier)
        assert keyfilter.eventFilter(window,override) and override.isAccepted()
        assert keyfilter.eventFilter(window,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Escape,Qt.KeyboardModifier.NoModifier))
        assert cancellations==[True]
    finally:
        controller._mutation_state(active=False);controller.stop();window.close()


def test_ad_bin_membership_and_exclusions_preserve_canonical_identity_and_source_order():
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    import channelos
    from test_ad_settings_qml import evaluate
    app=QGuiApplication.instance() or QGuiApplication([])
    engine=QQmlApplicationEngine()
    component=QQmlComponent(engine,QUrl.fromLocalFile(str(Path(channelos.__file__).parent/'qml/AdMediaBin.qml')))
    item=component.create();assert item is not None,component.errors()
    try:
        item.setProperty('mediaLibrary',[
            {'assetId':'same','path':'C:/Ads/Show/ad-10.mp4','title':'Ten','locations':[
                {'path':'C:/Ads/Show/ad-10.mp4'},{'path':'D:/Duplicate/ad.mp4'}]},
            {'assetId':'two','path':'C:/Ads/Show/ad-2.mp4','title':'Two'},
            {'assetId':'outside','path':'E:/Fixed/clip.mp4','title':'Fixed'}])
        item.setProperty('assetIds',['outside'])
        item.setProperty('sources',['c:/ads','D:/Duplicate','C:/Ads/Show'])
        groups=evaluate(engine,item,'groups')
        assert [row['assetId'] for row in groups[0]['media']] == ['two','same']
        assert groups[1]['media'] == groups[2]['media'] == []
        assert groups[3]['media'][0]['assetId']=='outside'
        assert evaluate(engine,item,'(function(){var before=groups; excludedIds=["same","same"]; return before===groups && clipCount===2})()')
        assert evaluate(engine,item,'selection.counts["c:/ads"]')==1
        item.setProperty('sources',['D:/Duplicate','c:/ads'])
        groups=evaluate(engine,item,'groups')
        assert groups[0]['media'][0]['assetId']=='same'
        assert evaluate(engine,item,'clipCount')==2  # Exclusion follows the asset across duplicate paths.
    finally:
        item.deleteLater();app.processEvents()


def test_recovery_discards_stale_library_snapshot_and_retries(tmp_path, monkeypatch):
    from channelos import broadcaster_qt, media_resilience
    from channelos.guide_projection import install_incremental_guide_support
    module=SimpleNamespace(BroadcasterCouchController=broadcaster_qt.BroadcasterCouchController)
    media_resilience.install_media_resilience_support(module)
    install_incremental_guide_support(module)
    app,controller,_=controller_fixture(tmp_path,module.BroadcasterCouchController)
    original=media_resilience._usable_channel
    gate,entered=threading.Event(),threading.Event()
    calls=[]
    def blocked(*args,**kwargs):
        calls.append(True)
        if len(calls)==1:
            entered.set();gate.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(media_resilience,'_usable_channel',blocked)
    removed=controller._actions.runtime.channels[7].channel.media[0]
    try:
        controller._reload_resilient_lineup(restore_if_active=False)
        wait_for(app,entered.is_set)
        media_resilience._mark_location_offline(controller._library,removed.location.path)
        gate.set()
        def reconciled():
            return (controller._recovery_thread is None and not controller._recovery_adopting
                    and all(item.asset.asset_id!=removed.asset.asset_id for item in controller._actions.runtime.channels[7].channel.media))
        wait_for(app,reconciled)
        assert len(calls)>=4  # Both channels were rechecked against the new index.
        assert all(item['assetId']!=removed.asset.asset_id for item in controller.librarySnapshot['items'])
    finally:
        gate.set();controller.stop()


@pytest.mark.parametrize('cached_metadata',[False,True])
def test_scan_never_trusts_a_fingerprint_for_content_changed_during_probe(tmp_path,cached_metadata):
    import hashlib
    from channelos.library import MediaLibrary
    from channelos.probe import MediaProbeResult,NullMediaProbe
    from channelos.scanner import MediaScanner
    source=tmp_path/'source';source.mkdir()
    path=source/'changing.mp4';original=b'original content';path.write_bytes(original)
    library=MediaLibrary(tmp_path/'library.db')
    if cached_metadata:
        MediaScanner(library,NullMediaProbe()).scan(source)
    class ChangingProbe:
        def probe(self,path):
            path.write_bytes(b'new content still arriving from another process')
            return MediaProbeResult(duration_seconds=30,container_format='mp4')
    with pytest.raises(OSError,match='Media changed while'):
        MediaScanner(library,ChangingProbe()).scan(source)
    rows=library.list_cached_media()
    if cached_metadata:
        assert len(rows)==1
        assert rows[0].asset.content_sha256==hashlib.sha256(original).hexdigest()
        assert library.cached_asset_for_unchanged_path(path) is None
    else:
        assert rows==[]
