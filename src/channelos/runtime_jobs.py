"""Transfer prepared timelines between workers and Qt without sharing SQL handles."""
from dataclasses import dataclass, replace

from .ad_break_engine import BreakPlanStore
from .runtime import CalendarTimeline, ChannelRuntime
from .broadcast_planner.runtime import PlannerTimeline


@dataclass(frozen=True)
class PreparedRuntime:
    runtime: ChannelRuntime
    has_break_store: bool


def release_runtime(runtime: ChannelRuntime | None):
    if runtime is None:
        return None
    has_store = runtime.break_store is not None
    if has_store:
        runtime.break_store.close()
    if isinstance(runtime.timeline, (CalendarTimeline, PlannerTimeline)):
        runtime.timeline.break_store = None
        if isinstance(runtime.timeline,PlannerTimeline):
            runtime.timeline.bind_break_store(None)
    return PreparedRuntime(replace(runtime, break_store=None), has_store)


def adopt_runtime(prepared: PreparedRuntime | None, database_path):
    if prepared is None:
        return None
    store = BreakPlanStore(database_path, initialize=False) if prepared.has_break_store else None
    if isinstance(prepared.runtime.timeline, (CalendarTimeline, PlannerTimeline)):
        prepared.runtime.timeline.break_store = store
        if isinstance(prepared.runtime.timeline,PlannerTimeline):
            prepared.runtime.timeline.bind_break_store(store)
    return replace(prepared.runtime, break_store=store)
