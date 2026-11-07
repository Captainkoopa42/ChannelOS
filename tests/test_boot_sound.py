"""The boot jig: starts softly, loops in 3 s passes, ends on its final note."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from channelos.boot_sound import BOOT_SOUND_PATH, PASS_SECONDS, BootSound, finish_delay


def test_track_ships_and_passes_end_on_the_beat() -> None:
    assert BOOT_SOUND_PATH.is_file() and BOOT_SOUND_PATH.stat().st_size < 700_000
    assert PASS_SECONDS == 3.0
    # A quick boot hears the whole first pass, then the final note.
    assert finish_delay(0.4) == pytest.approx(2.6)
    # Later, it waits for the next pass boundary.
    assert finish_delay(4.0) == pytest.approx(2.0)
    assert finish_delay(5.98) == pytest.approx(3.02)  # too close to cut: one more pass
    assert finish_delay(9.0) == pytest.approx(3.0)


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
    # Pretend we are 2.8 s in: the fade starts at 3.0 s and lasts under half a second.
    backend.position = 2.8
    sound.finish()
    _pump(app, 0.1)
    assert backend.levels == [] and backend.playing, "waits for the final note"
    _pump(app, 0.8)
    assert backend.levels and backend.levels[-1] < 0.5
    _pump(app, 0.3)
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


def test_settings_toggle_and_preferences(tmp_path: Path) -> None:
    from channelos.settings import CouchSettings, SettingsStore
    from channelos.startup_qt import boot_preferences
    assert CouchSettings().boot_sound is True
    assert CouchSettings.from_mapping({"boot_sound": False}).boot_sound is False
    store = SettingsStore(tmp_path / "settings.json")
    store.save(CouchSettings(volume_percent=60))
    prefs = boot_preferences(tmp_path / "runtime.db")
    assert prefs["bootSound"] is True and prefs["volume"] == 60
    store.save(CouchSettings(volume_percent=60, muted=True))
    assert boot_preferences(tmp_path / "runtime.db")["volume"] == 0
