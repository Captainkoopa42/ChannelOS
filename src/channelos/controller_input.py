from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol

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
    GUIDE = "guide"
    MISC = "misc"
    PADDLE1 = "paddle1"
    PADDLE2 = "paddle2"
    PADDLE3 = "paddle3"
    PADDLE4 = "paddle4"
    TOUCHPAD = "touchpad"


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
    family: str = "xbox"


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


def _control_key(control: str) -> str:
    """Binding id -> internal key ("south" -> "button:south")."""
    if control in ("left_trigger", "right_trigger"):
        return "trigger:" + control.split("_")[0]
    if control.startswith("rstick_"):
        return "rstick:" + control.removeprefix("rstick_")
    return "button:" + control


def _right_stick_direction(horizontal: float, vertical: float, threshold: float) -> str | None:
    x = max(-1.0, min(1.0, float(horizontal)))
    y = max(-1.0, min(1.0, float(vertical)))
    if max(abs(x), abs(y)) < threshold:
        return None
    if abs(x) > abs(y):
        return "right" if x > 0 else "left"
    return "up" if y > 0 else "down"


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
        bindings: Mapping[str, ControlIntent | None] | None = None,
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
        self._right_direction: str | None = None
        self.set_bindings(bindings)

    def set_bindings(self, bindings: Mapping[str, ControlIntent | None] | None) -> None:
        """Physical control id (``south``, ``left_trigger``, ``rstick_up``…) -> intent."""
        merged: dict[str, ControlIntent | None] = {
            **{f"button:{button.value}": intent for button, intent in _BUTTON_INTENTS.items()},
            "trigger:left": ControlIntent.SKIP_BACK,
            "trigger:right": ControlIntent.SKIP_FORWARD,
            "rstick:up": ControlIntent.VOLUME_UP,
            "rstick:down": ControlIntent.VOLUME_DOWN,
        }
        for control, intent in (bindings or {}).items():
            merged[_control_key(control)] = intent
        self._bindings = merged

    def raw_controls(self, snapshot: GamepadSnapshot) -> set[str]:
        """Physical controls held now, as binding ids (for the button mapper)."""
        held = {button.value for button in snapshot.buttons}
        if snapshot.left_trigger >= self._trigger_threshold:
            held.add("left_trigger")
        if snapshot.right_trigger >= self._trigger_threshold:
            held.add("right_trigger")
        direction = _right_stick_direction(snapshot.right_x, snapshot.right_y, self._stick_press_threshold)
        if direction:
            held.add("rstick_" + direction)
        return held

    def reset(self) -> None:
        self._active_controls.clear()
        self._repeat_at.clear()
        self._suppressed_until_release.clear()
        self._stick_direction = None
        self._right_direction = None

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
        bindings = self._bindings
        controls: dict[str, ControlIntent] = {}
        for button in snapshot.buttons:
            intent = bindings.get(f"button:{button.value}")
            if intent is not None:
                controls[f"button:{button.value}"] = intent

        if snapshot.left_trigger >= self._trigger_threshold and bindings.get("trigger:left") is not None:
            controls["trigger:left"] = bindings["trigger:left"]
        if snapshot.right_trigger >= self._trigger_threshold and bindings.get("trigger:right") is not None:
            controls["trigger:right"] = bindings["trigger:right"]

        # The left stick always navigates, so a remapped D-pad can't strand anyone.
        direction = self._left_stick_direction(snapshot.left_x, snapshot.left_y)
        if direction is not None:
            controls["stick:left"] = direction
        right = self._right_stick_hold(snapshot.right_x, snapshot.right_y)
        if right is not None and bindings.get(f"rstick:{right}") is not None:
            controls[f"rstick:{right}"] = bindings[f"rstick:{right}"]
        return controls

    def _right_stick_hold(self, horizontal: float, vertical: float) -> str | None:
        """Right stick as four held directions, with release hysteresis."""
        x = max(-1.0, min(1.0, float(horizontal)))
        y = max(-1.0, min(1.0, float(vertical)))
        previous = self._right_direction
        if previous is not None:
            component = {"up": y, "down": -y, "left": -x, "right": x}[previous]
            if component >= self._stick_release_threshold:
                return previous
        self._right_direction = _right_stick_direction(x, y, self._stick_press_threshold)
        return self._right_direction

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
        self._get_state = library.XInputGetState
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
                family="xbox",
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

        self._controller_family = ""
        self._capture: Callable[[str], object] | None = None
        self._capture_mapper = GamepadIntentMapper()
        self._held_raw: set[str] = set()

    @property
    def connected(self) -> bool:
        return bool(self._controller_id)

    @property
    def controller_name(self) -> str:
        return self._controller_name

    @property
    def controller_family(self) -> str:
        return self._controller_family

    def set_bindings(self, bindings: Mapping[str, ControlIntent | None] | None) -> None:
        self._mapper.set_bindings(bindings)

    def set_capture(self, callback: Callable[[str], object] | None) -> None:
        """Button mapper mode: report each newly pressed physical control.

        While capturing, navigation uses the default layout so a half-finished
        remap can never strand the user inside the mapper.
        """
        self._capture = callback
        self._capture_mapper.reset()
        self._held_raw = set()

    def reset(self) -> None:
        """Forget connection and held-input state without dispatching commands."""

        self._controller_id = ""
        self._controller_name = ""
        self._controller_family = ""
        self._mapper.reset()
        self._capture_mapper.reset()

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
                self._controller_family = ""
                self._mapper.reset()
                if self._connection_changed is not None:
                    self._connection_changed(False, "")
            return ()

        if reading.controller_id != self._controller_id:
            self._controller_id = reading.controller_id
            self._controller_name = reading.name
            self._controller_family = reading.family
            self._mapper.reset()
            self._mapper.prime(reading.snapshot, now=sampled_at)
            self._capture_mapper.prime(reading.snapshot, now=sampled_at)
            self._held_raw = self._mapper.raw_controls(reading.snapshot)
            if self._connection_changed is not None:
                self._connection_changed(True, reading.name)
            return ()

        if self._capture is not None:
            held = self._capture_mapper.raw_controls(reading.snapshot)
            for control in sorted(held - self._held_raw):
                self._capture(control)
            self._held_raw = held
            commands = self._capture_mapper.update(reading.snapshot, now=sampled_at)
            for command in commands:
                self._dispatch(command)
            return commands

        commands = self._mapper.update(reading.snapshot, now=sampled_at)
        for command in commands:
            self._dispatch(command)
        return commands


