from __future__ import annotations

import os
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Match the app's Fusion theme before any QML controls are loaded. Windows'
# native style rejects the custom backgrounds/content used by Channel Studio.
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Fusion")

pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QObject, Property, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression

import channelos


def _process_events_until(
    app: QGuiApplication,
    predicate,
    timeout: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert predicate()


class FakeStudioHost(QObject):
    screenChanged = Signal()
    studioChannelNumberChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._screen = "studio"
        self._studio_channel_number = 7

    @Property(str, notify=screenChanged)
    def screen(self) -> str:
        return self._screen

    @screen.setter
    def screen(self, value: str) -> None:
        if value == self._screen:
            return
        self._screen = value
        self.screenChanged.emit()

    @Property(int, notify=studioChannelNumberChanged)
    def studioChannelNumber(self) -> int:
        return self._studio_channel_number

    @studioChannelNumber.setter
    def studioChannelNumber(self, value: int) -> None:
        value = int(value)
        if value == self._studio_channel_number:
            return
        self._studio_channel_number = value
        self.studioChannelNumberChanged.emit()


class FakeStudioController(QObject):
    studioAutoFillChanged = Signal()
    studioAutoFillCompleted = Signal("QVariantMap")

    def __init__(self) -> None:
        super().__init__()
        self._studio_auto_fill = {
            "active": False,
            "phase": "idle",
            "current": 0,
            "total": 0,
            "percent": 0,
            "message": "",
        }

    @Property("QVariantMap", notify=studioAutoFillChanged)
    def studioAutoFill(self):
        return self._studio_auto_fill

    @Slot(int, result="QVariantMap")
    def loadChannelStudio(self, channel_number: int):
        assert channel_number == 7
        return {
            "ok": True,
            "message": "loaded",
            "draft": {
                "editingChannelNumber": 7,
                "channel": 7,
                "name": "Studio Test",
                "description": "Detached test draft",
                "numberWidth": 3,
                "fillerMode": "sequential",
                "avoidRepeatDays": 0,
                "sources": ["C:/Owned Media"],
                "groups": [
                    {
                        "groupId": "test-group",
                        "name": "Test Bumpers",
                        "mode": "sequential",
                        "assetIds": ["sha256:test"],
                        "memberCount": 1,
                        "availableCount": 1,
                    }
                ],
                "media": [
                    {
                        "assetId": "sha256:test",
                        "title": "Program",
                        "path": "C:/Owned Media/program.mp4",
                        "sourceRoot": "C:/Owned Media",
                        "durationSeconds": 1800.0,
                        "containerFormat": "MP4",
                    }
                ],
                "calendarBlocks": [
                    {
                        "assetId": "sha256:test",
                        "title": "Program",
                        "path": "C:/Owned Media/program.mp4",
                        "sourceRoot": "C:/Owned Media",
                        "durationSeconds": 1800.0,
                        "startUtc": "2026-09-07T19:00:00+00:00",
                        "endUtc": "2026-09-07T19:30:00+00:00",
                    }
                ],
            },
        }

    @Slot("QVariantMap", str, str, result="QVariantMap")
    def startStudioAutoFill(self, _editor, _start: str, _end: str):
        return {"ok": True, "message": "started"}

    @Slot(result="QVariantMap")
    def cancelStudioAutoFill(self):
        return {"ok": False, "message": "not active"}

    @Slot(str, "QVariantList", str, result="QVariantMap")
    def createStudioGroup(self, name: str, asset_ids, mode: str):
        group = {
            "groupId": "test-group",
            "name": name,
            "mode": mode,
            "assetIds": list(asset_ids),
            "memberCount": len(asset_ids),
            "availableCount": len(asset_ids),
        }
        return {
            "ok": True,
            "message": "saved",
            "group": group,
            "groups": [group],
        }

    @Slot(str, result="QVariantMap")
    def deleteStudioGroup(self, _group_id: str):
        return {"ok": True, "message": "deleted", "groups": []}

    @Slot("QVariantMap", result="QVariantMap")
    def createChannel(self, _editor):
        return {"ok": True, "message": "created", "channelNumber": 7}

    @Slot(int, "QVariantMap", result="QVariantMap")
    def updateChannel(self, original: int, _editor):
        return {"ok": True, "message": "updated", "channelNumber": original}


def test_channel_studio_component_loads_and_guards_an_unapplied_draft() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeStudioController()
    host = FakeStudioHost()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    qml_path = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "ChannelStudioScreen.qml"
    )
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    if component.isLoading():
        app.processEvents()

    errors = "\n".join(error.toString() for error in component.errors())
    assert component.isReady(), errors

    item = component.create(engine.rootContext())
    assert item is not None, errors
    item.setProperty("hostWindow", host)
    app.processEvents()

    assert item.property("editingChannelNumber") == 7
    assert item.property("selectedBlockIndex") == 0
    assert item.property("dirty") is False

    oversized_result = QQmlExpression(
        engine.rootContext(), item,
        'acceptAutoFillResult({ok: true, '
        'startUtc: "2027-01-01T00:00:00.000Z", '
        'endUtc: "2027-01-02T00:00:00.000Z", '
        'blocks: new Array(maximumCalendarBlocks)})'
    )
    oversized_result.evaluate()
    assert not oversized_result.hasError(), oversized_result.error().toString()
    assert item.property("calendarBlockCount") == 1
    assert item.property("feedbackIsError") is True
    assert "10,000-block" in str(item.property("feedbackMessage"))

    assert QMetaObject.invokeMethod(
        item,
        "assignSelectedGroupAsFiller",
        Qt.ConnectionType.DirectConnection,
    )
    assert item.property("dirty") is True
    assert "Test Bumpers" in str(item.property("feedbackMessage"))

    open_day = QQmlExpression(
        engine.rootContext(), item,
        "openDay(new Date(editorObject().calendarBlocks[0].startUtc))"
    )
    open_day.evaluate()
    assert not open_day.hasError(), open_day.error().toString()
    app.processEvents()
    assert item.property("viewMode") == "day"
    selected_day_key = str(item.property("selectedDayKey"))

    day_state = QQmlExpression(
        engine.rootContext(), item,
        '[dayKey(visibleStart()), localDayDistance(visibleStart(), visibleEnd()), '
        'dayBlocks().length, minuteForTrackPosition(1440, 2880)]'
    )
    state_result, state_is_undefined = day_state.evaluate()
    assert state_is_undefined is False
    assert not day_state.hasError(), day_state.error().toString()
    state = state_result.toVariant()
    assert state[0] == selected_day_key
    assert state[1:] == [1, 1, 720]

    place_program = QQmlExpression(
        engine.rootContext(), item,
        'addAssetAtMinute(mediaLibrary[0], '
        "visibleStart(), 600)"
    )
    place_result, place_is_undefined = place_program.evaluate()
    assert place_is_undefined is False
    assert place_result is True
    assert not place_program.hasError(), place_program.error().toString()
    assert item.property("calendarBlockCount") == 2

    move_program = QQmlExpression(
        engine.rootContext(), item,
        'moveBlockToMinute(selectedBlockIndex, '
        "visibleStart(), 615)"
    )
    move_result, move_is_undefined = move_program.evaluate()
    assert move_is_undefined is False
    assert move_result is True
    assert not move_program.hasError(), move_program.error().toString()

    collide_program = QQmlExpression(
        engine.rootContext(), item,
        'addAssetAtMinute(mediaLibrary[0], '
        "visibleStart(), 615)"
    )
    collide_result, collide_is_undefined = collide_program.evaluate()
    assert collide_is_undefined is False
    assert collide_result is False
    assert item.property("calendarBlockCount") == 2
    assert "overlaps another fixed program" in str(item.property("feedbackMessage"))

    remove_placed = QQmlExpression(
        engine.rootContext(), item, "removeBlock(selectedBlockIndex); viewMode = 'week'"
    )
    remove_placed.evaluate()
    assert not remove_placed.hasError(), remove_placed.error().toString()
    assert item.property("calendarBlockCount") == 1

    copy_expression = QQmlExpression(
        engine.rootContext(), item, "copyWeekPattern(1, 1, false)"
    )
    copy_result, copy_is_undefined = copy_expression.evaluate()
    assert copy_is_undefined is False
    assert copy_result is True
    assert not copy_expression.hasError(), copy_expression.error().toString()
    _process_events_until(
        app, lambda: not item.property("autoFillApplying")
    )
    assert item.property("autoFillApplying") is False
    assert item.property("calendarBlockCount") == 2
    editor_expression = QQmlExpression(
        engine.rootContext(), item, "editorObject()"
    )
    copied_editor, editor_is_undefined = editor_expression.evaluate()
    assert editor_is_undefined is False
    assert not editor_expression.hasError(), editor_expression.error().toString()
    copied_editor = copied_editor.toVariant()
    assert [block["startUtc"] for block in copied_editor["calendarBlocks"]] == [
        "2026-09-07T19:00:00.000Z",
        "2026-09-14T19:00:00.000Z",
    ]
    assert copied_editor["calendarBlocks"][1]["fillerAssetIds"] == [
        "sha256:test"
    ]

    reset_anchor = QQmlExpression(
        engine.rootContext(), item,
        'anchorDate = new Date("2026-09-07T12:00:00.000Z")'
    )
    reset_anchor.evaluate()
    assert not reset_anchor.hasError(), reset_anchor.error().toString()
    collision_expression = QQmlExpression(
        engine.rootContext(), item, "copyWeekPattern(1, 1, false)"
    )
    collision_result, collision_is_undefined = collision_expression.evaluate()
    assert collision_is_undefined is False
    assert collision_result is False
    assert item.property("calendarBlockCount") == 2
    assert "Target weeks contain 1 fixed block" in str(
        item.property("feedbackMessage")
    )

    repeat_expression = QQmlExpression(
        engine.rootContext(), item, "copyWeekPattern(2, 2, false)"
    )
    repeat_result, repeat_is_undefined = repeat_expression.evaluate()
    assert repeat_is_undefined is False
    assert repeat_result is True
    _process_events_until(
        app, lambda: not item.property("autoFillApplying")
    )
    assert item.property("calendarBlockCount") == 4
    item.setProperty("dirty", False)

    auto_fill_start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    auto_fill_blocks = []
    for block_index in range(560):
        block_start = auto_fill_start + timedelta(seconds=60 * block_index)
        block_end = block_start + timedelta(seconds=60)
        auto_fill_blocks.append(
            {
                "assetId": f"sha256:test-{block_index}",
                "title": f"Program {block_index}",
                "path": f"C:/Owned Media/program-{block_index}.mp4",
                "sourceRoot": "C:/Owned Media",
                "durationSeconds": 60.0,
                "startUtc": block_start.isoformat(),
                "endUtc": block_end.isoformat(),
            }
        )

    controller.studioAutoFillCompleted.emit(
        {
            "ok": True,
            "message": "filled",
            "startUtc": "2026-09-07T00:00:00+00:00",
            "endUtc": "2026-09-08T00:00:00+00:00",
            "blocks": auto_fill_blocks,
        }
    )
    _process_events_until(
        app, lambda: not item.property("autoFillApplying")
    )
    assert item.property("autoFillApplying") is False
    assert item.property("dirty") is True
    assert item.property("calendarBlockCount") == 564
    item.setProperty("dirty", False)

    item.setProperty("dirty", True)
    invoked = QMetaObject.invokeMethod(
        item,
        "leaveStudio",
        Qt.ConnectionType.DirectConnection,
    )
    assert invoked
    app.processEvents()
    assert host.screen == "studio"
    assert item.property("pendingExitDestination") == "home"

    invoked = QMetaObject.invokeMethod(
        item,
        "finishExit",
        Qt.ConnectionType.DirectConnection,
    )
    assert invoked
    assert host.screen == "home"
    assert item.property("dirty") is False

    item.deleteLater()
    app.processEvents()


