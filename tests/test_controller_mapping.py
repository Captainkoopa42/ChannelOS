"""Settings → Controller: button mapper, keyboard mapper and layouts."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

QML = Path(__file__).resolve().parents[1] / "src" / "channelos" / "qml"


class FakeControllerInput:
    def __init__(self):
        self.bindings = None
        self.capture = None

    def set_bindings(self, bindings):
        self.bindings = bindings

    def set_capture(self, callback):
        self.capture = callback


@pytest.fixture
def controller(tmp_path):
    from channelos.couch_qt import CouchKeyFilter
    from test_performance_operations import controller_fixture
    _app, controller, _root = controller_fixture(tmp_path)
    yield controller
    controller.stop()
    CouchKeyFilter.set_key_overrides({})


def test_button_bindings_save_apply_and_reset(controller, tmp_path: Path) -> None:
    from channelos.control import ControlIntent
    from channelos.settings import SettingsStore
    fake = FakeControllerInput()
    controller.attach_controller_input(fake)
    assert fake.bindings["south"] is ControlIntent.SELECT
    assert controller.setControllerBinding("south", "PLAY_PAUSE")["ok"]
    assert controller.setControllerBinding("guide", "HOME")["ok"]
    assert fake.bindings["south"] is ControlIntent.PLAY_PAUSE and fake.bindings["guide"] is ControlIntent.HOME
    assert controller.controllerBindings["south"] == "PLAY_PAUSE"
    assert controller.settings["controllerRemapped"] == 2
    assert not controller.setControllerBinding("laser", "HOME")["ok"]
    saved = SettingsStore(controller._settings_store.path).load()
    assert dict(saved.controller_bindings) == {"guide": "HOME", "south": "PLAY_PAUSE"}
    assert controller.resetControllerBindings()["ok"]
    assert fake.bindings["south"] is ControlIntent.SELECT and controller.settings["controllerRemapped"] == 0

    controller.setControllerCapture(True)
    assert fake.capture is not None
    seen = []
    controller.controllerButtonPressed.connect(seen.append)
    fake.capture("north")
    assert seen == ["north"]
    controller.setControllerCapture(False)
    assert fake.capture is None


def test_key_bindings_remap_and_protect_escape_and_digits(controller) -> None:
    from PySide6.QtCore import Qt
    from channelos.control import ControlIntent
    from channelos.couch_qt import CouchKeyFilter
    assert CouchKeyFilter.command_for_key(Qt.Key.Key_G).intent is ControlIntent.GUIDE
    assert controller.setKeyBinding("Key_F2", "GUIDE")["ok"]
    assert controller.setKeyBinding("Key_G", "NONE")["ok"]
    assert CouchKeyFilter.command_for_key(Qt.Key.Key_F2).intent is ControlIntent.GUIDE
    assert CouchKeyFilter.command_for_key(Qt.Key.Key_G) is None
    guide = next(row for row in controller.keyBindings if row["action"] == "GUIDE")
    assert [key["label"] for key in guide["keys"]] == ["F2"]
    assert "always Back" in controller.setKeyBinding("Key_Escape", "HOME")["message"]
    assert not controller.setKeyBinding("Key_5", "HOME")["ok"]
    back = next(row for row in controller.keyBindings if row["action"] == "BACK")
    assert {"key": "Key_Escape", "label": "Esc", "fixed": True} in back["keys"]
    assert controller.clearKeysForAction("GUIDE")["ok"]
    assert CouchKeyFilter.command_for_key(Qt.Key.Key_F2) is None
    assert controller.keyName(int(Qt.Key.Key_F7)) == "Key_F7"
    assert controller.resetKeyBindings()["ok"]
    assert CouchKeyFilter.command_for_key(Qt.Key.Key_G).intent is ControlIntent.GUIDE
    assert CouchKeyFilter.command_for_key(Qt.Key.Key_F2) is None


def test_layout_and_dedicated_mode_settings(controller) -> None:
    assert controller.settings["controllerLayout"] == "auto"
    assert controller.adjustSetting("controllerLayout", 1)["ok"]
    assert controller.settings["controllerLayout"] == "xbox"
    assert controller.adjustSetting("controllerLayout", -1)["ok"]
    assert controller.settings["controllerLayout"] == "auto"
    assert not controller.settings["dedicatedController"]
    assert "on-screen keyboard" in controller.adjustSetting("dedicatedController", 1)["message"]
    assert controller.settings["dedicatedController"]


def _load(controller, name, extra=None):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
    app = QGuiApplication.instance()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    engine.loadData(b'import QtQuick; import QtQuick.Controls; ApplicationWindow { width: 1400; height: 860; visible: true;'
                    b' property bool keyCaptureActive: false }')
    host = engine.rootObjects()[0]
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / name)))
    item = component.create()
    assert item is not None, [e.toString() for e in component.errors()]
    item.setProperty("parent", host.contentItem())
    host._keep = (engine, component, item)

    def evaluate(code):
        expression = QQmlExpression(engine.contextForObject(item), item, code)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value.toVariant() if hasattr(value, "toVariant") else value
    return app, host, item, evaluate


def test_button_mapper_qml_picks_actions_and_finds_buttons(controller) -> None:
    from PySide6.QtCore import qInstallMessageHandler
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    fake = FakeControllerInput()
    controller.attach_controller_input(fake)
    app, host, mapper, evaluate = _load(controller, "ControllerMapper.qml")
    try:
        evaluate('connectedFamily = "playstation"')
        evaluate("openMapper()")
        app.processEvents()
        assert fake.capture is not None, "opening the mapper listens for raw presses"
        assert evaluate("family.name") == "PlayStation"
        kinds = evaluate("rows.map(function(r) { return r.kind })")
        assert kinds[:2] == ["layout", "find"] and kinds[-2:] == ["stick", "reset"]

        # Find a button: press Select on "Find", then a button on the pad.
        evaluate('handleIntent("DOWN")')
        evaluate('handleIntent("SELECT")')
        assert evaluate("listening")
        evaluate('buttonPressed("north")')
        assert not evaluate("listening") and evaluate("currentRow.id") == "north"
        evaluate('handleIntent("SELECT")')
        assert not evaluate("pickerOpen"), "the press that found the button is not reused"
        evaluate("swallowUntil = 0")

        evaluate('handleIntent("SELECT")')
        assert evaluate("pickerOpen")
        index = evaluate('actions.map(function(a) { return a.id }).indexOf("MUTE")')
        evaluate(f"pickerIndex = {index}")
        evaluate('handleIntent("SELECT")')
        assert not evaluate("pickerOpen") and controller.controllerBindings["north"] == "MUTE"

        evaluate('current = 0')
        evaluate('handleIntent("RIGHT")')
        assert controller.settings["controllerLayout"] == "xbox"
        assert evaluate("family.id") == "xbox"
        evaluate('handleIntent("BACK")')
        app.processEvents()
        assert not evaluate("visible") and fake.capture is None
    finally:
        qInstallMessageHandler(previous)
        host.close()
        app.processEvents()
    assert [m for m in messages if "ControllerMapper.qml" in m or "ControllerDiagram.qml" in m] == []


def test_keyboard_mapper_qml_captures_keys(controller) -> None:
    from PySide6.QtCore import Qt, qInstallMessageHandler
    from channelos.couch_qt import CouchKeyFilter
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    app, host, keys, evaluate = _load(controller, "KeyboardMapper.qml")
    try:
        keys.setProperty("hostWindow", host)
        evaluate("openMapper()")
        app.processEvents()
        row = evaluate('rows.map(function(r) { return r.action }).indexOf("MUTE")')
        evaluate(f"activate({row})")
        assert evaluate("listening") and host.property("keyCaptureActive") is True
        evaluate(f"captured({int(Qt.Key.Key_Shift)})")
        assert evaluate("listening"), "modifier keys alone wait for a real key"
        evaluate(f"captured({int(Qt.Key.Key_F9)})")
        assert not evaluate("listening") and host.property("keyCaptureActive") is False
        assert CouchKeyFilter.command_for_key(Qt.Key.Key_F9).intent.value == "MUTE"
        evaluate(f"activate({row})")
        evaluate(f"captured({int(Qt.Key.Key_Escape)})")
        assert not evaluate("listening")
        evaluate('handleIntent("BACK")')
        app.processEvents()
        assert not evaluate("visible")
    finally:
        qInstallMessageHandler(previous)
        host.close()
        app.processEvents()
    assert [m for m in messages if "KeyboardMapper.qml" in m] == []


def test_on_screen_keyboard_types_with_a_controller(controller) -> None:
    from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
    from channelos.control import ControlCommand, ControlIntent
    from channelos.couch_qt import CouchKeyFilter
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    app = QGuiApplication.instance()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    qml = f'''
import QtQuick
import QtQuick.Controls
import "{QML.as_uri()}"
ApplicationWindow {{
    width: 1400; height: 860; visible: true
    property bool pinPadVisible: false
    property string screen: "settings"
    property int finishedCount: 0
    readonly property bool keyboardVisible: osk.visible
    function openKeyboard(target, label) {{ osk.openFor(target, String(label || "")) }}
    function closeKeyboard() {{ osk.close() }}
    function handleKeyboardIntent(intent) {{ return osk.handleIntent(String(intent)) }}
    TextField {{ id: field; objectName: "nameField"; placeholderText: "Theme name"; onEditingFinished: finishedCount += 1 }}
    OnScreenKeyboard {{ id: osk }}
}}'''
    engine.loadData(qml.encode())
    host = engine.rootObjects()[0]
    field = host.findChild(QObject, "nameField")
    router = CouchKeyFilter.__new__(CouchKeyFilter)
    QObject.__init__(router)
    router._window = host
    router._controller = controller
    router._profile_checked = None

    def send(intent):
        router._profile_guard(ControlCommand(intent))
        app.processEvents()

    try:
        field.forceActiveFocus()
        app.processEvents()
        assert not router.open_keyboard_for_focus(), "only in Dedicated Controller Mode"
        controller.adjustSetting("dedicatedController", 1)
        assert router.navigate_focus(ControlIntent.SELECT)
        assert host.property("keyboardVisible") is True
        assert QGuiApplication.focusObject() is field, "the keyboard never steals focus"

        # Row 1 starts on "q": type q, move right to w, type it, then Shift and z.
        send(ControlIntent.SELECT)
        send(ControlIntent.RIGHT)
        send(ControlIntent.SELECT)
        for _ in range(2):
            send(ControlIntent.DOWN)         # straight down from "w" lands on "z"
        send(ControlIntent.LEFT)
        send(ControlIntent.SELECT)          # Shift
        send(ControlIntent.RIGHT)
        send(ControlIntent.SELECT)          # Z
        assert field.property("text") == "qwZ"
        send(ControlIntent.PLAY_PAUSE)       # X deletes
        send(ControlIntent.INFO)             # Y adds a space
        assert field.property("text") == "qw "
        send(ControlIntent.CHANNEL_DOWN)     # cursor left
        send(ControlIntent.CHANNEL_DOWN)
        send(ControlIntent.UP)
        send(ControlIntent.UP)
        send(ControlIntent.UP)               # number row
        send(ControlIntent.SELECT)
        assert field.property("text") == "q2w "
        send(ControlIntent.BACK)              # Done
        assert host.property("keyboardVisible") is False
        assert host.property("finishedCount") >= 1
        # Physical typing still reaches the box while the keyboard is open.
        assert CouchKeyFilter._text_entry_has_focus()
    finally:
        qInstallMessageHandler(previous)
        host.close()
        app.processEvents()
    assert [m for m in messages if "OnScreenKeyboard.qml" in m] == []
