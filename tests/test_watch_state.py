from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from channelos.runtime import (
    RuntimeStore,
    on_demand_watch_is_complete,
    on_demand_watch_is_resumable,
)


def test_runtime_store_round_trips_on_demand_watch_state(tmp_path) -> None:
    store = RuntimeStore(tmp_path / "runtime.db")
    watched_at = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)

    saved = store.save_on_demand_watch(
        "sha256:movie",
        642.5,
        7200.0,
        now=watched_at,
    )
    loaded = store.load_on_demand_watch("sha256:movie")

    assert loaded == saved
    assert loaded is not None
    assert loaded.resumable
    assert loaded.progress_fraction == pytest.approx(642.5 / 7200.0)


def test_recent_watch_state_is_ordered_and_scoped_per_viewer(tmp_path) -> None:
    store = RuntimeStore(tmp_path / "runtime.db")
    first = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)
    store.save_on_demand_watch("sha256:first", 30.0, 120.0, now=first)
    store.save_on_demand_watch(
        "sha256:second",
        40.0,
        120.0,
        now=first + timedelta(minutes=1),
    )
    store.save_on_demand_watch(
        "sha256:other-viewer",
        50.0,
        120.0,
        viewer_id="other",
        now=first + timedelta(minutes=2),
    )

    assert [item.asset_id for item in store.list_on_demand_watch()] == [
        "sha256:second",
        "sha256:first",
    ]


def test_only_meaningful_unfinished_positions_are_resumable() -> None:
    assert not on_demand_watch_is_resumable(5.0, 120.0)
    assert on_demand_watch_is_resumable(30.0, 120.0)
    assert not on_demand_watch_is_resumable(114.0, 120.0)
    assert on_demand_watch_is_complete(114.0, 120.0)


def test_completed_watch_restarts_instead_of_resuming(tmp_path) -> None:
    store = RuntimeStore(tmp_path / "runtime.db")
    saved = store.save_on_demand_watch(
        "sha256:complete",
        119.0,
        120.0,
    )

    assert saved.completed
    assert not saved.resumable
