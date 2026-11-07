"""The boot jig: starts softly, loops in 3 s passes, ends on its final note."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from channelos.boot_sound import BAR_SECONDS, BOOT_SOUND_PATH, FADE_OUT_SECONDS, BootSound, finish_delay


def test_track_ships_and_passes_end_on_the_beat() -> None:
    assert BOOT_SOUND_PATH.is_file() and BOOT_SOUND_PATH.stat().st_size < 1_000_000
    assert BAR_SECONDS == 1.5 and FADE_OUT_SECONDS == 1.5
    # A quick boot still hears two bars before fading.
    assert finish_delay(0.4) == pytest.approx(2.6)
    # Later, the fade starts on the next bar line.
    assert finish_delay(4.0) == pytest.approx(0.5)
    assert finish_delay(5.98) == pytest.approx(1.52)  # too close to the line: the next one
    assert finish_delay(40.0) == pytest.approx(0.5)


class FakeBackend:
    def __init__(self, volume):
        self.volume = volume
        self.loaded = None
        self.playing = False
        self.levels = []
        self.position = 0.0

    def load(self, path):
        self.loaded = Path(path)

    def play(self):
        self.playing = True

    def set_volume(self, percent):
        self.user_volume = percent

    def get_position(self):
        return self.position

    def set_transition_level(self, level):
        self.levels.append(level)

    def stop(self):
        self.playing = False


def _pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_boot_sound_plays_then_fades_on_the_next_boundary(monkeypatch) -> None:
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    made = []
    sound = BootSound(40, False, backend_factory=lambda volume: made.append(FakeBackend(volume)) or made[-1])
    assert sound.start()
    _pump(app, 0.2)
    backend = made[0]
    assert backend.volume == 40 and backend.playing and backend.loaded == BOOT_SOUND_PATH
    # Pretend we are 2.8 s in: the fade starts on the bar line at 3.0 s and lasts a bar.
    backend.position = 2.8
    sound.finish()
    _pump(app, 0.1)
    assert backend.levels == [] and backend.playing, "waits for the bar line"
    _pump(app, 1.2)
    assert backend.levels and 0.0 < backend.levels[-1] < 0.9
    _pump(app, 1.0)
    assert sound.finished and not backend.playing


def test_muted_or_zero_volume_never_plays() -> None:
    made = []
    for volume, muted in ((0, False), (70, True)):
        sound = BootSound(volume, muted, backend_factory=lambda v: made.append(v))
        assert not sound.start() and sound.finished
    assert made == []


def test_missing_audio_stays_silent() -> None:
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])

    def broken(volume):
        raise OSError("no audio device")

    sound = BootSound(50, False, backend_factory=broken)
    sound.start()
    _pump(app, 0.2)
    sound.finish()
    _pump(app, 0.1)
    assert sound.finished


def test_settings_and_boot_plan(tmp_path: Path) -> None:
    from channelos.boot_sound import POPPIE_LOOP, boot_sound_plan
    from channelos.settings import CouchSettings, SettingsStore
    from channelos.startup_qt import boot_preferences
    defaults = CouchSettings()
    assert (defaults.boot_sound, defaults.boot_sound_volume) == ("poppie", 25)
    # Older settings files stored a yes/no.
    assert CouchSettings.from_mapping({"boot_sound": False}).boot_sound == "off"
    assert CouchSettings.from_mapping({"boot_sound": True}).boot_sound == "poppie"
    assert CouchSettings.from_mapping({"boot_sound": "custom"}).boot_sound == "poppie", "custom needs a file"
    assert CouchSettings.from_mapping({"boot_sound_volume": 33}).boot_sound_volume == 25
    store = SettingsStore(tmp_path / "settings.json")
    store.save(CouchSettings(volume_percent=80))
    plan = boot_preferences(tmp_path / "runtime.db")["bootSoundPlan"]
    assert plan["volume"] == 20 and plan["loop"] == POPPIE_LOOP and plan["path"] == BOOT_SOUND_PATH
    assert boot_sound_plan(CouchSettings(muted=True), tmp_path) is None
    assert boot_sound_plan(CouchSettings(boot_sound="off"), tmp_path) is None
    (tmp_path / "boot").mkdir()
    (tmp_path / "boot" / "sound-1.mp3").write_bytes(b"x")
    custom = boot_sound_plan(CouchSettings(boot_sound="custom", boot_sound_file="sound-1.mp3", boot_sound_volume=50), tmp_path)
    assert custom["path"].name == "sound-1.mp3" and custom["loop"] is None and custom["volume"] == 50


def test_poppie_loops_back_to_the_lead_in_while_loading() -> None:
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])

    class Looping(FakeBackend):
        seeks: list = []
        ended = False
        def seek(self, seconds):
            self.seeks.append(seconds)
            self.position = seconds
        def has_ended(self):
            return self.ended

    made = []
    sound = BootSound(25, backend_factory=lambda v: made.append(Looping(v)) or made[-1])
    sound.start()
    _pump(app, 0.2)
    backend = made[0]
    backend.position = 54.0
    _pump(app, 0.1)
    assert backend.seeks and abs(backend.seeks[-1] - 18.03) < 0.05, "back to the lead-in at the cycle end"
    backend.ended = True
    _pump(app, 0.1)
    assert backend.playing and abs(backend.seeks[-1] - 18.03) < 0.05
    sound.stop()


def test_custom_sound_import_and_volume(tmp_path: Path) -> None:
    from test_performance_operations import controller_fixture
    _app, controller, _root = controller_fixture(tmp_path)
    try:
        assert controller.settings["bootSoundLabel"] == "Poppie" and controller.settings["bootSoundVolume"] == 25
        assert controller.adjustSetting("bootSoundVolume", -1)["message"] == "Boot sound volume: 20%"
        song = tmp_path / "my song.mp3"
        song.write_bytes(b"ID3 fake")
        assert not controller.importBootSound(str(tmp_path / "notes.txt"))["ok"]
        result = controller.importBootSound(str(song))
        assert result["ok"] and controller.settings["bootSound"] == "custom"
        stored = controller._boot_sound_path()
        assert stored is not None and stored.read_bytes() == b"ID3 fake"
        assert controller.adjustSetting("bootSound", 1)["message"] == "Boot sound: Off"
        assert controller.adjustSetting("bootSound", 1)["message"] == "Boot sound: Poppie"
    finally:
        controller.stop()
