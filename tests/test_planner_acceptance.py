"""The master-plan release gate, including real Apply and closed-app catch-up."""
from datetime import datetime, timedelta, timezone

from channelos.broadcaster import BroadcasterService
from channelos.broadcast_planner.contracts import PlannerDefinition
from channelos.broadcast_planner.engine import forecast
from channelos.broadcast_planner.runtime import assets_for
from channelos.guide import GuideService
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, ViewerClock
from planner_helpers import planner_rules
from test_runtime import build_resolved_channel


def test_master_plan_multiwindow_holiday_all_date_gate_apply_shutdown_restart(tmp_path):
    owned=build_resolved_channel(tmp_path,[3600]*630)
    raw=planner_rules()
    raw['groups']=[{'id':'a','name':'270-hour series','asset_ids':[m.asset.asset_id for m in owned.media[:270]]},
                   {'id':'b','name':'Later-finishing collection','asset_ids':[m.asset.asset_id for m in owned.media[270:]]}]
    raw['tracks']=[{'id':'a','group_id':'a','post_completion':'loop'}, {'id':'b','group_id':'b'}]
    raw['windows']=[{'id':f'a-{hour}','track_id':'a','start':f'{hour:02}:00','end':f'{hour+1:02}:00',
                    'scope':{'weekdays':[0,1,2,3,4]},'bracket_minutes':60} for hour in (9,10,11)]
    raw['windows'].append({'id':'b','track_id':'b','start':'13:00','end':'16:00','scope':{'weekdays':[0,1,2,3,4]},'bracket_minutes':60})
    raw['suspensions']=[{'id':'holiday','target':'track','target_id':'a','scope':{'from_date':'2026-06-15','until_date':'2026-06-28'}}]
    raw['cycle']={'completion':'all','not_before':'2026-11-15T00:00:00Z','boundary':'week'}
    rules=PlannerDefinition.from_mapping(raw)
    result=forecast(rules,assets_for(owned.media),view_days=1,max_seconds=10)
    assert result['confidence']=='Exact'
    assert result['tracks'][0]['last_airing']=='2026-10-16T12:00:00+00:00'
    assert result['tracks'][1]['last_airing']=='2026-11-13T16:00:00+00:00'
    assert result['media_ends']=='2026-11-13T16:00:00+00:00'
    assert result['cycle_ready']=='2026-11-15T00:00:00+00:00'
    assert result['actual_restart']=='2026-11-16T00:00:00+00:00'
    store=RuntimeStore(tmp_path/'runtime.db')
    service=BroadcasterService([],tmp_path/'channels',owned.library,runtime_database_path=store.database_path)
    saved=service.create({'channel':7,'name':'Acceptance network','sources':[str(s.path) for s in owned.definition.sources],
        'mode':'planner','planner':raw}).record.definition
    resolved=resolve_channel(saved,owned.library)
    start=datetime(2026,6,1,tzinfo=timezone.utc)
    opened=ChannelRuntime.open(resolved,store,now=start)
    paused=ViewerClock(start+timedelta(hours=9),start+timedelta(days=1),False)
    store.save_viewer(7,paused,now=start+timedelta(days=1))
    # No decoder is opened while this station is closed for several months.
    autumn=datetime(2026,10,1,10,30,tzinfo=timezone.utc)
    returned=ChannelRuntime.open(resolved,store,now=autumn)
    selection=returned.broadcast_at(autumn)
    guide=GuideService((returned,)).now_next(7,at=autumn)
    assert guide.now.asset_id==selection.media.asset.asset_id
    assert store.load_viewer(7)==paused
    with store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM planner_completions').fetchone()[0]==0
    after=datetime(2026,11,16,9,30,tzinfo=timezone.utc)
    restarted=ChannelRuntime.open(resolved,store,now=after)
    selected=restarted.broadcast_at(after)
    assert selected.cycle_index==1
    assert selected.media.asset.asset_id==raw['groups'][0]['asset_ids'][0]
    assert selected.offset_seconds==1800
    with store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM planner_cycles').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM planner_completions WHERE cycle_index=0').fetchone()[0]==2
    assert store.load_viewer(7)==paused
