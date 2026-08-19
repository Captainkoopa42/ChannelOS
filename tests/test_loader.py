from pathlib import Path

import pytest

from channelos.loader import load_channel
from channelos.models import ChannelDefinition, ChannelValidationError


EXAMPLE = Path(__file__).parents[1] / "examples" / "channels" / "sci-fi.yaml"


def test_example_channel_loads() -> None:
    channel = load_channel(EXAMPLE)
    assert channel.channel == 7
    assert channel.display_number == "07"
    assert channel.name == "Sci-Fi"
    assert channel.programming.mode == "sequential"
    assert channel.programming.preserve_episode_order is True
    assert len(channel.sources) == 2


def test_unknown_top_level_field_is_rejected() -> None:
    with pytest.raises(ChannelValidationError, match="unknown top-level"):
        ChannelDefinition.from_mapping(
            {
                "schema_version": "0.1",
                "channel": 1,
                "name": "Test",
                "sources": [{"path": "/media/test"}],
                "programming": {"mode": "sequential"},
                "surprise": True,
            }
        )


def test_channel_number_must_be_valid() -> None:
    with pytest.raises(ChannelValidationError, match="channel must be"):
        ChannelDefinition.from_mapping(
            {
                "schema_version": "0.1",
                "channel": 0,
                "name": "Test",
                "sources": [{"path": "/media/test"}],
                "programming": {"mode": "sequential"},
            }
        )


def test_programming_mode_must_be_supported() -> None:
    with pytest.raises(ChannelValidationError, match="programming.mode"):
        ChannelDefinition.from_mapping(
            {
                "schema_version": "0.1",
                "channel": 1,
                "name": "Test",
                "sources": [{"path": "/media/test"}],
                "programming": {"mode": "telepathy"},
            }
        )