def test_ad_management_controls_edit_transition_placements_and_restore_cancelled_values():
    from PySide6.QtQuick import QQuickWindow
    app = QGuiApplication.instance() or QGuiApplication([])
    class AdController(FakeStudioController):
        saved = None

        @Slot(int, result='QVariantMap')
        def loadChannelStudio(self, channel_number):
            result = super().loadChannelStudio(channel_number)
            result['draft'].update(adSmooshMaxTrimSeconds=0, adTriggers=[])
            return result

        @Slot(result='QVariantMap')
        def adCatalogSnapshot(self):
            return {'ok': True, 'collections': [{'collectionId': 'ads', 'name': 'Commercials'}],
                    'profiles': [{'profileId': 'standard', 'name': 'Standard'}], 'assignments': []}

        @Slot('QVariantMap', result='QVariantMap')
        def assignAdBreakProfile(self, value):
            self.saved = value
            return {'ok': True, 'message': 'Saved', **self.adCatalogSnapshot()}

    controller, host = AdController(), FakeStudioHost()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('channelOS', controller)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(
        Path(channelos.__file__).resolve().parent / 'qml' / 'ChannelStudioScreen.qml')))
    while component.isLoading():
        app.processEvents()
    assert component.isReady(), [error.toString() for error in component.errors()]
    item = component.create()
    window = QQuickWindow()
    window.resize(1280, 900)
    item.setParentItem(window.contentItem())
    item.setProperty('hostWindow', host)
    window.show()
    app.processEvents()

    def evaluate(code):
        expression = QQmlExpression(engine.contextForObject(item), item, code)
        result, undefined = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        app.processEvents()
        return result.toVariant() if hasattr(result, 'toVariant') else result

    edited = evaluate('adBreakSettingsDialog.open(); adTransitionBox.currentIndex = 1; '
                      'adTransitionSecondsField.text = "0.75"; adSlotSecondsField.text = "1800"; '
                      'adBreakSettingsDialog.accept(); editorObject()')
    assert edited['adTransitionBehavior'] == 'fade'
    assert edited['adTransitionSeconds'] == .75
    assert edited['adSmooshMaxTrimSeconds'] == 0
    assert edited['adTriggers'] == []
    assert edited['adSlotSeconds'] == 1800
    restored = evaluate('adBreakSettingsDialog.open(); adTransitionSecondsField.text = "4"; '
                        'adBreakSettingsDialog.reject(); editorObject()')
    assert restored['adTransitionSeconds'] == .75
    evaluate('adCatalogDialog.open(); placementTrigger.currentIndex = 2; '
             'addAdPlacementButton.clicked(); saveAdAssignmentButton.clicked()')
    assert len(controller.saved['placements']) == 1
    assert controller.saved['placements'][0]['trigger'] == 'between_programs'
    assert controller.saved['placements'][0]['collection_id'] == 'ads'
    evaluate('adCatalogDialog.close()')
    window.close()
    item.setParentItem(None)
    item.deleteLater()
    engine.deleteLater()
    app.processEvents()


