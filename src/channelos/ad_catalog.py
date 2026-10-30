from __future__ import annotations

"""Persistent ad catalogs, reusable break profiles, and channel assignments.

Collections store canonical media asset IDs, never paths. Resolution is always
performed against MediaLibrary so offline assets cannot silently be substituted.
"""

import json
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Protocol

from .ad_break_engine import BreakPolicy
from .library import IndexedMedia, MediaLibrary
from .models import ChannelDefinition


class AdCatalogValidationError(ValueError):
    pass


class AssetLibrary(Protocol):
    def online_locations_for_assets(self, asset_ids: Any) -> dict[str, list[Any]]: ...


@dataclass(frozen=True, slots=True)
class AdCollection:
    collection_id: str
    name: str
    asset_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.collection_id.strip() or not self.name.strip():
            raise AdCatalogValidationError("collection ID and name are required")
        if not self.asset_ids:
            raise AdCatalogValidationError("an ad collection must contain at least one asset")
        if any(not value.strip() for value in self.asset_ids):
            raise AdCatalogValidationError("asset IDs cannot be empty")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise AdCatalogValidationError("duplicate asset IDs are not allowed")


@dataclass(frozen=True, slots=True)
class BreakProfile:
    profile_id: str
    name: str
    defaults: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.name.strip():
            raise AdCatalogValidationError("profile ID and name are required")
        allowed = {
            "enabled", "interval_seconds", "breakpoints_seconds", "duration_seconds",
            "priority", "strategy", "timing_policy", "smoosh_minimum_seconds",
            "smoosh_max_trim_seconds", "expand_max_seconds", "transition_behavior",
            "triggers",
        }
        unknown = set(self.defaults) - allowed
        if unknown:
            raise AdCatalogValidationError("unknown profile settings: " + ", ".join(sorted(unknown)))
        policy = {key: value for key, value in self.defaults.items() if key in {
            "enabled", "interval_seconds", "breakpoints_seconds", "duration_seconds",
            "priority", "strategy", "timing_policy", "smoosh_minimum_seconds",
            "smoosh_max_trim_seconds", "expand_max_seconds",
        }}
        try:
            BreakPolicy(**policy)
        except (TypeError, ValueError) as exc:
            raise AdCatalogValidationError(f"invalid break profile: {exc}") from exc
        triggers = self.defaults.get("triggers")
        valid_triggers = {"breakpoint", "interval", "between_programs", "calendar_boundary"}
        if triggers is not None and (
            not isinstance(triggers, (list, tuple)) or not set(triggers) <= valid_triggers
        ):
            raise AdCatalogValidationError("profile contains an unsupported trigger")
        if self.defaults.get("transition_behavior", "cut") not in {"cut", "fade", "hold"}:
            raise AdCatalogValidationError("unsupported transition behavior")


@dataclass(frozen=True, slots=True)
class ChannelAdAssignment:
    channel_number: int
    collection_id: str | None = None
    profile_id: str | None = None
    overrides: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.channel_number < 1:
            raise AdCatalogValidationError("channel number must be positive")
        allowed = {
            "enabled", "interval_seconds", "breakpoints_seconds", "duration_seconds",
            "priority", "strategy", "timing_policy", "smoosh_minimum_seconds",
            "smoosh_max_trim_seconds", "expand_max_seconds", "transition_behavior",
            "triggers",
        }
        unknown = set(self.overrides) - allowed
        if unknown:
            raise AdCatalogValidationError("unknown channel overrides: " + ", ".join(sorted(unknown)))


@dataclass(frozen=True, slots=True)
class ResolvedAdAssignment:
    collection: AdCollection | None
    profile: BreakProfile | None
    settings: Mapping[str, Any]
    ad_media: tuple[Any, ...]


