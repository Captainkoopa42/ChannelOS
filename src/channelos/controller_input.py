from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .control import ControlCommand, ControlIntent


class GamepadButton(StrEnum):
    """Physical gamepad controls before ChannelOS assigns screen meaning."""

    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTH = "north"
    DPAD_UP = "dpad_up"
    DPAD_DOWN = "dpad_down"
    DPAD_LEFT = "dpad_left"
    DPAD_RIGHT = "dpad_right"
    LEFT_SHOULDER = "left_shoulder"
    RIGHT_SHOULDER = "right_shoulder"
    VIEW = "view"
    MENU = "menu"
    LEFT_STICK = "left_stick"
    RIGHT_STICK = "right_stick"


@dataclass(frozen=True, slots=True)
class GamepadSnapshot:
    """One normalized controller sample.

    Stick axes use ``-1.0 .. 1.0`` and triggers use ``0.0 .. 1.0``. Positive
    left-Y is up, matching XInput rather than screen coordinates.
    """

    buttons: frozenset[GamepadButton] = frozenset()
    left_x: float = 0.0
    left_y: float = 0.0
    right_x: float = 0.0
    right_y: float = 0.0
    left_trigger: float = 0.0
    right_trigger: float = 0.0


@dataclass(frozen=True, slots=True)
class ControllerReading:
    controller_id: str
    name: str
    snapshot: GamepadSnapshot


class ControllerBackend(Protocol):
    def read_first(self) -> ControllerReading | None:
        """Return the first connected controller, or ``None``."""


_BUTTON_INTENTS: dict[GamepadButton, ControlIntent] = {
    GamepadButton.SOUTH: ControlIntent.SELECT,
    GamepadButton.EAST: ControlIntent.BACK,
    GamepadButton.WEST: ControlIntent.PLAY_PAUSE,
    GamepadButton.NORTH: ControlIntent.INFO,
    GamepadButton.DPAD_UP: ControlIntent.UP,
    GamepadButton.DPAD_DOWN: ControlIntent.DOWN,
    GamepadButton.DPAD_LEFT: ControlIntent.LEFT,
    GamepadButton.DPAD_RIGHT: ControlIntent.RIGHT,
    GamepadButton.LEFT_SHOULDER: ControlIntent.CHANNEL_DOWN,
    GamepadButton.RIGHT_SHOULDER: ControlIntent.CHANNEL_UP,
    GamepadButton.VIEW: ControlIntent.GUIDE,
    GamepadButton.MENU: ControlIntent.HOME,
    GamepadButton.LEFT_STICK: ControlIntent.GO_LIVE,
    GamepadButton.RIGHT_STICK: ControlIntent.PREVIOUS_CHANNEL,
}

_REPEATABLE_INTENTS = {
    ControlIntent.UP,
    ControlIntent.DOWN,
    ControlIntent.LEFT,
    ControlIntent.RIGHT,
    ControlIntent.VOLUME_UP,
    ControlIntent.VOLUME_DOWN,
}


