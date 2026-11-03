"""Plain Library presentation data that can be prepared by a worker."""
from .library import IndexedMedia


def build_library_view(library, store, artwork_urls, *, online_media=None):
    online = online_media if online_media is not None else library.list_online_media()
    unique: list[IndexedMedia] = []
    seen_assets: set[str] = set()

    for media in online:
        if media.asset.asset_id in seen_assets:
            continue
        seen_assets.add(media.asset.asset_id)
        unique.append(media)


    sources = {
        str(media.location.source_root)
        for media in online
    }

    watches = {
        watch.asset_id: watch
        for watch in store.list_on_demand_watch()
    }

    items: list[dict[str, object]] = []
    for media in unique:
        path = media.location.path
        watch = watches.get(media.asset.asset_id)
        container = (
            media.asset.container_format
            or path.suffix.lstrip(".")
            or "media"
        )

        items.append(
            {
                "assetId": media.asset.asset_id,
                "title": path.stem,
                "fileName": path.name,
                "path": str(path),
                "sourceRoot": str(media.location.source_root),
                "sourceName": (
                    media.location.source_root.name
                    or str(media.location.source_root)
                ),
                "durationSeconds": float(
                    media.asset.duration_seconds or 0.0
                ),
                "sizeBytes": int(media.asset.size_bytes),
                "containerFormat": str(container).upper(),
                "artworkUrl": artwork_urls.get(
                    media.asset.asset_id,
                    "",
                ),
                "continueWatching": bool(
                    watch is not None and watch.resumable
                ),
                "watchPositionSeconds": float(
                    0.0 if watch is None else watch.position_seconds
                ),
                "watchProgress": float(
                    0.0 if watch is None else watch.progress_fraction
                ),
                "lastWatchedAt": (
                    ""
                    if watch is None
                    else watch.last_watched_at.isoformat()
                ),
            }
        )

    snapshot = {
        "count": len(items),
        "locationCount": len(online),
        "sourceCount": len(sources),
        "items": items,
    }

    return snapshot, unique


def add_source_information(snapshot, library, broadcaster, *, indexed_media=None):
    sources: list[dict[str, object]] = []
    indexed_media = indexed_media if indexed_media is not None else (library.list_cached_media() if broadcaster is not None else [])
    source_records = library.list_sources()
    dependencies = broadcaster.source_dependency_reports(
        (source.source_root for source in source_records), indexed_media=indexed_media
    ) if broadcaster is not None else {}
    for source in source_records:
        root = source.source_root
        sources.append(
            {
                "path": str(root),
                "name": root.name or str(root),
                "status": source.status,
                "available": root.exists(),
                "discoveredCount": source.discovered_count,
                "locationCount": source.location_count,
                "onlineLocationCount": source.online_location_count,
                "assetCount": source.asset_count,
                "lastScanStartedAt": source.last_scan_started_at or "",
                "lastScanFinishedAt": source.last_scan_finished_at or "",
                "lastError": source.last_error or "",
                "usedByChannels": dependencies.get(str(root), []),
            }
        )

    snapshot["sources"] = sources
    snapshot["sourceCount"] = len(sources)
    return snapshot

