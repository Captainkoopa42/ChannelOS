from __future__ import annotations

import json

from channelos.settings import (
    LIGHTWEIGHT_PERFORMANCE,
    STANDARD_PERFORMANCE,
    CouchSettings,
    SettingsStore,
)


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
        display_mode="windowed",
    )

    assert store.save(expected) == expected
    assert store.load() == expected
    assert not path.with_name("settings.json.tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "artwork_cache_limit_mb": 0,
        "background_artwork_during_playback": True,
        "display_mode": "windowed",
        "ffmpeg_threads": 0,
        "generate_video_thumbnails": True,
        "muted": True,
        "performance_profile": "standard",
        "reduced_motion": False,
        "skip_back_seconds": 15,
        "skip_forward_seconds": 60,
        "thumbnail_width": 640,
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
                "display_mode": "floating-space-window",
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
            "display_mode": "windowed",
        }
    ) == CouchSettings(
        volume_percent=0,
        muted=True,
        skip_back_seconds=30,
        skip_forward_seconds=90,
        display_mode="windowed",
    )


def test_legacy_settings_without_performance_fields_preserve_full_behavior() -> None:
    settings = CouchSettings.from_mapping(
        {
            "volume_percent": 70,
            "muted": True,
            "skip_back_seconds": 15,
            "skip_forward_seconds": 60,
        }
    )

    assert settings.performance_profile == "standard"
    assert settings.display_mode == "fullscreen"
    for name, value in STANDARD_PERFORMANCE.items():
        assert getattr(settings, name) == value


def test_lightweight_profile_applies_conservative_artwork_defaults() -> None:
    settings = CouchSettings(display_mode="windowed").with_performance_profile("lightweight")

    assert settings.performance_profile == "lightweight"
    assert settings.display_mode == "windowed"
    for name, value in LIGHTWEIGHT_PERFORMANCE.items():
        assert getattr(settings, name) == value
    assert settings.volume_percent == 100
    assert settings.skip_forward_seconds == 30


def test_named_profiles_ignore_stale_custom_values() -> None:
    settings = CouchSettings.from_mapping(
        {
            "performance_profile": "lightweight",
            "generate_video_thumbnails": True,
            "artwork_cache_limit_mb": 0,
            "background_artwork_during_playback": True,
            "reduced_motion": False,
            "thumbnail_width": 640,
            "ffmpeg_threads": 0,
        }
    )

    assert settings == CouchSettings().with_performance_profile("lightweight")


def test_custom_performance_values_are_validated_and_persisted() -> None:
    settings = CouchSettings.from_mapping(
        {
            "performance_profile": "custom",
            "generate_video_thumbnails": False,
            "artwork_cache_limit_mb": 512,
            "background_artwork_during_playback": False,
            "reduced_motion": True,
            "thumbnail_width": 480,
            "ffmpeg_threads": 2,
            "display_mode": "windowed",
        }
    )

    assert settings.performance_profile == "custom"
    assert settings.display_mode == "windowed"
    assert settings.generate_video_thumbnails is False
    assert settings.artwork_cache_limit_mb == 512
    assert settings.background_artwork_during_playback is False
    assert settings.reduced_motion is True
    assert settings.thumbnail_width == 480
    assert settings.ffmpeg_threads == 2
