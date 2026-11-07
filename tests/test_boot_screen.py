"""Boot video and loading styles."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import channelos
from channelos.settings import CouchSettings, SettingsStore

QML = Path(channelos.__file__).resolve().parent / "qml"


def test_boot_settings_persist_and_fall_back(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    saved = CouchSettings(boot_video="custom", boot_video_file="boot-1.mp4", boot_video_sound=False, loading_style="tv")
    store.save(saved)
    assert store.load() == saved
    # Custom without a file, or unknown values, fall back to the first-boot defaults.
    assert CouchSettings.from_mapping({"boot_video": "custom"}).boot_video == "static"
    broken = CouchSettings.from_mapping({"boot_video": "laser", "loading_style": "spin", "boot_video_file": "../../x.mp4"})
    assert (broken.boot_video, broken.loading_style) == ("static", "classic")
    assert CouchSettings.from_mapping({"boot_video_file": "../../x.mp4", "boot_video": "custom"}).boot_video_file == "x.mp4"
    assert CouchSettings().boot_video == "static" and CouchSettings().loading_style == "classic"


def test_boot_preferences_read_before_the_setup_opens(tmp_path: Path) -> None:
    from channelos.startup_qt import boot_preferences
    state_db = tmp_path / "state.sqlite3"
    assert boot_preferences(state_db)["video"] == "static"
    SettingsStore(tmp_path / "settings.json").save(
        CouchSettings(boot_video="custom", boot_video_file="boot-1.mp4", loading_style="bar"))
    # The file is missing: static, never a broken boot.
    prefs = boot_preferences(state_db)
    assert prefs["video"] == "static" and prefs["loadingStyle"] == "bar"
    (tmp_path / "boot").mkdir()
    (tmp_path / "boot" / "boot-1.mp4").write_bytes(b"0")
    prefs = boot_preferences(state_db)
    assert prefs["video"] == "custom" and prefs["videoPath"].endswith("boot-1.mp4")
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert boot_preferences(state_db)["video"] == "static"


def test_boot_video_import_cycle_and_preview(tmp_path: Path) -> None:
    from test_performance_operations import controller_fixture
    app, controller, _root = controller_fixture(tmp_path)
    try:
        assert controller.adjustSetting("bootVideo", 1)["message"].startswith("Boot video: Off")
        assert "choose a video" in controller.adjustSetting("bootVideo", 1)["message"]
        clip = tmp_path / "intro.MP4"
        clip.write_bytes(b"\0" * 64)
        assert not controller.importBootVideo(str(tmp_path / "notes.txt"))["ok"]
        result = controller.importBootVideo(str(clip))
        assert result["ok"] and controller.settings["bootVideo"] == "custom"
        stored = controller._boot_video_path()
        assert stored is not None and stored.parent.name == "boot" and stored.suffix == ".mp4"
        # Replacing the video removes the old copy.
        assert controller.importBootVideo(str(clip))["ok"]
        assert not stored.exists() and controller._boot_video_path().exists()
        assert controller.bootPreview()["url"].startswith("file:")
        cycle = [controller.adjustSetting("bootVideo", 1)["message"] for _ in range(3)]
        assert cycle == ["Boot video: Off", "Boot video: TV Static", "Boot video: My Video"]
        assert controller.adjustSetting("bootVideoSound", 1)["message"] == "Boot video sound: Off"
        assert controller.adjustSetting("loadingStyle", 1)["message"] == "Loading style: Fill Bar"
        assert controller.adjustSetting("loadingStyle", 1)["message"] == "Loading style: Dancing TV"
        assert controller.settings["loadingStyleLabel"] == "Dancing TV"
    finally:
        controller.stop()


def _boot_item(app, engine, properties: dict):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtQuick import QQuickWindow
    window = QQuickWindow()
    window.resize(1280, 720)
    window.show()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "BootScreen.qml")))
    item = component.create(engine.rootContext())
    assert item is not None, [e.toString() for e in component.errors()]
    item.setParentItem(window.contentItem())
    item.setWidth(1280)
    item.setHeight(720)
    for key, value in properties.items():
        item.setProperty(key, value)
    return window, component, item


@pytest.mark.parametrize("style", ["classic", "bar", "tv"])
def test_every_loading_style_renders_without_qml_warnings(style: str) -> None:
    import time
    from PySide6.QtCore import QObject, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlEngine
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    try:
        window, component, item = _boot_item(app, engine, {"loadingStyle": style, "progress": 0.55, "message": "Tuning in…"})
        for _ in range(30):
            app.processEvents()
            time.sleep(0.02)
        visible = {name: item.findChild(QObject, name).property("visible") for name in ("bootClassic", "bootBar", "bootTv")}
        expected = {"classic": "bootClassic", "bar": "bootBar", "tv": "bootTv"}[style]
        assert [name for name, shown in visible.items() if shown] == [expected]
        directory = os.environ.get("CHANNELOS_BOOT_SCREENSHOTS")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            window.grabWindow().save(str(Path(directory) / f"boot-{style}.png"))
        # Reduced Motion swaps the dancing TV for the fill bar.
        item.setProperty("reducedMotion", True)
        app.processEvents()
        assert item.property("effectiveStyle") == ("bar" if style == "tv" else style)
        window.close()
        del item, component
        app.processEvents()
    finally:
        qInstallMessageHandler(previous)
    assert [m for m in messages if "BootScreen.qml" in m] == []


def test_mascot_layers_recompose_the_app_icon() -> None:
    from PySide6.QtGui import QImage, QPainter
    assets = Path(channelos.__file__).resolve().parent / "assets"
    icon = QImage(str(assets / "ChannelOS.png")).convertToFormat(QImage.Format.Format_ARGB32)
    composed = QImage(icon.size(), QImage.Format.Format_ARGB32)
    composed.fill(0)
    painter = QPainter(composed)
    for layer in ("body", "antenna_left", "antenna_right"):
        image = QImage(str(assets / "mascot" / f"{layer}.png"))
        assert not image.isNull(), layer
        painter.drawImage(0, 0, image)
    painter.end()
    different = sum(1 for y in range(0, 512, 4) for x in range(0, 512, 4)
                    if abs(composed.pixelColor(x, y).alpha() - icon.pixelColor(x, y).alpha()) > 8)
    assert different < 40


def test_startup_window_loads_and_skips_the_boot_video() -> None:
    from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QWindow
    from PySide6.QtQml import QQmlApplicationEngine

    class FakeStartup(QObject):
        changed = Signal()

        def __init__(self):
            super().__init__()
            self.playing = True
            self.skips = 0

        @Property(str, notify=changed)
        def message(self): return "Opening your ChannelOS setup…"

        @Property(bool, notify=changed)
        def canClose(self): return False

        @Property(float, notify=changed)
        def progress(self): return 0.4

        @Property(bool, notify=changed)
        def videoPlaying(self): return self.playing

        @Property("QVariantMap", constant=True)
        def boot(self): return {"video": "custom", "loadingStyle": "tv", "reducedMotion": False}

        @Property("QVariantMap", constant=True)
        def themeSpec(self): return {"name": "chromespace", "palette": {}}

        @Slot()
        def skipBootVideo(self):
            self.skips += 1
            self.playing = False
            self.changed.emit()

        @Slot()
        def closeRequested(self): pass

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _m, _c, text: messages.append(text))
    app = QGuiApplication.instance() or QGuiApplication([])
    control = FakeStartup()
    video = QWindow()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("startupControl", control)
    engine.rootContext().setContextProperty("bootVideoWindow", video)
    try:
        engine.load(QUrl.fromLocalFile(str(QML / "StartupWindow.qml")))
        window = engine.rootObjects()[0]
        window.requestActivate()
        for _ in range(5):
            app.processEvents()
        boot = window.findChild(QObject, "bootScreen")
        assert boot.property("showStatic") is False, "the video covers the static while it plays"
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from channelos.startup_qt import BootSkipFilter
        skipper = BootSkipFilter(control.skipBootVideo)
        app.installEventFilter(skipper)
        app.sendEvent(video, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
        app.removeEventFilter(skipper)
        app.processEvents()
        assert control.skips == 1 and boot.property("showStatic") is True
        window.close()
    finally:
        qInstallMessageHandler(previous)
    assert [m for m in messages if "StartupWindow.qml" in m or "BootScreen.qml" in m] == []
