"""Profiles: Home, Kids, Daycare and Lobby with a PIN to leave a locked one."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from channelos.control import ControlCommand, ControlIntent
from channelos.profiles import DEFAULTS, ProfileStore, valid_pin

QML = Path(__file__).resolve().parents[1] / "src" / "channelos" / "qml"


# --- Store -------------------------------------------------------------------------------------

def test_defaults_and_pin_are_stored_hashed(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles.json")
    state = store.load()
    assert state.active == "home" and not state.has_pin
    assert DEFAULTS["kids"].locked and DEFAULTS["kids"].channels == ()
    assert not DEFAULTS["lobby"].home and not DEFAULTS["lobby"].change_channels
    assert not DEFAULTS["daycare"].seek and not DEFAULTS["daycare"].ondemand

    state = store.save(ProfileStore.with_pin(state, "2468"))
    text = (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert "2468" not in text
    loaded = store.load()
    assert loaded.check_pin("2468")
    assert not loaded.check_pin("1357") and not loaded.check_pin("") and not loaded.check_pin("abcd")
    with pytest.raises(ValueError):
        ProfileStore.with_pin(loaded, "12")
    assert valid_pin("12345678") and not valid_pin("123456789")


def test_load_sanitizes_and_never_strands_a_viewer(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({
        "active": "kids",  # but no PIN: must fall back to Home
        "profiles": {
            "home": {"settings": False, "channels": [7]},
            "kids": {"settings": True, "management": True, "volume_limit": 55, "channels": [8, 7, 7, "x"]},
            "lobby": {"boot_channel": 8, "channels": [8]},
        },
    }), encoding="utf-8")
    state = ProfileStore(path).load()
    assert state.active == "home"
    home, kids, lobby = (state.profiles[p] for p in ("home", "kids", "lobby"))
    assert home.settings and home.channels is None, "Home is always open"
    assert not kids.settings and not kids.management, "locked profiles keep Settings behind the PIN"
    assert kids.volume_limit == DEFAULTS["kids"].volume_limit
    assert kids.channels == DEFAULTS["kids"].channels, "a bad channel list falls back"
    assert lobby.boot_channel == 8 and lobby.channels == (8,)
    path.write_text("not json", encoding="utf-8")
    assert ProfileStore(path).load().active == "home"


# --- Controller --------------------------------------------------------------------------------

def _fixture(tmp_path: Path):
    pytest.importorskip("PySide6")
    from test_performance_operations import controller_fixture
    app, controller, _root = controller_fixture(tmp_path)
    return app, controller


def _channels(controller) -> list[int]:
    return sorted(int(row["channelNumber"]) for row in controller.snapshot["rows"]
                  if not row.get("isUnassigned") and int(row.get("channelNumber", 0)) > 0)


def test_kids_profile_filters_channels_and_needs_the_pin_to_leave(tmp_path: Path) -> None:
    app, controller = _fixture(tmp_path)
    try:
        assert _channels(controller) == [7, 8]
        assert "PIN first" in controller.activateProfile("kids")["message"]
        assert controller.setProfilePin("4321")["ok"]
        assert "Choose channels" in controller.activateProfile("kids")["message"]
        assert [c["number"] for c in controller.profileChannelChoices] == [7, 8]
        assert controller.updateProfile("kids", json.dumps({"channels": [7], "volume_limit": 50}))["ok"]

        result = controller.activateProfile("kids")
        assert result["ok"], result
        assert controller.profile["id"] == "kids"
        assert _channels(controller) == [7]
        assert controller.settings["volumePercent"] <= 50
        controller.changeVolume(10)
        assert controller.settings["volumePercent"] <= 50

        # Locked: no editing, no PIN change, no switching without the PIN.
        assert not controller.updateProfile("kids", json.dumps({"channels": [7, 8]}))["ok"]
        assert not controller.setProfilePin("0000")["ok"]
        assert controller.activateProfile("home").get("needPin")

        assert not controller.unlockProfile("1111")["ok"]
        assert controller.unlockProfile("4321")["ok"]
        assert controller.profile["id"] == "home"
        assert _channels(controller) == [7, 8]

        # The choice survives a restart.
        assert controller.activateProfile("kids")["ok"]
        reloaded = ProfileStore(tmp_path / "profiles.json").load()
        assert reloaded.active == "kids" and reloaded.current.channels == (7,)
        assert controller.unlockProfile("4321")["ok"]
    finally:
        controller.stop()


def _router(tmp_path: Path, profile: str, changes: dict):
    from PySide6.QtGui import QWindow
    from channelos.couch_qt import CouchKeyFilter
    app, controller = _fixture(tmp_path)
    controller.setProfilePin("4321")
    controller.updateProfile(profile, json.dumps(changes))
    assert controller.activateProfile(profile)["ok"]
    window = QWindow()
    for name, value in {"screen": "home", "selectedRow": 1, "selectedProgram": 0, "guideFocusMs": 0.0,
                        "guideSelectionScheduleId": "", "infoVisible": False, "statusMessage": "",
                        "pinPadVisible": False, "pinPadTitle": "", "pinPadReason": ""}.items():
        window.setProperty(name, value)
    return app, controller, window, CouchKeyFilter(controller, window)


def test_locked_profile_routes_settings_to_the_pin_pad(tmp_path: Path) -> None:
    app, controller, window, router = _router(tmp_path, "daycare", {"channels": [7, 8]})
    try:
        assert router.dispatch_command(ControlCommand(ControlIntent.SETTINGS))
        assert window.property("pinPadVisible") is True
        assert "Daycare" in window.property("pinPadTitle")
        window.setProperty("pinPadVisible", False)

        assert router.dispatch_command(ControlCommand(ControlIntent.POWER))
        assert window.property("pinPadVisible") is True, "closing the app needs the PIN"
        window.setProperty("pinPadVisible", False)

        window.setProperty("screen", "live")
        assert router.dispatch_command(ControlCommand(ControlIntent.SKIP_FORWARD))
        assert "Skipping is off" in str(window.property("statusMessage"))
        assert router.dispatch_command(ControlCommand(ControlIntent.LIBRARY))
        assert window.property("screen") == "live"

        # A click or QML navigation into Settings is sent back too.
        window.setProperty("screen", "settings")
        router._guard_profile_screen()  # Main.qml's screenChanged calls this
        for _ in range(5):
            app.processEvents()
        assert window.property("screen") != "settings"
        assert window.property("pinPadVisible") is True

        router.submitPin("4321")
        assert window.property("pinPadVisible") is False
        assert controller.profile["id"] == "home"
        assert not router._profile_guard(ControlCommand(ControlIntent.SETTINGS))
    finally:
        controller.stop()


def test_lobby_starts_on_its_channel_and_ignores_the_menus(tmp_path: Path, monkeypatch) -> None:
    app, controller, window, router = _router(tmp_path, "lobby", {"channels": [7, 8], "boot_channel": 8})
    try:
        tuned: list[int] = []
        monkeypatch.setattr(controller, "tuneChannel", lambda number: tuned.append(number) or {"ok": True, "message": ""})
        controller._surface_ready = True
        router._enter_profile_start(attempts=0)
        assert tuned == [8] and window.property("screen") == "live"

        assert router.dispatch_command(ControlCommand(ControlIntent.BACK))
        assert window.property("screen") == "live"
        assert router.dispatch_command(ControlCommand(ControlIntent.CHANNEL_UP))
        assert "Changing channels is off" in str(window.property("statusMessage"))
        assert router.dispatch_command(ControlCommand(ControlIntent.GUIDE))
        assert window.property("screen") == "live"
        assert router.dispatch_command(ControlCommand(ControlIntent.HOME))
        assert window.property("pinPadVisible") is True
    finally:
        controller.stop()


# --- QML ---------------------------------------------------------------------------------------

_KEEP: list = []


def _load(name: str):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlApplicationEngine()
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, message: messages.append(message))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / name)))
    item = component.create(engine.rootContext())
    _KEEP.append((engine, component, item))
    assert item is not None, [e.toString() for e in component.errors()]
    return app, engine, item, messages, previous


def test_pin_pad_works_with_a_remote_and_reports_the_pin() -> None:
    from PySide6.QtCore import QMetaObject, Q_ARG, Qt, qInstallMessageHandler
    app, engine, pad, messages, previous = _load("PinPad.qml")
    try:
        submitted: list[str] = []
        cancelled: list[bool] = []
        from PySide6.QtCore import QObject, SIGNAL
        QObject.connect(pad, SIGNAL("submitted(QString)"), submitted.append)
        QObject.connect(pad, SIGNAL("cancelled()"), lambda: cancelled.append(True))

        def intent(name, digit=-1):
            QMetaObject.invokeMethod(pad, "handleIntent", Qt.ConnectionType.DirectConnection,
                                     Q_ARG("QVariant", name), Q_ARG("QVariant", digit))

        for digit in (1, 2, 3):
            intent("DIGIT", digit)
        assert pad.property("entered") == "123"
        # Focus starts on "1"; Down x3 lands on Clear, Right on 0, Right on OK.
        intent("SELECT")  # types 1
        intent("SELECT")  # types 1
        intent("DOWN"); intent("DOWN"); intent("DOWN")
        intent("SELECT")  # Clear removes one
        assert pad.property("entered") == "1231"
        intent("RIGHT"); intent("RIGHT")
        intent("SELECT")
        assert submitted == ["1231"]

        pad.setProperty("entered", "12")
        intent("RIGHT"); intent("RIGHT"); intent("RIGHT")  # wraps back to OK
        intent("SELECT")
        assert submitted == ["1231"] and "4 to 8" in pad.property("error")
        intent("BACK")
        assert cancelled == [True]
    finally:
        qInstallMessageHandler(previous)
        app.processEvents()
    assert [m for m in messages if "PinPad.qml" in m] == []


def test_profile_editor_edits_channels_toggles_and_saves() -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
    from PySide6.QtQuick import QQuickWindow

    class Host(QObject):
        profileChanged = Signal()
        saved: list = []

        @Property("QVariantList", notify=profileChanged)
        def profiles(self):
            return [dict(DEFAULTS[p].to_mapping(), id=p) for p in ("home", "kids", "daycare", "lobby")]

        @Property("QVariantList", notify=profileChanged)
        def profileChannelChoices(self):
            return [{"number": 7, "name": "Cartoons"}, {"number": 8, "name": "Movies"}]

        @Property("QVariantList", constant=True)
        def profileVolumeLimits(self):
            return [30, 40, 50, 60, 70, 80, 90, 100]

        @Slot(str, str, result="QVariantMap")
        def updateProfile(self, profile_id, changes):
            self.saved.append((profile_id, json.loads(changes)))
            return {"ok": True, "message": "saved"}

    app = QGuiApplication.instance() or QGuiApplication([])
    host = Host()
    window = QQuickWindow()
    window.resize(1280, 720)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", host)
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, message: messages.append(message))
    try:
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "ProfileEditor.qml")))
        editor = component.create(engine.rootContext())
        assert editor is not None, [e.toString() for e in component.errors()]
        _KEEP.append((engine, component, editor, window))
        editor.setParent(window.contentItem())

        def run(code):
            expression = QQmlExpression(engine.contextForObject(editor), editor, code)
            value, _ = expression.evaluate()
            assert not expression.hasError(), expression.error().toString()
            return value.toVariant() if hasattr(value, "toVariant") else value

        run('openFor("kids")')
        kinds = run("items.map(function(i) { return i.kind })")
        assert kinds == ["toggle"] * 4 + ["volume", "allChannels", "channel", "channel", "save"]
        run('handleIntent("SELECT")')          # Guide off
        run("current = 4")
        run('handleIntent("LEFT")')            # volume 70 -> 60
        run("current = 6")
        run('handleIntent("SELECT")')          # channel 7 on
        run("current = 8")
        run('handleIntent("SELECT")')          # Save
        profile_id, changes = host.saved[-1]
        assert profile_id == "kids"
        assert changes["guide"] is False and changes["volume_limit"] == 60 and changes["channels"] == [7]

        run('openFor("lobby")')
        assert run("items.map(function(i) { return i.kind })")[:3] == ["volume", "boot", "allChannels"]
        run("current = 2")
        run('handleIntent("SELECT")')          # all channels
        run("current = 1")
        run('handleIntent("RIGHT")'); run('handleIntent("RIGHT")')  # starts on 8
        run('save()')
        assert host.saved[-1] == ("lobby", {"channels": [7, 8], "volume_limit": 100, "boot_channel": 8})
    finally:
        qInstallMessageHandler(previous)
        window.close()
        app.processEvents()
    assert [m for m in messages if "ProfileEditor.qml" in m] == []
