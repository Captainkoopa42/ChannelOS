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


@dataclass(frozen=True, slots=True)
class CouchSettings:
    """Small, user-owned couch preferences with conservative defaults."""

    volume_percent: int = DEFAULT_VOLUME_PERCENT
    muted: bool = DEFAULT_MUTED
    skip_back_seconds: int = DEFAULT_SKIP_BACK_SECONDS
    skip_forward_seconds: int = DEFAULT_SKIP_FORWARD_SECONDS

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

        return cls(
            volume_percent=max(0, min(100, int(volume))),
            muted=muted,
            skip_back_seconds=int(skip_back),
            skip_forward_seconds=int(skip_forward),
        )

    def to_mapping(self) -> dict[str, int | bool]:
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
