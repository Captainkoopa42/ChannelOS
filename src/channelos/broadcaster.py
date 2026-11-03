from __future__ import annotations

import os
import hashlib
import json
import sqlite3
from contextlib import closing
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .ad_catalog import (
    AdCatalogStore, AdCollection, AdPlacementAssignment, BreakProfile, ChannelAdAssignment,
    export_portable_channel,
)
from .ad_break_engine import ProgramOccurrence
from .ad_scheduling import calendar_ad_room, calendar_gap_policy, configured_policies, eligible_media, select_segments
from .library import MediaLibrary, normalize_path, path_key_is_within
from .loader import load_channel
from .models import (
    CalendarBlockDefinition,
    ChannelDefinition,
    ChannelValidationError,
    SourceDefinition,
    advertising_to_mapping,
)
from .portable import PortablePaths, path_tree, decode_tree
from .resolve import ResolvedChannel, resolve_channel
from .runtime import (
    ChannelRuntime,
    ChannelRuntimeError,
    RuntimeStore,
    deterministic_shuffle_order,
    advertising_signature,
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
    archive_id: str = ""
    assignment: ChannelAdAssignment | None = None


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
    if (
        definition.schema_version in {"0.4", "0.5", "0.6"}
        and (definition.advertising.enabled
             or definition.advertising.sources
             or definition.advertising.asset_ids or definition.advertising.placements
             or definition.advertising.profile_id or definition.advertising.collection_id)
    ):
        mapping["advertising"] = {
            "enabled": definition.advertising.enabled,
            "sources": [
                {"path": str(source.path)}
                for source in definition.advertising.sources
            ],
            "selection_strategy": definition.advertising.selection_strategy,
            "breakpoints_seconds": list(definition.advertising.breakpoints_seconds),
            "interval_seconds": definition.advertising.interval_seconds,
            "break_duration_seconds": definition.advertising.break_duration_seconds,
            "priority": definition.advertising.priority,
        }
        if definition.schema_version in {"0.5", "0.6"}:
            mapping["advertising"].update({
                "asset_ids": list(definition.advertising.asset_ids),
                "collection_id": definition.advertising.collection_id,
                "profile_id": definition.advertising.profile_id,
                "timing_policy": definition.advertising.timing_policy,
                "smoosh_minimum_seconds": definition.advertising.smoosh_minimum_seconds,
                "smoosh_max_trim_seconds": definition.advertising.smoosh_max_trim_seconds,
                "expand_max_seconds": definition.advertising.expand_max_seconds,
                "triggers": list(definition.advertising.triggers),
                "transition_behavior": definition.advertising.transition_behavior,
            })
            mapping["advertising"] = advertising_to_mapping(definition.advertising)
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
    if block.ad_plan is not None:
        result["ad_plan"] = block.ad_plan
    return result


def serialize_channel(definition: ChannelDefinition, *, portable: PortablePaths | None = None) -> str:
    """Return stable, human-readable YAML for a portable channel definition."""

    return yaml.safe_dump(
        path_tree(channel_to_mapping(definition), portable.encode) if portable else channel_to_mapping(definition),
        sort_keys=False,
        allow_unicode=True,
    )


def _coerce_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ChannelValidationError(f"{field} must be an integer")
    # QML JavaScript Numbers arrive through QVariantMap as Python doubles,
    # even when the user entered a whole number such as the default priority 0.
    # Normalize at the editor boundary; the portable schema stays strict.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ChannelValidationError(f"{field} must be an integer") from exc


def _editor_ad_policy(raw: dict[str, Any]) -> dict[str, Any]:
    policy = dict(raw)
    if "priority" in policy:
        policy["priority"] = _coerce_int(policy["priority"], "advertising.priority")
    return policy


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
        if block.get("adPlan") is not None:
            item["ad_plan"] = block["adPlan"]
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

    raw_ad_sources = raw.get("adSources", [])
    if not isinstance(raw_ad_sources, (list, tuple)):
        raise ChannelValidationError("adSources must be a list")
    ad_sources = [
        {"path": str(path).strip()}
        for path in raw_ad_sources
        if str(path).strip()
    ]
    ad_enabled = bool(raw.get("adBreaksEnabled", False))
    ad_strategy = str(raw.get("adSelectionStrategy", "best_fit")).strip().lower()
    ad_asset_ids = raw.get("adAssetIds", [])
    if not isinstance(ad_asset_ids, (list, tuple)):
        raise ChannelValidationError("adAssetIds must be a list")
    ad_collection_id = str(raw.get("adCollectionId", "") or "").strip()
    ad_profile_id = str(raw.get("adProfileId", "") or "").strip()
    advanced_ads = bool(
        raw.get("adSetupMode", "advanced") != "advanced"
        or
        raw.get("adConfigVersion") in {"0.5", "0.6"}
        or ad_asset_ids or ad_collection_id or ad_profile_id
        or raw.get("adBreakpointsSeconds")
        or raw.get("adIntervalSeconds")
        or raw.get("adTimingPolicy") or raw.get("adPlacements")
    )
    has_advertising = ad_enabled or bool(ad_sources) or bool(ad_asset_ids) or bool(
        ad_collection_id or ad_profile_id or raw.get("adPlacements")
    )

    mapping = {
        "schema_version": (
            "0.6" if (any(block.get("adPlan") for block in calendar_raw)
                       or has_advertising and raw.get("adSetupMode", "advanced") != "advanced") else "0.5"
            if has_advertising and advanced_ads
            else "0.4"
            if has_advertising
            else "0.3"
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
    if has_advertising:
        mapping["advertising"] = {
            "enabled": ad_enabled,
            "sources": ad_sources,
            "selection_strategy": ad_strategy,
        }
        if advanced_ads:
            def values(key: str) -> list[str]:
                value = raw.get(key, [])
                if not isinstance(value, (list, tuple)):
                    raise ChannelValidationError(f"{key} must be a list")
                return [str(item).strip() for item in value if str(item).strip()]

            placements = raw.get("adPlacements", [])
            if isinstance(placements, (list, tuple)):
                placements = [
                    {**item, "policy": _editor_ad_policy(item["policy"])}
                    if isinstance(item, dict) and isinstance(item.get("policy"), dict)
                    else item
                    for item in placements
                ]
            settings = mapping["advertising"]
            settings.update({
                "asset_ids": [str(value) for value in ad_asset_ids],
                "collection_id": ad_collection_id or None,
                "profile_id": ad_profile_id or None,
                "breakpoints_seconds": values("adBreakpointsSeconds"),
                "interval_seconds": raw.get("adIntervalSeconds") or None,
                "break_duration_seconds": raw.get("adBreakDurationSeconds", 120),
                "priority": _coerce_int(raw.get("adPriority", 0), "advertising.priority"),
                "timing_policy": raw.get("adTimingPolicy", "strict_fit"),
                "smoosh_minimum_seconds": raw.get("adSmooshMinimumSeconds", 5),
                "smoosh_max_trim_seconds": raw.get("adSmooshMaxTrimSeconds", 15),
                "expand_max_seconds": raw.get("adExpandMaxSeconds", 0),
                "triggers": values("adTriggers") if "adTriggers" in raw else [
                    "breakpoint", "interval", "between_programs", "calendar_boundary",
                ],
                "transition_behavior": raw.get("adTransitionBehavior", "cut"),
                "transition_seconds": raw.get("adTransitionSeconds", 0.5),
                "slot_seconds": raw.get("adSlotSeconds") or None,
                "schedule_priority": raw.get("adSchedulePriority", "program"),
                "expand_source": raw.get("adExpandSource", "schedule_shift"),
                "placements": placements,
                "collection_membership": raw.get("adCollectionMembership", "fixed"),
                "excluded_asset_ids": raw.get("adExcludedAssetIds", []),
            })
            if mapping["schema_version"] == "0.6":
                settings.update(setup_mode=raw.get("adSetupMode", "after_show"),
                                play_order=raw.get("adPlayOrder", "shuffle"),
                                clock_interval_seconds=raw.get("adClockIntervalSeconds", 900),
                                clock_offset_seconds=raw.get("adClockOffsetSeconds", 0))
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
        *, runtime_database_path: str | Path | None = None,
    ) -> None:
        self.library = library
        self.runtime_database_path = Path(runtime_database_path) if runtime_database_path is not None else library.database_path.with_name("runtime.db")
        self.ad_catalog = AdCatalogStore(
            self.library.database_path.with_name("ad_catalog.sqlite")
        )
        self.managed_directory = Path(managed_directory)
        self._explicit_paths = tuple(
            self._normalize_path(path)
            for path in channel_paths
        )
        self._records: dict[int, ChannelRecord] = {}
        self._definition_cache: dict[Path, tuple[tuple[int, ...], ChannelDefinition]] = {}
        self._recover_deletions()
        self.refresh()

    def _recover_deletions(self) -> None:
        for journal in self.managed_directory.glob("channel-deletion-*.json"):
            self._finish_deletion(journal)

    def _finish_deletion(self, journal: Path) -> None:
        operation = decode_tree(json.loads(journal.read_text(encoding="utf-8")), self.library.portable)
        original, backup = Path(operation["original"]), Path(operation["backup"])
        number, identity = int(operation["channel"]), operation["archive_id"]
        managed = self._normalize_path(self.managed_directory)
        if (len(identity) != 32 or any(character not in "0123456789abcdef" for character in identity)
                or journal.name != f"channel-deletion-{identity}.json"
                or self._normalize_path(original).parent != managed
                or self._normalize_path(backup).parent != managed
                or not backup.name.startswith(original.name + ".deleted-")
                or self._normalize_path(operation["runtime_database"]) != self._normalize_path(self.runtime_database_path)
                or operation.get("assignment") and operation["assignment"].get("channel_number") != number):
            raise BroadcasterError("The channel recovery record does not match this setup. No recovery files were changed.")
        store = RuntimeStore(self.runtime_database_path)
        if operation.get("restore"):
            store.restore_deleted_channel(identity)
            assignment = operation.get("assignment")
            if assignment:
                assignment["placements"] = tuple(AdPlacementAssignment(**item) for item in assignment.get("placements", ()))
                self.ad_catalog.assign_channel(ChannelAdAssignment(**assignment))
            else:
                self.ad_catalog.clear_channel_assignment(number)
            if not original.exists():
                os.replace(backup, original)
        elif not original.exists():
            if not backup.is_file():
                raise BroadcasterError(f"Cannot recover channel deletion: {backup} is unavailable")
            store.delete_channel(number, archive_id=identity)
            self.ad_catalog.clear_channel_assignment(number)
        journal.unlink()

    def _deletion_journal(self, operation: dict[str, Any]) -> Path:
        journal = self.managed_directory / f"channel-deletion-{operation['archive_id']}.json"
        encoded = path_tree(operation, self.library.portable.encode) if self.library.portable else operation
        self._atomic_write(journal, json.dumps(encoded, sort_keys=True))
        return journal

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
        if self.library.portable:
            self.library.portable.check_available()
        records: dict[int, ChannelRecord] = {}
        managed_root = self._normalize_path(self.managed_directory)

        for path in self._all_candidate_paths():
            stat = path.stat()
            revision = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
            cached = self._definition_cache.get(path)
            definition = cached[1] if cached is not None and cached[0] == revision else load_channel(path)
            self._definition_cache[path] = (revision, definition)
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
        active_paths = {record.path for record in records.values()}
        self._definition_cache = {path: value for path, value in self._definition_cache.items() if path in active_paths}

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

    def _before_mutation_commit(self, definition=None) -> None:
        callback = getattr(self, '_commit_callback', None)
        if callback is not None:
            callback(definition)

    def _source_dependency_context(self, indexed_media=None):
        indexed = self.library.list_cached_media() if indexed_media is None else indexed_media
        catalog = self.ad_catalog.read_snapshot()
        locations, source_keys, affected_by_root, path_keys = {}, {}, {}, {}
        for item in indexed:
            location = item.location
            locations.setdefault(item.asset.asset_id, []).append(location)
            if location.source_root not in source_keys:
                source_keys[location.source_root] = self.library.storage_path(location.source_root)[1]
            root_key = source_keys[location.source_root]
            affected_by_root.setdefault(root_key, []).append(item)
            path_keys[location.path] = normalize_path(location.path)[1]
        channel_specs, assigned_collections = [], set()
        for record in self.records:
            definition = record.definition
            policies = (definition.advertising,) + tuple(p.policy for p in definition.advertising.placements)
            groups = [tuple(s.path for s in definition.sources)] + [tuple(s.path for s in p.sources) for p in policies]
            explicit = {asset for policy in policies for asset in policy.asset_ids}
            for block in definition.programming.calendar:
                explicit.add(block.asset_id)
                if block.filler:
                    explicit.update(block.filler.asset_ids)
            assignment = catalog['assignments'].get(definition.channel)
            if assignment is not None:
                collection_ids = {assignment.collection_id, *(p.collection_id for p in assignment.placements)} - {None}
                assigned_collections.update(collection_ids)
                for identity in collection_ids:
                    collection = catalog['collections'].get(identity)
                    if collection:
                        explicit.update(set(collection.asset_ids) - set(collection.excluded_asset_ids))
                        groups.append(tuple(Path(path) for path in collection.source_paths))
            keys = tuple(tuple(normalize_path(path)[1] for path in group) for group in groups)
            channel_specs.append((definition, keys, explicit))
        return {'locations': locations, 'source_keys': source_keys, 'affected': affected_by_root,
                'path_keys': path_keys, 'channels': channel_specs, 'catalog': catalog,
                'assigned': assigned_collections, 'usable': {}}

    def source_dependency_reports(self, source_roots, *, indexed_media=None):
        context = self._source_dependency_context(indexed_media)
        return {str(root): self.source_dependencies(root, context=context) for root in source_roots}

    def source_dependencies(self, source_root: str | Path, *, indexed_media=None, context=None) -> list[dict[str, object]]:
        """Fresh removal checks and batched presentation share the same rules."""
        context = context if context is not None else self._source_dependency_context(indexed_media)
        _, root_key = self.library.storage_path(source_root)
        affected = context['affected'].get(root_key, ())
        path_keys, source_keys = context['path_keys'], context['source_keys']
        survivor_cache = {}
        def alternatives(asset_id):
            if asset_id not in survivor_cache:
                survivors = []
                for location in context['locations'].get(asset_id, ()):
                    if source_keys[location.source_root] == root_key or not location.online:
                        continue
                    if location.path not in context['usable']:
                        try:
                            context['usable'][location.path] = location.path.is_file()
                        except OSError:
                            context['usable'][location.path] = False
                    if context['usable'][location.path]:
                        survivors.append(location)
                survivor_cache[asset_id] = survivors
            return survivor_cache[asset_id]
        matches = []
        for definition, groups, explicit in context['channels']:
            reasons = set()
            for item in affected:
                asset_id, path_key = item.asset.asset_id, path_keys[item.location.path]
                required = [group for group in groups if any(path_key_is_within(path_key, key) for key in group)]
                if asset_id not in explicit and not required:
                    continue
                survivors = alternatives(asset_id)
                if asset_id in explicit and not survivors:
                    reasons.add('scheduled or advertising asset')
                for group in required:
                    if not any(path_key_is_within(path_keys[loc.path], key) for loc in survivors for key in group):
                        reasons.add('program or advertising source')
            if not affected and any(path_key_is_within(key, normalize_path(source_root)[1]) for group in groups for key in group):
                reasons.add('saved source')
            if reasons:
                matches.append({'channelNumber': definition.channel, 'displayNumber': definition.display_number,
                                'name': definition.name, 'reasons': sorted(reasons)})
        for collection in context['catalog']['collections'].values():
            if collection.collection_id in context['assigned']:
                continue
            selectors = tuple(normalize_path(path)[1] for path in collection.source_paths)
            ids = set(collection.asset_ids) - set(collection.excluded_asset_ids)
            needed = False
            for item in affected:
                asset_id = item.asset.asset_id
                selected = any(path_key_is_within(path_keys[item.location.path], key) for key in selectors)
                if asset_id not in ids and not selected:
                    continue
                survivors = alternatives(asset_id)
                if (asset_id in ids and not survivors or selected and not any(
                        path_key_is_within(path_keys[loc.path], key) for loc in survivors for key in selectors)):
                    needed = True
                    break
            if not affected and any(path_key_is_within(key, normalize_path(source_root)[1]) for key in selectors):
                needed = True
            if needed:
                matches.append({'channelNumber': 0, 'displayNumber': 'Ad collection', 'name': collection.name,
                                'kind': 'collection', 'reasons': ['saved ad collection']})
        return matches

    def remove_library_source(self, source_root: str | Path):
        dependencies = self.source_dependencies(source_root)
        if dependencies:
            labels = ", ".join(str(item["displayNumber"]) for item in dependencies)
            raise BroadcasterError(f"This source is still used by saved channel or ad collection references: {labels}. Edit them before removing it.")
        return self.library.remove_source_from_index(source_root)

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

    def studio_media(self, *, indexed_media=None) -> list[dict[str, Any]]:
        """Return one online Library card per stable asset for Channel Studio."""
        revision = self.library.revision()
        cached = getattr(self, '_studio_media_cache', None)
        if cached is not None and cached[0] == revision:
            return cached[1]
        items: dict[str, dict[str, Any]] = {}
        for media in (indexed_media if indexed_media is not None else self.library.list_online_media()):
            asset_id = media.asset.asset_id
            if asset_id not in items:
                items[asset_id] = {
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
                    "locations": [],
                }
            # A canonical asset can have copies in several sources. Retain
            # every online location so the bin can scope to any selected copy.
            items[asset_id]["locations"].append({
                "path": str(media.location.path),
                "sourceRoot": str(media.location.source_root),
            })
        result = list(items.values())
        self._studio_media_cache = (self.library.revision(), result)
        return result

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

    def studio_groups(
        self,
        *,
        available_asset_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if available_asset_ids is None:
            available_asset_ids = {
                media.asset.asset_id
                for media in self.library.list_online_media()
            }
        result: list[dict[str, Any]] = []
        for group in self._load_studio_groups():
            available_count = sum(
                asset_id in available_asset_ids
                for asset_id in group.asset_ids
            )
            result.append(
                {
                    "groupId": group.group_id,
                    "name": group.name,
                    "mode": group.mode,
                    "assetIds": list(group.asset_ids),
                    "memberCount": len(group.asset_ids),
                    "availableCount": available_count,
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

    def ad_catalog_snapshot(self) -> dict[str, Any]:
        history_review_count = 0
        if Path(self.runtime_database_path).is_file():
            with closing(sqlite3.connect(Path(self.runtime_database_path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='ad_history_review'").fetchone():
                    history_review_count = db.execute("SELECT COUNT(*) FROM ad_history_review").fetchone()[0]
        return {
            "historyReviewCount": history_review_count,
            "historyReviewMessage": "Older airing records need review after calendar changes; the original records were retained." if history_review_count else "",
            "collections": [
                {
                    "collectionId": item.collection_id,
                    "name": item.name,
                    "assetIds": list(item.asset_ids),
                    "sourcePaths": list(item.source_paths),
                    "excludedAssetIds": list(item.excluded_asset_ids),
                    "membership": item.membership,
                }
                for item in self.ad_catalog.list_collections()
            ],
            "profiles": [
                {"profileId": item.profile_id, "name": item.name,
                 "defaults": dict(item.defaults)}
                for item in self.ad_catalog.list_profiles()
            ],
            "assignments": [
                {"channelNumber": item.channel_number,
                 "collectionId": item.collection_id or "",
                 "profileId": item.profile_id or "",
                 "overrides": dict(item.overrides),
                 "placements": [
                     {"placement_id": p.placement_id, "trigger": p.trigger,
                      "collection_id": p.collection_id, "profile_id": p.profile_id,
                      "overrides": dict(p.overrides)} for p in item.placements
                 ]}
                for item in self.ad_catalog.list_assignments()
            ],
        }

    def save_ad_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        collection = AdCollection(
            str(payload.get("collectionId", "")).strip(),
            str(payload.get("name", "")).strip(),
            tuple(str(x).strip() for x in payload.get("assetIds", [])),
            tuple(str(x).strip() for x in payload.get("sourcePaths", [])),
            tuple(str(x).strip() for x in payload.get("excludedAssetIds", [])),
            str(payload.get("membership", "fixed")),
        )
        self.ad_catalog.save_collection(collection)
        return self.ad_catalog_snapshot()

    def save_ad_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = BreakProfile(
            str(payload.get("profileId", "")).strip(),
            str(payload.get("name", "")).strip(),
            _editor_ad_policy(payload.get("defaults", {})),
        )
        self.ad_catalog.save_profile(profile)
        return self.ad_catalog_snapshot()

    def assign_ad_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        assignment = ChannelAdAssignment(
            int(payload.get("channelNumber", 0)),
            str(payload.get("collectionId") or "").strip() or None,
            str(payload.get("profileId") or "").strip() or None,
            _editor_ad_policy(payload.get("overrides", {})),
            tuple(AdPlacementAssignment(**{
                **item, "overrides": _editor_ad_policy(item.get("overrides", {})),
            }) for item in payload.get("placements", [])),
        )
        self.ad_catalog.assign_channel(assignment)
        return self.ad_catalog_snapshot()

    def _apply_ad_catalog(self, definition: ChannelDefinition) -> ChannelDefinition:
        if definition.advertising.setup_mode != "advanced":
            return definition
        return export_portable_channel(definition, self.ad_catalog, self.library,
            enabled_override=definition.advertising.enabled)

    def _configured_definition(self, raw: dict[str, Any]) -> ChannelDefinition:
        definition = self._unreconciled_definition(raw)
        if (definition.programming.mode != "calendar" or not definition.advertising.enabled
                or definition.advertising.setup_mode == "advanced"):
            return definition
        from .calendar_reconcile import detached_store, replay_blocks, snapshot_matches
        resolved = resolve_channel(definition, self.library)
        by_id = {item.asset.asset_id: item for item in resolved.media}
        media_maps = ({item.asset.asset_id: item for item in resolved.ad_media}, by_id)
        revision = advertising_signature(resolved)
        original = self._records.get(definition.channel)
        old_blocks = {block.start_utc: block for block in original.definition.programming.calendar} if original else {}
        blocks = definition.programming.calendar
        changes = [block.start_utc for block in blocks if old_blocks.get(block.start_utc) != block]
        current_starts = {block.start_utc for block in blocks}
        changes.extend(start for start in old_blocks if start not in current_starts)
        for block in blocks:
            media = by_id.get(block.asset_id)
            if media is None:
                raise BroadcasterError("A scheduled show is outside this channel's indexed sources")
            if not snapshot_matches(block.ad_plan, media, block.start_utc, revision, definition.channel, resolved.ad_media, program_media=resolved.media, media_maps=media_maps):
                changes.append(block.start_utc)
        if not changes:
            return definition
        with detached_store(self.runtime_database_path, channel_number=definition.channel) as store:
            replay_from = max(min(changes), datetime.now(timezone.utc)) if original else min(changes)
            reconciled = replay_blocks(resolved, blocks, store=store, replay_from=replay_from)
        return replace(definition, schema_version="0.6",
                       programming=replace(definition.programming, calendar=reconciled))

    def _unreconciled_definition(self, raw: dict[str, Any]) -> ChannelDefinition:
        """Resolve authoring references before validating an enabled snapshot."""
        editor = dict(raw)
        assignment = self._catalog_assignment_for_editor(editor)
        if editor.get("adCatalogAssignment") is not None:
            editor["adPlacements"] = []
        if (assignment is not None and editor.get("adSetupMode", "advanced") == "advanced"
                and editor.get("adBreaksEnabled") and not (
            editor.get("adSources") or editor.get("adAssetIds") or editor.get("adPlacements")
        )):
            editor["adBreaksEnabled"] = False
            base = definition_from_editor(editor)
            return export_portable_channel(base, self.ad_catalog, self.library, enabled_override=True,
                                           assignment_override=assignment)
        definition = definition_from_editor(editor)
        if assignment is not None:
            return export_portable_channel(definition, self.ad_catalog, self.library,
                enabled_override=definition.advertising.enabled if "adBreaksEnabled" in editor else None,
                assignment_override=assignment)
        return definition

    def preview_ad_settings(self, channel_number: int, raw: dict[str, Any]) -> dict[str, Any]:
        """Resolve profile inheritance without changing catalog or channel files."""
        record = self._records.get(int(channel_number))
        editor = dict(raw)
        editor.update(channel=int(channel_number), name=record.definition.name if record else "Draft",
                      sources=[str(source.path) for source in record.definition.sources] if record else ["."],
                      mode="sequential", calendarBlocks=[])
        ad = self._unreconciled_definition(editor).advertising
        fields = {"adBreaksEnabled": "enabled", "adSetupMode": "setup_mode", "adPlayOrder": "play_order",
                  "adClockIntervalSeconds": "clock_interval_seconds", "adClockOffsetSeconds": "clock_offset_seconds",
                  "adSelectionStrategy": "selection_strategy", "adBreakDurationSeconds": "break_duration_seconds",
                  "adBreakpointsSeconds": "breakpoints_seconds", "adIntervalSeconds": "interval_seconds",
                  "adPriority": "priority", "adTimingPolicy": "timing_policy",
                  "adSmooshMinimumSeconds": "smoosh_minimum_seconds", "adSmooshMaxTrimSeconds": "smoosh_max_trim_seconds",
                  "adExpandMaxSeconds": "expand_max_seconds", "adTriggers": "triggers",
                  "adTransitionBehavior": "transition_behavior", "adTransitionSeconds": "transition_seconds",
                  "adSlotSeconds": "slot_seconds", "adSchedulePriority": "schedule_priority",
                  "adExpandSource": "expand_source", "adAssetIds": "asset_ids", "adCollectionId": "collection_id",
                  "adProfileId": "profile_id", "adCollectionMembership": "collection_membership",
                  "adExcludedAssetIds": "excluded_asset_ids"}
        values = {key: list(value) if isinstance(value := getattr(ad, attribute), tuple) else value
                  for key, attribute in fields.items()}
        values.update(adSources=[str(source.path) for source in ad.sources],
                      adPlacements=advertising_to_mapping(ad)["placements"], adConfigVersion="0.6")
        return values

    def _catalog_assignment_for_editor(self, raw: dict[str, Any]) -> ChannelAdAssignment | None:
        number = int(raw.get("channel", 0))
        assignment = self.ad_catalog.get_assignment(number)
        staged = raw.get("adCatalogAssignment")
        if staged is not None:
            assignment = ChannelAdAssignment(number, staged.get("collectionId") or None,
                staged.get("profileId") or None, _editor_ad_policy(staged.get("overrides", {})),
                tuple(AdPlacementAssignment(**item) for item in staged.get("placements", ())))
        if assignment is None or raw.get("adSetupMode", "advanced") != "advanced":
            return assignment
        safe = dict(raw)
        safe["adBreaksEnabled"] = False
        if staged is not None:
            safe["adPlacements"] = []
        safe["adProfileId"] = assignment.profile_id or "draft-policy"
        policy = definition_from_editor(safe).advertising
        baseline = self._records[number].definition.advertising if number in self._records else None
        fields = {
            "adBreaksEnabled": ("enabled", "enabled"),
            "adSelectionStrategy": ("selection_strategy", "strategy"),
            "adBreakDurationSeconds": ("break_duration_seconds", "duration_seconds"),
            "adBreakpointsSeconds": ("breakpoints_seconds", "breakpoints_seconds"),
            "adIntervalSeconds": ("interval_seconds", "interval_seconds"),
            "adPriority": ("priority", "priority"), "adTimingPolicy": ("timing_policy", "timing_policy"),
            "adSmooshMinimumSeconds": ("smoosh_minimum_seconds", "smoosh_minimum_seconds"),
            "adSmooshMaxTrimSeconds": ("smoosh_max_trim_seconds", "smoosh_max_trim_seconds"),
            "adExpandMaxSeconds": ("expand_max_seconds", "expand_max_seconds"),
            "adTriggers": ("triggers", "triggers"),
            "adTransitionBehavior": ("transition_behavior", "transition_behavior"),
            "adTransitionSeconds": ("transition_seconds", "transition_seconds"),
            "adSlotSeconds": ("slot_seconds", "slot_seconds"),
            "adSchedulePriority": ("schedule_priority", "schedule_priority"),
            "adExpandSource": ("expand_source", "expand_source"),
        }
        overrides = dict(assignment.overrides)
        edited = set(raw["adEditedKeys"]) if "adEditedKeys" in raw else None
        for key, (attribute, setting) in fields.items():
            if key not in raw:
                continue
            value = bool(raw[key]) if key == "adBreaksEnabled" else getattr(policy, attribute)
            changed = key in edited if edited is not None else baseline is None or value != getattr(baseline, attribute)
            if changed:
                overrides[setting] = list(value) if isinstance(value, tuple) else value
        collection_id = str(raw.get("adCollectionId", assignment.collection_id or "")).strip() or None
        profile_id = str(raw.get("adProfileId", assignment.profile_id or "")).strip() or None
        return replace(assignment, collection_id=collection_id, profile_id=profile_id, overrides=overrides)

    def studio_draft(self, channel_number: int = 0) -> dict[str, Any]:
        """Build a detached Studio draft; opening it never alters live TV."""

        number = int(channel_number)
        if number <= 0:
            sources = list(self.source_options())
            media = self.studio_media()
            return {
                "editingChannelNumber": 0,
                "channel": self.suggested_channel_number(),
                "name": "",
                "description": "",
                "numberWidth": 3,
                "fillerMode": "sequential",
                "avoidRepeatDays": 0,
                "adBreaksEnabled": False,
                "adSetupMode": "after_show",
                "adPlayOrder": "shuffle",
                "adClockIntervalSeconds": 900,
                "adSources": [],
                "adSelectionStrategy": "best_fit",
                "adAssetIds": [],
                "adCollectionId": "",
                "adProfileId": "",
                "adConfigVersion": "0.5",
                "adBreakpointsSeconds": [],
                "adIntervalSeconds": "",
                "adBreakDurationSeconds": 120,
                "adTimingPolicy": "strict_fit",
                "adSmooshMinimumSeconds": 5,
                "adSmooshMaxTrimSeconds": 15,
                "adExpandMaxSeconds": 0,
                "adPriority": 0,
                "adTriggers": ["breakpoint", "interval", "between_programs", "calendar_boundary"],
                "adTransitionBehavior": "cut",
                "sources": sources,
                "sourceOptions": list(self.source_options()),
                "calendarBlocks": [],
                "media": media,
                "groups": self.studio_groups(
                    available_asset_ids={item["assetId"] for item in media}
                ),
            }

        try:
            definition = self._records[number].definition
        except KeyError as exc:
            raise ChannelNotFoundError(
                f"channel {number} is no longer in the active lineup"
            ) from exc

        definition = self._apply_ad_catalog(definition)

        media_by_id = {
            item["assetId"]: item
            for item in self.studio_media()
        }
        groups = self.studio_groups(
            available_asset_ids=set(media_by_id)
        )
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
                    "adPlan": block.ad_plan,
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
            "adBreaksEnabled": definition.advertising.enabled,
            "adSetupMode": definition.advertising.setup_mode,
            "adPlayOrder": definition.advertising.play_order,
            "adClockIntervalSeconds": definition.advertising.clock_interval_seconds,
            "adClockOffsetSeconds": definition.advertising.clock_offset_seconds,
            "adSources": [str(source.path) for source in definition.advertising.sources],
            "adSelectionStrategy": definition.advertising.selection_strategy,
            "adConfigVersion": definition.schema_version,
            "adAssetIds": list(definition.advertising.asset_ids),
            "adCollectionId": definition.advertising.collection_id or "",
            "adProfileId": definition.advertising.profile_id or "",
            "adBreakpointsSeconds": list(definition.advertising.breakpoints_seconds),
            "adIntervalSeconds": definition.advertising.interval_seconds or "",
            "adBreakDurationSeconds": definition.advertising.break_duration_seconds,
            "adTimingPolicy": definition.advertising.timing_policy,
            "adSmooshMinimumSeconds": definition.advertising.smoosh_minimum_seconds,
            "adSmooshMaxTrimSeconds": definition.advertising.smoosh_max_trim_seconds,
            "adExpandMaxSeconds": definition.advertising.expand_max_seconds,
            "adPriority": definition.advertising.priority,
            "adTriggers": list(definition.advertising.triggers),
            "adTransitionBehavior": definition.advertising.transition_behavior,
            "adTransitionSeconds": definition.advertising.transition_seconds,
            "adSlotSeconds": definition.advertising.slot_seconds,
            "adSchedulePriority": definition.advertising.schedule_priority,
            "adExpandSource": definition.advertising.expand_source,
            "adPlacements": advertising_to_mapping(definition.advertising)["placements"],
            "adCollectionMembership": definition.advertising.collection_membership,
            "adExcludedAssetIds": list(definition.advertising.excluded_asset_ids),
            "sources": [str(source.path) for source in definition.sources],
            "sourceOptions": list(self.source_options()),
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
        definition = self._configured_definition(pool_editor)
        check_cancelled()
        publish(0, 0, "Resolving indexed local media…")
        resolved = self._resolve_and_validate(definition)
        check_cancelled()
        if filler_mode == "shuffle":
            ordered = deterministic_shuffle_order(resolved)
        else:
            ordered = resolved.media

        if definition.advertising.enabled and definition.advertising.setup_mode != "advanced":
            from .simple_ads import auto_fill
            return auto_fill(resolved, ordered, raw, start, end, self.runtime_database_path,
                             publish=publish, check_cancelled=check_cancelled)

        advertising = definition.advertising
        revision = advertising_signature(resolved)

        def ad_room(asset_id: str, begins: datetime, finishes: datetime):
            identity = hashlib.sha256(
                f"calendar:{definition.channel}:{asset_id}:{begins.isoformat()}".encode()
            ).hexdigest()
            return calendar_ad_room(advertising, ProgramOccurrence(
                identity, definition.channel, asset_id, begins, finishes,
            ), revision)

        ad_warnings: list[str] = []
        if advertising.enabled:
            policies = [(identity, trigger, policy) for identity, trigger, policy in configured_policies(advertising)
                        if policy.enabled]
            if not policies:
                ad_warnings.append("No ad triggers are enabled.")
            for identity, trigger, policy in policies:
                budget = policy.slot_seconds if trigger == "fixed_slot" else policy.break_duration_seconds
                gap_trigger = trigger in {"calendar_boundary", "between_programs", "fixed_slot"}
                fit_policy = replace(policy, timing_policy="strict_fit") if gap_trigger and policy.timing_policy == "expand" else policy
                extra = fit_policy.expand_max_seconds if fit_policy.timing_policy == "expand" and fit_policy.schedule_priority != "fixed" else 0.0
                selected = select_segments(eligible_media(resolved.ad_media, policy), budget, fit_policy,
                    seed=f"autofill-fit:{identity}:{trigger}", expand_max_seconds=extra)
                if not selected:
                    ad_warnings.append(f"No ad fits the {budget:g}-second {trigger} break. Use shorter clips or increase the break length.")

        # Existing fixed programs are occupied time, not disposable filler.
        # Auto Fill only creates complete media blocks inside genuinely empty
        # portions of the requested range. This prevents generated blocks from
        # overlapping hand-authored programs and leaves ad/filler gaps intact.
        occupied: list[tuple[datetime, datetime]] = []
        existing_programs: list[tuple[datetime, datetime, str]] = []
        raw_existing = raw.get("calendarBlocks", [])
        if not isinstance(raw_existing, (list, tuple)):
            raise ChannelValidationError("calendarBlocks must be a list")
        duration_by_asset = {
            item.asset.asset_id: float(item.asset.duration_seconds or 0.0)
            for item in resolved.media
        }
        for block_index, existing in enumerate(raw_existing):
            check_cancelled()
            if not isinstance(existing, dict):
                raise ChannelValidationError(
                    f"calendarBlocks[{block_index}] must be a mapping"
                )
            existing_start = self._studio_timestamp(
                existing.get("startUtc", ""), f"calendarBlocks[{block_index}].startUtc"
            )
            end_value = existing.get("endUtc")
            if end_value:
                existing_end = self._studio_timestamp(
                    end_value, f"calendarBlocks[{block_index}].endUtc"
                )
            else:
                asset_id = str(existing.get("assetId", "")).strip()
                duration = duration_by_asset.get(asset_id, 0.0)
                if duration <= 0:
                    raise ChannelValidationError(
                        f"calendarBlocks[{block_index}] has no valid end time or indexed duration"
                    )
                existing_end = existing_start + timedelta(seconds=duration)
            if existing_end <= existing_start:
                raise ChannelValidationError(
                    f"calendarBlocks[{block_index}] ends before it starts"
                )
            existing_programs.append((existing_start, existing_end, str(existing.get("assetId", ""))))
        existing_programs.sort()
        for existing_index, (existing_start, existing_end, asset_id) in enumerate(existing_programs):
            middle, gap, _ = ad_room(asset_id, existing_start, existing_end)
            boundary = min(end, existing_programs[existing_index + 1][0]) if existing_index + 1 < len(existing_programs) else end
            padding = min(middle + gap, max(0.0, (boundary - existing_end).total_seconds()))
            existing_end += timedelta(seconds=padding)
            if existing_start < end and existing_end > start:
                occupied.append((max(start, existing_start), min(end, existing_end)))
        occupied.sort(key=lambda interval: interval[0])
        merged_occupied: list[tuple[datetime, datetime]] = []
        for occupied_start, occupied_end in occupied:
            if merged_occupied and occupied_start <= merged_occupied[-1][1]:
                previous_start, previous_end = merged_occupied[-1]
                merged_occupied[-1] = (
                    previous_start, max(previous_end, occupied_end)
                )
            else:
                merged_occupied.append((occupied_start, occupied_end))

        blocks: list[dict[str, Any]] = []
        cursor = start
        index = 0
        range_seconds = max(1, int((end - start).total_seconds()))
        last_percent = -1
        ad_slots = 0
        ad_reserved_seconds = 0.0
        publish(0, range_seconds, "Building the editable schedule…")

        def fill_gap(gap_end: datetime) -> None:
            nonlocal cursor, index, last_percent, ad_slots, ad_reserved_seconds
            while cursor < gap_end and len(blocks) < 10000:
                check_cancelled()
                media = ordered[index % len(ordered)]
                duration = float(media.asset.duration_seconds or 0.0)
                if duration <= 0:
                    raise BroadcasterError(
                        f"Auto Fill requires a positive duration for {media.location.path}"
                    )
                block_end = cursor + timedelta(seconds=duration)
                middle, gap, middle_count = ad_room(media.asset.asset_id, cursor, block_end)
                broadcast_end = block_end + timedelta(seconds=middle)
                if broadcast_end > gap_end:
                    break
                gap = min(gap, max(0.0, (gap_end - broadcast_end).total_seconds()))
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
                cursor = broadcast_end + timedelta(seconds=gap)
                ad_slots += middle_count + (1 if gap > 0 else 0)
                ad_reserved_seconds += middle + gap
                index += 1
                completed_seconds = min(
                    range_seconds, int((cursor - start).total_seconds())
                )
                percent = int(completed_seconds * 100 / range_seconds)
                if percent != last_percent:
                    publish(
                        completed_seconds, range_seconds,
                        f"Scheduled {len(blocks)} program block(s)…",
                    )
                    last_percent = percent

        for occupied_start, occupied_end in merged_occupied:
            if cursor >= end or len(blocks) >= 10000:
                break
            if occupied_start > cursor:
                fill_gap(occupied_start)
            cursor = max(cursor, occupied_end)
            completed_seconds = min(
                range_seconds, int((cursor - start).total_seconds())
            )
            percent = int(completed_seconds * 100 / range_seconds)
            if percent != last_percent:
                publish(
                    completed_seconds, range_seconds,
                    "Preserving existing scheduled programs…",
                )
                last_percent = percent
        if cursor < end and len(blocks) < 10000:
            fill_gap(end)

        check_cancelled()
        hit_limit = cursor < end and len(blocks) >= 10000
        message = (
            f"Auto-filled {len(blocks)} empty-gap program blocks from "
            f"{start.date().isoformat()} through {end.date().isoformat()}, "
            "preserving existing fixed programs; "
        )
        if hit_limit:
            message += (
                "the 10000-block safety limit was reached and filler covers "
                "the remaining time"
            )
        else:
            message += "the normal filler covers any short remainder"
        if advertising.enabled:
            ad_summary = f"Reserved {ad_slots} ad windows ({ad_reserved_seconds:g} seconds). "
            if not blocks and existing_programs:
                ad_warnings.append("This range is already filled. Use Clear Range, then Auto Fill + Ads to rebuild it with ad space; existing programs were preserved.")
            elif not ad_slots:
                ad_warnings.append("No ad window fits this range and its program lengths. Check the triggers, interval and break length.")
            if ad_warnings:
                message = " ".join(dict.fromkeys(ad_warnings)) + " " + ad_summary + message
            else:
                message = ad_summary + message

        result = {
            "ok": True,
            "message": message,
            "startUtc": start.isoformat(),
            "endUtc": end.isoformat(),
            "completeThroughUtc": cursor.isoformat(),
            "hitBlockLimit": hit_limit,
            "adSlotCount": ad_slots,
            "adReservedSeconds": ad_reserved_seconds,
            "adWarnings": list(dict.fromkeys(ad_warnings)),
            "blocks": blocks,
        }
        publish(range_seconds, range_seconds, "Auto Fill schedule ready")
        return result

    def _resolve_and_validate(
        self,
        definition: ChannelDefinition,
    ) -> ResolvedChannel:
        resolved = resolve_channel(definition, self.library)
        if definition.advertising.enabled and definition.advertising.setup_mode != "advanced" and not resolved.ad_media:
            raise BroadcasterError("No eligible ad clips are selected. Choose clips in the Ad Bin or turn ads off.")
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
            validation_store = self._detached_runtime_store(Path(temporary) / "runtime.db", definition.channel)
            validation_at = (definition.programming.calendar[0].start_utc
                             if definition.programming.mode == "calendar" and validation_store.load_channel(definition.channel) is None else None)
            validated_runtime = ChannelRuntime.open(resolved, validation_store, now=validation_at)
            try:
                validated_runtime.validate_schedule()
            except ChannelRuntimeError as exc:
                raise ChannelValidationError(str(exc)) from exc
            finally:
                if validated_runtime.break_store is not None:
                    validated_runtime.break_store.close()

        return resolved

    def _detached_runtime_store(self, path: Path, channel_number: int | None = None) -> RuntimeStore:
        if channel_number is not None:
            from .runtime_snapshot import channel_snapshot
            return channel_snapshot(self.runtime_database_path, path, channel_number)
        if Path(self.runtime_database_path).is_file():
            with closing(sqlite3.connect(Path(self.runtime_database_path).resolve().as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(path)) as target:
                    source.backup(target)
        return RuntimeStore(path)

    def preview(self, raw: dict[str, Any], limit: int = 8) -> dict[str, Any]:
        definition = self._configured_definition(raw)
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

        ad_preview: list[dict[str, Any]] = []
        broadcast_preview: list[dict[str, Any]] = []
        preview_diagnostics: dict[str, Any] = {}
        if definition.advertising.enabled and resolved.ad_media:
            with tempfile.TemporaryDirectory(
                prefix="channelos-ad-preview-"
            ) as temporary:
                now = datetime.now(timezone.utc)
                first_at = (
                    definition.programming.calendar[0].start_utc
                    if definition.programming.mode == "calendar"
                    else now
                )
                preview_store = self._detached_runtime_store(Path(temporary) / "runtime.sqlite")
                calendar_preview = definition.programming.mode == "calendar"
                if calendar_preview:
                    # A detached calendar preview shows the authored range,
                    # including historical dates. Live activation and immutable
                    # occurrence checks were verified by _resolve_and_validate.
                    with preview_store.connect() as connection:
                        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='ad_break_policy_state'").fetchone():
                            connection.execute("DELETE FROM ad_break_policy_state WHERE channel_number=?", (definition.channel,))
                runtime = ChannelRuntime.open(resolved, preview_store,
                    now=first_at if calendar_preview or preview_store.load_channel(definition.channel) is None else now,
                    transient=calendar_preview)
                try:
                    horizon = first_at + timedelta(seconds=min(7200.0, max(300.0,
                        sum(float(item.asset.duration_seconds or 0) for item in resolved.media[:max(1, int(limit))])
                        + definition.advertising.break_duration_seconds * max(1, int(limit)))))
                    media_by_id = {item.asset.asset_id: item for item in (*resolved.media, *resolved.ad_media)}
                    broadcast_preview = []
                    for event in runtime.events_between(first_at, horizon):
                        item = media_by_id.get(event.asset_id)
                        projection = {
                            "eventType": event.event_type, "assetId": event.asset_id,
                            "title": item.location.path.stem if item else "Transition",
                            "startUtc": event.start_utc.isoformat(), "endUtc": event.end_utc.isoformat(),
                            "sourceOffsetStart": event.source_offset_seconds,
                            "sourceOffsetEnd": event.source_offset_end_seconds,
                            "breakId": event.break_id or "", "parentProgramId": event.parent_program_id or "",
                        }
                        broadcast_preview.append(projection)
                        if event.event_type in {"advertisement", "transition"}:
                            ad_preview.append(projection)
                    preview_diagnostics = runtime.break_store.diagnostics(definition.channel) if runtime.break_store else {}
                finally:
                    if runtime.break_store is not None:
                        runtime.break_store.close()

        return {
            "ok": True,
            "channelNumber": definition.channel,
            "displayNumber": definition.display_number,
            "name": definition.name,
            "mode": definition.programming.mode,
            "resolvedCount": len(resolved.media),
            "items": items,
            "adPreview": ad_preview,
            "broadcastPreview": broadcast_preview,
            "adDiagnostics": preview_diagnostics,
        }

    def _managed_path_for(
        self,
        definition: ChannelDefinition,
    ) -> Path:
        return self._normalize_path(
            self.managed_directory
            / f"channel-{definition.channel:04d}.yaml"
        )

    def _atomic_write(self, path: Path, content: str) -> None:
        if self.library.portable:
            self.library.portable.check_available()
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
        definition = self._configured_definition(raw)
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

        assignment = self._catalog_assignment_for_editor(raw)
        previous_assignment = self.ad_catalog.get_assignment(definition.channel)
        self._before_mutation_commit(definition)
        try:
            self._atomic_write(target, serialize_channel(definition, portable=self.library.portable))
            if assignment is not None and definition.advertising.setup_mode == "advanced":
                self.ad_catalog.assign_channel(assignment)
            self.refresh()
        except Exception:
            target.unlink(missing_ok=True)
            if previous_assignment is not None:
                self.ad_catalog.assign_channel(previous_assignment)
            else:
                self.ad_catalog.clear_channel_assignment(definition.channel)
            self.refresh()
            raise
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

        definition = self._configured_definition(raw)

        # Renumbering is intentionally not an in-place edit. It changes
        # television identity/continuity and will get its own explicit flow.
        if definition.channel != original_number:
            raise ChannelConflictError(
                "renumbering an existing channel is not an in-place edit. "
                "Create the new channel explicitly so ChannelOS cannot "
                "accidentally overwrite another station or continuity state."
            )

        return self._save_existing(existing, definition, self._catalog_assignment_for_editor(raw))

    def add_library_item(self, channel_number: int, asset_id: str, path: str) -> ChannelSaveResult:
        """Add a source without reconstructing the channel from a summary view."""
        try:
            existing = self._records[int(channel_number)]
        except KeyError as exc:
            raise ChannelNotFoundError("That channel is no longer in the lineup") from exc
        target, key = normalize_path(path)
        if not any(item.asset.asset_id == asset_id and normalize_path(item.location.path)[1] == key
                   for item in self.library.list_online_media()) or not Path(target).is_file():
            raise BroadcasterError("The selected Library item is no longer available")
        definition = existing.definition
        for source in definition.sources:
            source_key = normalize_path(source.path)[1]
            if key == source_key or key.startswith(source_key + os.sep):
                return ChannelSaveResult(existing)
        return self._save_existing(existing, replace(
            definition, sources=(*definition.sources, SourceDefinition(Path(target)))
        ))

    def _save_existing(self, existing: ChannelRecord, definition: ChannelDefinition,
                       assignment: ChannelAdAssignment | None = None) -> ChannelSaveResult:
        self._resolve_and_validate(definition)
        if not existing.path.exists():
            raise ChannelNotFoundError(
                f"cannot edit Channel {definition.display_number}; "
                f"{existing.path} no longer exists"
            )
        if load_channel(existing.path) != existing.definition:
            raise ChannelConflictError("The channel changed on disk. Refresh it before saving.")

        backup = existing.path.with_suffix(
            existing.path.suffix + ".bak"
        )
        self._before_mutation_commit(definition)
        shutil.copy2(existing.path, backup)
        previous_assignment = self.ad_catalog.get_assignment(definition.channel)
        try:
            self._atomic_write(existing.path, serialize_channel(definition, portable=self.library.portable))
            if assignment is not None and definition.advertising.setup_mode == "advanced":
                self.ad_catalog.assign_channel(assignment)
            self.refresh()
        except Exception:
            self._atomic_write(existing.path, backup.read_text(encoding="utf-8"))
            if previous_assignment is not None:
                self.ad_catalog.assign_channel(previous_assignment)
            else:
                self.ad_catalog.clear_channel_assignment(definition.channel)
            self.refresh()
            raise

        return ChannelSaveResult(
            record=self._records[definition.channel],
            backup_path=backup,
        )

    def delete(self, channel_number: int) -> ChannelDeleteResult:
        """Remove one managed definition while retaining a recovery backup."""

        if self.library.portable:
            self.library.portable.check_available()

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

        # Unavailable media does not prevent management of saved definitions.

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

        assignment = self.ad_catalog.get_assignment(number)
        self._before_mutation_commit()
        identity = uuid.uuid4().hex
        operation = {"channel": number, "archive_id": identity, "original": str(existing.path),
                     "backup": str(backup), "runtime_database": str(self.runtime_database_path),
                     "assignment": asdict(assignment) if assignment else None}
        journal = self._deletion_journal(operation)
        try:
            os.replace(existing.path, backup)
            self._finish_deletion(journal)
            self.refresh()
        except Exception:
            operation["restore"] = True
            self._finish_deletion(self._deletion_journal(operation))
            self.refresh()
            raise

        return ChannelDeleteResult(
            record=existing,
            backup_path=backup,
            replacement_channel_number=replacement_channel_number,
            archive_id=identity,
            assignment=assignment,
        )

    def restore_deleted(self, result: ChannelDeleteResult) -> None:
        """Roll back an uncommitted lineup deletion from its recovery file."""

        if self.library.portable:
            self.library.portable.check_available()

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
        if result.archive_id:
            operation = {"channel": result.record.channel_number, "archive_id": result.archive_id,
                         "original": str(original), "backup": str(backup),
                         "runtime_database": str(self.runtime_database_path), "restore": True,
                         "assignment": asdict(result.assignment) if result.assignment else None}
            self._finish_deletion(self._deletion_journal(operation))
        else:
            os.replace(backup, original)
        self.refresh()
