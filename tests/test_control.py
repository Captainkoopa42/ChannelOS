from __future__ import annotations

import pytest

from channelos.control import ControlCommand, ControlIntent


def test_control_intent_vocabulary_is_transport_neutral() -> None:
    assert ControlIntent.GUIDE.value == "GUIDE"
    assert ControlIntent.HOME.value == "HOME"
    assert ControlIntent.PLAY_PAUSE.value == "PLAY_PAUSE"
    assert ControlIntent.CHANNEL_UP.value == "CHANNEL_UP"
    assert ControlIntent.SETTINGS.value == "SETTINGS"


def test_digit_command_carries_one_numeric_digit() -> None:
    assert ControlCommand.digit(7) == ControlCommand(
        ControlIntent.DIGIT,
        7,
    )

    with pytest.raises(ValueError, match="0 to 9"):
        ControlCommand.digit(12)
    with pytest.raises(ValueError, match="0 to 9"):
        ControlCommand(ControlIntent.DIGIT, True)


def test_tune_command_requires_a_non_negative_channel_number() -> None:
    assert ControlCommand.tune(666) == ControlCommand(
        ControlIntent.TUNE,
        666,
    )

    with pytest.raises(ValueError, match="non-negative"):
        ControlCommand.tune(-1)


def test_non_parameterized_intents_do_not_require_a_value() -> None:
    assert ControlCommand(ControlIntent.BACK).value is None
    assert ControlCommand(ControlIntent.VOLUME_UP).value is None
