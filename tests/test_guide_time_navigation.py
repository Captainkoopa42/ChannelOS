"""Guide time navigation: two weeks back and ahead, stable on every channel type."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from channelos.control import ControlCommand, ControlIntent
from channelos.couch_model import GUIDE_REACH, build_couch_snapshot, clamp_guide_start
from channelos.guide import GuideService

from test_couch_model import make_service

UTC = timezone.utc
EPOCH = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
HOUR_MS = 3_600_000


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _covers_window(row: dict, snapshot: dict) -> None:
    programs = row["programs"]
    assert programs, row["channelNumber"]
    assert programs[0]["startMs"] <= snapshot["horizonStartMs"]
    assert programs[-1]["endMs"] >= snapshot["horizonEndMs"]
    for earlier, later in zip(programs, programs[1:]):
        assert earlier["endMs"] == later["startMs"], "Guide rows must be gapless"


def test_clamp_keeps_the_guide_within_two_weeks_on_half_hours() -> None:
    now = EPOCH + timedelta(minutes=47)
    live = EPOCH + timedelta(minutes=30)
    assert clamp_guide_start(now, now) == live
    assert clamp_guide_start(now + timedelta(days=40), now) == live + GUIDE_REACH
    assert clamp_guide_start(now - timedelta(days=40), now) == live - GUIDE_REACH
    assert clamp_guide_start(now + timedelta(hours=5, minutes=10), now) == live + timedelta(hours=5)


@pytest.mark.parametrize("days", [-14, -3, 1, 7, 14])
def test_sequential_guide_is_gapless_two_weeks_out(tmp_path: Path, days: int) -> None:
    now = EPOCH + timedelta(days=15, minutes=7)
    service = make_service(tmp_path, EPOCH)
    snapshot = build_couch_snapshot(service, at=now, start=now + timedelta(days=days))
    assert snapshot["isLiveWindow"] is False
    assert snapshot["earliestStartMs"] <= snapshot["horizonStartMs"] <= snapshot["latestStartMs"]
    for row in snapshot["rows"][1:]:
        _covers_window(row, snapshot)
        assert not any(program.get("isOffAir") for program in row["programs"])
        assert not any(program["isCurrent"] for program in row["programs"])


def test_guide_before_a_channel_began_is_honest_off_air(tmp_path: Path) -> None:
    now = EPOCH + timedelta(hours=1, minutes=10)
    service = make_service(tmp_path, EPOCH)
    snapshot = build_couch_snapshot(service, at=now, start=EPOCH - timedelta(hours=2))
    for row in snapshot["rows"][1:]:
        _covers_window(row, snapshot)
        first = row["programs"][0]
        assert first["isOffAir"] is True
        assert first["endMs"] == _ms(EPOCH)
        assert row["programs"][1]["startMs"] == _ms(EPOCH)
        assert not row["programs"][1]["isOffAir"]
        offair = [segment for segment in row["displaySegments"] if segment.get("isOffAir")]
        assert len(offair) == 1 and not offair[0]["isCluster"]


def test_far_window_does_not_change_the_live_guide(tmp_path: Path) -> None:
    now = EPOCH + timedelta(minutes=7)
    service = make_service(tmp_path, EPOCH)
    before = build_couch_snapshot(service, at=now)
    build_couch_snapshot(service, at=now, start=now + timedelta(days=14))
    build_couch_snapshot(service, at=now, start=now - timedelta(days=14))
    after = build_couch_snapshot(service, at=now)
    assert after["isLiveWindow"] is True
    assert [[p["scheduleId"] for p in row["programs"]] for row in after["rows"]] == \
        [[p["scheduleId"] for p in row["programs"]] for row in before["rows"]]


# --- Ad channels: catch-up walks forward in bounded slices -----------------------------------

def _walker():
    from types import SimpleNamespace
    from PySide6.QtCore import QObject
    from channelos.guide_projection import install_incremental_guide_support
    module = SimpleNamespace(BroadcasterCouchController=QObject)
    install_incremental_guide_support(module)
    return module.BroadcasterCouchController._walk_catch_up


def test_ad_channel_far_guide_walks_catch_up_in_bounded_steps(tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    from test_ad_broadcast_integration import EPOCH as AD_EPOCH, open_runtime, setup
    library, definition, _ = setup(tmp_path, selection_strategy="least_played", break_duration_seconds=15)
    runtime, _store = open_runtime(tmp_path, library, definition)
    walk = _walker()
    target = AD_EPOCH + timedelta(hours=6)
    steps, cursors = 0, []
    while walk(runtime, target):
        steps += 1
        cursors.append(runtime.break_store.catchup_cursor(runtime.channel_number))
        assert steps < 100, "catch-up walk must converge"
    assert steps >= 6
    assert cursors == sorted(cursors) and len(set(cursors)) == len(cursors)
    # The cursor stops at the program airing at the target, never beyond it.
    remaining = target - runtime.break_store.catchup_cursor(runtime.channel_number)
    assert timedelta(0) <= remaining < timedelta(hours=2)
    # Projecting the far window afterwards is cheap and still writes no airings.
    rows = GuideService((runtime,)).horizon(target, target + timedelta(hours=3), generated_at=AD_EPOCH).rows
    assert rows[0].programs
    assert runtime.break_store.play_counts() == {}

    # The walked guide matches a fresh runtime that projected the same window directly.
    fresh, _ = open_runtime(tmp_path, library, definition, "fresh")
    direct = GuideService((fresh,)).horizon(target, target + timedelta(hours=3), generated_at=AD_EPOCH).rows
    assert [(p.schedule_id, p.start_utc, p.end_utc) for p in rows[0].programs] == \
        [(p.schedule_id, p.start_utc, p.end_utc) for p in direct[0].programs]


# --- Controller: paging, clamping and cached windows -----------------------------------------

def _wait_rows(app, controller, timeout=10.0) -> None:
    controller.requestGuideRows(0, len(controller.snapshot["rows"]))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if not any(row.get("isPending") for row in controller.snapshot["rows"]):
            return
    raise AssertionError("Guide rows did not finish loading")


def test_controller_pages_two_weeks_and_reuses_cached_windows(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("PySide6")
    from test_performance_operations import controller_fixture, incremental_controller_type
    original = GuideService.iter_programs
    projected = []

    def counted(runtime, start, *args):
        projected.append((runtime.channel_number, start))
        yield from original(runtime, start, *args)

    monkeypatch.setattr(GuideService, "iter_programs", staticmethod(counted))
    app, controller, _root = controller_fixture(tmp_path, incremental_controller_type())
    try:
        _wait_rows(app, controller)
        live_start = controller.snapshot["horizonStartMs"]
        assert controller.snapshot["isLiveWindow"] is True

        result = controller.shiftGuideWindow(180)
        assert result["ok"] and not result["isLive"]
        assert controller.snapshot["horizonStartMs"] == live_start + 3 * HOUR_MS
        assert controller.snapshot["isLiveWindow"] is False
        _wait_rows(app, controller)

        loaded = len(projected)
        assert controller.shiftGuideWindow(-180)["isLive"]
        assert not any(row.get("isPending") for row in controller.snapshot["rows"])
        assert controller.shiftGuideWindow(180)["ok"]
        assert not any(row.get("isPending") for row in controller.snapshot["rows"]), \
            "a recently viewed window must come back from cache"
        assert len(projected) == loaded

        far = controller.shiftGuideWindow(60 * 24 * 30)
        assert far["clamped"] and "14 days" in far["message"]
        assert controller.snapshot["horizonStartMs"] == controller.snapshot["latestStartMs"]
        _wait_rows(app, controller, timeout=30)
        for row in controller.snapshot["rows"]:
            if not row.get("isUnassigned"):
                _covers_window(row, controller.snapshot)
        assert not controller.shiftGuideWindow(30)["ok"]

        back = controller.shiftGuideWindow(-60 * 24 * 60)
        assert back["clamped"]
        assert controller.snapshot["horizonStartMs"] == controller.snapshot["earliestStartMs"]
        _wait_rows(app, controller, timeout=30)

        assert controller.guideWindowToNow()["moved"]
        assert controller.snapshot["horizonStartMs"] == live_start
        assert controller.snapshot["isLiveWindow"] is True
    finally:
        controller.stop()


# --- Remote keys ----------------------------------------------------------------------------

def _router(tmp_path: Path):
    from PySide6.QtGui import QWindow
    from channelos.couch_qt import CouchKeyFilter
    from test_performance_operations import controller_fixture
    app, controller, _root = controller_fixture(tmp_path)
    window = QWindow()
    for name, value in {"screen": "guide", "selectedRow": 1, "selectedProgram": 0,
                        "guideFocusMs": 0.0, "guideSelectionScheduleId": "",
                        "infoVisible": False, "statusMessage": ""}.items():
        window.setProperty(name, value)
    return app, controller, window, CouchKeyFilter(controller, window)


def _selected(controller, window) -> dict:
    row = controller.snapshot["rows"][int(window.property("selectedRow"))]
    return row["programs"][int(window.property("selectedProgram"))]


def test_remote_keys_page_time_and_scroll_at_the_edges(tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    app, controller, window, router = _router(tmp_path)
    try:
        def send(intent):
            assert router.dispatch_command(ControlCommand(intent))
            app.processEvents()

        live_start = controller.snapshot["horizonStartMs"]
        send(ControlIntent.GUIDE_NOW)
        assert _selected(controller, window)["isCurrent"]

        # Right past the last program pages forward and lands on the next one.
        last = controller.snapshot["rows"][1]["programs"][-1]
        window.setProperty("selectedProgram", len(controller.snapshot["rows"][1]["programs"]) - 1)
        send(ControlIntent.RIGHT)
        assert controller.snapshot["horizonStartMs"] > live_start
        assert _selected(controller, window)["startMs"] == last["endMs"]

        # Left past the first program pages back to the program before it.
        first = controller.snapshot["rows"][1]["programs"][0]
        window.setProperty("selectedProgram", 0)
        send(ControlIntent.LEFT)
        assert _selected(controller, window)["endMs"] == first["startMs"]

        send(ControlIntent.GUIDE_NOW)
        assert controller.snapshot["horizonStartMs"] == live_start
        assert _selected(controller, window)["isCurrent"]

        send(ControlIntent.FAST_FORWARD)
        assert controller.snapshot["horizonStartMs"] == live_start + 3 * HOUR_MS
        send(ControlIntent.SKIP_FORWARD)
        assert controller.snapshot["horizonStartMs"] == live_start + 27 * HOUR_MS
        program = _selected(controller, window)
        assert program["isFuture"]

        # Up/Down away from now keep the time column instead of snapping to now.
        send(ControlIntent.DOWN)
        focus = float(window.property("guideFocusMs"))
        moved = _selected(controller, window)
        assert moved["startMs"] <= focus < moved["endMs"] or moved["startMs"] >= controller.snapshot["horizonStartMs"]

        # Future programs explain themselves instead of leaving the Guide.
        send(ControlIntent.SELECT)
        assert window.property("screen") == "guide"

        send(ControlIntent.SKIP_BACK)
        send(ControlIntent.SKIP_BACK)
        assert controller.snapshot["horizonStartMs"] == live_start - 21 * HOUR_MS

        for _ in range(20):
            send(ControlIntent.SKIP_FORWARD)
        assert controller.snapshot["horizonStartMs"] == controller.snapshot["latestStartMs"]

        send(ControlIntent.GUIDE)
        assert controller.snapshot["isLiveWindow"] is True
        assert float(window.property("guideFocusMs")) == 0
    finally:
        window.close()
        controller.stop()


@pytest.mark.parametrize("key,intent", [
    ("Key_PageUp", ControlIntent.REWIND), ("Key_PageDown", ControlIntent.FAST_FORWARD),
    ("Key_Comma", ControlIntent.SKIP_BACK), ("Key_Period", ControlIntent.SKIP_FORWARD),
])
def test_keyboard_paging_keys(key, intent) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from channelos.couch_qt import CouchKeyFilter
    assert CouchKeyFilter.command_for_key(getattr(Qt.Key, key)) == ControlCommand(intent)
