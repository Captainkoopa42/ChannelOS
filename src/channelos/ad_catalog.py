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
from .portable import PortableConnection, decode_tree, find_setup, path_tree


class AdCatalogValidationError(ValueError):
    pass


class AssetLibrary(Protocol):
    def online_locations_for_assets(self, asset_ids: Any) -> dict[str, list[Any]]: ...


@dataclass(frozen=True, slots=True)
class AdCollection:
    collection_id: str
    name: str
    asset_ids: tuple[str, ...]
    source_paths: tuple[str, ...] = ()
    excluded_asset_ids: tuple[str, ...] = ()
    membership: str = "fixed"

    def __post_init__(self) -> None:
        if not self.collection_id.strip() or not self.name.strip():
            raise AdCatalogValidationError("collection ID and name are required")
        if self.membership not in {"fixed", "dynamic"}:
            raise AdCatalogValidationError("membership must be fixed or dynamic")
        if not self.asset_ids and not (
            self.membership == "dynamic" and self.source_paths
        ):
            raise AdCatalogValidationError("an ad collection must contain at least one asset or dynamic source")
        if any(not value.strip() for value in self.asset_ids):
            raise AdCatalogValidationError("asset IDs cannot be empty")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise AdCatalogValidationError("duplicate asset IDs are not allowed")
        if any(not path.strip() for path in self.source_paths):
            raise AdCatalogValidationError("ad source paths cannot be empty")
        if len(set(self.source_paths)) != len(self.source_paths):
            raise AdCatalogValidationError("duplicate ad source paths are not allowed")
        if len(set(self.excluded_asset_ids)) != len(self.excluded_asset_ids):
            raise AdCatalogValidationError("duplicate excluded asset IDs are not allowed")
        if self.membership == "fixed" and self.source_paths:
            raise AdCatalogValidationError("fixed collections cannot specify dynamic source paths")


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
            "transition_seconds", "slot_seconds", "schedule_priority", "expand_source",
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
        valid_triggers = {"breakpoint", "interval", "between_programs", "calendar_boundary", "fixed_slot"}
        if triggers is not None and (
            not isinstance(triggers, (list, tuple)) or not set(triggers) <= valid_triggers
        ):
            raise AdCatalogValidationError("profile contains an unsupported trigger")
        if self.defaults.get("transition_behavior", "cut") not in {"cut", "fade", "hold"}:
            raise AdCatalogValidationError("unsupported transition behavior")
        # Use the channel schema to validate every effective portable field.
        normalized = dict(self.defaults)
        normalized["selection_strategy"] = normalized.pop("strategy", "best_fit")
        normalized["break_duration_seconds"] = normalized.pop("duration_seconds", 120)
        normalized["sources"] = [{"path": "."}]
        try:
            ChannelDefinition.from_mapping({
                "schema_version": "0.5", "channel": 1, "name": "Validation",
                "sources": [{"path": "."}], "programming": {"mode": "sequential"},
                "advertising": normalized,
            })
        except ValueError as exc:
            raise AdCatalogValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AdPlacementAssignment:
    placement_id: str
    trigger: str
    collection_id: str | None = None
    profile_id: str | None = None
    overrides: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.placement_id.strip() or self.trigger not in {
            "breakpoint", "interval", "between_programs", "calendar_boundary", "fixed_slot"
        }:
            raise AdCatalogValidationError("placement requires an ID and supported trigger")
        BreakProfile("validation", "Validation", self.overrides)


@dataclass(frozen=True, slots=True)
class ChannelAdAssignment:
    channel_number: int
    collection_id: str | None = None
    profile_id: str | None = None
    overrides: Mapping[str, Any] = field(default_factory=dict)
    placements: tuple[AdPlacementAssignment, ...] = ()

    def __post_init__(self) -> None:
        if self.channel_number < 1:
            raise AdCatalogValidationError("channel number must be positive")
        allowed = {
            "enabled", "interval_seconds", "breakpoints_seconds", "duration_seconds",
            "priority", "strategy", "timing_policy", "smoosh_minimum_seconds",
            "smoosh_max_trim_seconds", "expand_max_seconds", "transition_behavior",
            "triggers",
            "transition_seconds", "slot_seconds", "schedule_priority", "expand_source",
        }
        unknown = set(self.overrides) - allowed
        if unknown:
            raise AdCatalogValidationError("unknown channel overrides: " + ", ".join(sorted(unknown)))
        if len({item.placement_id for item in self.placements}) != len(self.placements):
            raise AdCatalogValidationError("duplicate placement IDs")


@dataclass(frozen=True, slots=True)
class ResolvedAdAssignment:
    collection: AdCollection | None
    profile: BreakProfile | None
    settings: Mapping[str, Any]
    ad_media: tuple[Any, ...]


