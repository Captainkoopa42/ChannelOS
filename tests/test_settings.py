from __future__ import annotations

import json

from channelos.settings import CouchSettings, SettingsStore


def test_missing_settings_file_uses_existing_channelos_behavior(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    assert store.load() == CouchSettings(
        volume_percent=100,
        muted=False,
        skip_back_seconds=10,
        skip_forward_seconds=30,
    )


def test_settings_round_trip_to_separate_json_file(tmp_path) -> None:
    path = tmp_path / ".channelos" / "settings.json"
    store = SettingsStore(path)
    expected = CouchSettings(
        volume_percent=65,
        muted=True,
        skip_back_seconds=15,
        skip_forward_seconds=60,
    )

    assert store.save(expected) == expected
    assert store.load() == expected
    assert not path.with_name("settings.json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "muted": True,
        "skip_back_seconds": 15,
        "skip_forward_seconds": 60,
        "volume_percent": 65,
    }


def test_invalid_or_corrupt_settings_fall_back_safely(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")
    store = SettingsStore(path)

    assert store.load() == CouchSettings()

    path.write_text(
        json.dumps(
            {
                "volume_percent": 900,
                "muted": "yes",
                "skip_back_seconds": 999,
                "skip_forward_seconds": 1,
            }
        ),
        encoding="utf-8",
    )
    assert store.load() == CouchSettings(
        volume_percent=100,
        muted=False,
        skip_back_seconds=10,
        skip_forward_seconds=30,
    )


def test_volume_is_clamped_but_valid_skip_choices_are_preserved() -> None:
    assert CouchSettings.from_mapping(
        {
            "volume_percent": -12,
            "muted": True,
            "skip_back_seconds": 30,
            "skip_forward_seconds": 90,
        }
    ) == CouchSettings(
        volume_percent=0,
        muted=True,
        skip_back_seconds=30,
        skip_forward_seconds=90,
    )
