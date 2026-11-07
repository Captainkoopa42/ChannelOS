from datetime import date, datetime, timezone

import pytest

from channelos.broadcast_planner.contracts import PlannerDefinition, PlannerValidationError
from channelos.broadcast_planner.timezones import get_zone, local_instant
from planner_helpers import planner_rules


def test_rules_roundtrip_preserves_shared_windows_and_channel_neutral_profile():
    raw = planner_rules()
    raw['windows'].append({**raw['windows'][0], 'id':'evening','start':'19:00','end':'20:00'})
    raw['profile_bindings']=[{'id':'morning','version':2,'snapshot':{'id':'morning','version':2,'name':'Morning','slots':[{'id':'slot-1','start':'06:00','end':'07:00'}]},'assignments':{'slot-1':'primary'}}]
    parsed = PlannerDefinition.from_mapping(raw)
    assert parsed.windows[0].track_id == parsed.windows[1].track_id == 'primary'
    assert PlannerDefinition.from_mapping(parsed.to_mapping()) == parsed
    assert parsed.profile_bindings[0].snapshot['slots'][0].get('asset_id') is None
    assert parsed.revision == PlannerDefinition.from_mapping(raw).revision
    raw['groups'][0]['name']='Changed outside the parsed definition'
    assert parsed.groups[0].name=='Series A'


def test_gate_completion_is_independent_of_track_loop_policy():
    raw = planner_rules()
    raw['tracks'][0]['post_completion']='loop'
    plan = PlannerDefinition.from_mapping(raw)
    assert not plan.completion_satisfied(set())
    assert plan.completion_satisfied({'primary'})
    assert plan.tracks[0].post_completion=='loop'


@pytest.mark.parametrize('patch',[
    {'timezone':'../../private'},
    {'windows':[{'id':'w','track_id':'missing','start':'12:00','end':'15:00'}]},
    {'windows':[{'id':'w','track_id':'primary','start':'12:00','end':'15:00','fit':'overrun'}]},
    {'suspensions':[{'id':'s','target':'track','target_id':'missing'}]},
    {'cycle':{'completion':'none','not_before':'2026-06-01T00:00:00Z'}},
    {'cycle':{'gate_mode':'or'}},
    {'cycle':{'completion':'selected_all'}},
    {'tracks':[{'id':'primary','group_id':'show','mode':'rerun','required':True}]},
    {'groups':[{'id':'show','name':'Invalid','asset_ids':['same','same']}]},
    {'windows':[{'id':'w','track_id':'primary','start':'12:00','end':'15:00','scope':[]}]},
])
def test_invalid_or_implicit_destructive_rules_are_rejected(patch):
    with pytest.raises(PlannerValidationError):
        PlannerDefinition.from_mapping(planner_rules(**patch))


def test_nested_all_any_gate_and_forced_date_are_explicit():
    raw=planner_rules()
    raw['tracks'].append({'id':'second','group_id':'show'})
    raw['cycle']={'completion':'custom','custom_gate':{'op':'all','children':[
        {'op':'track','track_id':'primary'},{'op':'any','children':[{'op':'track','track_id':'second'}]}]}}
    plan=PlannerDefinition.from_mapping(raw)
    assert not plan.completion_satisfied({'primary'})
    assert plan.completion_satisfied({'primary','second'})
    raw['cycle']={'completion':'none','not_before':'2026-07-01T00:00:00Z','allow_unfinished':True}
    assert PlannerDefinition.from_mapping(raw).cycle.allow_unfinished


def test_overnight_and_dst_boundaries_have_unique_utc_identity():
    raw=planner_rules()
    raw['windows'][0].update(start='23:00',end='02:00')
    assert PlannerDefinition.from_mapping(raw).windows[0].end=='02:00'
    zone=get_zone('America/Los_Angeles')
    first=local_instant(date(2026,11,1),'01:30',zone,fold='first')
    second=local_instant(date(2026,11,1),'01:30',zone,fold='second')
    assert (second-first).total_seconds()==3600
    assert local_instant(date(2026,3,8),'02:30',zone,gap='skip') is None
    moved=local_instant(date(2026,3,8),'02:30',zone)
    assert moved.astimezone(zone).hour==3 and moved.astimezone(zone).minute==0
    assert first.tzinfo==timezone.utc
