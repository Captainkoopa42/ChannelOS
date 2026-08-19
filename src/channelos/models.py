from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {"0.1"}
SUPPORTED_PROGRAMMING_MODES = {"sequential", "shuffle"}
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
class ProgrammingDefinition:
    mode: str
    preserve_episode_order: bool = False
    avoid_repeat_days: int = 0


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
                    f"sources[{index}] must contain exactly one 'path' field in schema 0.1"
                )
            path_value = item["path"]
            if not isinstance(path_value, str) or not path_value.strip():
                raise ChannelValidationError(f"sources[{index}].path must be a non-empty string")
            sources.append(SourceDefinition(path=Path(path_value)))

        raw_programming = raw.get("programming")
        if not isinstance(raw_programming, dict):
            raise ChannelValidationError("programming must be a mapping")

        allowed_programming = {"mode", "preserve_episode_order", "avoid_repeat_days"}
        unknown_programming = set(raw_programming) - allowed_programming
        if unknown_programming:
            names = ", ".join(sorted(unknown_programming))
            raise ChannelValidationError(f"unknown programming field(s): {names}")

        mode = raw_programming.get("mode")
        if mode not in SUPPORTED_PROGRAMMING_MODES:
            raise ChannelValidationError(
                f"programming.mode must be one of {sorted(SUPPORTED_PROGRAMMING_MODES)}"
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
            ),
            presentation=PresentationDefinition(number_width=number_width),
        )
