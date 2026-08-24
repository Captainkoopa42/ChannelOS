from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .library import MediaLibrary
from .loader import load_channel
from .models import ChannelDefinition, ChannelValidationError
from .resolve import ResolvedChannel, resolve_channel
from .runtime import (
    ChannelRuntime,
    ChannelRuntimeError,
    RuntimeStore,
    deterministic_shuffle_order,
)


class BroadcasterError(RuntimeError):
    """Base error for user-facing channel management."""


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


def channel_to_mapping(definition: ChannelDefinition) -> dict[str, Any]:
    """Serialize the public 0.1 channel contract without runtime-only state."""

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
    mapping["presentation"] = {
        "number_width": definition.presentation.number_width,
    }
    return mapping


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

    mapping = {
        "schema_version": "0.1",
        "channel": _coerce_int(raw.get("channel"), "channel"),
        "name": str(raw.get("name", "")),
        "description": str(raw.get("description", "")).strip() or None,
        "sources": sources,
        "programming": {
            "mode": str(raw.get("mode", "sequential")).strip().lower(),
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
        else:
            ordered = resolved.media

        items: list[dict[str, Any]] = []
        for media in ordered[: max(1, int(limit))]:
            items.append(
                {
                    "assetId": media.asset.asset_id,
                    "title": media.location.path.stem,
                    "path": str(media.location.path),
                    "durationSeconds": float(
                        media.asset.duration_seconds or 0.0
                    ),
                }
            )

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
