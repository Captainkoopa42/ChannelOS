from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .library import IndexedMedia, MediaLibrary, normalize_path
from .models import ChannelDefinition


class ChannelResolutionError(RuntimeError):
    """Raised when a channel cannot resolve any indexed playable media."""


@dataclass(frozen=True, slots=True)
class ResolvedChannel:
    definition: ChannelDefinition
    media: tuple[IndexedMedia, ...]

    @property
    def first(self) -> IndexedMedia:
        if not self.media:
            raise ChannelResolutionError(
                f"Channel {self.definition.display_number} — {self.definition.name} has no indexed media"
            )
        return self.media[0]


def _path_is_within(candidate_key: str, source_key: str) -> bool:
    if candidate_key == source_key:
        return True
    boundary = source_key.rstrip("/\\") + os.sep
    return candidate_key.startswith(boundary)


_NATURAL_PART_RE = re.compile(r"(\d+)")
_SEASON_EPISODE_RE = re.compile(
    r"(?:^|[\s._-])s(\d{1,3})[\s._-]*e(\d{1,4})(?:\D|$)",
    re.IGNORECASE,
)
_X_EPISODE_RE = re.compile(
    r"(?:^|[\s._-])(\d{1,3})x(\d{1,4})(?:\D|$)",
    re.IGNORECASE,
)
_EPISODE_WORD_RE = re.compile(
    r"(?:^|[\s._-])(?:ep|episode)[\s._-]*(\d{1,4})(?:\D|$)",
    re.IGNORECASE,
)
_LEADING_ORDINAL_RE = re.compile(r"^\s*(\d{1,5})(?:[\s._-]|$)")
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _natural_key(value: str) -> tuple[tuple[int, object], ...]:
    """Case-insensitive natural ordering that keeps numeric runs numeric."""

    parts: list[tuple[int, object]] = []
    for part in _NATURAL_PART_RE.split(value.casefold()):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts)


def _relative_sequence_text(candidate_key: str, source_key: str) -> str:
    """Return a deterministic source-relative path string."""

    if candidate_key == source_key:
        return os.path.basename(candidate_key)

    boundary = source_key.rstrip("/\\") + os.sep
    if candidate_key.startswith(boundary):
        return candidate_key[len(boundary) :]
    return candidate_key


def _semantic_sequence_key(relative_path: str) -> tuple[object, ...]:
    """Order common owned-media names like a human-authored series.

    Priority is intentionally conservative and explainable:
    1. explicit season/episode markers (S01E02 or 1x02),
    2. explicit episode labels (Episode 2 / Ep 2),
    3. leading numeric ordinals (01 - Title),
    4. release-year-like tokens,
    5. natural path order.

    The final natural-path component is always present as a deterministic
    tie-breaker. This requires no cloud metadata and never renames user files.
    """

    basename = os.path.basename(relative_path)
    stem, _ = os.path.splitext(basename)
    natural = _natural_key(relative_path)

    match = _SEASON_EPISODE_RE.search(stem)
    if match:
        return (0, int(match.group(1)), int(match.group(2)), natural)

    match = _X_EPISODE_RE.search(stem)
    if match:
        return (0, int(match.group(1)), int(match.group(2)), natural)

    match = _EPISODE_WORD_RE.search(stem)
    if match:
        return (1, int(match.group(1)), natural)

    match = _LEADING_ORDINAL_RE.search(stem)
    if match:
        return (2, int(match.group(1)), natural)

    years = [int(value) for value in _YEAR_RE.findall(stem)]
    if years:
        # Prefer the earliest year-like token. In common release filenames this
        # keeps an original release year ahead of a later remaster/encode year.
        return (3, min(years), natural)

    return (4, natural)


def _resolve_preserved_sequence(
    channel: ChannelDefinition,
    indexed: list[IndexedMedia],
    source_keys: list[str],
) -> tuple[IndexedMedia, ...]:
    """Respect channel source declaration order plus media-aware local order."""

    candidates: list[tuple[int, tuple[object, ...], str, IndexedMedia]] = []

    for item in indexed:
        match: tuple[int, str] | None = None
        for source_index, source_key in enumerate(source_keys):
            if _path_is_within(item.location.path_key, source_key):
                match = (source_index, source_key)
                break

        if match is None:
            continue

        source_index, source_key = match
        relative = _relative_sequence_text(item.location.path_key, source_key)
        candidates.append(
            (
                source_index,
                _semantic_sequence_key(relative),
                item.location.path_key,
                item,
            )
        )

    candidates.sort(key=lambda entry: (entry[0], entry[1], entry[2]))

    selected: list[IndexedMedia] = []
    seen_assets: set[str] = set()
    for _, _, _, item in candidates:
        if item.asset.asset_id in seen_assets:
            continue
        selected.append(item)
        seen_assets.add(item.asset.asset_id)

    return tuple(selected)


def resolve_channel(channel: ChannelDefinition, library: MediaLibrary) -> ResolvedChannel:
    source_keys = [normalize_path(source.path)[1] for source in channel.sources]
    indexed: list[IndexedMedia] = []
    seen_locations: set[str] = set()
    for source in channel.sources:
        for item in library.list_online_media_for_source(source.path):
            if item.location.path_key in seen_locations:
                continue
            seen_locations.add(item.location.path_key)
            indexed.append(item)

    if (
        channel.programming.mode == "sequential"
        and channel.programming.preserve_episode_order
    ):
        media = _resolve_preserved_sequence(channel, indexed, source_keys)
        return ResolvedChannel(definition=channel, media=media)

    # Compatibility/default behavior: resolve from the canonical library's
    # stable path ordering. Shuffle later derives its own deterministic order.
    selected: list[IndexedMedia] = []
    seen_assets: set[str] = set()
    for item in indexed:
        if item.asset.asset_id in seen_assets:
            continue
        if any(
            _path_is_within(item.location.path_key, source_key)
            for source_key in source_keys
        ):
            selected.append(item)
            seen_assets.add(item.asset.asset_id)

    selected.sort(key=lambda item: item.location.path_key)
    return ResolvedChannel(definition=channel, media=tuple(selected))