class GamepadIntentMapper:
    """Translate button edges and held navigation into ``ControlCommand``s."""

    def __init__(
        self,
        *,
        stick_press_threshold: float = 0.55,
        stick_release_threshold: float = 0.35,
        trigger_threshold: float = 0.55,
        repeat_delay_seconds: float = 0.38,
        repeat_interval_seconds: float = 0.12,
    ) -> None:
        if not 0.0 < stick_release_threshold < stick_press_threshold <= 1.0:
            raise ValueError("stick thresholds must satisfy 0 < release < press <= 1")
        if not 0.0 < trigger_threshold <= 1.0:
            raise ValueError("trigger threshold must be in (0, 1]")
        if repeat_delay_seconds <= 0.0 or repeat_interval_seconds <= 0.0:
            raise ValueError("controller repeat timings must be positive")

        self._stick_press_threshold = float(stick_press_threshold)
        self._stick_release_threshold = float(stick_release_threshold)
        self._trigger_threshold = float(trigger_threshold)
        self._repeat_delay_seconds = float(repeat_delay_seconds)
        self._repeat_interval_seconds = float(repeat_interval_seconds)
        self._active_controls: dict[str, ControlIntent] = {}
        self._repeat_at: dict[str, float] = {}
        self._suppressed_until_release: set[str] = set()
        self._stick_direction: ControlIntent | None = None
        self._volume_direction: ControlIntent | None = None

    def reset(self) -> None:
        self._active_controls.clear()
        self._repeat_at.clear()
        self._suppressed_until_release.clear()
        self._stick_direction = None
        self._volume_direction = None

    def prime(self, snapshot: GamepadSnapshot, *, now: float | None = None) -> None:
        """Accept current held state without firing ghost input on connection."""

        # Keep ``now`` in the public signature so callers can use the same
        # clock for prime/update without this method starting a repeat timer.
        _ = now
        active = self._controls(snapshot)
        self._active_controls = active
        self._repeat_at.clear()
        self._suppressed_until_release = set(active)

    def update(
        self,
        snapshot: GamepadSnapshot,
        *,
        now: float | None = None,
    ) -> tuple[ControlCommand, ...]:
        sampled_at = time.monotonic() if now is None else float(now)
        active = self._controls(snapshot)
        emitted: list[ControlCommand] = []

        for key, intent in active.items():
            if key in self._suppressed_until_release:
                continue
            if key not in self._active_controls:
                emitted.append(ControlCommand(intent))
                if intent in _REPEATABLE_INTENTS:
                    self._repeat_at[key] = sampled_at + self._repeat_delay_seconds
                continue

            if (
                intent in _REPEATABLE_INTENTS
                and sampled_at >= self._repeat_at.get(key, float("inf"))
            ):
                emitted.append(ControlCommand(intent))
                self._repeat_at[key] = sampled_at + self._repeat_interval_seconds

        released = set(self._active_controls) - set(active)
        for key in released:
            self._repeat_at.pop(key, None)
            self._suppressed_until_release.discard(key)

        self._active_controls = active

        # A D-pad and stick can represent the same direction simultaneously.
        # One physical sample should still produce only one ChannelOS intent.
        unique: list[ControlCommand] = []
        seen: set[ControlIntent] = set()
        for command in emitted:
            if command.intent in seen:
                continue
            seen.add(command.intent)
            unique.append(command)
        return tuple(unique)

    def _controls(self, snapshot: GamepadSnapshot) -> dict[str, ControlIntent]:
        controls = {
            f"button:{button.value}": _BUTTON_INTENTS[button]
            for button in snapshot.buttons
            if button in _BUTTON_INTENTS
        }

        if snapshot.left_trigger >= self._trigger_threshold:
            controls["trigger:left"] = ControlIntent.SKIP_BACK
        if snapshot.right_trigger >= self._trigger_threshold:
            controls["trigger:right"] = ControlIntent.SKIP_FORWARD

        direction = self._left_stick_direction(snapshot.left_x, snapshot.left_y)
        if direction is not None:
            controls["stick:left"] = direction
        volume_direction = self._right_stick_volume(snapshot.right_y)
        if volume_direction is not None:
            controls["stick:right:volume"] = volume_direction
        return controls

    def _left_stick_direction(
        self,
        horizontal: float,
        vertical: float,
    ) -> ControlIntent | None:
        x = max(-1.0, min(1.0, float(horizontal)))
        y = max(-1.0, min(1.0, float(vertical)))

        previous = self._stick_direction
        if previous is not None:
            component = {
                ControlIntent.LEFT: -x,
                ControlIntent.RIGHT: x,
                ControlIntent.UP: y,
                ControlIntent.DOWN: -y,
            }[previous]
            perpendicular = abs(y) if previous in {ControlIntent.LEFT, ControlIntent.RIGHT} else abs(x)
            if (
                component >= self._stick_release_threshold
                and perpendicular <= component + 0.12
            ):
                return previous

        if max(abs(x), abs(y)) < self._stick_press_threshold:
            self._stick_direction = None
            return None

        if abs(x) > abs(y):
            self._stick_direction = ControlIntent.RIGHT if x > 0 else ControlIntent.LEFT
        else:
            self._stick_direction = ControlIntent.UP if y > 0 else ControlIntent.DOWN
        return self._stick_direction

    def _right_stick_volume(self, vertical: float) -> ControlIntent | None:
        y = max(-1.0, min(1.0, float(vertical)))
        previous = self._volume_direction
        if previous is not None:
            component = y if previous is ControlIntent.VOLUME_UP else -y
            if component >= self._stick_release_threshold:
                return previous
        if abs(y) < self._stick_press_threshold:
            self._volume_direction = None
            return None
        self._volume_direction = (
            ControlIntent.VOLUME_UP if y > 0 else ControlIntent.VOLUME_DOWN
        )
        return self._volume_direction


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad", _XInputGamepad),
    ]


