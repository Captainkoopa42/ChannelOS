from dataclasses import replace
from datetime import timedelta

from channelos.broadcaster import channel_to_mapping
from channelos.broadcast_planner.contracts import PlannerDefinition
from channelos.models import AdvertisingDefinition,ChannelDefinition
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime,RuntimeStore
from planner_helpers import planner_rules
from test_planner_runtime import planner_channel,START
from test_runtime import build_resolved_channel


def test_future_media_replacement_uses_each_revisions_own_source_pool(tmp_path):
    channel=planner_channel(tmp_path)
    replacement=build_resolved_channel(tmp_path,[3600],channel_number=12)
    store=RuntimeStore(tmp_path/'runtime.db')
    before=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=30))
    raw=channel_to_mapping(channel.definition)
    raw['sources']=[{'path':str(replacement.definition.sources[0].path)}]
    raw['programming']['planner']['groups'][0]['asset_ids']=[replacement.media[0].asset.asset_id]
    raw['programming']['planner']['edit_effect']='safe_future'
    after=ChannelRuntime.open(resolve_channel(ChannelDefinition.from_mapping(raw),channel.library),store,now=START+timedelta(hours=12,minutes=30))
    old_time=START+timedelta(hours=12,minutes=45)
    assert after.project_at(old_time).event==before.project_at(old_time).event
    assert after.project_at(old_time).media.location.path==channel.media[0].location.path
    new_time=START+timedelta(hours=13,minutes=5)
    assert after.broadcast_at(new_time).media.asset.asset_id==replacement.media[0].asset.asset_id
    with store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM planner_failures').fetchone()[0]==0


def test_disabling_future_ads_keeps_current_committed_break_and_guide_markers(tmp_path):
    owned=build_resolved_channel(tmp_path,[1200,1200])
    ads=build_resolved_channel(tmp_path,[15,15],channel_number=12)
    raw=planner_rules(cycle={'action':'once'})
    raw['groups'][0]['asset_ids']=[m.asset.asset_id for m in owned.media]
    raw['windows'][0]['bracket_minutes']=30
    settings=AdvertisingDefinition(enabled=True,setup_mode='after_show',play_order='sequential',asset_ids=tuple(m.asset.asset_id for m in ads.media))
    schema=channel_to_mapping(owned.definition)
    schema.update(schema_version='0.7',programming={'mode':'planner','planner':raw})
    definition=replace(ChannelDefinition.from_mapping(schema),advertising=settings)
    channel=replace(owned,definition=definition,ad_media=ads.media)
    store=RuntimeStore(tmp_path/'runtime.db')
    before=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=5))
    raw['edit_effect']='safe_future'
    edited=replace(definition,advertising=replace(settings,enabled=False),programming=replace(definition.programming,planner=PlannerDefinition.from_mapping(raw)))
    after=ChannelRuntime.open(replace(channel,definition=edited,ad_media=()),store,now=START+timedelta(hours=12,minutes=5))
    try:
        active=after.broadcast_at(START+timedelta(hours=12,minutes=20,seconds=5))
        assert active.origin=='advertisement'
        assert after.break_store is not None
        assert len(after.break_plans_for_event(active))==1
        later=after.broadcast_at(START+timedelta(hours=12,minutes=35))
        assert later.origin=='program' and later.media.asset.asset_id==owned.media[1].asset.asset_id
        assert after.break_plans_for_event(later)==()
    finally:
        before.break_store.close()
        after.break_store.close()


def test_second_edit_uses_effective_pending_revision_without_a_status_poll(tmp_path):
    channel=planner_channel(tmp_path,action='restart')
    store=RuntimeStore(tmp_path/'runtime.db')
    ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=30))
    raw=channel_to_mapping(channel.definition)
    raw['programming']['planner']['edit_effect']='safe_future'
    raw['programming']['planner']['windows'][0].update(start='14:00',end='17:00')
    staged=ChannelRuntime.open(replace(channel,definition=ChannelDefinition.from_mapping(raw)),store,now=START+timedelta(hours=12,minutes=30))
    assert staged.timeline.activation==START+timedelta(hours=13)
    raw['programming']['planner']['edit_effect']='next_cycle'
    raw['programming']['planner']['windows'][0]['end']='18:00'
    second=ChannelRuntime.open(replace(channel,definition=ChannelDefinition.from_mapping(raw)),store,now=START+timedelta(hours=14,minutes=30))
    assert second.timeline.activation==START+timedelta(hours=16)
    assert second.project_at(START+timedelta(hours=13,minutes=30)).origin=='offair'
    with store.connect() as connection:
        assert connection.execute('SELECT status FROM planner_revisions WHERE revision=?',(staged.timeline.revision,)).fetchone()[0]!='superseded'


