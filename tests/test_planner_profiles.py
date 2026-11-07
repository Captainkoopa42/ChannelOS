from copy import deepcopy
import json

import pytest

from channelos.broadcast_planner.contracts import PlannerDefinition, PlannerValidationError
from channelos.broadcast_planner.engine import Asset, Compiler
from channelos.broadcast_planner.profiles import ProfileStore, bind_profile, import_airings, validate_profile
from planner_helpers import planner_rules


def profile():
    return {'id':'morning','version':1,'name':'Morning block','slots':[
        {'id':'slot-a','name':'First show','start':'06:00','end':'07:00','bracket_minutes':60},
        {'id':'slot-b','name':'Later episode','start':'08:00','end':'09:00','bracket_minutes':60}]}


def test_profile_bindings_are_pinned_and_media_progression_is_channel_local(tmp_path):
    store=ProfileStore(tmp_path/'profiles')
    first=store.save(profile())
    raw=planner_rules(windows=[],cycle={'action':'once'})
    rules=PlannerDefinition.from_mapping(raw)
    a=bind_profile(rules,first,{'slot-a':'primary','slot-b':'primary'})
    raw['groups'][0]['asset_ids']=['other-1','other-2']
    b=bind_profile(PlannerDefinition.from_mapping(raw),first,{'slot-a':'primary','slot-b':'primary'})
    assets=[Asset(f'episode-{i}',3600) for i in range(1,4)]+[Asset('other-1',3600),Asset('other-2',3600)]
    left,right=Compiler(a,assets,channel=7),Compiler(b,assets,channel=12)
    left.day()
    assert right.cursors['primary'].remaining==['other-1','other-2']
    right.day()
    assert right.closed and not left.closed
    edited=deepcopy(first)
    edited['slots'][0]['start']='05:00'
    second=store.save(edited)
    assert second['version']==2
    assert a.profile_bindings[0].version==b.profile_bindings[0].version==1
    assert a.windows[0].start=='06:00'
    with pytest.raises(TypeError,match='immutable'):
        a.profile_bindings[0].snapshot['name']='Silently changed'
    reapplied=bind_profile(a,second,{'slot-a':'primary','slot-b':'primary'})
    assert reapplied.windows[0].start=='05:00'
    assert a.windows[0].start=='06:00'
    copied=store.save(second,duplicate=True)
    assert copied['id']!='morning' and copied['version']==1
    assert len(store.list())==2
    saved=[json.loads(path.read_text()) for path in (tmp_path/'profiles').glob('*.json')]
    assert sorted(item['version'] for item in saved if item['id']=='morning')==[1,2]


def test_valid_profile_ids_remain_distinct_with_windows_filename_rules(tmp_path):
    store=ProfileStore(tmp_path/'profiles')
    for identity in ('CON','con','season:holiday'):
        store.save({**profile(),'id':identity})
    assert {item['id'] for item in store.list()}=={'CON','con','season:holiday'}
    assert len({path.name.casefold() for path in store.directory.glob('*.json')})==3
    assert all(':' not in path.name for path in store.directory.glob('*.json'))


@pytest.mark.parametrize('key,value', [('asset_ids',['episode-1']),('cursor',3),('track_id','primary')])
def test_profile_slots_reject_media_and_progression(key,value):
    raw=profile()
    raw['slots'][0][key]=value
    with pytest.raises(PlannerValidationError):
        validate_profile(raw)


def test_reapply_refuses_to_overwrite_a_protected_local_window():
    rules=bind_profile(PlannerDefinition.from_mapping(planner_rules(windows=[])),profile(),{'slot-a':'primary','slot-b':'primary'})
    raw=rules.to_mapping()
    raw['windows'][0]['protected']=True
    with pytest.raises(PlannerValidationError,match='protected'):
        bind_profile(PlannerDefinition.from_mapping(raw),profile(),{'slot-a':'primary','slot-b':'primary'})


def test_csv_original_airings_keep_provenance_and_validate_time_offsets():
    csv='id,asset_id,starts_at,ends_at,source,accuracy,rerun\n'
    csv+='premiere,episode-1,1993-01-03T20:00:00Z,1993-01-03T21:00:00Z,User TV log,exact,false\n'
    record=import_airings(csv,'csv')[0]
    assert record.source=='User TV log' and not record.rerun
    with pytest.raises(PlannerValidationError,match='UTC offset'):
        import_airings(csv.replace('20:00:00Z','20:00:00'),'csv')


def test_manual_cycle_release_cannot_bypass_required_completion(tmp_path):
    from dataclasses import replace
    from datetime import timedelta
    from test_planner_runtime import planner_channel, START
    from channelos.runtime import ChannelRuntime, RuntimeStore
    channel=planner_channel(tmp_path,action='restart')
    raw=channel.definition.programming.planner.to_mapping()
    raw['cycle']['boundary']='manual'
    channel=replace(channel,definition=replace(channel.definition,programming=replace(channel.definition.programming,planner=PlannerDefinition.from_mapping(raw))))
    store=RuntimeStore(tmp_path/'runtime.db')
    current=ChannelRuntime.open(channel,store,now=START)
    with pytest.raises(PlannerValidationError,match='have not been met'):
        current.timeline.release_manual_cycle(START+timedelta(hours=13))
    current.broadcast_at(START+timedelta(days=1,hours=8))
    safe=current.timeline.release_manual_cycle(START+timedelta(days=1,hours=8))
    assert safe==START+timedelta(days=1,hours=8)
    reopened=ChannelRuntime.open(channel,store,now=safe+timedelta(hours=4,minutes=5))
    assert reopened.broadcast_at(safe+timedelta(hours=4,minutes=5)).cycle_index==1