_SDL_BUTTONS: tuple[tuple[str, GamepadButton], ...] = (
    ("A", GamepadButton.SOUTH), ("B", GamepadButton.EAST), ("X", GamepadButton.WEST), ("Y", GamepadButton.NORTH),
    ("DPAD_UP", GamepadButton.DPAD_UP), ("DPAD_DOWN", GamepadButton.DPAD_DOWN),
    ("DPAD_LEFT", GamepadButton.DPAD_LEFT), ("DPAD_RIGHT", GamepadButton.DPAD_RIGHT),
    ("LEFTSHOULDER", GamepadButton.LEFT_SHOULDER), ("RIGHTSHOULDER", GamepadButton.RIGHT_SHOULDER),
    ("BACK", GamepadButton.VIEW), ("START", GamepadButton.MENU), ("GUIDE", GamepadButton.GUIDE),
    ("LEFTSTICK", GamepadButton.LEFT_STICK), ("RIGHTSTICK", GamepadButton.RIGHT_STICK),
    ("MISC1", GamepadButton.MISC), ("PADDLE1", GamepadButton.PADDLE1), ("PADDLE2", GamepadButton.PADDLE2),
    ("PADDLE3", GamepadButton.PADDLE3), ("PADDLE4", GamepadButton.PADDLE4), ("TOUCHPAD", GamepadButton.TOUCHPAD),
)

_SDL_TYPES = {
    "XBOX360": "Xbox 360", "XBOXONE": "Xbox One", "PS3": "PS3", "PS4": "PS4", "PS5": "PS5",
    "NINTENDO_SWITCH_PRO": "Switch Pro", "NINTENDO_SWITCH_JOYCON_PAIR": "Joy-Con",
    "NINTENDO_SWITCH_JOYCON_LEFT": "Joy-Con", "NINTENDO_SWITCH_JOYCON_RIGHT": "Joy-Con",
    "AMAZON_LUNA": "Luna", "GOOGLE_STADIA": "Stadia", "NVIDIA_SHIELD": "Shield", "VIRTUAL": "Virtual",
}


