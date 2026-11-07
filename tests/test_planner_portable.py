import shutil

from channelos.broadcast_planner.contracts import PlannerDefinition
from channelos.broadcast_planner.profiles import ProfileStore, bind_profile
from channelos.broadcaster import BroadcasterService
from channelos.library import MediaLibrary
from channelos.portable import load_setup
from channelos.resolve import resolve_channel
from channelos.runtime import RuntimeStore, ChannelRuntime
from test_portable_copy import source_setup, copy_setup, EPOCH
from datetime import timedelta


def test_portable_move_preserves_pinned_profiles_occurrences_and_pending_completion(tmp_path):
    library,service,store,legacy=source_setup(tmp_path)
    try:
        from channelos.probe import MediaProbeResult
        import hashlib
        owned=tmp_path/'planner-owned'
        owned.mkdir()
        for index in range(2):
            path=owned/f'episode-{index}.mp4'
            payload=f'owned-planner-{index}'.encode()
            path.write_bytes(payload)
            library.upsert_file(path,owned,content_sha256=hashlib.sha256(payload).hexdigest(),
                probe=MediaProbeResult(duration_seconds=60,container_format='mp4'))
        shows=library.list_cached_media(owned)
        show=shows[0]
        ad=legacy.channel.ad_media[0]
        profile=ProfileStore(service.managed_directory/'studio'/'time-block-profiles').save({
            'id':'morning','name':'Morning','version':1,'slots':[
                {'id':'slot','name':'Morning show','start':'12:00','end':'14:00','bracket_minutes':2}]})
        rules=PlannerDefinition.from_mapping({'start_at':EPOCH.isoformat(),'timezone':'UTC',
            'groups':[{'id':'g','name':'Owned shows','asset_ids':[item.asset.asset_id for item in shows]}],
            'tracks':[{'id':'primary','group_id':'g'}],'windows':[],'cycle':{'action':'once'},'gap_filler':False})
        rules=bind_profile(rules,profile,{'slot':'primary'})
        definition=service.create({'channel':8,'name':'Portable Planner','sources':[str(show.location.source_root)],
            'mode':'planner','planner':rules.to_mapping(),'adBreaksEnabled':True,
            'adSetupMode':'after_show','adSources':[str(ad.location.source_root)],'adAssetIds':[ad.asset.asset_id]}).record.definition
        runtime=ChannelRuntime.open(resolve_channel(definition,library),store,now=EPOCH+timedelta(seconds=10))
        revision=runtime.timeline.revision
        selection=runtime.project_at(EPOCH+timedelta(seconds=30))
        uncommitted_ad=runtime.project_at(EPOCH+timedelta(minutes=3,seconds=5)).event
        runtime.break_store.close()
        first=tmp_path/'Portable copy'
        copy_setup(library,service,store,first,copy_media=True)
        moved=tmp_path/'Second drive letter'
        shutil.move(first,moved)
        paths=load_setup(moved)
        copied_library=MediaLibrary(paths.data_directory/'library.db')
        copied_service=BroadcasterService([],paths.data_directory/'channels',copied_library)
        copied_store=RuntimeStore(paths.data_directory/'runtime.db')
        copied_definition=copied_service._records[8].definition
        assert copied_definition.programming.planner.profile_bindings[0].version==1
        assert ProfileStore(copied_service.managed_directory/'studio'/'time-block-profiles').list()[0]['id']=='morning'
        reopened=ChannelRuntime.open(resolve_channel(copied_definition,copied_library),copied_store,now=EPOCH+timedelta(minutes=4))
        try:
            assert reopened.timeline.revision==revision
            assert reopened.project_at(EPOCH+timedelta(seconds=30)).event==selection.event
            assert reopened.project_at(EPOCH+timedelta(minutes=3,seconds=5)).event==uncommitted_ad
            with copied_store.connect() as connection:
                assert connection.execute('SELECT COUNT(*) FROM planner_completions WHERE channel_number=8').fetchone()[0]==1
                assert connection.execute('SELECT COUNT(*) FROM planner_cycles WHERE channel_number=8').fetchone()[0]==1
        finally:
            reopened.break_store.close()
    finally:
        legacy.break_store.close()


def test_manual_studio_ad_snapshots_keep_planner_revision_and_events_after_move(tmp_path):
    from test_simple_ads import setup,START
    local=tmp_path/'local'
    local.mkdir()
    library,service,raw=setup(local)
    raw['mode']='calendar'
    filled=service.auto_fill_studio(raw,START.isoformat(),(START+timedelta(seconds=600)).isoformat())
    raw['calendarBlocks']=filled['blocks']
    raw['mode']='planner'
    show=library.list_online_media_for_source(raw['sources'][0])[0]
    raw['planner']={'start_at':START.isoformat(),'timezone':'UTC',
        'groups':[{'id':'g','name':'Owned show','asset_ids':[show.asset.asset_id]}],
        'tracks':[{'id':'primary','group_id':'g'}],
        'windows':[{'id':'later','track_id':'primary','start':'13:00','end':'14:00','bracket_minutes':2}],
        'cycle':{'action':'once'},'gap_filler':False}
    definition=service.create(raw).record.definition
    assert definition.advertising.setup_mode=='after_show'
    store=RuntimeStore(service.runtime_database_path)
    runtime=ChannelRuntime.open(resolve_channel(definition,library),store,now=START)
    try:
        revision=runtime.timeline.revision
        expected=runtime.events_between(START,START+timedelta(seconds=300))
        assert any(event.event_type=='advertisement' for event in expected)
        destination=tmp_path/'portable'
        copy_setup(library,service,store,destination,copy_media=True)
        moved=tmp_path/'another-drive'
        shutil.move(destination,moved)
        paths=load_setup(moved)
        copied_library=MediaLibrary(paths.data_directory/'library.db')
        copied_service=BroadcasterService([],paths.data_directory/'channels',copied_library)
        copied=ChannelRuntime.open(resolve_channel(copied_service.records[0].definition,copied_library),
            RuntimeStore(paths.data_directory/'runtime.db'),now=START+timedelta(seconds=1))
        try:
            assert copied.timeline.revision==revision
            assert copied.events_between(START,START+timedelta(seconds=300))==expected
        finally:
            copied.break_store.close()
    finally:
        runtime.break_store.close()
