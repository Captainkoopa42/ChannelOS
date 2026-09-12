from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .library import MediaLibrary
from .loader import load_channel
from .models import (
    CalendarBlockDefinition,
    ChannelDefinition,
    ChannelValidationError,
)
from .resolve import ResolvedChannel, resolve_channel
from .runtime import (
    ChannelRuntime,
    ChannelRuntimeError,
    RuntimeStore,
    deterministic_shuffle_order,
)


class BroadcasterError(RuntimeError):
    """Base error for user-facing channel management."""


class StudioAutoFillCancelled(BroadcasterError):
    """Raised when the user cancels detached Studio Auto Fill generation."""


class ChannelConflictError(BroadcasterError):
    """Raised when a create/update operation could overwrite another channel."""


class ChannelNotFoundError(BroadcasterError):
    """Raised when an explicit edit target no longer exists."""


@dataclass(frozen=True, slots=True)
class ChannelRecord:
    definition: ChannelDefinition
    path: Path
    managed: bool

    @property
    def channel_number(self) -> int:
        return self.definition.channel


@dataclass(frozen=True, slots=True)
class ChannelSaveResult:
    record: ChannelRecord
    backup_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ChannelDeleteResult:
    record: ChannelRecord
    backup_path: Path
    replacement_channel_number: int


@dataclass(frozen=True, slots=True)
class StudioGroup:
    group_id: str
    name: str
    mode: str
    asset_ids: tuple[str, ...]


def channel_to_mapping(definition: ChannelDefinition) -> dict[str, Any]:
    """Serialize the portable channel contract without runtime-only state."""

    mapping: dict[str, Any] = {
        "schema_version": definition.schema_version,
        "channel": definition.channel,
        "name": definition.name,
    }
    if definition.description:
        mapping["description"] = definition.description

    mapping["sources"] = [
        {"path": str(source.path)}
        for source in definition.sources
    ]
    mapping["programming"] = {
        "mode": definition.programming.mode,
        "preserve_episode_order": definition.programming.preserve_episode_order,
        "avoid_repeat_days": definition.programming.avoid_repeat_days,
    }
    if definition.programming.mode == "calendar":
        mapping["programming"]["filler_mode"] = (
            definition.programming.filler_mode
        )
        mapping["programming"]["calendar"] = [
            _calendar_block_mapping(block)
            for block in definition.programming.calendar
        ]
    mapping["presentation"] = {
        "number_width": definition.presentation.number_width,
    }
    return mapping


def _calendar_block_mapping(block: CalendarBlockDefinition) -> dict[str, Any]:
    result: dict[str, Any] = {
        "start_utc": block.start_utc.isoformat(),
        "asset_id": block.asset_id,
    }
    if block.filler is not None:
        result["filler"] = {
            "mode": block.filler.mode,
            "asset_ids": list(block.filler.asset_ids),
        }
    return result


def serialize_channel(definition: ChannelDefinition) -> str:
    """Return stable, human-readable YAML for a portable channel definition."""

    return yaml.safe_dump(
        channel_to_mapping(definition),
        sort_keys=False,
        allow_unicode=True,
    )


def _coerce_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ChannelValidationError(f"{field} must be an integer")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ChannelValidationError(f"{field} must be an integer") from exc


