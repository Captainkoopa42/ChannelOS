from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine

import channelos
from test_couch_qml import FakeChannelOS

HOUR_MS = 3_600_000
START_MS = 1_777_000_200_000


def _program(channel: int, index: int, start_ms: int, end_ms: int) -> dict:
    return {
        "channelNumber": channel, "scheduleId": f"ch{channel}-p{index}",
        "title": f"Show {channel}.{index}", "startMs": start_ms, "endMs": end_ms,
        "durationSeconds": (end_ms - start_ms) / 1000,
        "isCurrent": index == 0, "isPast": False, "isFuture": index > 0,
    }


def _row(channel: int) -> dict:
    programs = [_program(channel, i, START_MS + i * HOUR_MS, START_MS + (i + 1) * HOUR_MS)
                for i in range(3)]
    segments = [dict(program, firstProgramIndex=i, lastProgramIndex=i, isCluster=False)
                for i, program in enumerate(programs)]
    return {"channelNumber": channel, "displayNumber": f"{channel:03d}",
            "channelName": f"Channel {channel}", "isUnassigned": False,
            "programs": programs, "displaySegments": segments}


def _pump(app, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()


def _guide(app):
    controller = FakeChannelOS()
    controller._snapshot = {"generatedAtMs": START_MS + 60_000, "horizonStartMs": START_MS,
                            "horizonEndMs": START_MS + 3 * HOUR_MS,
                            "rows": [_row(1), _row(2), _row(3)]}
    engine = QQmlApplicationEngine()
    video_window = QWindow()
    engine.rootContext().setContextProperty("channelOS", controller)
    engine.rootContext().setContextProperty("channelOSVideoWindow", video_window)
    engine.load(QUrl.fromLocalFile(str(Path(channelos.__file__).resolve().parent / "qml" / "Main.qml")))
    root = engine.rootObjects()[0]
    root.show()
    root.setProperty("screen", "guide")
    controller.snapshotChanged.emit()
    _pump(app)
    return controller, engine, video_window, root


def _segments(item, found=None) -> list:
    # Repeater delegates live in the visual item tree, not the QObject tree.
    found = [] if found is None else found
    for child in item.childItems():
        if child.objectName() == "guideProgramSegment":
            found.append(child)
        _segments(child, found)
    return found


def _highlighted(root) -> list[str]:
    segments = _segments(root.contentItem())
    assert segments, "Guide program segments were not created"
    return [segment.property("broadcastSegment")["scheduleId"] for segment in segments
            if segment.property("selectedSegment")]


def test_selected_guide_program_is_highlighted_and_follows_selection() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    _controller, engine, _video, root = _guide(app)
    try:
        root.setProperty("selectedRow", 1)
        root.setProperty("selectedProgram", 0)
        _pump(app)
        assert _highlighted(root) == ["ch2-p0"]

        root.setProperty("selectedProgram", 2)
        _pump(app)
        assert _highlighted(root) == ["ch2-p2"]

        root.setProperty("selectedRow", 2)
        _pump(app)
        assert _highlighted(root) == ["ch3-p2"]
    finally:
        root.close()
        engine.deleteLater()
        app.processEvents()


def _find(item, name):
    for child in item.childItems():
        if child.objectName() == name:
            return child
        found = _find(child, name)
        if found is not None:
            return found
    return None


def test_guide_header_names_the_day_being_browsed_and_cuts_early_programs() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller, engine, _video, root = _guide(app)
    try:
        label = _find(root.contentItem(), "guideDayLabel")
        assert label.property("text").startswith("TODAY")
        snapshot = dict(controller._snapshot)
        snapshot.update(horizonStartMs=START_MS + 24 * HOUR_MS + HOUR_MS // 2,
                        horizonEndMs=START_MS + 27 * HOUR_MS + HOUR_MS // 2, isLiveWindow=False)
        snapshot["rows"] = [_row(1)]
        for program in snapshot["rows"][0]["programs"] + snapshot["rows"][0]["displaySegments"]:
            program["startMs"] += 24 * HOUR_MS
            program["endMs"] += 24 * HOUR_MS
        controller._snapshot = snapshot
        controller.snapshotChanged.emit()
        _pump(app)
        assert not label.property("text").startswith(("TODAY", "YESTERDAY"))
        # The first program began half an hour before the window: it is drawn
        # from the left edge to its own end, not shifted to the right.
        segment = next(s for s in _segments(root.contentItem())
                       if s.property("broadcastSegment")["scheduleId"] == "ch1-p0")
        area = segment.parentItem().width()
        assert abs(segment.property("width") - area / 6) < 3
    finally:
        root.close()
        engine.deleteLater()
        app.processEvents()
