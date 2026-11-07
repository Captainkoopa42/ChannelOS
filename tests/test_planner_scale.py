import pytest

from channelos.broadcast_planner.contracts import PlannerDefinition
from channelos.broadcast_planner.engine import Asset, PlannerCancelled, forecast
from planner_helpers import planner_rules


def test_month_view_returns_counts_and_nearby_details_are_bounded():
    raw=planner_rules(cycle={'action':'once'})
    raw['groups'][0]['asset_ids']=[f'item-{i}' for i in range(10000)]
    raw['windows']=[{'id':'daily','track_id':'primary','start':'00:00','end':'24:00','bracket_minutes':1}]
    rules=PlannerDefinition.from_mapping(raw)
    media=[Asset(key,60) for key in raw['groups'][0]['asset_ids']]
    monthly=forecast(rules,media,view_days=31,max_seconds=10)
    assert monthly['confidence']=='Exact'
    assert monthly['segments']==[]
    assert len(monthly['calendar_days'])==31
    assert monthly['calendar_days']['2026-06-01']['programs']==1440
    weekly=forecast(rules,media,view_days=7,max_seconds=10)
    assert len(weekly['segments'])==3000 and weekly['view_truncated']
    assert weekly['confidence']=='Exact'
    calls=0
    def cancel():
        nonlocal calls
        calls+=1
        return calls>1000
    with pytest.raises(PlannerCancelled):
        forecast(rules,media,cancel=cancel,max_seconds=10)