def definition_from_editor(raw: dict[str, Any]) -> ChannelDefinition:
    """Translate the Qt/QML editor shape into the public channel schema."""

    sources_raw = raw.get("sources", [])
    if not isinstance(sources_raw, (list, tuple)):
        raise ChannelValidationError("sources must be a list")

    sources = [
        {"path": str(path).strip()}
        for path in sources_raw
        if str(path).strip()
    ]

    mode = str(raw.get("mode", "sequential")).strip().lower()
    calendar_raw = raw.get("calendarBlocks", [])
    if not isinstance(calendar_raw, (list, tuple)):
        raise ChannelValidationError("calendarBlocks must be a list")
    calendar = []
    has_show_filler = False
    for index, block in enumerate(calendar_raw):
        if not isinstance(block, dict):
            raise ChannelValidationError(
                f"calendarBlocks[{index}] must be a mapping"
            )
        item = {
            "start_utc": str(block.get("startUtc", "")).strip(),
            "asset_id": str(block.get("assetId", "")).strip(),
        }
        filler_asset_ids = block.get("fillerAssetIds", [])
        if not isinstance(filler_asset_ids, (list, tuple)):
            raise ChannelValidationError(
                f"calendarBlocks[{index}].fillerAssetIds must be a list"
            )
        normalized_filler_ids = [
            str(asset_id).strip()
            for asset_id in filler_asset_ids
            if str(asset_id).strip()
        ]
        if normalized_filler_ids:
            has_show_filler = True
            item["filler"] = {
                "mode": str(
                    block.get("fillerMode", "sequential")
                ).strip().lower(),
                "asset_ids": normalized_filler_ids,
            }
        calendar.append(item)

    mapping = {
        "schema_version": (
            "0.3"
            if mode == "calendar" and has_show_filler
            else "0.2"
            if mode == "calendar"
            else "0.1"
        ),
        "channel": _coerce_int(raw.get("channel"), "channel"),
        "name": str(raw.get("name", "")),
        "description": str(raw.get("description", "")).strip() or None,
        "sources": sources,
        "programming": {
            "mode": mode,
            "preserve_episode_order": bool(
                raw.get("preserveEpisodeOrder", False)
            ),
            "avoid_repeat_days": _coerce_int(
                raw.get("avoidRepeatDays", 0),
                "avoidRepeatDays",
            ),
        },
        "presentation": {
            "number_width": _coerce_int(
                raw.get("numberWidth", 3),
                "numberWidth",
            ),
        },
    }
    if mode == "calendar":
        mapping["programming"]["filler_mode"] = str(
            raw.get("fillerMode", "sequential")
        ).strip().lower()
        mapping["programming"]["calendar"] = calendar
    return ChannelDefinition.from_mapping(mapping)