class _CatalogConnection(PortableConnection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class AdCatalogStore:
    """SQLite-backed collections, profiles, and per-channel assignments."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self.portable = find_setup(database)
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
            columns = {row[1] for row in db.execute("PRAGMA table_info(channel_ad_assignments)")}
            if "placements_json" not in columns:
                db.execute("ALTER TABLE channel_ad_assignments ADD COLUMN placements_json TEXT NOT NULL DEFAULT '[]'")

    def _connect(self) -> sqlite3.Connection:
        if self.portable:
            self.portable.check_available()
        db = sqlite3.connect(self.database, factory=_CatalogConnection)
        db.portable = self.portable
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _dump(self, value, **kwargs):
        return json.dumps(path_tree(value, self.portable.encode) if self.portable else value, **kwargs)

    def _load(self, value):
        return decode_tree(json.loads(value), self.portable)

    def save_collection(self, item: AdCollection) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO ad_collections VALUES (?, ?, ?)
                ON CONFLICT(collection_id) DO UPDATE SET
                name=excluded.name, asset_ids_json=excluded.asset_ids_json""",
                (item.collection_id, item.name, self._dump({
                    "asset_ids": item.asset_ids,
                    "source_paths": item.source_paths,
                    "excluded_asset_ids": item.excluded_asset_ids,
                    "membership": item.membership,
                }, sort_keys=True)))

    def get_collection(self, collection_id: str) -> AdCollection | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM ad_collections WHERE collection_id=?", (collection_id,)).fetchone()
        if row is None:
            return None
        payload = self._load(row["asset_ids_json"])
        # Old catalog rows were plain JSON lists; load them without migration.
        if isinstance(payload, list):
            return AdCollection(row["collection_id"], row["name"], tuple(payload))
        return AdCollection(
            row["collection_id"], row["name"], tuple(payload.get("asset_ids", ())),
            tuple(payload.get("source_paths", ())),
            tuple(payload.get("excluded_asset_ids", ())),
            payload.get("membership", "fixed"),
        )

    def save_profile(self, item: BreakProfile) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO ad_break_profiles VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                name=excluded.name, defaults_json=excluded.defaults_json""",
                (item.profile_id, item.name, self._dump(dict(item.defaults), sort_keys=True)))

    def get_profile(self, profile_id: str) -> BreakProfile | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM ad_break_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        return None if row is None else BreakProfile(row["profile_id"], row["name"], self._load(row["defaults_json"]))

    def list_collections(self) -> tuple[AdCollection, ...]:
        with self._connect() as db:
            ids = [
                row[0] for row in db.execute(
                    "SELECT collection_id FROM ad_collections ORDER BY name, collection_id"
                )
            ]
        return tuple(
            item for collection_id in ids
            if (item := self.get_collection(collection_id)) is not None
        )

    def list_profiles(self) -> tuple[BreakProfile, ...]:
        with self._connect() as db:
            ids = [
                row[0] for row in db.execute(
                    "SELECT profile_id FROM ad_break_profiles ORDER BY name, profile_id"
                )
            ]
        return tuple(
            item for profile_id in ids
            if (item := self.get_profile(profile_id)) is not None
        )

    def list_assignments(self) -> tuple[ChannelAdAssignment, ...]:
        with self._connect() as db:
            numbers = [
                row[0] for row in db.execute(
                    "SELECT channel_number FROM channel_ad_assignments ORDER BY channel_number"
                )
            ]
        return tuple(
            item for number in numbers
            if (item := self.get_assignment(number)) is not None
        )

    def assign_channel(self, item: ChannelAdAssignment) -> None:
        from dataclasses import asdict
        with self._connect() as db:
            references = [
                ("ad_collections", "collection_id", item.collection_id),
                ("ad_break_profiles", "profile_id", item.profile_id),
            ]
            for placement in item.placements:
                references.extend([
                    ("ad_collections", "collection_id", placement.collection_id),
                    ("ad_break_profiles", "profile_id", placement.profile_id),
                ])
            for table, key, value in references:
                if value and not db.execute(f"SELECT 1 FROM {table} WHERE {key}=?", (value,)).fetchone():
                    raise AdCatalogValidationError(f"unknown {key.replace('_', ' ')}: {value}")
            db.execute("""INSERT INTO channel_ad_assignments VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel_number) DO UPDATE SET
                collection_id=excluded.collection_id, profile_id=excluded.profile_id,
                overrides_json=excluded.overrides_json, placements_json=excluded.placements_json""",
                (item.channel_number, item.collection_id, item.profile_id,
                 self._dump(dict(item.overrides), sort_keys=True),
                 self._dump([asdict(p) for p in item.placements], sort_keys=True)))

    def get_assignment(self, channel_number: int) -> ChannelAdAssignment | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM channel_ad_assignments WHERE channel_number=?", (channel_number,)).fetchone()
        return None if row is None else ChannelAdAssignment(
            row["channel_number"], row["collection_id"], row["profile_id"], self._load(row["overrides_json"]),
            tuple(AdPlacementAssignment(**item) for item in self._load(row["placements_json"])))

    def resolve_channel(self, channel_number: int, library: AssetLibrary, *,
                        legacy_settings: Mapping[str, Any] | None = None,
                        explicitly_enabled: bool = False) -> ResolvedAdAssignment:
        assignment = self.get_assignment(channel_number)
        if assignment is None:
            return ResolvedAdAssignment(None, None, dict(legacy_settings or {"enabled": False}), ())
        return self.resolve_assignment(assignment, library, explicitly_enabled=explicitly_enabled)

    def resolve_assignment(self, assignment: ChannelAdAssignment, library: AssetLibrary, *,
                           explicitly_enabled: bool = False) -> ResolvedAdAssignment:
        channel_number = assignment.channel_number
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
            ids = list(collection.asset_ids)
            if collection.membership == "dynamic":
                seen = set(ids)
                for root in collection.source_paths:
                    for item in library.list_online_media_for_source(root):
                        if item.asset.asset_id not in seen:
                            seen.add(item.asset.asset_id)
                            ids.append(item.asset.asset_id)
            ids = [
                asset_id for asset_id in ids
                if asset_id not in collection.excluded_asset_ids
            ]
            if not ids:
                raise AdCatalogValidationError(
                    "advertising collection has no eligible online media"
                )
            online = library.online_locations_for_assets(ids)
            missing = [asset_id for asset_id in ids if not online.get(asset_id)]
            if missing:
                raise AdCatalogValidationError(
                    "collection contains missing or offline library assets: " + ", ".join(missing))
            media = tuple(online[asset_id][0] for asset_id in ids)
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
    requested = tuple(location.asset_id for location in assignment.ad_media)
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
    *, enabled_override: bool | None = None,
) -> ChannelDefinition:
    """Embed the assigned catalog and effective profile into a portable v0.5 YAML.

    The catalog remains an authoring aid, not a runtime dependency. Once
    serialized, all required canonical media IDs and policy defaults travel
    with the channel. Unassigned channels are left unchanged.
    """
    assignment = store.get_assignment(channel.channel)
    if assignment is None:
        return channel
    effective_assignment = replace(assignment, overrides={**assignment.overrides, "enabled": enabled_override}) if enabled_override is not None else assignment
    resolved = store.resolve_assignment(
        effective_assignment, library, explicitly_enabled=channel.advertising.enabled,
    )
    settings = dict(resolved.settings)
    if enabled_override is not None:
        settings["enabled"] = enabled_override
    enabled = settings.get("enabled", False)
    if not isinstance(enabled, bool):
        raise AdCatalogValidationError("advertising.enabled must be boolean")
    collection = resolved.collection
    if enabled and collection is None and not channel.advertising.sources and not assignment.placements:
        raise AdCatalogValidationError(
            "an enabled catalog assignment needs a collection or legacy ad source"
        )
    options = {
        "enabled": enabled,
        "asset_ids": (
            tuple(location.asset_id for location in resolved.ad_media)
            if collection and enabled else (channel.advertising.asset_ids or (collection.asset_ids if collection else ()))
        ),
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
        "transition_seconds": settings.get("transition_seconds", 0.5),
        "slot_seconds": settings.get("slot_seconds"),
        "schedule_priority": settings.get("schedule_priority", "program"),
        "expand_source": settings.get("expand_source", "schedule_shift"),
    }
    from .models import AdPlacementDefinition, SourceDefinition
    if collection:
        options.update(
            sources=tuple(SourceDefinition(Path(path)) for path in collection.source_paths),
            collection_membership=collection.membership,
            excluded_asset_ids=collection.excluded_asset_ids,
        )
    placements = []
    for item in assignment.placements:
        defaults = dict(settings)
        if item.profile_id:
            profile = store.get_profile(item.profile_id)
            if profile is None:
                raise AdCatalogValidationError(f"missing profile {item.profile_id}")
            defaults.update(profile.defaults)
        defaults.update(item.overrides)
        defaults["enabled"] = bool(enabled and defaults.get("enabled", True))
        defaults["triggers"] = [item.trigger]
        effective = store.resolve_assignment(ChannelAdAssignment(
            channel.channel, item.collection_id or assignment.collection_id,
            None, defaults,
        ), library, explicitly_enabled=enabled)
        leaf = dict(options)
        aliases = {"strategy": "selection_strategy", "duration_seconds": "break_duration_seconds"}
        leaf.update({aliases.get(key, key): value for key, value in defaults.items()})
        leaf.update(
            asset_ids=(tuple(location.asset_id for location in effective.ad_media)
                       or next((p.policy.asset_ids for p in channel.advertising.placements
                                if p.placement_id == item.placement_id), ())
                       or (effective.collection.asset_ids if effective.collection else ())),
            collection_id=item.collection_id or assignment.collection_id,
            profile_id=item.profile_id or assignment.profile_id,
            sources=(), placements=(), triggers=(item.trigger,),
            collection_membership=effective.collection.membership if effective.collection else "fixed",
            excluded_asset_ids=effective.collection.excluded_asset_ids if effective.collection else (),
            breakpoints_seconds=tuple(defaults.get("breakpoints_seconds", ())),
        )
        if effective.collection and effective.collection.membership == "dynamic":
            leaf["sources"] = tuple(SourceDefinition(Path(path)) for path in effective.collection.source_paths)
        placements.append(AdPlacementDefinition(item.placement_id, item.trigger,
                                               replace(channel.advertising, **leaf)))
    options["placements"] = tuple(placements)
    return replace(
        channel,
        schema_version="0.5",
        advertising=replace(channel.advertising, **options),
    )
