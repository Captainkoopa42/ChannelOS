"""Themes: every QML colour goes through Theme.c and every theme covers them."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import channelos

QML = Path(channelos.__file__).resolve().parent / "qml"
LITERAL = re.compile(r'"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?"')


def _theme_colors() -> set[str]:
    found = set()
    for path in QML.glob("*.qml"):
        if path.name != "Theme.qml":
            found |= {m.lower() for m in re.findall(r'Theme\.c\("(#[0-9a-fA-F]{6,8})"\)', path.read_text("utf-8"))}
    return found


def test_qmldir_lists_every_qml_type() -> None:
    listed = {line.split()[-1] for line in (QML / "qmldir").read_text().splitlines()
              if line.strip() and not line.startswith("#")}
    assert listed == {path.name for path in QML.glob("*.qml")}


def test_no_screen_hardcodes_a_colour_outside_the_theme() -> None:
    for path in QML.glob("*.qml"):
        # Theme.qml holds the palettes; ThemeBuilder.qml offers raw colours
        # as picker swatches (data the viewer chooses, not interface colours).
        if path.name in {"Theme.qml", "ThemeBuilder.qml"}:
            continue
        text = path.read_text("utf-8")
        stray = [m.group() for m in LITERAL.finditer(text)
                 if not text[max(0, m.start() - 8):m.start()].endswith(("Theme.c(", "Theme.v("))]
        assert stray == [], f"{path.name}: {stray[:5]}"


def _theme(engine):
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtCore import QUrl
    component = QQmlComponent(engine)
    component.setData(b'import QtQuick\nQtObject { property var theme: Theme }', QUrl.fromLocalFile(str(QML / "probe.qml")))
    probe = component.create()
    assert probe is not None, [e.toString() for e in component.errors()]
    return component, probe


def test_every_theme_maps_every_colour_and_switches_live() -> None:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    component, probe = _theme(engine)

    def evaluate(code):
        expression = QQmlExpression(engine.rootContext(), probe, code)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value.toVariant() if hasattr(value, "toVariant") else value

    colors = _theme_colors()
    assert evaluate('theme.c("#081625")') == "#081625"
    names = evaluate("theme.names")
    assert names[0] == "channelos" and "chromespace" in names
    for name in names[1:]:
        palette = evaluate(f"theme.palettes['{name}']")
        missing = sorted(colors - set(palette))
        assert missing == [], f"{name} lacks {missing[:5]}"
        evaluate(f'theme.name = "{name}"')
        assert evaluate('theme.c("#081625")') == palette["#081625"]
        assert evaluate("theme.light") is True
        # Text and surfaces keep strong contrast in a light theme.
        assert _contrast(palette["#f4f7fb"], palette["#081625"]) >= 7
        assert _contrast(palette["#9fb0c2"], palette["#081625"]) >= 4.5
        assert _contrast("#ffffff", palette["#1a91ff"]) >= 4.5
        assert _contrast(palette["#fffffe"], palette["#12527f"]) >= 7
    del probe, component
    app.processEvents()


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[-6:][i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_theme_builder_saves_previews_uses_and_deletes_custom_themes(tmp_path: Path) -> None:
    import json
    from PySide6.QtGui import QImage, QColor
    from test_performance_operations import controller_fixture
    app, controller, _root = controller_fixture(tmp_path)
    try:
        builtins = [t["id"] for t in controller.themes]
        assert builtins == ["channelos", "chromespace"]
        assert controller.themeSpec["palette"] == {}

        picture = tmp_path / "wall.png"
        image = QImage(64, 36, QImage.Format.Format_RGB32)
        image.fill(QColor("#6699cc"))
        assert image.save(str(picture))
        imported = controller.importThemeImage(str(picture))
        assert imported["ok"] and imported["url"].startswith("file:")
        assert not controller.importThemeImage(str(tmp_path / "notes.txt"))["ok"]

        roles = dict(controller.themes[1]["roles"], accent="#003399", highlight="#ff6600")
        draft = {"name": "MySpace Blue", "roles": roles, "wallpaper": imported["file"],
                 "wallpaperFit": "tile", "wallpaperOpacity": 80, "panelOpacity": 70}
        assert controller.previewTheme(json.dumps(draft))["ok"]
        preview = controller.themeSpec
        assert preview["name"].startswith("custom-") and preview["wallpaper"] == imported["url"]
        # Translucent panels over the wallpaper, an opaque background behind it.
        assert preview["palette"]["#081625"].startswith("#b2")
        assert len(preview["palette"]["#050c15"]) == 7
        controller.endThemePreview()
        assert controller.themeSpec["palette"] == {}

        saved = controller.saveTheme(json.dumps(draft), True)
        assert saved["ok"] and controller._settings.theme == saved["id"]
        assert controller.settings["themeName"] == "MySpace Blue"
        spec = controller.themeSpec
        assert spec["name"] == saved["id"] and spec["wallpaperFit"] == "tile"
        assert spec["palette"]["#1a91ff"] == "#003399"
        assert [t["name"] for t in controller.themes][-1] == "MySpace Blue"

        # The Settings Theme row cycles through custom themes too.
        assert controller.adjustSetting("theme", 1)["message"] == "Theme: ChannelOS"
        assert controller.adjustSetting("theme", -1)["message"] == "Theme: MySpace Blue"

        # Reloading the controller keeps the theme; deleting falls back safely.
        assert controller._theme_store.get(saved["id"]).wallpaper == imported["file"]
        assert controller.deleteTheme(saved["id"])["ok"]
        assert controller._settings.theme == "channelos" and controller.themeSpec["palette"] == {}
        assert not controller.deleteTheme("chromespace")["ok"]
    finally:
        controller.stop()


def test_custom_palettes_keep_text_readable_for_light_and_dark_roles() -> None:
    from channelos.themes import CHANNELOS_ROLES, CHROMESPACE_ROLES, contrast, derive_palette, theme_literals
    for roles in (CHANNELOS_ROLES, CHROMESPACE_ROLES, dict(CHROMESPACE_ROLES, accent="#ffcc00")):
        palette = derive_palette(roles)
        assert set(palette) == set(theme_literals())
        assert contrast(palette["#f4f7fb"], palette["#081625"]) >= 7
        assert contrast(palette["#ffffff"], palette["#1a91ff"]) >= 4.5
        assert contrast(palette["#fffffe"], palette["#12396a"]) >= 4.5
    # The ChannelOS roles reproduce the ChannelOS look exactly where it matters.
    same = derive_palette(CHANNELOS_ROLES)
    for key in ("#050c15", "#081625", "#0d2035", "#1a3550", "#f4f7fb", "#9fb0c2", "#1a91ff", "#42adff"):
        assert same[key] == key


def test_theme_builder_qml_opens_and_edits_a_draft(tmp_path: Path) -> None:
    import json
    from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
    from test_performance_operations import controller_fixture
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    app, controller, _root = controller_fixture(tmp_path)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    engine.loadData(b'import QtQuick; import QtQuick.Controls; ApplicationWindow { width: 1400; height: 860; visible: true }')
    host = engine.rootObjects()[0]
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "ThemeBuilder.qml")))
    builder = component.create()
    assert builder is not None, [e.toString() for e in component.errors()]
    builder.setProperty("parent", host.contentItem())
    host._keep = (component, builder)

    def evaluate(code):
        expression = QQmlExpression(engine.contextForObject(builder), builder, code)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value.toVariant() if hasattr(value, "toVariant") else value

    try:
        evaluate("openBuilder()")
        app.processEvents()
        assert evaluate("visible") and evaluate("selectedId") == "channelos"
        assert evaluate("draft.name") == "My ChannelOS"
        evaluate('setRole("accent", "#ff3399")')
        evaluate('set("name", "Pink")')
        assert evaluate("dirty")
        evaluate("preview()")
        assert controller.themeSpec["palette"]["#1a91ff"] == "#ff3399"
        evaluate("save(true)")
        assert not evaluate("dirty") and controller.settings["themeName"] == "Pink"
        evaluate('handleIntent("BACK")')
        app.processEvents()
        assert not evaluate("visible")
        directory = os.environ.get("CHANNELOS_THEME_SCREENSHOTS")
        if directory:
            evaluate("openBuilder()")
            for _ in range(20):
                app.processEvents()
            host.grabWindow().save(str(Path(directory) / "theme-builder.png"))
    finally:
        qInstallMessageHandler(previous)
        controller.stop()
        host.close()
        app.processEvents()
    assert [m for m in messages if "ThemeBuilder.qml" in m] == []


def test_theme_builder_works_with_a_controller_and_keeps_sliders_in_sync(tmp_path: Path) -> None:
    """Remote/controller directions walk the builder's controls; typing stays in text boxes."""
    from PySide6.QtCore import QEvent, QObject, Qt, QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QKeyEvent
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
    from channelos.control import ControlIntent
    from channelos.couch_qt import CouchKeyFilter
    from test_performance_operations import controller_fixture
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    app, controller, _root = controller_fixture(tmp_path)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)
    engine.loadData(b'import QtQuick; import QtQuick.Controls; ApplicationWindow { width: 1400; height: 860; visible: true }')
    host = engine.rootObjects()[0]
    host.requestActivate()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "ThemeBuilder.qml")))
    builder = component.create()
    assert builder is not None, [e.toString() for e in component.errors()]
    builder.setProperty("parent", host.contentItem())
    host._keep = (component, builder)
    router = CouchKeyFilter.__new__(CouchKeyFilter)
    QObject.__init__(router)
    router._window = host

    def evaluate(code):
        expression = QQmlExpression(engine.contextForObject(builder), builder, code)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value.toVariant() if hasattr(value, "toVariant") else value

    def focused():
        item = QGuiApplication.focusObject()
        return (item.objectName() if item else "", item.metaObject().className() if item else "")

    def press(intent):
        router.navigate_focus(intent)
        for _ in range(3):
            app.processEvents()

    try:
        evaluate("openBuilder()")
        for _ in range(10):
            app.processEvents()
        assert evaluate("selectedId") == "channelos"
        start = focused()
        # Down walks forward through the controls, Up walks back.
        press(ControlIntent.DOWN)
        after = focused()
        assert after != start
        press(ControlIntent.UP)
        assert focused() == start

        # Reach a role swatch and press Select: the colour picker opens on it.
        for _ in range(80):
            if focused()[0].startswith("themeRoleSwatch_"):
                break
            press(ControlIntent.DOWN)
        role = focused()[0].removeprefix("themeRoleSwatch_")
        assert role, "a colour swatch is reachable with the controller"
        press(ControlIntent.SELECT)
        assert evaluate("picker.visible") and evaluate("editingRole") == role
        # The picker's first control is a slider: Right nudges it and edits the draft.
        before = evaluate(f'draft.roles["{role}"]')
        press(ControlIntent.RIGHT)
        press(ControlIntent.RIGHT)
        assert evaluate("dirty") and evaluate(f'draft.roles["{role}"]') != before
        evaluate("picker.close()")
        app.processEvents()

        # Sliders keep following the draft after being moved (binding fix).
        evaluate('set("panelOpacity", 60)')
        evaluate('load("chromespace")')
        app.processEvents()
        assert round(evaluate("panelPercent.sliderValue")) == evaluate("draft.panelOpacity") == 85

        # Typing into a text box is never taken as a remote command.
        evaluate('set("panelOpacity", 50)')
        app.processEvents()
        assert round(evaluate("panelPercent.sliderValue")) == 50
        name = builder.findChild(QObject, "themeBuilderName")
        assert name is not None
        name.forceActiveFocus()
        app.processEvents()
        assert CouchKeyFilter._text_entry_has_focus()
        backspace = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier)
        letter_h = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_H, Qt.KeyboardModifier.NoModifier, "h")
        assert router.eventFilter(name, backspace) is False
        assert router.eventFilter(name, letter_h) is False
        assert CouchKeyFilter.command_for_key(Qt.Key.Key_Backspace) is None
    finally:
        qInstallMessageHandler(previous)
        controller.stop()
        host.close()
        app.processEvents()
    assert [m for m in messages if "ThemeBuilder.qml" in m] == []
