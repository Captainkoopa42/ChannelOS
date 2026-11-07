import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Fusion")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
from PySide6.QtQuick import QQuickWindow

import channelos
from test_couch_qml import FakeChannelOS


def evaluate(engine, item, source):
    expression = QQmlExpression(engine.rootContext(), item, source)
    result = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    value = result[0] if isinstance(result, tuple) else result
    return value.toVariant() if hasattr(value, "toVariant") else value


def test_shared_ad_editor_preserves_advanced_and_basic_modes_and_cancel():
    app = QGuiApplication.instance() or QGuiApplication([])
    controller = FakeChannelOS()
    window = QQuickWindow()
    window.resize(1280, 900)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(channelos.__file__).parent / "qml/AdSettingsEditor.qml")))
    item = component.create()
    assert item is not None, "\n".join(error.toString() for error in component.errors())
    item.setParentItem(window.contentItem())
    item.setProperty("hostItem", window.contentItem())
    window.show()
    try:
        data = {"adBreaksEnabled": True, "adSources": ["C:/Ads"], "adSetupMode": "after_show",
                "adPlayOrder": "shuffle", "adSmooshMinimumSeconds": 7}
        evaluate(engine, item, "load(" + json.dumps(data) + ")")
        saved = evaluate(engine, item, "editorObject()")
        assert saved["adSetupMode"] == "after_show"
        assert saved["adSmooshMinimumSeconds"] == 7
        evaluate(engine, item, "openBasic()")
        app.processEvents()
        dialog = item.findChild(QObject, "simpleAdBreaksDialog")
        assert dialog.property("visible")
        assert item.findChild(QObject, "simpleAdSummary").property("text").startswith("Play one full ad")
        item.setProperty("setupMode", "aligned")
        item.setProperty("clockInterval", 1800)
        evaluate(engine, dialog, "reject()")
        assert evaluate(engine, item, "editorObject()")["adSetupMode"] == "after_show"
        assert evaluate(engine, item, "editorObject()")["adClockIntervalSeconds"] == 900

        evaluate(engine, item, "load(" + json.dumps({**data, "adSetupMode": "advanced", "adPriority": 11}) + ")")
        evaluate(engine, item, "openAdvanced()")
        app.processEvents()
        advanced = item.findChild(QObject, "advancedAdSettingsDialog")
        assert advanced.property("visible")
        assert item.findChild(QObject, "adProfilesTab").property("text") == "Profiles"
        evaluate(engine, advanced, "accept()")
        assert evaluate(engine, item, "editorObject()")["adPriority"] == 11
        assert evaluate(engine, item, "editorObject()")["adSetupMode"] == "advanced"
    finally:
        # Destroy in a fixed order. A deleteLater() that never runs leaves the
        # item parented to the window, and a later garbage collection then
        # deletes it twice (seen as a segfault in a later Qt test).
        window.close()
        item.setParentItem(None)
        item.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        del item, component
        del window
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
