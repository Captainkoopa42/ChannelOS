"""The Broadcast Planner lives in Channel Studio as its Planner tab."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Fusion")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression

from channelos import broadcaster_qt
from channelos.channel_jobs import install_channel_operations_support
from channelos.planner_qt import install_planner_support, planner_iso_to_local, planner_local_to_iso
from test_studio_autofill_qt import _controller

QML = Path(__file__).resolve().parents[1] / "src" / "channelos" / "qml"


def until(predicate, seconds: float = 20) -> None:
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(.005)
    assert predicate()


def _studio(tmp_path: Path):
    app = QGuiApplication.instance() or QGuiApplication([])
    original, media_root = _controller(tmp_path)
    library = original._library
    asset = library.list_online_media_for_source(media_root)[0].asset.asset_id
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    original._broadcaster.create({
        "channel": 9, "name": "Calendar Nine", "sources": [str(media_root)], "mode": "calendar",
        "fillerMode": "sequential", "preserveEpisodeOrder": False, "avoidRepeatDays": 0, "numberWidth": 3,
        "calendarBlocks": [{"assetId": asset, "startUtc": start.isoformat()}],
    })
    module = SimpleNamespace(BroadcasterCouchController=broadcaster_qt.BroadcasterCouchController,
                             BroadcasterKeyFilter=broadcaster_qt.BroadcasterKeyFilter)
    install_channel_operations_support(module)
    install_planner_support(module)
    controller = module.BroadcasterCouchController(original._service, original._actions.runtime,
                                                   original._library, original._broadcaster, original._runtime_store)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    engine.loadData(b'import QtQuick; import QtQuick.Controls; ApplicationWindow { width:1600; height:1000; '
                    b'visible:true; property string screen:"home"; property int studioChannelNumber:9; '
                    b'property int plannerChannelNumber:0; property string statusMessage:"" }')
    host = engine.rootObjects()[0]
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "ChannelStudioScreen.qml")))
    until(lambda: not component.isLoading())
    assert component.isReady(), [e.toString() for e in component.errors()]
    studio = component.create()
    studio.setParentItem(host.contentItem())
    host._channelos_keep = (component, studio)
    studio.setProperty("hostWindow", host)
    host.setProperty("screen", "studio")

    def evaluate(code):
        expression = QQmlExpression(engine.contextForObject(studio), studio, code)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value.toVariant() if hasattr(value, "toVariant") else value

    return app, original, controller, engine, host, studio, evaluate


def _screenshot(host, name: str) -> None:
    directory = os.environ.get("CHANNELOS_PLANNER_SCREENSHOTS")
    if not directory:
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    for _ in range(6):
        QCoreApplication.processEvents()
        time.sleep(.03)
    image = host.grabWindow()
    assert not image.isNull() and image.save(str(path / name), "PNG")


def test_planner_tab_converts_a_calendar_channel_with_one_identity_and_apply(tmp_path: Path) -> None:
    app, original, controller, engine, host, studio, evaluate = _studio(tmp_path)
    try:
        until(lambda: evaluate("calendarBlocks.count") == 1 and not evaluate("loading"))
        assert evaluate("viewMode") != "planner", "calendar channels open on the calendar"
        evaluate('viewMode = "planner"')
        until(lambda: evaluate("plannerPanel.loaded") and controller._planner_thread is None)
        # Studio owns the identity and Apply: the planner's own are hidden.
        assert evaluate("plannerPanel.embedded")
        assert evaluate("plannerPanel.mediaBin.length") == 1
        assert evaluate("timelinePanel.visible") is False
        # Only visiting the tab never converts the channel.
        assert evaluate("plannerPanel.rules.tracks.length") == 0 and not evaluate("plannerPanel.hasRules")

        # Adding the first rule to a calendar channel asks before converting.
        evaluate("plannerPanel.addTrack(plannerPanel.mediaBin[0], false)")
        assert evaluate("convertDialog.visible")
        assert evaluate("plannerPanel.rules.tracks.length") == 0
        evaluate("convertDialog.reject()")
        app.processEvents()
        assert evaluate("plannerPanel.rules.tracks.length") == 0
        assert not evaluate("plannerPanel.dirty")

        evaluate("plannerPanel.addTrack(plannerPanel.mediaBin[0], false)")
        evaluate("convertDialog.accept()")
        app.processEvents()
        assert evaluate("plannerPanel.rules.tracks.length") == 1
        assert evaluate("draftDirty")
        until(lambda: evaluate("plannerPanel.previewCurrent") and controller._planner_thread is None)
        assert evaluate("plannerPanel.forecast.confidence") != "Blocked", evaluate("plannerPanel.feedback")
        # A second rule does not ask again.
        evaluate("plannerPanel.addTrack(plannerPanel.mediaBin[0], true)")
        assert not evaluate("convertDialog.visible")
        until(lambda: evaluate("plannerPanel.previewCurrent") and controller._planner_thread is None)
        _screenshot(host, "studio-planner-tab-1600.png")

        evaluate('channelNameField.text = "Planner Nine"')
        evaluate("applyDraft()")
        until(lambda: controller._mutation_thread is None and not evaluate("pendingChannelSave"))
        assert not evaluate("feedbackIsError"), evaluate("feedbackMessage")
        saved = controller._broadcaster._records[9].definition
        assert saved.name == "Planner Nine"
        assert saved.programming.mode == "planner"
        assert len(saved.programming.planner.tracks) == 2
        assert evaluate("plannerIntent") is not None
        until(lambda: evaluate("plannerPanel.loaded") and controller._planner_thread is None)
        assert not evaluate("draftDirty")
        # Studio blocks survive as protected manual blocks of the planner.
        draft = controller._broadcaster.studio_draft(9)
        assert len(draft["calendarBlocks"]) == 1

        # Reopening Studio lands planner channels on the Planner tab.
        evaluate('viewMode = "week"')
        host.setProperty("screen", "home")
        app.processEvents()
        host.setProperty("screen", "studio")
        until(lambda: not evaluate("loading") and evaluate("viewMode") == "planner")
        until(lambda: evaluate("plannerPanel.loaded") and controller._planner_thread is None)
        assert evaluate("plannerPanel.rules.tracks.length") == 2
        assert evaluate("mediaPanel.visible")

        for width, height in [(1600, 1000), (1280, 760)]:
            host.setWidth(width)
            host.setHeight(height)
            until(lambda: evaluate("plannerPanel.previewCurrent") and controller._planner_thread is None)
            assert evaluate("plannerPanel.width") > 0
            _screenshot(host, f"studio-planner-reopen-{width}.png")
    finally:
        controller.stop()
        original.stop()
        host.close()
        app.processEvents()
        del engine


def test_planner_entry_points_live_in_studio_only() -> None:
    broadcaster = (QML / "BroadcasterScreen.qml").read_text(encoding="utf-8")
    assert "New Planner" not in broadcaster and "Open Planner" not in broadcaster
    assert 'screen = "planner"' not in broadcaster
    studio = (QML / "ChannelStudioScreen.qml").read_text(encoding="utf-8")
    assert studio.index('text: "Month"') < studio.index('text: "Planner"')


def test_planner_time_pickers_convert_wall_clock_in_the_channel_zone() -> None:
    assert planner_local_to_iso("2026-07-04", "19:30", "America/New_York") == \
        {"ok": True, "iso": "2026-07-04T19:30:00-04:00"}
    assert planner_local_to_iso("2026-12-04", "19:30", "America/New_York")["iso"].endswith("-05:00")
    skipped = planner_local_to_iso("2026-03-08", "02:30", "America/New_York")
    assert not skipped["ok"] and "does not exist" in skipped["message"]
    assert not planner_local_to_iso("2026-03-08", "02:30", "Mars/Olympus")["ok"]
    local = planner_iso_to_local("2026-07-04T23:30:00+00:00", "America/New_York")
    assert (local["date"], local["time"]) == ("2026-07-04", "19:30")
    assert "UTC-04:00" in local["zoneLabel"]
