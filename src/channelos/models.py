from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {"0.1", "0.2"}
SUPPORTED_PROGRAMMING_MODES = {"sequential", "shuffle", "calendar"}
TOP_LEVEL_KEYS = {
    "schema_version",
    "channel",
    "name",
    "description",
    "sources",
    "programming",
    "presentation",
}


class ChannelValidationError(ValueError):
    """Raised when a portable channel definition is invalid."""


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    path: Path


@dataclass(frozen=True, slots=True)
class CalendarBlockDefinition:
    """One fixed UTC program start in a Studio-authored calendar."""

    start_utc: datetime
    asset_id: str


@dataclass(frozen=True, slots=True)
class ProgrammingDefinition:
    mode: str
    preserve_episode_order: bool = False
    avoid_repeat_days: int = 0
    filler_mode: str = "sequential"
    calendar: tuple[CalendarBlockDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class PresentationDefinition:
    number_width: int = 1


@dataclass(frozen=True, slots=True)
class ChannelDefinition:
    schema_version: str
    channel: int
    name: str
    sources: tuple[SourceDefinition, ...]
    programming: ProgrammingDefinition
    description: str | None = None
    presentation: PresentationDefinition = PresentationDefinition()

    @property
    def display_number(self) -> str:
        return str(self.channel).zfill(self.presentation.number_width)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "ChannelDefinition":
        unknown = set(raw) - TOP_LEVEL_KEYS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ChannelValidationError(f"unknown top-level field(s): {names}")

        version = raw.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ChannelValidationError(
                f"unsupported schema_version {version!r}; expected one of "
                f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        channel = raw.get("channel")
        if not isinstance(channel, int) or isinstance(channel, bool) or not 1 <= channel <= 9999:
            raise ChannelValidationError("channel must be an integer from 1 through 9999")

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ChannelValidationError("name must be a non-empty string")

        description = raw.get("description")
        if description is not None and not isinstance(description, str):
            raise ChannelValidationError("description must be a string when provided")

        raw_sources = raw.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ChannelValidationError("sources must be a non-empty list")

        sources: list[SourceDefinition] = []
        for index, item in enumerate(raw_sources):
            if not isinstance(item, dict) or set(item) != {"path"}:
                raise ChannelValidationError(
                    f"sources[{index}] must contain exactly one 'path' field"
                )
            path_value = item["path"]
            if not isinstance(path_value, str) or not path_value.strip():
                raise ChannelValidationError(f"sources[{index}].path must be a non-empty string")
            sources.append(SourceDefinition(path=Path(path_value)))

        raw_programming = raw.get("programming")
        if not isinstance(raw_programming, dict):
            raise ChannelValidationError("programming must be a mapping")

        allowed_programming = {
            "mode",
            "preserve_episode_order",
            "avoid_repeat_days",
        }
        if version == "0.2":
            allowed_programming.update({"filler_mode", "calendar"})
        unknown_programming = set(raw_programming) - allowed_programming
        if unknown_programming:
            names = ", ".join(sorted(unknown_programming))
            raise ChannelValidationError(f"unknown programming field(s): {names}")

        mode = raw_programming.get("mode")
        if mode not in SUPPORTED_PROGRAMMING_MODES:
            raise ChannelValidationError(
                f"programming.mode must be one of {sorted(SUPPORTED_PROGRAMMING_MODES)}"
            )
        if version == "0.1" and mode == "calendar":
            raise ChannelValidationError(
                "calendar programming requires schema_version '0.2'"
            )

        preserve = raw_programming.get("preserve_episode_order", False)
        if not isinstance(preserve, bool):
            raise ChannelValidationError("programming.preserve_episode_order must be boolean")

        avoid_repeat_days = raw_programming.get("avoid_repeat_days", 0)
        if (
            not isinstance(avoid_repeat_days, int)
            or isinstance(avoid_repeat_days, bool)
            or avoid_repeat_days < 0
        ):
            raise ChannelValidationError("programming.avoid_repeat_days must be a non-negative integer")

        filler_mode = raw_programming.get("filler_mode", "sequential")
        if filler_mode not in {"sequential", "shuffle"}:
            raise ChannelValidationError(
                "programming.filler_mode must be 'sequential' or 'shuffle'"
            )

        raw_calendar = raw_programming.get("calendar", [])
        if not isinstance(raw_calendar, list):
            raise ChannelValidationError("programming.calendar must be a list")
        if mode != "calendar" and raw_calendar:
            raise ChannelValidationError(
                "programming.calendar is only valid when mode is 'calendar'"
            )
        if mode == "calendar" and not raw_calendar:
            raise ChannelValidationError(
                "calendar programming requires at least one calendar block"
            )
        if len(raw_calendar) > 10000:
            raise ChannelValidationError(
                "programming.calendar cannot contain more than 10000 blocks"
            )

        calendar: list[CalendarBlockDefinition] = []
        seen_starts: set[datetime] = set()
        for index, item in enumerate(raw_calendar):
            if not isinstance(item, dict) or set(item) != {"start_utc", "asset_id"}:
                raise ChannelValidationError(
                    f"programming.calendar[{index}] must contain exactly "
                    "'start_utc' and 'asset_id'"
                )
            start_text = item["start_utc"]
            if not isinstance(start_text, str) or not start_text.strip():
                raise ChannelValidationError(
                    f"programming.calendar[{index}].start_utc must be an ISO timestamp"
                )
            try:
                start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ChannelValidationError(
                    f"programming.calendar[{index}].start_utc must be an ISO timestamp"
                ) from exc
            if start.tzinfo is None or start.utcoffset() is None:
                raise ChannelValidationError(
                    f"programming.calendar[{index}].start_utc must include a timezone"
                )
            start = start.astimezone(timezone.utc)
            if start in seen_starts:
                raise ChannelValidationError(
                    f"programming.calendar has duplicate start time {start.isoformat()}"
                )

            asset_id = item["asset_id"]
            if not isinstance(asset_id, str) or not asset_id.strip():
                raise ChannelValidationError(
                    f"programming.calendar[{index}].asset_id must be a non-empty string"
                )
            calendar.append(
                CalendarBlockDefinition(
                    start_utc=start,
                    asset_id=asset_id.strip(),
                )
            )
            seen_starts.add(start)

        calendar.sort(key=lambda block: block.start_utc)

        raw_presentation = raw.get("presentation", {})
        if not isinstance(raw_presentation, dict):
            raise ChannelValidationError("presentation must be a mapping")
        if set(raw_presentation) - {"number_width"}:
            names = ", ".join(sorted(set(raw_presentation) - {"number_width"}))
            raise ChannelValidationError(f"unknown presentation field(s): {names}")

        number_width = raw_presentation.get("number_width", 1)
        if not isinstance(number_width, int) or isinstance(number_width, bool) or not 1 <= number_width <= 4:
            raise ChannelValidationError("presentation.number_width must be an integer from 1 through 4")

        return cls(
            schema_version=version,
            channel=channel,
            name=name.strip(),
            description=description,
            sources=tuple(sources),
            programming=ProgrammingDefinition(
                mode=mode,
                preserve_episode_order=preserve,
                avoid_repeat_days=avoid_repeat_days,
                filler_mode=filler_mode,
                calendar=tuple(calendar),
            ),
            presentation=PresentationDefinition(number_width=number_width),
        )
