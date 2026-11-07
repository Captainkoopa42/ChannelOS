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
        if path.name == "Theme.qml":
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
