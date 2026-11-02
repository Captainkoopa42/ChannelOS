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


def test_arbitration_resolves_overlapping_windows_by_priority():
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    low = BreakOpportunityScheduler.for_occurrence(
        ProgramOccurrence("low", 2, "show-low", start, start + timedelta(minutes=10)),
        BreakPolicy(enabled=True, breakpoints_seconds=(60,), duration_seconds=90, priority=1),
    )[0]
    high = BreakOpportunityScheduler.for_occurrence(
        ProgramOccurrence("high", 1, "show-high", start, start + timedelta(minutes=10)),
        BreakPolicy(enabled=True, breakpoints_seconds=(120,), duration_seconds=90, priority=5),
    )[0]
    assert BreakOpportunityScheduler.arbitrate((low, high)) == (high,)


def test_record_aired_rejects_asset_not_in_committed_segment(tmp_path):
    store = BreakPlanStore(tmp_path / "breaks.db")
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    plan = BreakPlan("plan-check", "opp-check", "occ-check", 7, at, 30,
                     (PlannedSegment("ad-real", 0, 0, 30),),
                     "best_fit", "strict_fit")
    store.commit(plan)
    try:
        store.record_aired("plan-check", 0, "ad-forged", aired_at=at)
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched aired asset must be rejected")
    assert store.record_aired("plan-check", 0, "ad-real", aired_at=at)
    store.close()


def test_selection_rejects_non_finite_budget_and_duplicate_asset_ids():
    engine = AdSelectionEngine()
    try:
        engine.select((AdCandidate("ad-a", 10),), float("inf"))
    except ValueError:
        pass
    else:
        raise AssertionError("infinite budgets must be rejected")
    try:
        engine.select((AdCandidate("same", 10), AdCandidate("same", 20)), 30)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate asset IDs must be rejected")


def test_break_plan_rejects_segments_that_overrun_reserved_window():
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    try:
        BreakPlan("plan-overrun", "opp-overrun", "occ-overrun", 7, at, 30,
                  (PlannedSegment("ad-too-long", 0, 0, 31),),
                  "best_fit", "strict_fit")
    except ValueError:
        pass
    else:
        raise AssertionError("a plan must not overrun its reserved break window")


def test_planned_segment_rejects_non_finite_offsets():
    try:
        PlannedSegment("ad-bad", float("nan"), 0, 10)
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite segment offsets must be rejected")


def test_committed_plan_and_airing_ledger_survive_store_reopen(tmp_path):
    database = tmp_path / "shared-runtime.db"
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    plan = BreakPlan(
        "plan-recovery", "opp-recovery", "occ-recovery", 7, at, 40,
        (
            PlannedSegment("ad-a", 0, 0, 20),
            PlannedSegment("ad-b", 20, 0, 20),
        ),
        "complete_rotation", "strict_fit",
    )
    first = BreakPlanStore(database)
    assert first.commit(plan) == plan
    assert first.record_aired("plan-recovery", 0, "ad-a", aired_at=at)
    first.close()

    recovered = BreakPlanStore(database)
    assert recovered.load_opportunity("opp-recovery") == plan
    assert recovered.load_plan("plan-recovery") == plan
    assert recovered.aired_segments("plan-recovery") == (
        (0, "ad-a", at),
    )
    assert recovered.play_counts() == {"ad-a": 1}
    recovered.close()


def test_unknown_plan_recovery_returns_none(tmp_path):
    store = BreakPlanStore(tmp_path / "empty.db")
    assert store.load_opportunity("missing") is None
    assert store.load_plan("missing") is None
    assert store.aired_segments("missing") == ()
    store.close()


def test_runtime_can_query_committed_plans_by_channel_and_instant(tmp_path):
    store = BreakPlanStore(tmp_path / "runtime.db")
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    plan = BreakPlan(
        "plan-runtime", "opp-runtime", "occ-runtime", 9, start, 60,
        (PlannedSegment("ad-runtime", 0, 0, 60),),
        "best_fit", "strict_fit",
    )
    store.commit(plan)
    assert store.active_plan_at(9, start + timedelta(seconds=30)) == plan
    assert store.active_plan_at(9, start + timedelta(seconds=60)) is None
    assert store.active_plan_at(8, start + timedelta(seconds=30)) is None
    assert store.plans_for_channel(
        9, start=start + timedelta(seconds=30),
        end=start + timedelta(seconds=90),
    ) == (plan,)
    store.close()



def test_air_ledger_only_advances_after_scheduled_completion(tmp_path):
    store = BreakPlanStore(tmp_path / "ledger.db")
    start = datetime(2026, 10, 30, 12, tzinfo=UTC)
    plan = BreakPlan(
        "air-plan", "air-opportunity", "air-occurrence", 7, start, 20,
        (PlannedSegment("ad-one", 0, 0, 10),
         PlannedSegment("ad-two", 10, 0, 10)),
        "least_played", "strict_fit",
    )
    store.commit(plan)
    assert store.reconcile_completed(7, through=start + timedelta(seconds=9)) == 0
    assert store.play_counts() == {}
    assert store.reconcile_completed(7, through=start + timedelta(seconds=10)) == 1
    assert store.play_counts() == {"ad-one": 1}
    assert store.reconcile_completed(7, through=start + timedelta(seconds=21)) == 1
    assert store.play_counts() == {"ad-one": 1, "ad-two": 1}
    assert store.reconcile_completed(7, through=start + timedelta(seconds=60)) == 0
    assert store.diagnostics(7)["completedAirings"] == 2
    store.close()


def test_view_history_is_separate_and_requires_proven_consumption(tmp_path):
    import pytest

    store = BreakPlanStore(tmp_path / "views.db")
    start = datetime(2026, 10, 30, 12, tzinfo=UTC)
    plan = BreakPlan(
        "view-plan", "view-opportunity", "view-occurrence", 3, start, 5,
        (PlannedSegment("ad-one", 0, 0, 5),),
        "best_fit", "strict_fit",
    )
    store.commit(plan)
    with pytest.raises(ValueError, match="full-duration"):
        store.record_viewed("view-plan", 0, "ad-one",
                            consumed_seconds=1, completed_at=start)
    assert store.record_viewed("view-plan", 0, "ad-one",
                               consumed_seconds=5, completed_at=start + timedelta(seconds=5))
    assert not store.record_viewed("view-plan", 0, "ad-one",
                                   consumed_seconds=5, completed_at=start + timedelta(seconds=6))
    assert store.viewer_counts(3) == {"ad-one": 1}
    assert store.play_counts() == {}
    assert store.diagnostics(3)["completedViewings"] == 1
    store.close()



def test_best_fit_finds_exact_combination_greedy_misses():
    candidates = (
        AdCandidate("almost-fills", 88),
        AdCandidate("part-one", 60),
        AdCandidate("part-two", 40),
    )
    engine = AdSelectionEngine()
    selected = engine.select(candidates, 100, strategy="best_fit", seed="stable")
    assert {item.asset_id for item in selected} == {"part-one", "part-two"}
    assert sum(item.duration_seconds for item in selected) == 100
    assert engine.select(candidates, 100, strategy="best_fit", seed="stable") == selected
