from __future__ import annotations

import ctypes
from collections.abc import Iterable

import pytest

from channelos.control import ControlCommand, ControlIntent
from channelos.controller_input import (
    ControllerInputHub,
    ControllerReading,
    GamepadButton,
    GamepadIntentMapper,
    GamepadSnapshot,
    XInputBackend,
    create_controller_backend,
)
import channelos.controller_input as controller_input


def snapshot(
    *buttons: GamepadButton,
    left_x: float = 0.0,
    left_y: float = 0.0,
    right_x: float = 0.0,
    right_y: float = 0.0,
    left_trigger: float = 0.0,
    right_trigger: float = 0.0,
) -> GamepadSnapshot:
    return GamepadSnapshot(
        buttons=frozenset(buttons),
        left_x=left_x,
        left_y=left_y,
        right_x=right_x,
        right_y=right_y,
        left_trigger=left_trigger,
        right_trigger=right_trigger,
    )


def intents(commands: Iterable[ControlCommand]) -> tuple[ControlIntent, ...]:
    return tuple(command.intent for command in commands)


def test_face_and_system_buttons_map_to_transport_neutral_intents() -> None:
    mapper = GamepadIntentMapper()
    commands = mapper.update(
        snapshot(
            GamepadButton.SOUTH,
            GamepadButton.EAST,
            GamepadButton.WEST,
            GamepadButton.NORTH,
            GamepadButton.VIEW,
            GamepadButton.MENU,
        ),
        now=1.0,
    )

    assert set(intents(commands)) == {
        ControlIntent.SELECT,
        ControlIntent.BACK,
        ControlIntent.PLAY_PAUSE,
        ControlIntent.INFO,
        ControlIntent.GUIDE,
        ControlIntent.HOME,
    }


def test_non_navigation_buttons_fire_only_on_press_edges() -> None:
    mapper = GamepadIntentMapper()
    held = snapshot(GamepadButton.SOUTH)

    assert intents(mapper.update(held, now=1.0)) == (ControlIntent.SELECT,)
    assert mapper.update(held, now=2.0) == ()
    assert mapper.update(snapshot(), now=2.1) == ()
    assert intents(mapper.update(held, now=2.2)) == (ControlIntent.SELECT,)


def test_dpad_and_stick_navigation_repeat_after_a_deliberate_delay() -> None:
    mapper = GamepadIntentMapper(
        repeat_delay_seconds=0.4,
        repeat_interval_seconds=0.1,
    )
    held = snapshot(GamepadButton.DPAD_DOWN)

    assert intents(mapper.update(held, now=1.0)) == (ControlIntent.DOWN,)
    assert mapper.update(held, now=1.39) == ()
    assert intents(mapper.update(held, now=1.4)) == (ControlIntent.DOWN,)
    assert mapper.update(held, now=1.49) == ()
    assert intents(mapper.update(held, now=1.5)) == (ControlIntent.DOWN,)

    mapper.reset()
    assert intents(mapper.update(snapshot(left_x=0.75), now=3.0)) == (
        ControlIntent.RIGHT,
    )
    # Hysteresis keeps a partially released stick from becoming a new press.
    assert mapper.update(snapshot(left_x=0.4), now=3.1) == ()
    assert mapper.update(snapshot(left_x=0.2), now=3.2) == ()
    assert intents(mapper.update(snapshot(left_y=-0.8), now=3.3)) == (
        ControlIntent.DOWN,
    )


def test_triggers_and_shoulders_expose_tv_transport_controls() -> None:
    mapper = GamepadIntentMapper()
    commands = mapper.update(
        snapshot(
            GamepadButton.LEFT_SHOULDER,
            GamepadButton.RIGHT_SHOULDER,
            GamepadButton.LEFT_STICK,
            GamepadButton.RIGHT_STICK,
            left_trigger=0.8,
            right_trigger=0.9,
        ),
        now=1.0,
    )

    assert set(intents(commands)) == {
        ControlIntent.CHANNEL_DOWN,
        ControlIntent.CHANNEL_UP,
        ControlIntent.GO_LIVE,
        ControlIntent.PREVIOUS_CHANNEL,
        ControlIntent.SKIP_BACK,
        ControlIntent.SKIP_FORWARD,
    }


def test_right_stick_controls_volume_with_deadzone_and_repeat() -> None:
    mapper = GamepadIntentMapper(
        repeat_delay_seconds=0.4,
        repeat_interval_seconds=0.1,
    )
    held = snapshot(right_y=0.8)

    assert intents(mapper.update(held, now=1.0)) == (ControlIntent.VOLUME_UP,)
    assert mapper.update(snapshot(right_y=0.4), now=1.2) == ()
    assert intents(mapper.update(snapshot(right_y=0.4), now=1.4)) == (
        ControlIntent.VOLUME_UP,
    )
    assert mapper.update(snapshot(right_y=0.2), now=1.5) == ()
    assert intents(mapper.update(snapshot(right_y=-0.8), now=1.6)) == (
        ControlIntent.VOLUME_DOWN,
    )


