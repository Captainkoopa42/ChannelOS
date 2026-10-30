from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {"0.1", "0.2", "0.3", "0.4", "0.5"}
SUPPORTED_PROGRAMMING_MODES = {"sequential", "shuffle", "calendar"}
TOP_LEVEL_KEYS = {
    "schema_version",
    "channel",
    "name",
    "description",
    "sources",
    "programming",
    "presentation",
    "advertising",
}


class ChannelValidationError(ValueError):
    """Raised when a portable channel definition is invalid."""


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    path: Path


@dataclass(frozen=True, slots=True)
class CalendarFillerDefinition:
    """A self-contained media pool used after one fixed calendar show."""

    mode: str
    asset_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalendarBlockDefinition:
    """One fixed UTC program start in a Studio-authored calendar."""

    start_utc: datetime
    asset_id: str
    filler: CalendarFillerDefinition | None = None


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
class AdvertisingDefinition:
    """Portable ad-break settings; ad roots remain separate from program roots."""

    enabled: bool = False
    sources: tuple[SourceDefinition, ...] = ()
    selection_strategy: str = "best_fit"
    breakpoints_seconds: tuple[float, ...] = ()
    interval_seconds: float | None = None
    break_duration_seconds: float = 120.0
    priority: int = 0
    # Schema 0.5 embeds canonical asset IDs and effective profile settings:
    # playback does not depend on the author's private Studio catalog.
    asset_ids: tuple[str, ...] = ()
    collection_id: str | None = None
    profile_id: str | None = None
    timing_policy: str = "strict_fit"
    smoosh_minimum_seconds: float = 5.0
    smoosh_max_trim_seconds: float = 15.0
    expand_max_seconds: float = 0.0
    triggers: tuple[str, ...] = ("breakpoint", "interval", "between_programs", "calendar_boundary")
    transition_behavior: str = "cut"
    transition_seconds: float = 0.5
    slot_seconds: float | None = None
    schedule_priority: str = "program"
    expand_source: str = "schedule_shift"
    placements: tuple[AdPlacementDefinition, ...] = ()
    collection_membership: str = "fixed"
    excluded_asset_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdPlacementDefinition:
    placement_id: str
    trigger: str
    policy: AdvertisingDefinition


def advertising_to_mapping(value: AdvertisingDefinition) -> dict[str, Any]:
    """Serialize effective snapshots, including independently assigned placements."""
    from dataclasses import fields
    result = {field.name: getattr(value, field.name) for field in fields(value)
              if field.name not in {"sources", "placements"}}
    result["sources"] = [{"path": str(source.path)} for source in value.sources]
    for key in ("asset_ids", "breakpoints_seconds", "triggers", "excluded_asset_ids"):
        result[key] = list(result[key])
    result["placements"] = [
        {"id": item.placement_id, "trigger": item.trigger,
         "policy": {key: setting for key, setting in advertising_to_mapping(item.policy).items()
                    if key != "placements"}}
        for item in value.placements
    ]
    return result


