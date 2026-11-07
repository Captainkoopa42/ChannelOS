import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from channelos.broadcaster import channel_to_mapping, definition_from_editor
from channelos.broadcast_planner.contracts import PlannerDefinition
from channelos.models import AdvertisingDefinition, ChannelDefinition
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
from channelos.runtime_snapshot import channel_snapshot, restore_channel_snapshot
from test_runtime import build_resolved_channel
from planner_helpers import planner_rules

UTC=timezone.utc
START=datetime(2026,6,1,tzinfo=UTC)


def planner_channel(tmp_path, *, action='once'):
    channel=build_resolved_channel(tmp_path,[3600,3600,3600])
    rules=planner_rules(cycle={'action':action})
    rules['groups'][0]['asset_ids']=[m.asset.asset_id for m in channel.media]
    raw=channel_to_mapping(channel.definition)
    raw['schema_version']='0.7'
    raw['programming']={'mode':'planner','planner':rules}
    return replace(channel,definition=ChannelDefinition.from_mapping(raw))


def row_counts(store):
    with store.connect() as c:
        return {table:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in ('channel_runtime','viewer_runtime','planner_revisions','planner_occurrences','planner_completions','planner_cycles','planner_checkpoints','ad_break_history')
                if c.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone()}


def test_schema_and_editor_roundtrip_embeds_portable_planner_intent(tmp_path):
    channel=planner_channel(tmp_path)
    raw=channel_to_mapping(channel.definition)
    assert ChannelDefinition.from_mapping(raw)==channel.definition
    editor={'channel':7,'name':'Planner','sources':[str(s.path) for s in channel.definition.sources],
            'mode':'planner','planner':raw['programming']['planner']}
    assert definition_from_editor(editor).programming.planner==channel.definition.programming.planner


def test_forecast_guide_projection_and_rewind_do_not_earn_future_completions(tmp_path):
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    runtime=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=30))
    before=row_counts(store)
    future=runtime.project_at(START+timedelta(hours=14,minutes=30))
    assert future.media.asset.asset_id==channel.media[2].asset.asset_id
    assert row_counts(store)==before
    assert runtime.project_at(START+timedelta(hours=12,minutes=15)).offset_seconds==900
    assert row_counts(store)==before
    actual=runtime.broadcast_at(START+timedelta(hours=12,minutes=45))
    assert actual.media.asset.asset_id==channel.media[0].asset.asset_id
    assert row_counts(store)['planner_completions']==0


def test_closed_app_elapsed_time_reconciles_once_and_guide_matches_playback(tmp_path):
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    ChannelRuntime.open(channel,store,now=START)
    reopened=ChannelRuntime.open(channel,store,now=START+timedelta(days=3,hours=10))
    assert reopened.broadcast_at(START+timedelta(days=3,hours=10)).origin=='offair'
    counts=row_counts(store)
    assert counts['planner_completions']==counts['planner_cycles']==1
    assert counts['planner_checkpoints']==1
    again=ChannelRuntime.open(channel,store,now=START+timedelta(days=3,hours=10))
    assert row_counts(store)==counts
    projected=again.project_at(START+timedelta(hours=13,minutes=5))
    assert projected.media.asset.asset_id==channel.media[1].asset.asset_id
    assert projected.event.source_offset_seconds==0
    assert row_counts(store)==counts


def test_channel_scoped_rollback_delete_and_restore_preserve_planner_history(tmp_path):
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    ChannelRuntime.open(channel,store,now=START+timedelta(days=2))
    counts=row_counts(store)
    snapshot=channel_snapshot(store.database_path,tmp_path/'snapshot.db',7)
    archive=store.delete_channel(7)
    assert row_counts(store)['planner_occurrences']==0
    store.restore_deleted_channel(archive)
    assert row_counts(store)==counts
    store.delete_channel(7)
    restore_channel_snapshot(snapshot.database_path,store.database_path,7)
    assert row_counts(store)==counts


def test_next_cycle_edit_keeps_todays_immutable_occurrences(tmp_path):
    channel=planner_channel(tmp_path,action='restart')
    store=RuntimeStore(tmp_path/'runtime.db')
    before=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=30))
    original=before.project_at(START+timedelta(hours=12,minutes=30))
    raw=channel_to_mapping(channel.definition)
    raw['programming']['planner']['windows'][0]['start']='11:00'
    edited=replace(channel,definition=ChannelDefinition.from_mapping(raw))
    after=ChannelRuntime.open(edited,store,now=START+timedelta(hours=12,minutes=30))
    assert after.project_at(START+timedelta(hours=12,minutes=30)).event==original.event
    with store.connect() as c:
        row=c.execute("SELECT activation_at FROM planner_revisions WHERE status='pending'").fetchone()
    assert row['activation_at']=='2026-06-01T15:00:00+00:00'
    after.broadcast_at(START+timedelta(days=1,hours=11,minutes=5))
    with store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM planner_cycles').fetchone()[0]>=1
        assert c.execute('SELECT COUNT(*) FROM planner_completions WHERE revision=?',(before.timeline.revision,)).fetchone()[0]==1