def test_editing_a_future_initial_plan_cancels_the_unstarted_alternative(tmp_path):
    channel=planner_channel(tmp_path)
    raw=channel_to_mapping(channel.definition)
    raw['programming']['planner']['start_at']=(START+timedelta(days=2)).isoformat()
    store=RuntimeStore(tmp_path/'runtime.db')
    original=ChannelRuntime.open(replace(channel,definition=ChannelDefinition.from_mapping(raw)),store,now=START)
    raw['programming']['planner']['start_at']=(START+timedelta(days=1)).isoformat()
    replacement=ChannelRuntime.open(replace(channel,definition=ChannelDefinition.from_mapping(raw)),store,now=START)
    with store.connect() as connection:
        assert connection.execute('SELECT status FROM planner_revisions WHERE revision=?',(original.timeline.revision,)).fetchone()[0]=='superseded'
    assert replacement.timeline._revision_at(START+timedelta(days=3)) is None


def test_reapplying_retired_rules_creates_new_activation_and_preserves_history(tmp_path):
    channel=planner_channel(tmp_path,action='restart')
    store=RuntimeStore(tmp_path/'runtime.db')
    original=ChannelRuntime.open(channel,store,now=START+timedelta(hours=12,minutes=30))
    historical=original.project_at(START+timedelta(hours=12,minutes=15)).event
    raw=channel_to_mapping(channel.definition)
    raw['programming']['planner']['edit_effect']='safe_future'
    raw['programming']['planner']['windows'][0].update(start='14:00',end='17:00')
    edited=ChannelRuntime.open(replace(channel,definition=ChannelDefinition.from_mapping(raw)),store,now=START+timedelta(hours=12,minutes=30))
    edited.broadcast_at(START+timedelta(hours=14,minutes=30))
    reapplied=ChannelRuntime.open(channel,store,now=START+timedelta(hours=14,minutes=30))
    assert reapplied.timeline.activation==START+timedelta(hours=16)
    assert reapplied.timeline.revision!=original.timeline.revision
    assert reapplied.project_at(START+timedelta(hours=12,minutes=15)).event==historical
    reopened=ChannelRuntime.open(channel,store,now=START+timedelta(hours=16,minutes=30))
    assert reopened.timeline.revision==reapplied.timeline.revision
    assert reopened.project_at(START+timedelta(hours=12,minutes=15)).event==historical


def test_advanced_calendar_boundary_uses_its_assigned_ad_pool(tmp_path):
    from channelos.models import AdPlacementDefinition
    from channelos.broadcast_planner.advertising import AdPlanner
    from channelos.broadcast_planner.engine import forecast
    from channelos.broadcast_planner.runtime import assets_for
    channel=planner_channel(tmp_path)
    ads=build_resolved_channel(tmp_path,[15,15],channel_number=12).media
    raw=channel.definition.programming.planner.to_mapping()
    raw['groups'][0]['asset_ids']=[channel.media[0].asset.asset_id]
    raw['windows'][0].update(end='14:00',bracket_minutes=120)
    placement=AdvertisingDefinition(enabled=True,asset_ids=(ads[1].asset.asset_id,),break_duration_seconds=15,triggers=('calendar_boundary',))
    settings=AdvertisingDefinition(enabled=True,asset_ids=(ads[0].asset.asset_id,),placements=(AdPlacementDefinition('tail','calendar_boundary',placement),))
    result=forecast(PlannerDefinition.from_mapping(raw),assets_for(channel.media),ads=AdPlanner(channel.media,(ads[1],),settings,'revision',7),view_days=1)
    assert result['confidence']=='Exact'
    assert result['actual_restart']=='2026-06-01T13:00:15+00:00'
    assert [s['asset_id'] for s in result['segments'] if s['kind']=='advertisement']==[ads[1].asset.asset_id]
