from datetime import timezone
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


def test_calendar_schema_normalizes_and_sorts_aware_starts() -> None:
    channel = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.2",
            "channel": 9,
            "name": "Calendar TV",
            "sources": [{"path": "/media/test"}],
            "programming": {
                "mode": "calendar",
                "filler_mode": "shuffle",
                "calendar": [
                    {
                        "start_utc": "2026-09-08T08:00:00-04:00",
                        "asset_id": "sha256:later",
                    },
                    {
                        "start_utc": "2026-09-08T10:00:00Z",
                        "asset_id": "sha256:earlier",
                    },
                ],
            },
        }
    )

    assert channel.schema_version == "0.2"
    assert channel.programming.mode == "calendar"
    assert channel.programming.filler_mode == "shuffle"
    assert [block.asset_id for block in channel.programming.calendar] == [
        "sha256:earlier",
        "sha256:later",
    ]
    assert all(
        block.start_utc.tzinfo is timezone.utc
        for block in channel.programming.calendar
    )


def test_schema_0_3_accepts_self_contained_show_specific_filler() -> None:
    channel = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.3",
            "channel": 9,
            "name": "Grouped Calendar TV",
            "sources": [{"path": "/media/test"}],
            "programming": {
                "mode": "calendar",
                "filler_mode": "sequential",
                "calendar": [
                    {
                        "start_utc": "2026-09-08T10:00:00Z",
                        "asset_id": "sha256:show",
                        "filler": {
                            "mode": "shuffle",
                            "asset_ids": ["sha256:a", "sha256:b"],
                        },
                    }
                ],
            },
        }
    )

    block = channel.programming.calendar[0]
    assert block.filler is not None
    assert block.filler.mode == "shuffle"
    assert block.filler.asset_ids == ("sha256:a", "sha256:b")


def test_show_specific_filler_rejects_duplicate_assets() -> None:
    with pytest.raises(ChannelValidationError, match="contains duplicate"):
        ChannelDefinition.from_mapping(
            {
                "schema_version": "0.3",
                "channel": 9,
                "name": "Grouped Calendar TV",
                "sources": [{"path": "/media/test"}],
                "programming": {
                    "mode": "calendar",
                    "calendar": [
                        {
                            "start_utc": "2026-09-08T10:00:00Z",
                            "asset_id": "sha256:show",
                            "filler": {
                                "mode": "sequential",
                                "asset_ids": ["sha256:a", "sha256:a"],
                            },
                        }
                    ],
                },
            }
        )


@pytest.mark.parametrize(
    ("calendar", "message"),
    [
        ([], "requires at least one"),
        (
            [{"start_utc": "2026-09-08T10:00:00", "asset_id": "sha256:a"}],
            "include a timezone",
        ),
        (
            [
                {"start_utc": "2026-09-08T10:00:00Z", "asset_id": "sha256:a"},
                {"start_utc": "2026-09-08T10:00:00+00:00", "asset_id": "sha256:b"},
            ],
            "duplicate start time",
        ),
    ],
)
def test_calendar_schema_rejects_ambiguous_or_duplicate_blocks(
    calendar: list[dict[str, str]],
    message: str,
) -> None:
    with pytest.raises(ChannelValidationError, match=message):
        ChannelDefinition.from_mapping(
            {
                "schema_version": "0.2",
                "channel": 9,
                "name": "Calendar TV",
                "sources": [{"path": "/media/test"}],
                "programming": {
                    "mode": "calendar",
                    "calendar": calendar,
                },
            }
        )


def test_calendar_mode_requires_schema_0_2() -> None:
    with pytest.raises(ChannelValidationError, match="requires schema_version"):
        ChannelDefinition.from_mapping(
            {
                "schema_version": "0.1",
                "channel": 9,
                "name": "Calendar TV",
                "sources": [{"path": "/media/test"}],
                "programming": {"mode": "calendar"},
            }
        )