class SDLBackend:
    """SDL2 game-controller backend: PlayStation, Nintendo, retro adapters and more.

    SDL ships a large community database that maps hundreds of pads (including
    GameCube/N64 adapters and 8BitDo retro pads) to one positional layout.
    Buttons are read by position, not by the letter printed on them.
    """

    def __init__(self, sdl: object) -> None:
        self._sdl = sdl
        self._controller = None
        self._instance_id: int | None = None
        self._name = ""
        self._family = "generic"
        self._buttons = tuple((getattr(sdl, f"SDL_CONTROLLER_BUTTON_{name}", None), button)
                              for name, button in _SDL_BUTTONS)
        self._buttons = tuple((code, button) for code, button in self._buttons if code is not None)

    @staticmethod
    def available() -> bool:
        """Cheap check that PySDL2 and its library can be found (no start-up)."""
        import importlib.util
        return importlib.util.find_spec("sdl2") is not None

    @classmethod
    def try_create(cls) -> "SDLBackend | None":
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import sdl2  # type: ignore[import-not-found]
        except Exception:
            return None
        try:
            # Positional buttons: Nintendo's A (east) stays "east" so one binding
            # table fits every brand. Read input while the window is focused only
            # (ChannelOS also gates on focus), and never grab the screen saver.
            for hint, value in (("SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS", b"0"),
                                ("SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1"),
                                ("SDL_HINT_VIDEO_ALLOW_SCREENSAVER", b"1")):
                name = getattr(sdl2, hint, None)
                if name is not None:
                    sdl2.SDL_SetHint(name, value)
            if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER | sdl2.SDL_INIT_JOYSTICK) != 0:
                return None
        except Exception:
            return None
        return cls(sdl2)

    def _open_first(self) -> None:
        sdl = self._sdl
        for index in range(int(sdl.SDL_NumJoysticks())):
            if not sdl.SDL_IsGameController(index):
                continue
            controller = sdl.SDL_GameControllerOpen(index)
            if not controller:
                continue
            raw_name = sdl.SDL_GameControllerName(controller)
            self._name = (raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name or "")) or "Controller"
            kind = ""
            get_type = getattr(sdl, "SDL_GameControllerGetType", None)
            if get_type is not None:
                code = int(get_type(controller))
                kind = next((label for key, label in _SDL_TYPES.items()
                             if getattr(sdl, f"SDL_CONTROLLER_TYPE_{key}", None) == code), "")
            from .controller_layouts import detect_family
            self._family = detect_family(kind, self._name)
            joystick = sdl.SDL_GameControllerGetJoystick(controller)
            self._instance_id = int(sdl.SDL_JoystickInstanceID(joystick))
            self._controller = controller
            return

    def read_first(self) -> ControllerReading | None:
        sdl = self._sdl
        sdl.SDL_GameControllerUpdate()
        if self._controller is not None and not sdl.SDL_GameControllerGetAttached(self._controller):
            sdl.SDL_GameControllerClose(self._controller)
            self._controller = None
            self._instance_id = None
        if self._controller is None:
            self._open_first()
            if self._controller is None:
                return None
        controller = self._controller
        buttons = frozenset(button for code, button in self._buttons
                            if sdl.SDL_GameControllerGetButton(controller, code))

        def axis(name: str) -> int:
            return int(sdl.SDL_GameControllerGetAxis(controller, getattr(sdl, f"SDL_CONTROLLER_AXIS_{name}")))

        return ControllerReading(
            controller_id=f"sdl:{self._instance_id}",
            name=self._name,
            family=self._family,
            snapshot=GamepadSnapshot(
                buttons=buttons,
                left_x=_normalize_signed_axis(axis("LEFTX")),
                left_y=-_normalize_signed_axis(axis("LEFTY")),   # SDL: down is positive
                right_x=_normalize_signed_axis(axis("RIGHTX")),
                right_y=-_normalize_signed_axis(axis("RIGHTY")),
                left_trigger=max(0.0, axis("TRIGGERLEFT") / 32767.0),
                right_trigger=max(0.0, axis("TRIGGERRIGHT") / 32767.0),
            ),
        )


class ThreadedBackend:
    """Run a slow-to-start backend on its own thread.

    SDL's controller start-up enumerates every HID device and took seconds on
    Windows, which froze the window if done on the GUI thread. The thread
    starts the backend, then samples it about 120 times a second while
    ChannelOS is asking; ``read_first`` just returns the latest sample.
    """

    ACTIVE_INTERVAL = 0.008
    IDLE_INTERVAL = 0.25

    def __init__(self, factory: Callable[[], ControllerBackend | None]) -> None:
        import threading
        self._factory = factory
        self._latest: ControllerReading | None = None
        self._requested_at = time.monotonic()
        self._stopping = threading.Event()
        self.backend: ControllerBackend | None = None
        self.started = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ChannelOS controller", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.backend = self._factory()
        except Exception:
            self.backend = None
        finally:
            self.started.set()
        backend = self.backend
        while backend is not None and not self._stopping.is_set():
            wanted = time.monotonic() - self._requested_at < 0.5
            if wanted:
                try:
                    self._latest = backend.read_first()
                except Exception:
                    self._latest = None
            interval = self.ACTIVE_INTERVAL if wanted and self._latest is not None else self.IDLE_INTERVAL
            self._stopping.wait(interval)

    def read_first(self) -> ControllerReading | None:
        self._requested_at = time.monotonic()
        return self._latest

    def stop(self) -> None:
        self._stopping.set()


def _sdl_then_xinput() -> ControllerBackend | None:
    return SDLBackend.try_create() or XInputBackend.try_create()


def create_controller_backend() -> ControllerBackend | None:
    """Return the native backend for this platform without making it required.

    SDL covers the most controllers and starts on its own thread; XInput is
    the dependency-free fallback (and is used directly when SDL is missing).
    """

    disabled = os.environ.get("CHANNELOS_DISABLE_CONTROLLER", "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return None
    if os.environ.get("CHANNELOS_CONTROLLER_BACKEND", "").strip().lower() != "xinput" and SDLBackend.available():
        return ThreadedBackend(_sdl_then_xinput)
    return XInputBackend.try_create()