def test_new_connection_suppresses_every_control_until_it_is_released() -> None:
    mapper = GamepadIntentMapper()
    held = snapshot(GamepadButton.SOUTH, GamepadButton.DPAD_RIGHT)

    mapper.prime(held, now=1.0)
    assert mapper.update(held, now=10.0) == ()
    assert mapper.update(snapshot(), now=10.1) == ()
    assert set(intents(mapper.update(held, now=10.2))) == {
        ControlIntent.SELECT,
        ControlIntent.RIGHT,
    }


class FakeBackend:
    def __init__(self, readings: list[ControllerReading | None]) -> None:
        self._readings = readings
        self._last: ControllerReading | None = None

    def read_first(self) -> ControllerReading | None:
        if self._readings:
            self._last = self._readings.pop(0)
        return self._last


def reading(sample: GamepadSnapshot, *, controller_id: str = "pad:0") -> ControllerReading:
    return ControllerReading(controller_id, "Test Controller", sample)


def test_hub_reports_hotplug_and_dispatches_only_normalized_commands() -> None:
    backend = FakeBackend(
        [
            reading(snapshot()),
            reading(snapshot(GamepadButton.NORTH)),
            None,
        ]
    )
    dispatched: list[ControlCommand] = []
    connections: list[tuple[bool, str]] = []
    hub = ControllerInputHub(
        backend,
        dispatched.append,
        connection_changed=lambda connected, name: connections.append(
            (connected, name)
        ),
    )

    assert hub.poll(now=1.0) == ()
    assert hub.connected
    assert connections == [(True, "Test Controller")]

    assert intents(hub.poll(now=1.1)) == (ControlIntent.INFO,)
    assert dispatched == [ControlCommand(ControlIntent.INFO)]

    assert hub.poll(now=1.2) == ()
    assert not hub.connected
    assert connections[-1] == (False, "")


def test_controller_threshold_validation_is_explicit() -> None:
    with pytest.raises(ValueError, match="stick thresholds"):
        GamepadIntentMapper(
            stick_press_threshold=0.3,
            stick_release_threshold=0.4,
        )
    with pytest.raises(ValueError, match="trigger threshold"):
        GamepadIntentMapper(trigger_threshold=0.0)
    with pytest.raises(ValueError, match="repeat timings"):
        GamepadIntentMapper(repeat_interval_seconds=0.0)


def test_non_windows_backend_is_optional(monkeypatch) -> None:
    monkeypatch.setattr("channelos.controller_input.sys.platform", "linux")
    assert XInputBackend.try_create() is None
    assert create_controller_backend() is None


def test_controller_can_be_disabled_without_affecting_keyboard(monkeypatch) -> None:
    monkeypatch.setenv("CHANNELOS_DISABLE_CONTROLLER", "1")
    assert create_controller_backend() is None


class FakeGetState:
    def __init__(self) -> None:
        self.argtypes = None
        self.restype = None
        self.calls: list[int] = []
        self.connected_slot = 2

    def __call__(self, user_index, state_pointer) -> int:
        index = int(user_index)
        self.calls.append(index)
        if index != self.connected_slot:
            return 1167
        state = ctypes.cast(
            state_pointer,
            ctypes.POINTER(controller_input._XInputState),
        ).contents
        state.dwPacketNumber = 7
        state.Gamepad.wButtons = 0x1000 | 0x8000
        state.Gamepad.sThumbLX = 16384
        state.Gamepad.sThumbRY = -32768
        state.Gamepad.bLeftTrigger = 128
        return 0


class FakeXInputLibrary:
    def __init__(self) -> None:
        self.XInputGetState = FakeGetState()


def test_xinput_backend_normalizes_state_and_prefers_the_active_slot() -> None:
    library = FakeXInputLibrary()
    backend = XInputBackend(library, library_name="fake-xinput.dll")

    first = backend.read_first()
    assert first is not None
    assert first.controller_id == "xinput:2"
    assert first.name == "Xbox-compatible Controller 3"
    assert first.snapshot.buttons == frozenset(
        {GamepadButton.SOUTH, GamepadButton.NORTH}
    )
    assert first.snapshot.left_x == pytest.approx(0.5, abs=0.001)
    assert first.snapshot.right_y == -1.0
    assert first.snapshot.left_trigger == pytest.approx(128 / 255)
    assert library.XInputGetState.calls == [0, 1, 2]

    library.XInputGetState.calls.clear()
    assert backend.read_first() is not None
    assert library.XInputGetState.calls == [2]
