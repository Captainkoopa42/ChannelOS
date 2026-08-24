from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ControlIntent(StrEnum):
    """Transport-neutral actions understood by the ChannelOS couch shell.

    A keyboard, gamepad, USB remote, Steam Input profile, phone remote, or
    future hardware adapter should translate its physical input into this
    vocabulary before ChannelOS decides what the action means on the current
    screen.
    """

    POWER = "POWER"

    DIGIT = "DIGIT"
    TUNE = "TUNE"
    CHANNEL_UP = "CHANNEL_UP"
    CHANNEL_DOWN = "CHANNEL_DOWN"
    PREVIOUS_CHANNEL = "PREVIOUS_CHANNEL"

    VOLUME_UP = "VOLUME_UP"
    VOLUME_DOWN = "VOLUME_DOWN"
    MUTE = "MUTE"

    PLAY = "PLAY"
    PAUSE = "PAUSE"
    PLAY_PAUSE = "PLAY_PAUSE"
    REWIND = "REWIND"
    FAST_FORWARD = "FAST_FORWARD"
    SKIP_BACK = "SKIP_BACK"
    SKIP_FORWARD = "SKIP_FORWARD"
    GO_LIVE = "GO_LIVE"

    GUIDE = "GUIDE"
    GUIDE_NOW = "GUIDE_NOW"
    INFO = "INFO"
    HOME = "HOME"
    BACK = "BACK"

    UP = "UP"
    DOWN = "DOWN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    SELECT = "SELECT"

    LIBRARY = "LIBRARY"
    CHANNELS = "CHANNELS"
    SETTINGS = "SETTINGS"
    ADD_MEDIA_SOURCE = "ADD_MEDIA_SOURCE"


@dataclass(frozen=True, slots=True)
class ControlCommand:
    """One normalized control request with an optional scalar value."""

    intent: ControlIntent
    value: int | float | str | None = None

    def __post_init__(self) -> None:
        if self.intent is ControlIntent.DIGIT:
            if (
                not isinstance(self.value, int)
                or isinstance(self.value, bool)
                or not 0 <= self.value <= 9
            ):
                raise ValueError("DIGIT control commands require an integer from 0 to 9")
        elif self.intent is ControlIntent.TUNE:
            if (
                not isinstance(self.value, int)
                or isinstance(self.value, bool)
                or self.value < 0
            ):
                raise ValueError("TUNE control commands require a non-negative channel number")

    @classmethod
    def digit(cls, value: int) -> "ControlCommand":
        return cls(ControlIntent.DIGIT, int(value))

    @classmethod
    def tune(cls, channel_number: int) -> "ControlCommand":
        return cls(ControlIntent.TUNE, int(channel_number))
