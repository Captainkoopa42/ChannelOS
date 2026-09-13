from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QObject, Property, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression

import channelos


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
                        "media": [
                            {
                                "assetId": "sha256:test",
                                "sourceRoot": "C:/Owned Media",
                            }
                        ],
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

    assert QMetaObject.invokeMethod(
        item,
        "assignSelectedGroupAsFiller",
        Qt.ConnectionType.DirectConnection,
    )
    assert item.property("dirty") is True
    assert "Test Bumpers" in str(item.property("feedbackMessage"))

    copy_expression = QQmlExpression(
        engine.rootContext(), item, "copyWeekPattern(1, 1, false)"
    )
    copy_result, copy_is_undefined = copy_expression.evaluate()
    assert copy_is_undefined is False
    assert copy_result is True
    assert not copy_expression.hasError(), copy_expression.error().toString()
    for _ in range(10):
        app.processEvents()
        if not item.property("autoFillApplying"):
            break
        assert QMetaObject.invokeMethod(
            item,
            "applyAutoFillBatch",
            Qt.ConnectionType.DirectConnection,
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
    for _ in range(10):
        app.processEvents()
        if not item.property("autoFillApplying"):
            break
        assert QMetaObject.invokeMethod(
            item,
            "applyAutoFillBatch",
            Qt.ConnectionType.DirectConnection,
        )
    assert item.property("calendarBlockCount") == 4
    item.setProperty("dirty", False)

    controller.studioAutoFillCompleted.emit(
        {
            "ok": True,
            "message": "filled",
            "startUtc": "2026-09-07T00:00:00+00:00",
            "endUtc": "2026-09-08T00:00:00+00:00",
            "blocks": [
                {
                    "assetId": "sha256:test",
                    "title": "Program",
                    "path": "C:/Owned Media/program.mp4",
                    "sourceRoot": "C:/Owned Media",
                    "durationSeconds": 1800.0,
                    "startUtc": "2026-09-07T20:00:00+00:00",
                    "endUtc": "2026-09-07T20:30:00+00:00",
                }
            ],
        }
    )
    for _ in range(10):
        app.processEvents()
        if not item.property("autoFillApplying"):
            break
        assert QMetaObject.invokeMethod(
            item,
            "applyAutoFillBatch",
            Qt.ConnectionType.DirectConnection,
        )
    assert item.property("autoFillApplying") is False
    assert item.property("dirty") is True
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