def test_whole_clip_ad_rotation_parent_identity_and_safe_cycle_end(tmp_path):
    from channelos.broadcast_planner.advertising import AdPlanner
    from channelos.broadcast_planner.engine import forecast
    from channelos.broadcast_planner.runtime import assets_for
    from channelos.runtime import advertising_signature
    channel=planner_channel(tmp_path)
    media=tuple(replace(m,asset=replace(m.asset,duration_seconds=1200)) for m in channel.media)
    ads_channel=build_resolved_channel(tmp_path,[15,15],channel_number=12)
    settings=AdvertisingDefinition(enabled=True,setup_mode='after_show',play_order='sequential',asset_ids=tuple(m.asset.asset_id for m in ads_channel.media))
    raw=channel.definition.programming.planner.to_mapping()
    raw['windows'][0]['bracket_minutes']=30
    definition=replace(channel.definition,programming=replace(channel.definition.programming,planner=PlannerDefinition.from_mapping(raw)),advertising=settings)
    channel=replace(channel,definition=definition,media=media,ad_media=ads_channel.media)
    detached=AdPlanner(media,channel.ad_media,settings,advertising_signature(channel),7)
    result=forecast(definition.programming.planner,assets_for(media),ads=detached,view_days=1)
    assert result['media_ends']=='2026-06-01T13:20:00+00:00'
    assert result['actual_restart']=='2026-06-01T13:20:15+00:00'
    ad_rows=[s for s in result['segments'] if s['kind']=='advertisement']
    assert [s['asset_id'] for s in ad_rows]==[channel.ad_media[0].asset.asset_id,channel.ad_media[1].asset.asset_id,channel.ad_media[0].asset.asset_id]
    store=RuntimeStore(tmp_path/'runtime.db')
    runtime=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=20,seconds=5))
    selected=runtime.broadcast_at(START+timedelta(hours=12,minutes=20,seconds=5))
    assert selected.origin=='advertisement'
    parent=runtime.project_at(START+timedelta(hours=12,minutes=5))
    assert selected.parent_program_id==parent.event.event_id
    assert selected.program_occurrence_id==parent.program_occurrence_id
    assert selected.offset_seconds==5
    before=row_counts(store)
    assert len(runtime.break_plans_for_event(selected))==1
    runtime.project_at(START+timedelta(hours=13,minutes=20,seconds=10))
    assert row_counts(store)==before
    runtime.broadcast_at(START+timedelta(hours=13,minutes=20,seconds=20))
    assert row_counts(store)['planner_cycles']==1
    runtime.break_store.close()


def test_safe_future_edit_keeps_completed_progress_and_current_program(tmp_path):
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    current=ChannelRuntime.open(channel,store,now=START+timedelta(hours=13,minutes=30))
    raw=channel_to_mapping(channel.definition)
    raw['programming']['planner']['edit_effect']='safe_future'
    raw['programming']['planner']['windows'][0].update(start='14:00',end='17:00')
    edited=ChannelRuntime.open(replace(channel,definition=ChannelDefinition.from_mapping(raw)),store,now=START+timedelta(hours=13,minutes=30))
    assert edited.broadcast_at(START+timedelta(hours=13,minutes=45)).media.asset.asset_id==channel.media[1].asset.asset_id
    assert edited.broadcast_at(START+timedelta(hours=14,minutes=5)).media.asset.asset_id==channel.media[2].asset.asset_id


def test_offair_never_loads_a_fake_media_file(tmp_path):
    from channelos.television import TelevisionSession
    from test_television import FakeBackend
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    runtime=ChannelRuntime.open(channel,store,now=START)
    tv=TelevisionRuntime((runtime,),store)
    backend=FakeBackend()
    session=TelevisionSession(tv,backend)
    session.tune(7,now=START)
    assert 'load' not in backend.events
    assert 'stop' in backend.events
    session.sync(now=START+timedelta(hours=12,minutes=5))
    assert backend.loaded==channel.media[0].location.path


def test_carryover_completes_original_source_before_one_whole_ad(tmp_path):
    from channelos.broadcast_planner.advertising import AdPlanner
    from channelos.broadcast_planner.engine import forecast
    from channelos.broadcast_planner.runtime import assets_for
    channel=planner_channel(tmp_path)
    raw=channel.definition.programming.planner.to_mapping()
    raw['groups'][0]['asset_ids']=[channel.media[0].asset.asset_id]
    raw['windows'][0].update(end='13:00',fit='carryover')
    media=(replace(channel.media[0],asset=replace(channel.media[0].asset,duration_seconds=5400)),)
    ad=build_resolved_channel(tmp_path,[15],channel_number=12).media
    settings=AdvertisingDefinition(enabled=True,setup_mode='after_show')
    result=forecast(PlannerDefinition.from_mapping(raw),assets_for(media),ads=AdPlanner(media,ad,settings,'rev',7),view_days=2)
    programs=[s for s in result['segments'] if s['kind']=='program']
    ads=[s for s in result['segments'] if s['kind']=='advertisement']
    assert [s['source_offset'] for s in programs]==[0,3600]
    assert len(ads)==1 and ads[0]['starts_at']=='2026-06-02T12:30:00+00:00'
    assert result['actual_restart']=='2026-06-02T12:30:15+00:00'


