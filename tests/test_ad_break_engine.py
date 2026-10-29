from datetime import datetime, timedelta, timezone

from channelos.ad_break_engine import (
    AdCandidate, AdSelectionEngine, BreakOpportunityScheduler, BreakPlan,
    BreakPlanStore, BreakPolicy, PlannedSegment, ProgramOccurrence,
)

UTC = timezone.utc


def occurrence():
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    return ProgramOccurrence("occ-1", 7, "show-1", start, start + timedelta(minutes=30))


def test_scheduler_merges_duplicate_trigger_instants_and_uses_priority():
    item = occurrence()
    policy = BreakPolicy(enabled=True, interval_seconds=300,
                         breakpoints_seconds=(300, 600), priority=2)
    opportunities = BreakOpportunityScheduler.for_occurrence(item, policy)
    assert [x.scheduled_at for x in opportunities] == [
        item.starts_at + timedelta(minutes=5),
        item.starts_at + timedelta(minutes=10),
        item.starts_at + timedelta(minutes=15),
        item.starts_at + timedelta(minutes=20),
        item.starts_at + timedelta(minutes=25),
    ]
    same_time = (opportunities[0],)
    assert BreakOpportunityScheduler.arbitrate(same_time) == same_time


def test_least_played_and_complete_rotation_use_history():
    candidates = tuple(AdCandidate(f"ad-{i}", 10) for i in range(3))
    engine = AdSelectionEngine()
    counts = {"ad-0": 4, "ad-1": 1, "ad-2": 0}
    plan = engine.select(candidates, 10, strategy="least_played",
                         play_counts=counts, seed="stable")
    assert plan[0].asset_id == "ad-2"
    rotation = engine.select(candidates, 20, strategy="complete_rotation",
                             play_counts=counts, seed="stable")
    assert [x.asset_id for x in rotation] == ["ad-2", "ad-1"]


def test_smoosh_trims_only_within_configured_limit():
    engine = AdSelectionEngine()
    plan = engine.select((AdCandidate("ad-long", 110),), 100,
                         timing_policy="smoosh", smoosh_minimum_seconds=80,
                         smoosh_max_trim_seconds=15)
    assert len(plan) == 1
    assert plan[0].duration_seconds == 100
    assert plan[0].trimmed_seconds == 10


def test_plan_commit_is_immutable_and_history_is_idempotent(tmp_path):
    store = BreakPlanStore(tmp_path / "breaks.db")
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    first = BreakPlan("plan-a", "opp-a", "occ-a", 7, at, 30,
                      (PlannedSegment("ad-a", 0, 0, 30),),
                      "best_fit", "strict_fit")
    changed = BreakPlan("plan-b", "opp-a", "occ-a", 7, at, 30,
                        (PlannedSegment("ad-b", 0, 0, 30),),
                        "largest", "strict_fit")
    assert store.commit(first) == first
    assert store.commit(changed) == first
    assert store.record_aired("plan-a", 0, "ad-a", aired_at=at)
    assert not store.record_aired("plan-a", 0, "ad-a", aired_at=at + timedelta(seconds=1))
    assert store.play_counts() == {"ad-a": 1}
    store.close()

def test_expand_uses_only_its_configured_borrow_limit():
    engine = AdSelectionEngine()
    candidates = (AdCandidate("ad-1", 110), AdCandidate("ad-2", 125))
    within_limit = engine.select(candidates, 100, timing_policy="expand",
                                 expand_max_seconds=15)
    beyond_limit = engine.select(candidates, 100, timing_policy="expand",
                                 expand_max_seconds=5)
    assert sum(x.duration_seconds for x in within_limit) == 110
    assert sum(x.duration_seconds for x in beyond_limit) == 0
