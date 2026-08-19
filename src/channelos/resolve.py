from __future__ import annotations

import os
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


def resolve_channel(channel: ChannelDefinition, library: MediaLibrary) -> ResolvedChannel:
    indexed = library.list_online_media()
    source_keys = [normalize_path(source.path)[1] for source in channel.sources]

    selected: list[IndexedMedia] = []
    seen_assets: set[str] = set()
    for item in indexed:
        if item.asset.asset_id in seen_assets:
            continue
        if any(_path_is_within(item.location.path_key, source_key) for source_key in source_keys):
            selected.append(item)
            seen_assets.add(item.asset.asset_id)

    selected.sort(key=lambda item: item.location.path_key)
    return ResolvedChannel(definition=channel, media=tuple(selected))
