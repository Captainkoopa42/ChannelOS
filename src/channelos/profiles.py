"""Viewing profiles: Home, Kids, Daycare and Lobby.

A profile limits which channels exist, which screens can be opened and which
remote actions work, caps the volume, and can boot straight to one channel
(Lobby). Leaving a locked profile needs the setup's PIN. Profiles live beside
the settings file, so a portable setup keeps its locks.

The PIN keeps viewers out of the parts they should not touch; it is a lock on
the app, not on the computer (pair Lobby with Windows assigned access for a
dedicated kiosk).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

PROFILE_IDS = ("home", "kids", "daycare", "lobby")
PROFILE_NAMES = {"home": "Home", "kids": "Kids", "daycare": "Daycare", "lobby": "Lobby"}
VOLUME_LIMITS = (30, 40, 50, 60, 70, 80, 90, 100)
PIN_ITERATIONS = 120_000

# Screens a profile can open. "management" covers Channels, Studio, Planner
# and the Library manager.
SCREEN_GROUPS = {
    "home": "home", "live": "live", "guide": "guide", "library": "ondemand", "ondemand": "ondemand",
    "settings": "settings", "broadcaster": "management", "studio": "management",
    "planner": "management", "librarymanager": "management", "library_manager": "management",
}


@dataclass(frozen=True)
class Profile:
    profile_id: str
    channels: tuple[int, ...] | None = None  # None: every channel
    home: bool = True
    guide: bool = True
    ondemand: bool = True
    settings: bool = True
    management: bool = True
    change_channels: bool = True
    seek: bool = True
    volume_limit: int = 100
    boot_channel: int | None = None  # Lobby: start full screen on this channel
    locked: bool = False             # leaving needs the PIN

    @property
    def name(self) -> str:
        return PROFILE_NAMES[self.profile_id]

    def allows_screen(self, screen: str) -> bool:
        group = SCREEN_GROUPS.get(screen)
        if group is None or group == "live":
            return True
        return bool(getattr(self, group))

    def allows_channel(self, number: int) -> bool:
        return self.channels is None or int(number) in self.channels

    def to_mapping(self) -> dict[str, Any]:
        data = asdict(self)
        data["channels"] = None if self.channels is None else list(self.channels)
        return data


DEFAULTS = {
    "home": Profile("home"),
    "kids": Profile("kids", channels=(), settings=False, management=False, volume_limit=70, locked=True),
    "daycare": Profile("daycare", channels=(), ondemand=False, settings=False, management=False,
                       seek=False, volume_limit=60, locked=True),
    "lobby": Profile("lobby", channels=(), home=False, guide=False, ondemand=False, settings=False,
                     management=False, change_channels=False, seek=False, volume_limit=100, locked=True),
}


def _profile(profile_id: str, raw: Mapping[str, Any] | None) -> Profile:
    base = DEFAULTS[profile_id]
    if not raw:
        return base
    values: dict[str, Any] = {}
    for key in ("home", "guide", "ondemand", "settings", "management", "change_channels", "seek"):
        if isinstance(raw.get(key), bool):
            values[key] = raw[key]
    channels = raw.get("channels", base.channels)
    if channels is None or profile_id == "home":
        values["channels"] = None if profile_id == "home" or channels is None else base.channels
    else:
        try:
            values["channels"] = tuple(sorted({int(c) for c in channels if 0 < int(c) < 10000}))
        except (TypeError, ValueError):
            values["channels"] = base.channels
    limit = raw.get("volume_limit", base.volume_limit)
    values["volume_limit"] = limit if limit in VOLUME_LIMITS else base.volume_limit
    boot = raw.get("boot_channel")
    values["boot_channel"] = int(boot) if isinstance(boot, int) and boot > 0 else None
    # Home is always open; the others always lock.
    values["locked"] = base.locked
    if profile_id == "home":
        values.update(home=True, guide=True, ondemand=True, settings=True, management=True,
                      change_channels=True, seek=True, volume_limit=100, channels=None, boot_channel=None)
    if profile_id != "home":
        values["settings"] = False  # locked profiles reach Settings only through the PIN
        values["management"] = False
    return replace(base, **values)


def hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PIN_ITERATIONS).hex()


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 8


@dataclass
class ProfileState:
    active: str = "home"
    profiles: dict[str, Profile] = field(default_factory=lambda: dict(DEFAULTS))
    pin_hash: str = ""
    pin_salt: str = ""

    @property
    def current(self) -> Profile:
        return self.profiles[self.active]

    @property
    def has_pin(self) -> bool:
        return bool(self.pin_hash and self.pin_salt)

    def check_pin(self, pin: str) -> bool:
        if not self.has_pin or not valid_pin(str(pin)):
            return False
        expected = hash_pin(str(pin), bytes.fromhex(self.pin_salt))
        return hmac.compare_digest(expected, self.pin_hash)


class ProfileStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> ProfileState:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return ProfileState()
        if not isinstance(raw, dict):
            return ProfileState()
        stored = raw.get("profiles") if isinstance(raw.get("profiles"), dict) else {}
        profiles = {pid: _profile(pid, stored.get(pid) if isinstance(stored.get(pid), dict) else None)
                    for pid in PROFILE_IDS}
        state = ProfileState(profiles=profiles,
                             pin_hash=str(raw.get("pinHash") or ""), pin_salt=str(raw.get("pinSalt") or ""))
        active = str(raw.get("active") or "home")
        # Without a PIN no profile can be locked; never strand a viewer.
        state.active = active if active in PROFILE_IDS and (active == "home" or state.has_pin) else "home"
        return state

    def save(self, state: ProfileState) -> ProfileState:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "active": state.active, "pinHash": state.pin_hash, "pinSalt": state.pin_salt,
                "profiles": {pid: profile.to_mapping() for pid, profile in state.profiles.items()}}
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return state

    @staticmethod
    def with_pin(state: ProfileState, pin: str) -> ProfileState:
        if not valid_pin(pin):
            raise ValueError("A PIN is 4 to 8 digits")
        salt = os.urandom(16)
        return replace(state, pin_hash=hash_pin(pin, salt), pin_salt=salt.hex())

    @staticmethod
    def updated(state: ProfileState, profile_id: str, changes: Mapping[str, Any]) -> ProfileState:
        if profile_id not in PROFILE_IDS:
            raise ValueError(f"Unknown profile: {profile_id}")
        merged = dict(state.profiles[profile_id].to_mapping())
        merged.update(changes)
        profiles = dict(state.profiles)
        profiles[profile_id] = _profile(profile_id, merged)
        return replace(state, profiles=profiles)
