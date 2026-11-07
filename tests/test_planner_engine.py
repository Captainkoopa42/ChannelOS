from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from channelos.broadcast_planner.contracts import PlannerDefinition
from channelos.broadcast_planner.engine import Asset, Compiler, PlannerCancelled, forecast
from planner_helpers import planner_rules


def compile_rules(raw=None, assets=None, **options):
    return Compiler(PlannerDefinition.from_mapping(raw or planner_rules()),
                    assets or [Asset(f'episode-{i}',3600) for i in range(1,4)], **options)


def shows(day):
    return [s for s in day.segments if s.kind == 'program']


def test_daily_windows_share_one_cursor_but_rerun_track_is_independent():
    raw=planner_rules()
    raw['windows'][0].update(end='13:00')
    raw['windows'].append({**raw['windows'][0], 'id':'later','start':'16:00','end':'17:00'})
    raw['tracks'].append({'id':'rerun','group_id':'show','mode':'rerun'})
    raw['windows'].append({**raw['windows'][0], 'id':'repeat','track_id':'rerun','start':'20:00','end':'21:00'})
    raw['cycle']={'action':'once'}
    engine=compile_rules(raw)
    first=engine.day()
    assert [s.asset_id for s in shows(first)]==['episode-1','episode-2','episode-1']
    second=engine.day()
    assert [s.asset_id for s in shows(second)]==['episode-3']
    assert engine.closed
    assert first.completions==[]
    assert second.completions[0][1]=='primary'


def test_loop_completion_stays_sticky_while_other_required_media_finishes():
    raw=planner_rules()
    raw['groups'].append({'id':'b','name':'Series B','asset_ids':['b1','b2']})
    raw['tracks'][0]['post_completion']='loop'
    raw['tracks'].append({'id':'b','group_id':'b'})
    raw['windows'][0]['end']='14:00'
    raw['windows'].append({'id':'b','track_id':'b','start':'17:00','end':'18:00'})
    raw['cycle']={'action':'once'}
    engine=compile_rules(raw,[Asset(f'episode-{i}',3600) for i in range(1,4)]+[Asset('b1',3600),Asset('b2',3600)])
    engine.day()
    day=engine.day()
    assert [s.asset_id for s in shows(day)][:2]==['episode-3','episode-1']
    assert engine.closed
    assert len(day.closed_cycles)==1
    assert set(day.closed_cycles[0]['completed_tracks'])=={'primary','b'}


def test_270_hours_fifteen_hours_per_week_holiday_and_date_monday_gate():
    raw=planner_rules()
    raw['groups'][0]['asset_ids']=[f'e{i}' for i in range(270)]
    raw['suspensions']=[{'id':'holiday','target':'track','target_id':'primary',
        'scope':{'from_date':'2026-06-15','until_date':'2026-06-28'}}]
    raw['cycle']={'action':'once','not_before':'2026-10-20T00:00:00Z','boundary':'week'}
    plan=PlannerDefinition.from_mapping(raw)
    result=forecast(plan,[Asset(f'e{i}',3600) for i in range(270)],view_days=7,max_seconds=10)
    assert result['confidence']=='Exact'
    # 18 active weeks, plus the two held weeks: Friday of week 20.
    assert result['media_ends']=='2026-10-16T15:00:00+00:00'
    assert result['cycle_ready']=='2026-10-20T00:00:00+00:00'
    assert result['actual_restart']=='2026-10-26T00:00:00+00:00'
    assert result['tracks'][0]['actual_hours']==270
    assert result['tracks'][0]['occupied_hours']==270
    assert plan.to_mapping()==PlannerDefinition.from_mapping(raw).to_mapping()


