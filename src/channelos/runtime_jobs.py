"""Transfer prepared timelines between workers and Qt without sharing SQL handles."""
from dataclasses import dataclass, replace

from .ad_break_engine import BreakPlanStore
from .runtime import CalendarTimeline, ChannelRuntime


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
    if isinstance(runtime.timeline, CalendarTimeline):
        runtime.timeline.break_store = None
    return PreparedRuntime(replace(runtime, break_store=None), has_store)


def adopt_runtime(prepared: PreparedRuntime | None, database_path):
    if prepared is None:
        return None
    store = BreakPlanStore(database_path, initialize=False) if prepared.has_break_store else None
    if isinstance(prepared.runtime.timeline, CalendarTimeline):
        prepared.runtime.timeline.break_store = store
    return replace(prepared.runtime, break_store=store)