def test_media_bin_browses_only_selected_sources_and_searches_their_programs():
    from PySide6.QtQuick import QQuickWindow

    class SourceController(FakeStudioController):
        @Slot(int, result="QVariantMap")
        def loadChannelStudio(self, channel_number):
            result = super().loadChannelStudio(channel_number)

            def media(asset, title, path, **extra):
                return {"assetId": asset, "title": title, "path": path,
                        "sourceRoot": "C:/Shows", "durationSeconds": 30,
                        "containerFormat": "MP4", **extra}

            result["draft"].update({
                "sources": ["C:/Shows/Comedy", "C:/Shows/Drama", "C:/Shows/Empty", "C:/Copies"],
                "adSources": ["C:/Shows/Comedy/Ads"],
                "media": [
                    media("a", "Alpha", "C:/Shows/Comedy/alpha.mp4", locations=[
                        {"path": "C:/Shows/Comedy/alpha.mp4", "sourceRoot": "C:/Shows"},
                        {"path": "C:/Copies/alpha.mp4", "sourceRoot": "C:/Copies"}]),
                    media("b", "Beta", "C:/Shows/Comedy/beta.mp4"),
                    media("c", "Drama", "c:\\shows\\DRAMA\\drama.mp4"),
                    media("sibling", "Wrong sibling", "C:/Shows/Comedy Extra/wrong.mp4"),
                    media("hidden", "Hidden", "X:/Other/hidden.mp4"),
                    media("ad", "Advertisement", "C:/Shows/Comedy/Ads/ad.mp4"),
                    media("shared", "Shared", "X:/Other/shared.mp4", locations=[
                        {"path": "X:/Other/shared.mp4", "sourceRoot": "X:/Other"},
                        {"path": "C:/Copies/shared.mp4", "sourceRoot": "C:/Copies"}]),
                ],
                "calendarBlocks": [],
            })
            return result

    app = QGuiApplication.instance() or QGuiApplication([])
    controller, host = SourceController(), FakeStudioHost()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty("channelOS", controller)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(
        Path(channelos.__file__).resolve().parent / "qml" / "ChannelStudioScreen.qml")))
    while component.isLoading():
        app.processEvents()
    assert component.isReady(), [error.toString() for error in component.errors()]
    item = component.create()
    window = QQuickWindow()
    window.resize(1600, 1000)
    item.setParentItem(window.contentItem())
    item.setProperty("hostWindow", host)
    window.show()
    app.processEvents()

    def evaluate(code):
        expression = QQmlExpression(engine.contextForObject(item), item, code)
        result, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        app.processEvents()
        return result.toVariant() if hasattr(result, "toVariant") else result

    assert evaluate("mediaBinRows().map(function(row) { return row.count })") == [2, 1, 0, 2]
    assert item.property("mediaBinAssetCount") == 4  # shared copies count once in the pool
    assert evaluate("mediaBinRows().every(function(row) { return row.kind === 'source' })")
    assert "C:/Copies" in evaluate("sourceChoices()")
    evaluate("toggleMediaSource('C:/Shows/Comedy')")
    assert evaluate("mediaBinRows().filter(function(row) { return row.kind === 'media' }).map(function(row) { return row.media.assetId })") == ["a", "b"]

    evaluate('mediaSearch.text = "Beta"')
    assert evaluate("mediaBinRows().filter(function(row) { return row.kind === 'source' }).map(function(row) { return row.matchCount })") == [1, 0, 0, 0]
    assert evaluate("mediaBinRows().filter(function(row) { return row.kind === 'media' }).map(function(row) { return row.media.assetId })") == ["b"]
    evaluate('mediaSearch.text = "Hidden"')
    assert evaluate("mediaBinRows().filter(function(row) { return row.kind === 'media' }).length") == 0
    evaluate('mediaSearch.text = "C:/Copies/shared"')
    assert evaluate("mediaBinRows().filter(function(row) { return row.kind === 'media' })[0].media.path") == "C:/Copies/shared.mp4"

    evaluate('mediaSearch.text = ""; removeMediaSource("C:/Shows/Comedy")')
    assert item.property("mediaBinAssetCount") == 3
    assert evaluate("editorObject().sources") == ["C:/Shows/Drama", "C:/Shows/Empty", "C:/Copies"]
    assert item.property("dirty") is True
    evaluate("clearMediaSources()")
    assert evaluate("mediaBinRows()") == []
    assert item.property("mediaBinAssetCount") == 0
    evaluate("appendSource('C:/Shows/Comedy', true)")
    assert evaluate("appendSource(" + json.dumps("c:\\shows\\COMEDY\\") + ", true)") is False
    assert evaluate("editorObject().sources") == ["C:/Shows/Comedy"]
    assert evaluate("mediaBinRows().length") == 3
    assert warnings == []

    window.close()
    item.setParentItem(None)
    item.deleteLater()
    engine.deleteLater()
    app.processEvents()