def test_precedence_scopes_only_overlap_and_same_priority_conflicts_block():
    raw=planner_rules()
    raw['groups'][0]['asset_ids']=[f'e{i}' for i in range(20)]
    raw['tracks'].append({'id':'special','group_id':'show'})
    raw['layers']=[{'id':'holiday','name':'Holiday','scope':{'months':[6]},'priority':100}]
    raw['windows'].append({'id':'special','track_id':'special','start':'13:00','end':'14:00','layer_id':'holiday'})
    engine=compile_rules(raw,[Asset(f'e{i}',3600) for i in range(20)])
    assert [s.track_id for s in shows(engine.day())]==['primary','special','primary']
    assert not engine.blocked
    raw['windows'][-1].pop('layer_id')
    raw['windows'][-1]['scope']={'weekdays':[0,1,2,3,4]}
    engine=compile_rules(raw,[Asset(f'e{i}',3600) for i in range(20)])
    engine.day()
    assert engine.blocked


def test_carryover_preserves_source_offsets_without_counting_partial_as_complete():
    raw=planner_rules()
    raw['groups'][0]['asset_ids']=['long']
    raw['windows'][0].update(end='13:00',bracket_minutes=30,fit='carryover')
    raw['cycle']={'action':'once'}
    engine=compile_rules(raw,[Asset('long',5400)])
    first=engine.day()
    assert [s.source_offset for s in shows(first)]==[0,1800]
    assert first.completions==[]
    second=engine.day()
    assert shows(second)[0].source_offset==3600
    assert second.completions and engine.closed


def test_strict_does_not_cut_long_media_next_fit_keeps_oversized_episode_pending():
    raw=planner_rules()
    raw['groups'][0]['asset_ids']=['long','short']
    raw['windows'][0].update(end='13:00',bracket_minutes=30)
    engine=compile_rules(raw,[Asset('long',3600),Asset('short',1800)])
    assert not shows(engine.day())
    raw['windows'][0]['fit']='next_fit'
    engine=compile_rules(raw,[Asset('long',3600),Asset('short',1800)])
    assert [s.asset_id for s in shows(engine.day())]==['short']
    assert engine.cursors['primary'].remaining==['long']
    assert engine.cursors['primary'].completed_at is None


def test_missing_media_holds_first_pass_and_forecast_is_honest_and_cancellable():
    raw=planner_rules()
    plan=PlannerDefinition.from_mapping(raw)
    result=forecast(plan,[Asset('episode-1',3600,online=False)],max_days=2,max_seconds=1)
    assert result['confidence']=='Blocked' and result['media_ends'] is None
    with pytest.raises(PlannerCancelled):
        forecast(plan,[],cancel=lambda:True)


def test_checkpoint_roundtrip_produces_identical_future_occurrences():
    raw=planner_rules()
    raw['windows'][0]['end']='13:00'
    first=compile_rules(raw)
    first.day()
    detached=compile_rules(raw,seed=deepcopy(first.snapshot()))
    assert detached.day().segments==first.day().segments


def test_original_airing_replay_keeps_provenance_and_explicit_substitutes():
    raw=planner_rules(historical_mode='replay',replay_start='2026-06-01',historical_airings=[
        {'id':'premiere','asset_id':'unowned','substitute_id':'episode-1',
         'starts_at':'1993-01-03T20:00:00Z','source':'User programme log','track_id':'primary'}])
    engine=compile_rules(raw)
    assert shows(engine.day())[0].starts_at.isoformat()=='2026-06-01T20:00:00+00:00'
    assert engine.definition.historical_airings[0].source=='User programme log'


def test_era_reference_year_maps_calendar_rules_without_changing_actual_time():
    raw=planner_rules(historical_mode='era',reference_year=1993)
    # June 1, 1993 was Tuesday; June 1, 2026 is Monday.
    raw['windows'][0]['scope']={'weekdays':[1]}
    engine=compile_rules(raw)
    day=engine.day()
    assert engine.scope_day(day.day)==date(1993,6,1)
    assert shows(day)[0].starts_at.year==2026
    result=forecast(engine.definition,[Asset(f'episode-{i}',3600) for i in range(1,4)],view_days=1)
    assert result['calendar_clock']=='reference year' and result['confidence']=='Estimated'
