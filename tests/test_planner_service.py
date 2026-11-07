from dataclasses import replace
from datetime import datetime, timedelta

from channelos.broadcaster import BroadcasterService
from channelos.broadcast_planner.service import PlannerService
from channelos.runtime import ChannelRuntime, RuntimeStore
from test_planner_runtime import planner_channel, START


def dump(store):
    with store.connect() as connection:
        tables=[row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table:[tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}


def test_live_draft_preview_reads_saved_progress_and_cannot_write_runtime(tmp_path,monkeypatch):
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    service=BroadcasterService([],tmp_path/'channels',channel.library,runtime_database_path=store.database_path)
    raw={'channel':7,'name':'Checkpoint preview','sources':[str(s.path) for s in channel.definition.sources],
         'mode':'planner','planner':channel.definition.programming.planner.to_mapping()}
    service.create(raw)
    at=START+timedelta(hours=12,minutes=30)
    ChannelRuntime.open(replace(channel,definition=service._records[7].definition,media=channel.media[1:]),store,now=at)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            return at if tz else at.replace(tzinfo=None)
    monkeypatch.setattr('channelos.broadcast_planner.service.datetime',FrozenDateTime)
    before=dump(store)
    planner=PlannerService(service)
    editor=planner.load(7)['editor']
    result=planner.preview(editor,view_start='2026-06-01',view_days=1)
    assert result['confidence']=='Exact'
    assert result['tracks'][0]['first_airing']=='2026-06-01T13:00:00+00:00'
    assert result['media_ends']=='2026-06-02T13:00:00+00:00'
    assert any(row['kind']=='offair' for row in result['segments'])
    assert dump(store)==before


def test_forecast_resolves_ads_from_cached_metadata_without_media_probes(tmp_path,monkeypatch):
    from pathlib import Path
    from channelos.probe import MediaProbeResult
    import hashlib
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    service=BroadcasterService([],tmp_path/'channels',channel.library,runtime_database_path=store.database_path)
    ads=tmp_path/'ads'
    ads.mkdir()
    path=ads/'commercial.mp4'
    path.write_bytes(b'owned-ad')
    channel.library.upsert_file(path,ads,content_sha256=hashlib.sha256(b'owned-ad').hexdigest(),probe=MediaProbeResult(duration_seconds=15,container_format='mp4'))
    ad=channel.library.list_cached_media(ads)[0]
    planner=PlannerService(service)
    editor=planner.load(0)['editor']
    rules=channel.definition.programming.planner.to_mapping()
    rules['groups'][0]['asset_ids']=[channel.media[0].asset.asset_id]
    rules['windows'][0].update(start='12:00',end='14:00',bracket_minutes=120)
    editor.update(name='Metadata preview',planner=rules,adBreaksEnabled=True,adSetupMode='after_show',adSources=[str(ads)],adAssetIds=[ad.asset.asset_id])
    original=Path.is_file
    def checked(path):
        assert path.suffix!='.mp4','A forecast probed a media file'
        return original(path)
    monkeypatch.setattr(Path,'is_file',checked)
    result=planner.preview(editor,view_start='2026-06-01',view_days=1)
    assert result['confidence']=='Exact'
    assert any(row['kind']=='advertisement' for row in result['segments'])


def test_pending_revision_protects_old_sources_and_recovery_rechecks_them(tmp_path,monkeypatch):
    import threading
    from channelos.resolve import resolve_channel
    from channelos.recovery_jobs import RecoveryWorker
    from channelos.media_resilience import _mark_location_offline
    from test_runtime import build_resolved_channel
    channel=planner_channel(tmp_path)
    other=build_resolved_channel(tmp_path,[3600],channel_number=12)
    clock=[START+timedelta(hours=12,minutes=30)]
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            return clock[0] if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr('channelos.broadcaster.datetime',FrozenDateTime)
    monkeypatch.setattr('channelos.runtime.utc_now',lambda:clock[0])
    store=RuntimeStore(tmp_path/'runtime.db')
    service=BroadcasterService([],tmp_path/'channels',channel.library,runtime_database_path=store.database_path)
    base={'channel':7,'name':'Scoped recovery','mode':'planner'}
    old=service.create({**base,'sources':[str(s.path) for s in channel.definition.sources],'planner':channel.definition.programming.planner.to_mapping()}).record.definition
    ChannelRuntime.open(resolve_channel(old,channel.library),store,now=clock[0])
    rules=channel.definition.programming.planner.to_mapping()
    rules['groups'][0]['asset_ids']=[other.media[0].asset.asset_id]
    rules['edit_effect']='safe_future'
    new=service.update(7,{**base,'sources':[str(s.path) for s in other.definition.sources],'planner':rules}).record.definition
    pending=ChannelRuntime.open(resolve_channel(new,channel.library),store,now=clock[0])
    old_root=channel.definition.sources[0].path
    assert service.source_dependencies(old_root)[0]['channelNumber']==7
    channel.media[0].location.path.unlink()
    _mark_location_offline(channel.library,channel.media[0].location.path)
    clock[0]=START+timedelta(hours=12,minutes=40)
    worker=RecoveryWorker(channel.library,service,store,{7:pending.channel},set(),threading.Event(),{7})
    publications=[]
    failures=[]
    worker.completed.connect(publications.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert not failures,failures
    assert 7 in publications[0]['prepared']
    assert publications[0]['prepared'][7].runtime.project_at(clock[0]).origin=='offair'
    clock[0]=START+timedelta(hours=14,minutes=1)
    assert service.source_dependencies(old_root)==[]


def test_future_conversion_caches_classic_playout_and_protects_its_sources(tmp_path,monkeypatch):
    from channelos.resolve import resolve_channel
    from channelos.media_resilience import _mark_location_offline
    from channelos.runtime_jobs import release_runtime,adopt_runtime
    from test_runtime import build_resolved_channel
    channel=planner_channel(tmp_path)
    replacement=build_resolved_channel(tmp_path,[3600],channel_number=12)
    now=START+timedelta(hours=12,minutes=30)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            return now if tz else now.replace(tzinfo=None)
    monkeypatch.setattr('channelos.broadcaster.datetime',FrozenDateTime)
    monkeypatch.setattr('channelos.broadcast_planner.service.datetime',FrozenDateTime)
    store=RuntimeStore(tmp_path/'runtime.db')
    service=BroadcasterService([],tmp_path/'channels',channel.library,runtime_database_path=store.database_path)
    base={'channel':7,'name':'Future conversion'}
    classic=service.create({**base,'sources':[str(s.path) for s in channel.definition.sources],'mode':'sequential'}).record.definition
    prior=ChannelRuntime.open(resolve_channel(classic,channel.library),store,now=START+timedelta(hours=12))
    rules=channel.definition.programming.planner.to_mapping()
    rules['start_at']=(START+timedelta(days=1)).isoformat()
    rules['groups'][0]['asset_ids']=[replacement.media[0].asset.asset_id]
    saved=service.update(7,{**base,'sources':[str(s.path) for s in replacement.definition.sources],'mode':'planner','planner':rules}).record.definition
    converted=ChannelRuntime.open(resolve_channel(saved,channel.library),store,now=now)
    assert converted.timeline.actual_source_roots==frozenset(s.path for s in classic.sources)
    assert service.source_dependencies(classic.sources[0].path)[0]['channelNumber']==7
    preview=PlannerService(service)
    before=dump(store)
    assert preview.preview(preview.load(7)['editor'],view_start='2026-06-02',view_days=1)['confidence']=='Exact'
    assert dump(store)==before
    adopted=adopt_runtime(release_runtime(converted),store.database_path)
    expected=prior.project_at(now).event
    original_open=ChannelRuntime.open
    def unexpected_open(*args,**kwargs):
        raise AssertionError('A playback tick reopened the cached legacy runtime')
    with monkeypatch.context() as check:
        check.setattr(ChannelRuntime,'open',unexpected_open)
        for delta in range(10):
            at=now+timedelta(seconds=delta)
            assert adopted.project_at(at).event==expected
            adopted.broadcast_at(at)
    _mark_location_offline(channel.library,channel.media[0].location.path)
    recovered=original_open(resolve_channel(saved,channel.library),store,now=now+timedelta(minutes=5))
    assert recovered.project_at(now+timedelta(minutes=5)).origin=='offair'
