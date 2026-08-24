from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_VOLUME_PERCENT = 100
DEFAULT_MUTED = False
DEFAULT_SKIP_BACK_SECONDS = 10
DEFAULT_SKIP_FORWARD_SECONDS = 30
SKIP_BACK_CHOICES = (5, 10, 15, 30)
SKIP_FORWARD_CHOICES = (15, 30, 60, 90)
PERFORMANCE_PROFILES = ("standard", "lightweight", "custom")
ARTWORK_CACHE_LIMIT_CHOICES_MB = (0, 128, 256, 512, 1024, 2048)
THUMBNAIL_WIDTH_CHOICES = (320, 480, 640)
FFMPEG_THREAD_CHOICES = (0, 1, 2)

STANDARD_PERFORMANCE = {
    "generate_video_thumbnails": True,
    "artwork_cache_limit_mb": 0,
    "background_artwork_during_playback": True,
    "reduced_motion": False,
    "thumbnail_width": 640,
    "ffmpeg_threads": 0,
}

LIGHTWEIGHT_PERFORMANCE = {
    "generate_video_thumbnails": False,
    "artwork_cache_limit_mb": 256,
    "background_artwork_during_playback": False,
    "reduced_motion": True,
    "thumbnail_width": 320,
    "ffmpeg_threads": 1,
}


@dataclass(frozen=True, slots=True)
class CouchSettings:
    """Small, user-owned couch preferences with conservative defaults."""

    volume_percent: int = DEFAULT_VOLUME_PERCENT
    muted: bool = DEFAULT_MUTED
    skip_back_seconds: int = DEFAULT_SKIP_BACK_SECONDS
    skip_forward_seconds: int = DEFAULT_SKIP_FORWARD_SECONDS
    performance_profile: str = "standard"
    generate_video_thumbnails: bool = True
    artwork_cache_limit_mb: int = 0
    background_artwork_during_playback: bool = True
    reduced_motion: bool = False
    thumbnail_width: int = 640
    ffmpeg_threads: int = 0

    def with_performance_profile(self, profile: str) -> "CouchSettings":
        selected = str(profile).strip().lower()
        if selected not in PERFORMANCE_PROFILES:
            raise ValueError(f"unknown performance profile: {profile}")
        if selected == "custom":
            values = self.to_mapping()
            values["performance_profile"] = "custom"
            return CouchSettings.from_mapping(values)
        preset = (
            STANDARD_PERFORMANCE
            if selected == "standard"
            else LIGHTWEIGHT_PERFORMANCE
        )
        values = self.to_mapping()
        values.update(preset)
        values["performance_profile"] = selected
        return CouchSettings.from_mapping(values)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "CouchSettings":
        volume = values.get("volume_percent", DEFAULT_VOLUME_PERCENT)
        if not isinstance(volume, int) or isinstance(volume, bool):
            volume = DEFAULT_VOLUME_PERCENT

        muted = values.get("muted", DEFAULT_MUTED)
        if not isinstance(muted, bool):
            muted = DEFAULT_MUTED

        skip_back = values.get(
            "skip_back_seconds",
            DEFAULT_SKIP_BACK_SECONDS,
        )
        if skip_back not in SKIP_BACK_CHOICES:
            skip_back = DEFAULT_SKIP_BACK_SECONDS

        skip_forward = values.get(
            "skip_forward_seconds",
            DEFAULT_SKIP_FORWARD_SECONDS,
        )
        if skip_forward not in SKIP_FORWARD_CHOICES:
            skip_forward = DEFAULT_SKIP_FORWARD_SECONDS

        performance_profile = str(
            values.get("performance_profile", "standard")
        ).strip().lower()
        if performance_profile not in PERFORMANCE_PROFILES:
            performance_profile = "standard"

        if performance_profile in {"standard", "lightweight"}:
            performance = (
                STANDARD_PERFORMANCE
                if performance_profile == "standard"
                else LIGHTWEIGHT_PERFORMANCE
            )
        else:
            performance = {
                "generate_video_thumbnails": values.get(
                    "generate_video_thumbnails",
                    True,
                ),
                "artwork_cache_limit_mb": values.get(
                    "artwork_cache_limit_mb",
                    0,
                ),
                "background_artwork_during_playback": values.get(
                    "background_artwork_during_playback",
                    True,
                ),
                "reduced_motion": values.get("reduced_motion", False),
                "thumbnail_width": values.get("thumbnail_width", 640),
                "ffmpeg_threads": values.get("ffmpeg_threads", 0),
            }

        generate_video_thumbnails = performance["generate_video_thumbnails"]
        if not isinstance(generate_video_thumbnails, bool):
            generate_video_thumbnails = True

        background_artwork = performance[
            "background_artwork_during_playback"
        ]
        if not isinstance(background_artwork, bool):
            background_artwork = True

        reduced_motion = performance["reduced_motion"]
        if not isinstance(reduced_motion, bool):
            reduced_motion = False

        cache_limit = performance["artwork_cache_limit_mb"]
        if cache_limit not in ARTWORK_CACHE_LIMIT_CHOICES_MB:
            cache_limit = 0

        thumbnail_width = performance["thumbnail_width"]
        if thumbnail_width not in THUMBNAIL_WIDTH_CHOICES:
            thumbnail_width = 640

        ffmpeg_threads = performance["ffmpeg_threads"]
        if ffmpeg_threads not in FFMPEG_THREAD_CHOICES:
            ffmpeg_threads = 0

        return cls(
            volume_percent=max(0, min(100, int(volume))),
            muted=muted,
            skip_back_seconds=int(skip_back),
            skip_forward_seconds=int(skip_forward),
            performance_profile=performance_profile,
            generate_video_thumbnails=generate_video_thumbnails,
            artwork_cache_limit_mb=int(cache_limit),
            background_artwork_during_playback=background_artwork,
            reduced_motion=reduced_motion,
            thumbnail_width=int(thumbnail_width),
            ffmpeg_threads=int(ffmpeg_threads),
        )

    def to_mapping(self) -> dict[str, int | bool | str]:
        return dict(asdict(self))


class SettingsStore:
    """Load and atomically save preferences outside media/runtime databases."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> CouchSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return CouchSettings()
        if not isinstance(raw, dict):
            return CouchSettings()
        return CouchSettings.from_mapping(raw)

    def save(self, settings: CouchSettings) -> CouchSettings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        payload = json.dumps(
            settings.to_mapping(),
            indent=2,
            sort_keys=True,
        )
        temporary.write_text(f"{payload}\n", encoding="utf-8")
        temporary.replace(self.path)
        return settings

    def reset(self) -> CouchSettings:
        return self.save(CouchSettings())