@dataclass(frozen=True, slots=True)
class ChannelDefinition:
    schema_version: str
    channel: int
    name: str
    sources: tuple[SourceDefinition, ...]
    programming: ProgrammingDefinition
    description: str | None = None
    presentation: PresentationDefinition = PresentationDefinition()
    advertising: AdvertisingDefinition = AdvertisingDefinition()

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

        raw_advertising = raw.get("advertising", {})
        if version not in {"0.4", "0.5"} and "advertising" in raw:
            raise ChannelValidationError(
                "advertising settings require schema_version '0.4'"
            )
        if not isinstance(raw_advertising, dict):
            raise ChannelValidationError("advertising must be a mapping")
        allowed_advertising = {
            "enabled", "sources", "selection_strategy", "breakpoints_seconds",
            "interval_seconds", "break_duration_seconds", "priority",
        }
        new_ad_keys = {
            "asset_ids", "collection_id", "profile_id", "timing_policy",
            "smoosh_minimum_seconds", "smoosh_max_trim_seconds",
            "expand_max_seconds", "triggers", "transition_behavior",
            "transition_seconds", "slot_seconds", "schedule_priority", "expand_source", "placements",
            "collection_membership", "excluded_asset_ids",
        }
        if version == "0.5":
            allowed_advertising.update(new_ad_keys)
        if set(raw_advertising) - allowed_advertising:
            names = ", ".join(sorted(set(raw_advertising) - allowed_advertising))
            raise ChannelValidationError(f"unknown advertising field(s): {names}")
        ad_enabled = raw_advertising.get("enabled", False)
        if not isinstance(ad_enabled, bool):
            raise ChannelValidationError("advertising.enabled must be boolean")
        ad_strategy = raw_advertising.get("selection_strategy", "best_fit")
        if not isinstance(ad_strategy, str) or ad_strategy not in {
            "best_fit", "largest", "smallest", "sequential", "least_played", "complete_rotation"
        }:
            raise ChannelValidationError("advertising.selection_strategy is not supported")
        raw_breakpoints = raw_advertising.get("breakpoints_seconds", [])
        if not isinstance(raw_breakpoints, list):
            raise ChannelValidationError("advertising.breakpoints_seconds must be a list")
        try:
            breakpoints = tuple(float(value) for value in raw_breakpoints)
            interval_seconds = raw_advertising.get("interval_seconds")
            interval_seconds = None if interval_seconds is None else float(interval_seconds)
            break_duration_seconds = float(raw_advertising.get("break_duration_seconds", 120.0))
        except (TypeError, ValueError) as exc:
            raise ChannelValidationError("advertising timing values must be numeric") from exc
        import math
        timing_values = (*breakpoints, break_duration_seconds)
        if interval_seconds is not None:
            timing_values += (interval_seconds,)
        if any(not math.isfinite(value) for value in timing_values):
            raise ChannelValidationError("advertising timing values must be finite")
        if any(value <= 0 for value in breakpoints) or len(set(breakpoints)) != len(breakpoints):
            raise ChannelValidationError("advertising breakpoints must be unique positive offsets")
        if interval_seconds is not None and interval_seconds <= 0:
            raise ChannelValidationError("advertising.interval_seconds must be positive")
        if break_duration_seconds <= 0:
            raise ChannelValidationError("advertising.break_duration_seconds must be positive")
        priority = raw_advertising.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ChannelValidationError("advertising.priority must be an integer")
        raw_ad_sources = raw_advertising.get("sources", [])
        if not isinstance(raw_ad_sources, list):
            raise ChannelValidationError("advertising.sources must be a list")
        ad_sources: list[SourceDefinition] = []
        seen_ad_paths: set[str] = set()
        for index, item in enumerate(raw_ad_sources):
            if not isinstance(item, dict) or set(item) != {"path"}:
                raise ChannelValidationError(
                    f"advertising.sources[{index}] must contain exactly one 'path' field"
                )
            path_value = item["path"]
            if not isinstance(path_value, str) or not path_value.strip():
                raise ChannelValidationError(
                    f"advertising.sources[{index}].path must be a non-empty string"
                )
            normalized_path = path_value.strip()
            if normalized_path.casefold() in seen_ad_paths:
                raise ChannelValidationError(
                    f"advertising.sources contains duplicate path {normalized_path!r}"
                )
            seen_ad_paths.add(normalized_path.casefold())
            ad_sources.append(SourceDefinition(path=Path(normalized_path)))
        raw_asset_ids = raw_advertising.get("asset_ids", [])
        if not isinstance(raw_asset_ids, list) or any(
            not isinstance(asset_id, str) or not asset_id.strip()
            for asset_id in raw_asset_ids
        ):
            raise ChannelValidationError("advertising.asset_ids must be a list of non-empty strings")
        ad_asset_ids = tuple(asset_id.strip() for asset_id in raw_asset_ids)
        if len(set(ad_asset_ids)) != len(ad_asset_ids):
            raise ChannelValidationError("advertising.asset_ids cannot contain duplicates")
        collection_membership = raw_advertising.get("collection_membership", "fixed")
        if collection_membership not in {"fixed", "dynamic"}:
            raise ChannelValidationError("unsupported advertising collection membership")
        excluded_ids = raw_advertising.get("excluded_asset_ids", [])
        if not isinstance(excluded_ids, list) or any(not isinstance(value, str) or not value.strip() for value in excluded_ids):
            raise ChannelValidationError("excluded_asset_ids must be a list of non-empty IDs")
        if len(set(excluded_ids)) != len(excluded_ids):
            raise ChannelValidationError("excluded_asset_ids cannot contain duplicates")
        collection_id = raw_advertising.get("collection_id")
        profile_id = raw_advertising.get("profile_id")
        for field_name, value in (("collection_id", collection_id), ("profile_id", profile_id)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ChannelValidationError(f"advertising.{field_name} must be a non-empty string")
        triggers = raw_advertising.get("triggers",
            ["breakpoint", "interval", "between_programs", "calendar_boundary"])
        if not isinstance(triggers, list) or any(
            not isinstance(trigger, str) for trigger in triggers
        ) or len(set(triggers)) != len(triggers) or set(triggers) - {
            "breakpoint", "interval", "between_programs", "calendar_boundary", "fixed_slot",
        }:
            raise ChannelValidationError("advertising.triggers contains invalid or duplicate triggers")
        transition = raw_advertising.get("transition_behavior", "cut")
        if transition not in {"cut", "fade", "hold"}:
            raise ChannelValidationError("advertising.transition_behavior is unsupported")
        policy_name = raw_advertising.get("timing_policy", "strict_fit")
        if policy_name not in {"strict_fit", "smoosh", "expand"}:
            raise ChannelValidationError("advertising.timing_policy is unsupported")
        try:
            smoosh_min = float(raw_advertising.get("smoosh_minimum_seconds", 5.0))
            smoosh_trim = float(raw_advertising.get("smoosh_max_trim_seconds", 15.0))
            expand_max = float(raw_advertising.get("expand_max_seconds", 0.0))
        except (TypeError, ValueError) as exc:
            raise ChannelValidationError("advertising timing limits must be numeric") from exc
        if not all(math.isfinite(value) for value in (smoosh_min, smoosh_trim, expand_max)):
            raise ChannelValidationError("advertising timing limits must be finite")
        if smoosh_min <= 0 or smoosh_trim < 0 or expand_max < 0:
            raise ChannelValidationError("advertising Smoosh/Expand limits are invalid")
        try:
            transition_seconds = float(raw_advertising.get("transition_seconds", 0.5))
            slot_seconds = raw_advertising.get("slot_seconds")
            slot_seconds = None if slot_seconds is None else float(slot_seconds)
        except (TypeError, ValueError) as exc:
            raise ChannelValidationError("transition and slot durations must be numeric") from exc
        if not math.isfinite(transition_seconds) or not 0 <= transition_seconds <= 10:
            raise ChannelValidationError("transition_seconds must be from 0 through 10")
        if slot_seconds is not None and (not math.isfinite(slot_seconds) or slot_seconds <= 0):
            raise ChannelValidationError("slot_seconds must be finite and positive")
        schedule_priority = raw_advertising.get("schedule_priority", "program")
        if schedule_priority not in {"program", "advertising", "fixed"}:
            raise ChannelValidationError("unsupported advertising.schedule_priority")
        expand_source = raw_advertising.get("expand_source", "schedule_shift")
        if expand_source not in {"schedule_shift", "available_slot_time", "current_program", "next_event"}:
            raise ChannelValidationError("unsupported advertising.expand_source")
        raw_placements = raw_advertising.get("placements", [])
        if not isinstance(raw_placements, list):
            raise ChannelValidationError("advertising.placements must be a list")
        placements = []
        placement_ids = set()
        for item in raw_placements:
            if not isinstance(item, dict) or set(item) - {"id", "trigger", "policy"}:
                raise ChannelValidationError("placement requires id, trigger and a portable policy snapshot")
            identity, trigger = item.get("id"), item.get("trigger")
            if not isinstance(identity, str) or not identity.strip() or identity in placement_ids:
                raise ChannelValidationError("placement IDs must be non-empty and unique")
            if trigger not in {"breakpoint", "interval", "between_programs", "calendar_boundary", "fixed_slot"}:
                raise ChannelValidationError("unsupported placement trigger")
            overrides = item.get("policy", {})
            if not isinstance(overrides, dict) or "placements" in overrides:
                raise ChannelValidationError("placement policy must be a mapping without nested placements")
            inherited = {key: value for key, value in raw_advertising.items() if key != "placements"}
            inherited.update(overrides)
            inherited["triggers"] = [trigger]
            if "asset_ids" in overrides and "sources" not in overrides:
                inherited["sources"] = []
            snapshot = cls.from_mapping({**raw, "advertising": inherited}).advertising
            if trigger == "fixed_slot" and snapshot.slot_seconds is None:
                raise ChannelValidationError("fixed_slot placement requires slot_seconds")
            placements.append(AdPlacementDefinition(identity, trigger, snapshot))
            placement_ids.add(identity)
        if "fixed_slot" in triggers and slot_seconds is None:
            raise ChannelValidationError("fixed_slot trigger requires slot_seconds")
        if ad_enabled and not (ad_sources or ad_asset_ids or placements):
            raise ChannelValidationError(
                "advertising requires indexed sources or canonical asset_ids when enabled"
            )

        raw_programming = raw.get("programming")
        if not isinstance(raw_programming, dict):
            raise ChannelValidationError("programming must be a mapping")

        allowed_programming = {
            "mode",
            "preserve_episode_order",
            "avoid_repeat_days",
        }
        if version in {"0.2", "0.3", "0.4", "0.5"}:
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
            allowed_block = {"start_utc", "asset_id"}
            if version in {"0.3", "0.4", "0.5"}:
                allowed_block.add("filler")
            if (
                not isinstance(item, dict)
                or not {"start_utc", "asset_id"}.issubset(item)
                or set(item) - allowed_block
            ):
                raise ChannelValidationError(
                    f"programming.calendar[{index}] must contain 'start_utc' "
                    "and 'asset_id' plus only supported optional fields"
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
            filler: CalendarFillerDefinition | None = None
            raw_filler = item.get("filler")
            if raw_filler is not None:
                if version not in {"0.3", "0.4", "0.5"}:
                    raise ChannelValidationError(
                        "show-specific filler requires schema_version '0.3' or '0.4'"
                    )
                if not isinstance(raw_filler, dict) or set(raw_filler) != {
                    "mode",
                    "asset_ids",
                }:
                    raise ChannelValidationError(
                        f"programming.calendar[{index}].filler must contain "
                        "exactly 'mode' and 'asset_ids'"
                    )
                block_filler_mode = raw_filler.get("mode")
                if block_filler_mode not in {"sequential", "shuffle"}:
                    raise ChannelValidationError(
                        f"programming.calendar[{index}].filler.mode must be "
                        "'sequential' or 'shuffle'"
                    )
                raw_asset_ids = raw_filler.get("asset_ids")
                if not isinstance(raw_asset_ids, list) or not raw_asset_ids:
                    raise ChannelValidationError(
                        f"programming.calendar[{index}].filler.asset_ids must "
                        "be a non-empty list"
                    )
                if len(raw_asset_ids) > 10000:
                    raise ChannelValidationError(
                        f"programming.calendar[{index}].filler.asset_ids cannot "
                        "contain more than 10000 items"
                    )
                asset_ids: list[str] = []
                seen_asset_ids: set[str] = set()
                for asset_index, value in enumerate(raw_asset_ids):
                    if not isinstance(value, str) or not value.strip():
                        raise ChannelValidationError(
                            f"programming.calendar[{index}].filler.asset_ids"
                            f"[{asset_index}] must be a non-empty string"
                        )
                    normalized = value.strip()
                    if normalized in seen_asset_ids:
                        raise ChannelValidationError(
                            f"programming.calendar[{index}].filler.asset_ids "
                            f"contains duplicate {normalized}"
                        )
                    seen_asset_ids.add(normalized)
                    asset_ids.append(normalized)
                filler = CalendarFillerDefinition(
                    mode=block_filler_mode,
                    asset_ids=tuple(asset_ids),
                )

            calendar.append(
                CalendarBlockDefinition(
                    start_utc=start,
                    asset_id=asset_id.strip(),
                    filler=filler,
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
            advertising=AdvertisingDefinition(
                enabled=ad_enabled,
                sources=tuple(ad_sources),
                selection_strategy=ad_strategy,
                breakpoints_seconds=breakpoints,
                interval_seconds=interval_seconds,
                break_duration_seconds=break_duration_seconds,
                priority=priority,
                asset_ids=ad_asset_ids,
                collection_id=collection_id,
                profile_id=profile_id,
                timing_policy=policy_name,
                smoosh_minimum_seconds=smoosh_min,
                smoosh_max_trim_seconds=smoosh_trim,
                expand_max_seconds=expand_max,
                transition_seconds=transition_seconds,
                slot_seconds=slot_seconds,
                schedule_priority=schedule_priority,
                expand_source=expand_source,
                placements=tuple(placements),
                collection_membership=collection_membership,
                excluded_asset_ids=tuple(excluded_ids),
                triggers=tuple(triggers),
                transition_behavior=transition,
            ),
        )