class AdCatalogStore:
    """SQLite-backed collections, profiles, and per-channel assignments."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ad_collections (
                    collection_id TEXT PRIMARY KEY, name TEXT NOT NULL, asset_ids_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ad_break_profiles (
                    profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, defaults_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channel_ad_assignments (
                    channel_number INTEGER PRIMARY KEY,
                    collection_id TEXT REFERENCES ad_collections(collection_id),
                    profile_id TEXT REFERENCES ad_break_profiles(profile_id),
                    overrides_json TEXT NOT NULL DEFAULT '{}'
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def save_collection(self, item: AdCollection) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO ad_collections VALUES (?, ?, ?)
                ON CONFLICT(collection_id) DO UPDATE SET
                name=excluded.name, asset_ids_json=excluded.asset_ids_json""",
                (item.collection_id, item.name, json.dumps(item.asset_ids)))

    def get_collection(self, collection_id: str) -> AdCollection | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM ad_collections WHERE collection_id=?", (collection_id,)).fetchone()
        return None if row is None else AdCollection(row["collection_id"], row["name"], tuple(json.loads(row["asset_ids_json"])))

    def save_profile(self, item: BreakProfile) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO ad_break_profiles VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                name=excluded.name, defaults_json=excluded.defaults_json""",
                (item.profile_id, item.name, json.dumps(dict(item.defaults), sort_keys=True)))

    def get_profile(self, profile_id: str) -> BreakProfile | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM ad_break_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        return None if row is None else BreakProfile(row["profile_id"], row["name"], json.loads(row["defaults_json"]))

    def assign_channel(self, item: ChannelAdAssignment) -> None:
        with self._connect() as db:
            for table, key, value in (
                ("ad_collections", "collection_id", item.collection_id),
                ("ad_break_profiles", "profile_id", item.profile_id),
            ):
                if value and not db.execute(f"SELECT 1 FROM {table} WHERE {key}=?", (value,)).fetchone():
                    raise AdCatalogValidationError(f"unknown {key.replace('_', ' ')}: {value}")
            db.execute("""INSERT INTO channel_ad_assignments VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_number) DO UPDATE SET
                collection_id=excluded.collection_id, profile_id=excluded.profile_id,
                overrides_json=excluded.overrides_json""",
                (item.channel_number, item.collection_id, item.profile_id, json.dumps(dict(item.overrides), sort_keys=True)))

    def get_assignment(self, channel_number: int) -> ChannelAdAssignment | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM channel_ad_assignments WHERE channel_number=?", (channel_number,)).fetchone()
        return None if row is None else ChannelAdAssignment(
            row["channel_number"], row["collection_id"], row["profile_id"], json.loads(row["overrides_json"]))

    def resolve_channel(self, channel_number: int, library: AssetLibrary, *,
                        legacy_settings: Mapping[str, Any] | None = None,
                        explicitly_enabled: bool = False) -> ResolvedAdAssignment:
        assignment = self.get_assignment(channel_number)
        if assignment is None:
            return ResolvedAdAssignment(None, None, dict(legacy_settings or {"enabled": False}), ())
        collection = self.get_collection(assignment.collection_id) if assignment.collection_id else None
        profile = self.get_profile(assignment.profile_id) if assignment.profile_id else None
        if assignment.collection_id and collection is None:
            raise AdCatalogValidationError(f"channel {channel_number} references missing collection {assignment.collection_id}")
        if assignment.profile_id and profile is None:
            raise AdCatalogValidationError(f"channel {channel_number} references missing profile {assignment.profile_id}")
        settings = dict(profile.defaults) if profile else {}
        settings.update(assignment.overrides)
        settings.setdefault("enabled", bool(explicitly_enabled))
        # Validate inherited defaults *after* overrides, so an invalid
        # channel-specific policy never slips into the portable snapshot.
        BreakProfile("resolved", "Resolved", settings)
        media: tuple[Any, ...] = ()
        if settings["enabled"] and collection:
            online = library.online_locations_for_assets(collection.asset_ids)
            missing = [asset_id for asset_id in collection.asset_ids if not online.get(asset_id)]
            if missing:
                raise AdCatalogValidationError(
                    "collection contains missing or offline library assets: " + ", ".join(missing))
            media = tuple(online[asset_id][0] for asset_id in collection.asset_ids)
        return ResolvedAdAssignment(collection, profile, settings, media)


def resolve_indexed_ad_media(
    assignment: ResolvedAdAssignment,
    library: MediaLibrary,
) -> tuple[IndexedMedia, ...]:
    """Resolve canonical collection membership into playable indexed media.

    MediaLocation alone is not playable: the broadcast engine needs the
    associated asset metadata, including duration. Keep collection order and
    never add advertisements to the normal program/filler candidate pool.
    """
    if not assignment.settings.get("enabled") or assignment.collection is None:
        return ()
    requested = assignment.collection.asset_ids
    indexed = {item.asset.asset_id: item for item in library.list_online_media()}
    missing = [asset_id for asset_id in requested if asset_id not in indexed]
    if missing:
        raise AdCatalogValidationError(
            "collection contains missing or offline library assets: " + ", ".join(missing)
        )
    return tuple(indexed[asset_id] for asset_id in requested)


def export_portable_channel(
    channel: ChannelDefinition,
    store: AdCatalogStore,
    library: MediaLibrary,
) -> ChannelDefinition:
    """Embed the assigned catalog and effective profile into a portable v0.5 YAML.

    The catalog remains an authoring aid, not a runtime dependency. Once
    serialized, all required canonical media IDs and policy defaults travel
    with the channel. Unassigned channels are left unchanged.
    """
    assignment = store.get_assignment(channel.channel)
    if assignment is None:
        return channel
    resolved = store.resolve_channel(
        channel.channel, library,
        explicitly_enabled=channel.advertising.enabled,
    )
    settings = resolved.settings
    enabled = settings.get("enabled", False)
    if not isinstance(enabled, bool):
        raise AdCatalogValidationError("advertising.enabled must be boolean")
    collection = resolved.collection
    if enabled and collection is None and not channel.advertising.sources:
        raise AdCatalogValidationError(
            "an enabled catalog assignment needs a collection or legacy ad source"
        )
    options = {
        "enabled": enabled,
        "asset_ids": collection.asset_ids if collection else (),
        "collection_id": assignment.collection_id,
        "profile_id": assignment.profile_id,
        "selection_strategy": settings.get("strategy", channel.advertising.selection_strategy),
        "breakpoints_seconds": tuple(settings.get(
            "breakpoints_seconds", channel.advertising.breakpoints_seconds)),
        "interval_seconds": settings.get("interval_seconds", channel.advertising.interval_seconds),
        "break_duration_seconds": settings.get("duration_seconds", channel.advertising.break_duration_seconds),
        "priority": settings.get("priority", channel.advertising.priority),
        "timing_policy": settings.get("timing_policy", "strict_fit"),
        "smoosh_minimum_seconds": settings.get("smoosh_minimum_seconds", 5.0),
        "smoosh_max_trim_seconds": settings.get("smoosh_max_trim_seconds", 15.0),
        "expand_max_seconds": settings.get("expand_max_seconds", 0.0),
        "triggers": tuple(settings.get(
            "triggers", ("breakpoint", "interval", "between_programs", "calendar_boundary"))),
        "transition_behavior": settings.get("transition_behavior", "cut"),
    }
    return replace(
        channel,
        schema_version="0.5",
        advertising=replace(channel.advertising, **options),
    )