class BroadcasterService:
    """Owns safe persistence and validation of portable channel definitions.

    The broadcaster is deliberately not the schedule authority. It writes the
    same portable definitions that ChannelRuntime already consumes, validates
    them through the real resolver/runtime path, and then lets the caller reload
    the authoritative television lineup.
    """

    def __init__(
        self,
        channel_paths: Iterable[str | Path],
        managed_directory: str | Path,
        library: MediaLibrary,
    ) -> None:
        self.library = library
        self.managed_directory = Path(managed_directory)
        self._explicit_paths = tuple(
            self._normalize_path(path)
            for path in channel_paths
        )
        self._records: dict[int, ChannelRecord] = {}
        self.refresh()

    @staticmethod
    def _normalize_path(path: str | Path) -> Path:
        return Path(path).expanduser().resolve(strict=False)

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    def _all_candidate_paths(self) -> tuple[Path, ...]:
        discovered = list(self._explicit_paths)
        managed = self._normalize_path(self.managed_directory)
        if managed.is_dir():
            discovered.extend(sorted(managed.glob("*.yaml")))
            discovered.extend(sorted(managed.glob("*.yml")))

        unique: list[Path] = []
        seen: set[str] = set()
        for path in discovered:
            resolved = self._normalize_path(path)
            key = self._path_key(resolved)
            if key in seen:
                continue
            seen.add(key)
            unique.append(resolved)
        return tuple(unique)

    def refresh(self) -> None:
        records: dict[int, ChannelRecord] = {}
        managed_root = self._normalize_path(self.managed_directory)

        for path in self._all_candidate_paths():
            definition = load_channel(path)
            number = definition.channel
            if number in records:
                previous = records[number]
                raise ChannelConflictError(
                    f"channel {definition.display_number} is defined by both "
                    f"{previous.path} and {path}; ChannelOS will not guess which "
                    "definition should win"
                )

            try:
                path.relative_to(managed_root)
                managed = True
            except ValueError:
                managed = False

            records[number] = ChannelRecord(
                definition=definition,
                path=path,
                managed=managed,
            )

        self._records = records

    @property
    def records(self) -> tuple[ChannelRecord, ...]:
        return tuple(
            self._records[number]
            for number in sorted(self._records)
        )

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(record.path for record in self.records)

    @property
    def channel_numbers(self) -> tuple[int, ...]:
        return tuple(record.channel_number for record in self.records)

    def source_options(self) -> tuple[str, ...]:
        roots = {
            str(source_root)
            for source_root in self.library.list_online_source_roots()
        }
        return tuple(sorted(roots, key=os.path.normcase))

    def suggested_channel_number(self) -> int:
        used = set(self.channel_numbers)
        for candidate in range(1, 10000):
            if candidate not in used:
                return candidate
        raise BroadcasterError("all channel numbers from 1 through 9999 are in use")

    def snapshot(self) -> dict[str, Any]:
        channels: list[dict[str, Any]] = []
        for record in self.records:
            definition = record.definition
            channels.append(
                {
                    "channelNumber": definition.channel,
                    "schemaVersion": definition.schema_version,
                    "displayNumber": definition.display_number,
                    "name": definition.name,
                    "description": definition.description or "",
                    "mode": definition.programming.mode,
                    "preserveEpisodeOrder": (
                        definition.programming.preserve_episode_order
                    ),
                    "avoidRepeatDays": (
                        definition.programming.avoid_repeat_days
                    ),
                    "fillerMode": definition.programming.filler_mode,
                    "calendarBlockCount": len(
                        definition.programming.calendar
                    ),
                    "numberWidth": definition.presentation.number_width,
                    "sources": [
                        str(source.path)
                        for source in definition.sources
                    ],
                    "sourceCount": len(definition.sources),
                    "path": str(record.path),
                    "managed": record.managed,
                }
            )

        return {
            "channels": channels,
            "channelCount": len(channels),
            "sourceOptions": list(self.source_options()),
            "suggestedChannel": self.suggested_channel_number(),
            "managedDirectory": str(
                self._normalize_path(self.managed_directory)
            ),
        }

    def studio_media(self) -> list[dict[str, Any]]:
        """Return one online Library card per stable asset for Channel Studio."""

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for media in self.library.list_online_media():
            if media.asset.asset_id in seen:
                continue
            seen.add(media.asset.asset_id)
            items.append(
                {
                    "assetId": media.asset.asset_id,
                    "title": media.location.path.stem,
                    "path": str(media.location.path),
                    "sourceRoot": str(media.location.source_root),
                    "durationSeconds": float(
                        media.asset.duration_seconds or 0.0
                    ),
                    "containerFormat": str(
                        media.asset.container_format or "media"
                    ).upper(),
                }
            )
        return items

    @property
    def _studio_groups_path(self) -> Path:
        # Authoring conveniences live beside managed channel definitions but
        # outside their directory scan. Applied channels embed a snapshot of
        # group members, so playback never depends on this private Studio file.
        return self.managed_directory / "studio" / "program-groups.yaml"

    def _load_studio_groups(self) -> tuple[StudioGroup, ...]:
        path = self._studio_groups_path
        if not path.exists():
            return ()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise BroadcasterError(
                f"Studio program groups could not be read: {exc}"
            ) from exc
        if not isinstance(raw, dict) or set(raw) != {"schema_version", "groups"}:
            raise BroadcasterError(
                "Studio program groups must contain schema_version and groups"
            )
        if raw.get("schema_version") != 1 or not isinstance(raw.get("groups"), list):
            raise BroadcasterError(
                "Studio program groups use an unsupported local format"
            )

        groups: list[StudioGroup] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for index, item in enumerate(raw["groups"]):
            if not isinstance(item, dict) or set(item) != {
                "id",
                "name",
                "mode",
                "asset_ids",
            }:
                raise BroadcasterError(
                    f"Studio program group {index} has an invalid shape"
                )
            group_id = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip()
            mode = str(item.get("mode", "")).strip().lower()
            raw_asset_ids = item.get("asset_ids")
            if not group_id or group_id in seen_ids:
                raise BroadcasterError(
                    f"Studio program group {index} has a missing or duplicate id"
                )
            name_key = name.casefold()
            if not name or name_key in seen_names:
                raise BroadcasterError(
                    f"Studio program group {index} has a missing or duplicate name"
                )
            if mode not in {"sequential", "shuffle"}:
                raise BroadcasterError(
                    f"Studio program group {name!r} has an invalid mode"
                )
            if not isinstance(raw_asset_ids, list) or not raw_asset_ids:
                raise BroadcasterError(
                    f"Studio program group {name!r} must contain media"
                )
            if len(raw_asset_ids) > 10_000:
                raise BroadcasterError(
                    f"Studio program group {name!r} cannot exceed 10000 media items"
                )
            asset_ids = tuple(str(value).strip() for value in raw_asset_ids)
            if any(not value for value in asset_ids) or len(set(asset_ids)) != len(asset_ids):
                raise BroadcasterError(
                    f"Studio program group {name!r} has invalid media ids"
                )
            seen_ids.add(group_id)
            seen_names.add(name_key)
            groups.append(
                StudioGroup(
                    group_id=group_id,
                    name=name,
                    mode=mode,
                    asset_ids=asset_ids,
                )
            )
        return tuple(groups)

    def _save_studio_groups(self, groups: Iterable[StudioGroup]) -> None:
        ordered = sorted(groups, key=lambda group: group.name.casefold())
        content = yaml.safe_dump(
            {
                "schema_version": 1,
                "groups": [
                    {
                        "id": group.group_id,
                        "name": group.name,
                        "mode": group.mode,
                        "asset_ids": list(group.asset_ids),
                    }
                    for group in ordered
                ],
            },
            sort_keys=False,
            allow_unicode=True,
        )
        self._atomic_write(self._studio_groups_path, content)

    def studio_groups(self) -> list[dict[str, Any]]:
        media_by_id = {
            item["assetId"]: item
            for item in self.studio_media()
        }
        result: list[dict[str, Any]] = []
        for group in self._load_studio_groups():
            available = [
                media_by_id[asset_id]
                for asset_id in group.asset_ids
                if asset_id in media_by_id
            ]
            result.append(
                {
                    "groupId": group.group_id,
                    "name": group.name,
                    "mode": group.mode,
                    "assetIds": list(group.asset_ids),
                    "memberCount": len(group.asset_ids),
                    "availableCount": len(available),
                    "media": available,
                }
            )
        return result

    def create_studio_group(
        self,
        name: str,
        asset_ids: Iterable[str],
        mode: str,
    ) -> dict[str, Any]:
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ChannelValidationError("program group name must not be empty")
        if len(normalized_name) > 80:
            raise ChannelValidationError(
                "program group name cannot exceed 80 characters"
            )
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in {"sequential", "shuffle"}:
            raise ChannelValidationError(
                "program group mode must be sequential or shuffle"
            )
        if isinstance(asset_ids, (str, bytes)):
            raise ChannelValidationError("program group media must be a list")
        unique_ids = tuple(dict.fromkeys(str(value).strip() for value in asset_ids))
        if not unique_ids or any(not value for value in unique_ids):
            raise ChannelValidationError(
                "program group must contain at least one valid media asset"
            )
        if len(unique_ids) > 10_000:
            raise ChannelValidationError(
                "program group cannot exceed 10000 media items"
            )
        online_ids = {
            item["assetId"]
            for item in self.studio_media()
        }
        missing = [asset_id for asset_id in unique_ids if asset_id not in online_ids]
        if missing:
            raise BroadcasterError(
                "program group contains media that is not currently available: "
                + ", ".join(missing[:3])
            )

        groups = list(self._load_studio_groups())
        if any(group.name.casefold() == normalized_name.casefold() for group in groups):
            raise ChannelConflictError(
                f"a Studio program group named {normalized_name!r} already exists"
            )
        group = StudioGroup(
            group_id=uuid.uuid4().hex,
            name=normalized_name,
            mode=normalized_mode,
            asset_ids=unique_ids,
        )
        groups.append(group)
        self._save_studio_groups(groups)
        return next(
            item
            for item in self.studio_groups()
            if item["groupId"] == group.group_id
        )

    def delete_studio_group(self, group_id: str) -> None:
        target = str(group_id).strip()
        groups = list(self._load_studio_groups())
        retained = [group for group in groups if group.group_id != target]
        if len(retained) == len(groups):
            raise BroadcasterError("Studio program group no longer exists")
        self._save_studio_groups(retained)

    def studio_draft(self, channel_number: int = 0) -> dict[str, Any]:
        """Build a detached Studio draft; opening it never alters live TV."""

        number = int(channel_number)
        if number <= 0:
            sources = list(self.source_options())
            return {
                "editingChannelNumber": 0,
                "channel": self.suggested_channel_number(),
                "name": "",
                "description": "",
                "numberWidth": 3,
                "fillerMode": "sequential",
                "avoidRepeatDays": 0,
                "sources": sources,
                "calendarBlocks": [],
                "media": self.studio_media(),
                "groups": self.studio_groups(),
            }

        try:
            definition = self._records[number].definition
        except KeyError as exc:
            raise ChannelNotFoundError(
                f"channel {number} is no longer in the active lineup"
            ) from exc

        media_by_id = {
            item["assetId"]: item
            for item in self.studio_media()
        }
        groups = self.studio_groups()
        group_names_by_snapshot = {
            (
                str(group["mode"]),
                tuple(str(value) for value in group["assetIds"]),
            ): str(group["name"])
            for group in groups
        }
        blocks: list[dict[str, Any]] = []
        for block in definition.programming.calendar:
            media = media_by_id.get(block.asset_id, {})
            duration = float(media.get("durationSeconds", 0.0))
            blocks.append(
                {
                    "assetId": block.asset_id,
                    "title": str(media.get("title", "Unavailable media")),
                    "path": str(media.get("path", "")),
                    "sourceRoot": str(media.get("sourceRoot", "")),
                    "durationSeconds": duration,
                    "startUtc": block.start_utc.isoformat(),
                    "endUtc": (
                        block.start_utc + timedelta(seconds=duration)
                    ).isoformat(),
                    "fillerMode": (
                        block.filler.mode
                        if block.filler is not None
                        else ""
                    ),
                    "fillerAssetIds": (
                        list(block.filler.asset_ids)
                        if block.filler is not None
                        else []
                    ),
                    "fillerGroupName": (
                        group_names_by_snapshot.get(
                            (block.filler.mode, block.filler.asset_ids),
                            "Embedded group",
                        )
                        if block.filler is not None
                        else ""
                    ),
                }
            )

        return {
            "editingChannelNumber": definition.channel,
            "channel": definition.channel,
            "name": definition.name,
            "description": definition.description or "",
            "numberWidth": definition.presentation.number_width,
            "fillerMode": (
                definition.programming.filler_mode
                if definition.programming.mode == "calendar"
                else definition.programming.mode
            ),
            "avoidRepeatDays": definition.programming.avoid_repeat_days,
            "sources": [str(source.path) for source in definition.sources],
            "calendarBlocks": blocks,
            "media": list(media_by_id.values()),
            "groups": groups,
        }

    @staticmethod
    def _studio_timestamp(value: str, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ChannelValidationError(
                f"{field} must be an ISO timestamp"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ChannelValidationError(f"{field} must include a timezone")
        return parsed.astimezone(timezone.utc)

    def auto_fill_studio(
        self,
        raw: dict[str, Any],
        start_text: str,
        end_text: str,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Generate editable calendar blocks from the selected channel sources."""

        def check_cancelled() -> None:
            if should_cancel is not None and should_cancel():
                raise StudioAutoFillCancelled("Studio Auto Fill was cancelled")

        def publish(current: int, total: int, message: str) -> None:
            if on_progress is not None:
                on_progress(int(current), int(total), message)

        check_cancelled()
        publish(0, 0, "Validating the selected range…")
        start = self._studio_timestamp(start_text, "calendar start")
        end = self._studio_timestamp(end_text, "calendar end")
        if end <= start:
            raise ChannelValidationError("calendar end must be after start")
        if end - start > timedelta(days=62):
            raise ChannelValidationError(
                "Auto Fill is limited to 62 days at a time"
            )

        pool_editor = dict(raw)
        filler_mode = str(raw.get("fillerMode", "sequential")).lower()
        pool_editor["channel"] = raw.get("channel") or self.suggested_channel_number()
        pool_editor["name"] = str(raw.get("name", "")).strip() or "Studio Draft"
        pool_editor["mode"] = filler_mode
        pool_editor["calendarBlocks"] = []
        definition = definition_from_editor(pool_editor)
        check_cancelled()
        publish(0, 0, "Resolving indexed local media…")
        resolved = self._resolve_and_validate(definition)
        check_cancelled()
        if filler_mode == "shuffle":
            ordered = deterministic_shuffle_order(resolved)
        else:
            ordered = resolved.media

        blocks: list[dict[str, Any]] = []
        cursor = start
        index = 0
        range_seconds = max(1, int((end - start).total_seconds()))
        last_percent = -1
        publish(0, range_seconds, "Building the editable schedule…")
        while cursor < end and len(blocks) < 10000:
            check_cancelled()
            media = ordered[index % len(ordered)]
            duration = float(media.asset.duration_seconds or 0.0)
            if duration <= 0:
                raise BroadcasterError(
                    f"Auto Fill requires a positive duration for {media.location.path}"
                )
            block_end = cursor + timedelta(seconds=duration)
            if block_end > end:
                break
            blocks.append(
                {
                    "assetId": media.asset.asset_id,
                    "title": media.location.path.stem,
                    "path": str(media.location.path),
                    "sourceRoot": str(media.location.source_root),
                    "durationSeconds": duration,
                    "startUtc": cursor.isoformat(),
                    "endUtc": block_end.isoformat(),
                }
            )
            cursor = block_end
            index += 1
            completed_seconds = min(
                range_seconds,
                int((cursor - start).total_seconds()),
            )
            percent = int(completed_seconds * 100 / range_seconds)
            if percent != last_percent:
                publish(
                    completed_seconds,
                    range_seconds,
                    f"Scheduled {len(blocks)} program block(s)…",
                )
                last_percent = percent

        check_cancelled()
        hit_limit = cursor < end and len(blocks) >= 10000
        message = (
            f"Auto-filled {len(blocks)} editable program blocks from "
            f"{start.date().isoformat()} through {end.date().isoformat()}; "
        )
        if hit_limit:
            message += (
                "the 10000-block safety limit was reached and filler covers "
                "the remaining time"
            )
        else:
            message += "the normal filler covers any short remainder"

        result = {
            "ok": True,
            "message": message,
            "startUtc": start.isoformat(),
            "endUtc": end.isoformat(),
            "completeThroughUtc": cursor.isoformat(),
            "hitBlockLimit": hit_limit,
            "blocks": blocks,
        }
        publish(range_seconds, range_seconds, "Auto Fill schedule ready")
        return result

    def _resolve_and_validate(
        self,
        definition: ChannelDefinition,
    ) -> ResolvedChannel:
        resolved = resolve_channel(definition, self.library)
        if not resolved.media:
            raise BroadcasterError(
                f"Channel {definition.display_number} - {definition.name} "
                "does not resolve any indexed online media. Add/scan the "
                "source in Library first or choose another indexed source."
            )

        # Use the real ChannelRuntime constructor against a disposable state
        # database. This validates durations, shuffle repeat guarantees, and
        # every other runtime invariant without mutating the live TV state.
        with tempfile.TemporaryDirectory(
            prefix="channelos-broadcaster-validate-"
        ) as temporary:
            validation_store = RuntimeStore(
                Path(temporary) / "runtime.db"
            )
            ChannelRuntime.open(resolved, validation_store)

        return resolved

    def preview(self, raw: dict[str, Any], limit: int = 8) -> dict[str, Any]:
        definition = definition_from_editor(raw)
        resolved = self._resolve_and_validate(definition)

        if definition.programming.mode == "shuffle":
            ordered = deterministic_shuffle_order(resolved)
        elif definition.programming.mode == "calendar":
            by_asset = {
                media.asset.asset_id: media
                for media in resolved.media
            }
            ordered = tuple(
                by_asset[block.asset_id]
                for block in definition.programming.calendar
            )
        else:
            ordered = resolved.media

        items: list[dict[str, Any]] = []
        calendar_blocks = definition.programming.calendar
        for index, media in enumerate(ordered[: max(1, int(limit))]):
            item = {
                "assetId": media.asset.asset_id,
                "title": media.location.path.stem,
                "path": str(media.location.path),
                "durationSeconds": float(
                    media.asset.duration_seconds or 0.0
                ),
            }
            if definition.programming.mode == "calendar":
                start = calendar_blocks[index].start_utc
                item["startUtc"] = start.isoformat()
                item["endUtc"] = (
                    start
                    + timedelta(
                        seconds=float(media.asset.duration_seconds or 0.0)
                    )
                ).isoformat()
            items.append(item)

        return {
            "ok": True,
            "channelNumber": definition.channel,
            "displayNumber": definition.display_number,
            "name": definition.name,
            "mode": definition.programming.mode,
            "resolvedCount": len(resolved.media),
            "items": items,
        }

    def _managed_path_for(
        self,
        definition: ChannelDefinition,
    ) -> Path:
        return self._normalize_path(
            self.managed_directory
            / f"channel-{definition.channel:04d}.yaml"
        )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            finally:
                raise

    def create(self, raw: dict[str, Any]) -> ChannelSaveResult:
        definition = definition_from_editor(raw)
        if definition.channel in self._records:
            existing = self._records[definition.channel]
            raise ChannelConflictError(
                f"Channel {definition.display_number} already exists at "
                f"{existing.path}. Nothing was overwritten. Select that "
                "channel and choose Edit Existing Channel instead."
            )

        self._resolve_and_validate(definition)
        target = self._managed_path_for(definition)

        if target.exists():
            raise ChannelConflictError(
                f"{target} already exists but is not part of the active "
                "channel registry. ChannelOS will not overwrite an unknown "
                "file."
            )

        self._atomic_write(target, serialize_channel(definition))
        self.refresh()
        return ChannelSaveResult(self._records[definition.channel])

    def update(
        self,
        original_channel_number: int,
        raw: dict[str, Any],
    ) -> ChannelSaveResult:
        original_number = int(original_channel_number)
        try:
            existing = self._records[original_number]
        except KeyError as exc:
            raise ChannelNotFoundError(
                f"channel {original_number} is no longer in the active lineup"
            ) from exc

        definition = definition_from_editor(raw)

        # Renumbering is intentionally not an in-place edit. It changes
        # television identity/continuity and will get its own explicit flow.
        if definition.channel != original_number:
            raise ChannelConflictError(
                "renumbering an existing channel is not an in-place edit. "
                "Create the new channel explicitly so ChannelOS cannot "
                "accidentally overwrite another station or continuity state."
            )

        self._resolve_and_validate(definition)

        if not existing.path.exists():
            raise ChannelNotFoundError(
                f"cannot edit Channel {definition.display_number}; "
                f"{existing.path} no longer exists"
            )

        backup = existing.path.with_suffix(
            existing.path.suffix + ".bak"
        )
        shutil.copy2(existing.path, backup)
        self._atomic_write(existing.path, serialize_channel(definition))
        self.refresh()

        return ChannelSaveResult(
            record=self._records[definition.channel],
            backup_path=backup,
        )

    def delete(self, channel_number: int) -> ChannelDeleteResult:
        """Remove one managed definition while retaining a recovery backup."""

        number = int(channel_number)
        try:
            existing = self._records[number]
        except KeyError as exc:
            raise ChannelNotFoundError(
                f"channel {number} is no longer in the active lineup"
            ) from exc

        if len(self._records) <= 1:
            raise BroadcasterError(
                "ChannelOS requires at least one active channel. Create its "
                "replacement before deleting this channel."
            )
        if not existing.managed:
            raise BroadcasterError(
                f"Channel {existing.definition.display_number} was loaded from "
                f"an external definition at {existing.path}. ChannelOS will not "
                "delete files outside its managed channel directory."
            )
        if any(
            self._path_key(path) == self._path_key(existing.path)
            for path in self._explicit_paths
        ):
            raise BroadcasterError(
                f"Channel {existing.definition.display_number} was supplied as "
                "an explicit startup path and cannot be deleted in Broadcaster."
            )
        if not existing.path.is_file():
            raise ChannelNotFoundError(
                f"cannot delete Channel {existing.definition.display_number}; "
                f"{existing.path} no longer exists"
            )

        ordered_numbers = list(self.channel_numbers)
        removed_index = ordered_numbers.index(number)
        remaining_numbers = [
            candidate for candidate in ordered_numbers if candidate != number
        ]
        replacement_channel_number = remaining_numbers[
            min(removed_index, len(remaining_numbers) - 1)
        ]

        # Prove the remaining lineup can still open before moving anything.
        for record in self.records:
            if record.channel_number != number:
                self._resolve_and_validate(record.definition)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = existing.path.with_name(
            f"{existing.path.name}.deleted-{timestamp}.bak"
        )
        suffix = 1
        while backup.exists():
            backup = existing.path.with_name(
                f"{existing.path.name}.deleted-{timestamp}-{suffix}.bak"
            )
            suffix += 1

        os.replace(existing.path, backup)
        try:
            self.refresh()
        except Exception:
            os.replace(backup, existing.path)
            self.refresh()
            raise

        return ChannelDeleteResult(
            record=existing,
            backup_path=backup,
            replacement_channel_number=replacement_channel_number,
        )

    def restore_deleted(self, result: ChannelDeleteResult) -> None:
        """Roll back an uncommitted lineup deletion from its recovery file."""

        original = self._normalize_path(result.record.path)
        backup = self._normalize_path(result.backup_path)
        if original.exists():
            raise ChannelConflictError(
                f"cannot restore Channel {result.record.definition.display_number}; "
                f"{original} already exists"
            )
        if not backup.is_file():
            raise ChannelNotFoundError(
                f"cannot restore Channel {result.record.definition.display_number}; "
                f"recovery backup {backup} is unavailable"
            )
        os.replace(backup, original)
        self.refresh()
