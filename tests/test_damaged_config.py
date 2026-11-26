"""Damaged or hand-edited config files must never stop ChannelOS from starting.

A realistic Windows case: someone opens settings.json in Notepad and saves it
as "Unicode" (UTF-16), which is not valid UTF-8.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from channelos.profiles import ProfileStore
from channelos.settings import CouchSettings, SettingsStore
from channelos.themes import ThemeStore

UTF16_JSON = '{"volume": 40}'.encode("utf-16")  # starts with the FF FE byte-order mark
DAMAGED = {
    "utf16": UTF16_JSON,
    "invalid-utf8": b"\xff\xfe\x00{",
    "truncated": b'{"profiles": {"kids": {"volumeLim',
    "zero-filled": b"\x00" * 64,  # what NTFS can leave after a power cut
}


@pytest.mark.parametrize("content", DAMAGED.values(), ids=DAMAGED.keys())
def test_settings_fall_back_to_defaults(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(content)
    assert SettingsStore(path).load() == CouchSettings()


@pytest.mark.parametrize("content", DAMAGED.values(), ids=DAMAGED.keys())
def test_profiles_fall_back_to_home(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "profiles.json"
    path.write_bytes(content)
    state = ProfileStore(path).load()
    assert state.active == "home" and not state.has_pin


@pytest.mark.parametrize("content", DAMAGED.values(), ids=DAMAGED.keys())
def test_themes_fall_back_to_none(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "themes.json").write_bytes(content)
    assert ThemeStore(tmp_path).load() == []


@pytest.mark.parametrize("salt", ["zz", "abc", 3])
def test_damaged_pin_never_strands_a_locked_profile(tmp_path: Path, salt) -> None:
    store = ProfileStore(tmp_path / "profiles.json")
    good = store.save(ProfileStore.with_pin(store.load(), "2468"))
    raw = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    raw["pinSalt"] = salt
    raw["active"] = "lobby"
    (tmp_path / "profiles.json").write_text(json.dumps(raw), encoding="utf-8")

    state = store.load()
    assert not state.has_pin
    assert state.active == "home"  # a PIN that can never be entered must not lock anyone in
    assert state.check_pin("2468") is False
    assert good.check_pin("2468") is True


def test_check_pin_tolerates_a_bad_salt_in_memory(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles.json")
    state = ProfileStore.with_pin(store.load(), "2468")
    state.pin_salt = "not-hex"
    assert state.check_pin("2468") is False