_XINPUT_BUTTONS: tuple[tuple[int, GamepadButton], ...] = (
    (0x1000, GamepadButton.SOUTH),
    (0x2000, GamepadButton.EAST),
    (0x4000, GamepadButton.WEST),
    (0x8000, GamepadButton.NORTH),
    (0x0001, GamepadButton.DPAD_UP),
    (0x0002, GamepadButton.DPAD_DOWN),
    (0x0004, GamepadButton.DPAD_LEFT),
    (0x0008, GamepadButton.DPAD_RIGHT),
    (0x0100, GamepadButton.LEFT_SHOULDER),
    (0x0200, GamepadButton.RIGHT_SHOULDER),
    (0x0020, GamepadButton.VIEW),
    (0x0010, GamepadButton.MENU),
    (0x0040, GamepadButton.LEFT_STICK),
    (0x0080, GamepadButton.RIGHT_STICK),
)


def _normalize_signed_axis(value: int) -> float:
    raw = int(value)
    divisor = 32767.0 if raw >= 0 else 32768.0
    return max(-1.0, min(1.0, raw / divisor))


class XInputBackend:
    """Dependency-free Windows controller backend using the system XInput DLL."""

    DLL_CANDIDATES = ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll")

    def __init__(self, library: object, *, library_name: str) -> None:
        self._library = library
        self.library_name = library_name
        self._get_state = getattr(library, "XInputGetState")
        self._get_state.argtypes = [ctypes.c_ulong, ctypes.POINTER(_XInputState)]
        self._get_state.restype = ctypes.c_ulong
        self._preferred_user_index: int | None = None

    @classmethod
    def try_create(cls) -> XInputBackend | None:
        if sys.platform != "win32":
            return None
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            return None
        for candidate in cls.DLL_CANDIDATES:
            try:
                return cls(loader(candidate), library_name=candidate)
            except (AttributeError, OSError):
                continue
        return None

    def read_first(self) -> ControllerReading | None:
        indices = list(range(4))
        if self._preferred_user_index is not None:
            indices.remove(self._preferred_user_index)
            indices.insert(0, self._preferred_user_index)
        for user_index in indices:
            state = _XInputState()
            result = int(self._get_state(user_index, ctypes.byref(state)))
            if result != 0:
                continue
            self._preferred_user_index = user_index
            gamepad = state.Gamepad
            buttons = frozenset(
                button
                for mask, button in _XINPUT_BUTTONS
                if int(gamepad.wButtons) & mask
            )
            return ControllerReading(
                controller_id=f"xinput:{user_index}",
                name=f"Xbox-compatible Controller {user_index + 1}",
                snapshot=GamepadSnapshot(
                    buttons=buttons,
                    left_x=_normalize_signed_axis(gamepad.sThumbLX),
                    left_y=_normalize_signed_axis(gamepad.sThumbLY),
                    right_x=_normalize_signed_axis(gamepad.sThumbRX),
                    right_y=_normalize_signed_axis(gamepad.sThumbRY),
                    left_trigger=float(gamepad.bLeftTrigger) / 255.0,
                    right_trigger=float(gamepad.bRightTrigger) / 255.0,
                ),
            )
        self._preferred_user_index = None
        return None


class ControllerInputHub:
    """Poll one backend and deliver normalized commands with hot-plug safety."""

    def __init__(
        self,
        backend: ControllerBackend,
        dispatch: Callable[[ControlCommand], object],
        *,
        connection_changed: Callable[[bool, str], object] | None = None,
        mapper: GamepadIntentMapper | None = None,
    ) -> None:
        self._backend = backend
        self._dispatch = dispatch
        self._connection_changed = connection_changed
        self._mapper = mapper or GamepadIntentMapper()
        self._controller_id = ""
        self._controller_name = ""

    @property
    def connected(self) -> bool:
        return bool(self._controller_id)

    @property
    def controller_name(self) -> str:
        return self._controller_name

    def poll(self, *, now: float | None = None) -> tuple[ControlCommand, ...]:
        sampled_at = time.monotonic() if now is None else float(now)
        try:
            reading = self._backend.read_first()
        except OSError:
            reading = None

        if reading is None:
            if self.connected:
                self._controller_id = ""
                self._controller_name = ""
                self._mapper.reset()
                if self._connection_changed is not None:
                    self._connection_changed(False, "")
            return ()

        if reading.controller_id != self._controller_id:
            self._controller_id = reading.controller_id
            self._controller_name = reading.name
            self._mapper.reset()
            self._mapper.prime(reading.snapshot, now=sampled_at)
            if self._connection_changed is not None:
                self._connection_changed(True, reading.name)
            return ()

        commands = self._mapper.update(reading.snapshot, now=sampled_at)
        for command in commands:
            self._dispatch(command)
        return commands


def create_controller_backend() -> ControllerBackend | None:
    """Return the native backend for this platform without making it required."""

    disabled = os.environ.get("CHANNELOS_DISABLE_CONTROLLER", "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return None
    return XInputBackend.try_create()