def test_source_return_does_not_retroactively_fill_already_missed_slots(tmp_path):
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    missing=replace(channel,media=channel.media[1:])
    ChannelRuntime.open(missing,store,now=START+timedelta(hours=12,minutes=30))
    returned=ChannelRuntime.open(channel,store,now=START+timedelta(hours=13,minutes=5))
    current=returned.broadcast_at(START+timedelta(hours=13,minutes=5))
    assert current.media.asset.asset_id==channel.media[0].asset.asset_id
    assert current.program_started_at==START+timedelta(hours=13)
    assert current.offset_seconds==300
    assert returned.project_at(START+timedelta(hours=12,minutes=15)).origin=='offair'
    with store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM planner_completions').fetchone()[0]==0


def test_repeated_status_keeps_the_original_bracket_after_a_short_program(tmp_path):
    channel=planner_channel(tmp_path)
    channel=replace(channel,media=tuple(replace(m,asset=replace(m.asset,duration_seconds=1200)) for m in channel.media))
    store=RuntimeStore(tmp_path/'runtime.db')
    first=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=5))
    assert first.broadcast_at(START+timedelta(hours=12,minutes=25)).origin=='offair'
    restarted=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=45))
    assert restarted.broadcast_at(START+timedelta(hours=12,minutes=45)).origin=='offair'
    next_program=restarted.broadcast_at(START+timedelta(hours=13,minutes=5))
    assert next_program.media.asset.asset_id==channel.media[1].asset.asset_id
    assert next_program.offset_seconds==300


def test_interrupted_source_holds_completion_and_resumes_unplayed_content(tmp_path):
    channel=planner_channel(tmp_path)
    raw=channel.definition.programming.planner.to_mapping()
    raw['groups'][0]['asset_ids']=[channel.media[0].asset.asset_id]
    channel=replace(channel,definition=replace(channel.definition,programming=replace(channel.definition.programming,planner=PlannerDefinition.from_mapping(raw))))
    store=RuntimeStore(tmp_path/'runtime.db')
    ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=5))
    offline=ChannelRuntime.open(replace(channel,media=channel.media[1:]),store,now=START+timedelta(hours=12,minutes=30))
    assert offline.broadcast_at(START+timedelta(hours=12,minutes=45)).origin=='offair'
    with store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM planner_failures').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM planner_completions').fetchone()[0]==0
    returned=ChannelRuntime.open(channel,store,now=START+timedelta(hours=13,minutes=5))
    playing=returned.broadcast_at(START+timedelta(hours=13,minutes=5))
    assert playing.media.asset.asset_id==channel.media[0].asset.asset_id
    assert playing.offset_seconds==2100  # Original 30 minutes + 5 resumed minutes.
    returned.broadcast_at(START+timedelta(hours=13,minutes=40))
    with store.connect() as c:
        completed=c.execute('SELECT completed_at FROM planner_completions').fetchone()[0]
    assert completed=='2026-06-01T13:30:00+00:00'


def test_classic_conversion_protects_the_current_program_and_past_viewer_time(tmp_path):
    from channelos.broadcaster import BroadcasterService
    from channelos.resolve import resolve_channel
    channel=planner_channel(tmp_path)
    store=RuntimeStore(tmp_path/'runtime.db')
    service=BroadcasterService([],tmp_path/'channels',channel.library,runtime_database_path=store.database_path)
    base={'channel':7,'name':'Conversion','sources':[str(s.path) for s in channel.definition.sources]}
    classic=service.create({**base,'mode':'sequential'}).record.definition
    prior=ChannelRuntime.open(resolve_channel(classic,channel.library),store,now=START+timedelta(hours=12))
    raw=channel.definition.programming.planner.to_mapping()
    raw['start_at']=(START+timedelta(hours=12,minutes=30)).isoformat()
    saved=service.update(7,{**base,'mode':'planner','planner':raw}).record.definition
    converted=ChannelRuntime.open(resolve_channel(saved,channel.library),store,now=START+timedelta(hours=12,minutes=30))
    assert converted.timeline.activation==START+timedelta(hours=13)
    before=START+timedelta(hours=12,minutes=45)
    assert converted.project_at(before).event==prior.project_at(before).event
    assert converted.project_at(START+timedelta(hours=13,minutes=5)).origin=='program'
