from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Slot

from .library import (
    IndexedMedia,
    MediaLibrary,
    normalize_path,
    path_key_is_within,
)
from .playback import PlaybackError
from .resolve import ResolvedChannel, resolve_channel
from .runtime import ChannelRuntime, ChannelRuntimeError

logger = logging.getLogger(__name__)


def _path_is_usable(path: Path) -> bool:
    """Return whether a playback path still exists and can be opened for reading."""

    try:
        if not path.is_file():
            return False
        with path.open("rb"):
            return True
    except OSError:
        return False


def _mark_location_offline(library: MediaLibrary, path: str | Path) -> bool:
    """Quarantine one vanished location without deleting its asset identity."""

    _, path_key = library.storage_path(path)
    with library.connect() as connection:
        cursor = connection.execute(
            """
            UPDATE media_locations
            SET online = 0
            WHERE path_key = ? AND online = 1
            """,
            (path_key,),
        )
    return bool(cursor.rowcount)


def _transient_available_media(
    resolved: ResolvedChannel,
    library: MediaLibrary | None = None,
    *, index=None, root_availability=None,
) -> tuple[IndexedMedia, ...]:
    """Exclude disconnected source roots without persisting them as deleted/offline.

    A USB/network source may simply be absent for this launch. Its indexed rows
    stay online in the database so reconnecting the source does not require
    rebuilding identity, metadata, schedules, or watch history.
    """

    root_available: dict[str, bool] = root_availability if root_availability is not None else {}
    selected: list[IndexedMedia | None] = []
    unavailable: list[tuple[int, IndexedMedia]] = []
    for media in resolved.media:
        root = media.location.source_root
        _, root_key = normalize_path(root)
        available = root_available.get(root_key)
        if available is None:
            available = root.exists()
            root_available[root_key] = available
        if available:
            selected.append(media)
            continue
        selected.append(None)
        unavailable.append((len(selected) - 1, media))

    if library is not None and unavailable:
        source_keys = tuple(
            normalize_path(source.path)[1]
            for source in resolved.definition.sources
        )
        if index is None:
            alternatives = library.online_locations_for_assets(media.asset.asset_id for _, media in unavailable)
        else:
            if not hasattr(index, "locations_by_asset"):
                index.locations_by_asset = {}
                for row in index.online:
                    index.locations_by_asset.setdefault(row.asset.asset_id, []).append(row.location)
            alternatives = index.locations_by_asset
        for index, media in unavailable:
            for location in alternatives.get(media.asset.asset_id, ()):
                if not any(
                    path_key_is_within(location.path_key, source_key)
                    for source_key in source_keys
                ):
                    continue
                alternate_root = location.source_root
                _, alternate_root_key = normalize_path(alternate_root)
                alternate_available = root_available.get(alternate_root_key)
                if alternate_available is None:
                    alternate_available = alternate_root.exists()
                    root_available[alternate_root_key] = alternate_available
                if alternate_available:
                    selected[index] = replace(media, location=location)
                    break

    return tuple(media for media in selected if media is not None)


def _degrade_calendar_for_available_media(
    resolved: ResolvedChannel,
) -> ResolvedChannel:
    """Build a temporary calendar view that ignores unavailable owned media.

    The portable channel definition is never changed. Fixed blocks whose asset
    is temporarily unavailable become ordinary filler gaps for this runtime.
    Show-specific filler pools are filtered to the currently available assets.
    If every fixed block is unavailable, the channel temporarily behaves like
    its configured filler mode until the media returns.
    """

    definition = resolved.definition
    programming = definition.programming
    if programming.mode != "calendar":
        return resolved

    available_ids = {media.asset.asset_id for media in resolved.media}
    blocks = []
    for block in programming.calendar:
        if block.asset_id not in available_ids:
            continue
        filler = block.filler
        if filler is not None:
            available_filler = tuple(
                asset_id
                for asset_id in filler.asset_ids
                if asset_id in available_ids
            )
            filler = (
                replace(filler, asset_ids=available_filler)
                if available_filler
                else None
            )
        blocks.append(replace(block, filler=filler))

    if blocks:
        degraded_programming = replace(
            programming,
            calendar=tuple(blocks),
        )
    else:
        degraded_programming = replace(
            programming,
            mode=programming.filler_mode,
            calendar=(),
        )

    degraded_definition = replace(
        definition,
        programming=degraded_programming,
    )
    return replace(resolved, definition=degraded_definition)


def _usable_channel(definition, library, *, verify_files=False, index=None,
                    availability=None, root_availability=None):
    resolved = resolve_channel(definition, library, allow_offline_ads=True, index=index)
    available = _transient_available_media(resolved, library, index=index, root_availability=root_availability)
    if verify_files:
        usable = availability if availability is not None else {}
        def check(path):
            if path not in usable:
                usable[path] = _path_is_usable(path)
            return usable[path]
        available = tuple(item for item in available if check(item.location.path))
    if not available and definition.programming.mode != "planner":
        return None
    return _degrade_calendar_for_available_media(replace(resolved, media=available))


def _resolved_runtime(
    definition,
    library: MediaLibrary,
    store,
    *,
    persistent_when_complete: bool = False,
    verify_files: bool = False,
    index=None,
    availability=None,
    root_availability=None,
    prepared_channel=None,
) -> ChannelRuntime | None:
    """Resolve one channel against media that is usable for this launch."""

    resolved = prepared_channel if prepared_channel is not None else _usable_channel(
        definition, library, verify_files=verify_files, index=index,
        availability=availability, root_availability=root_availability)
    if resolved is None:
        return None
    complete = resolved.definition == definition
    if index is not None:
        complete = complete and resolved.media == resolve_channel(definition, library, allow_offline_ads=True, index=index).media
    elif persistent_when_complete:
        complete = complete and resolved.media == resolve_channel(definition, library, allow_offline_ads=True).media

    try:
        return ChannelRuntime.open(resolved, store, transient=not (
            persistent_when_complete and (complete or definition.programming.mode=='planner')))
    except ChannelRuntimeError:
        # A temporarily smaller shuffle pool can invalidate a repeat-avoidance
        # promise even though the remaining media is perfectly playable. Relax
        # only the transient runtime; the user's saved channel stays unchanged.
        programming = resolved.definition.programming
        if programming.avoid_repeat_days <= 0:
            raise
        relaxed_definition = replace(
            resolved.definition,
            programming=replace(programming, avoid_repeat_days=0),
        )
        logger.warning(
            "Temporarily relaxed repeat avoidance for channel %s because media is unavailable",
            resolved.definition.display_number,
        )
        return ChannelRuntime.open(
            replace(resolved, definition=relaxed_definition),
            store,
            transient=True,
        )



def install_media_resilience_support(broadcaster_qt_module: Any) -> None:
    """Make missing/moved/disconnected media a recoverable runtime condition."""

    base_controller = broadcaster_qt_module.BroadcasterCouchController
    if getattr(base_controller, "_channelos_media_resilience_enabled", False):
        return

    from .recovery_jobs import RecoveryJobs

    class ResilientBroadcasterController(RecoveryJobs, base_controller):
        _channelos_media_resilience_enabled = True

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._initialize_recovery_jobs()
            self._media_recovery_active = False
            self._pending_on_demand_media: IndexedMedia | None = None
            self._temporarily_unavailable_roots: set[Path] = set()

        def _missing_media_target(self) -> tuple[IndexedMedia, str] | None:
            pending = self._pending_on_demand_media
            if pending is not None and not _path_is_usable(pending.location.path):
                return pending, "ondemand"

            current_on_demand = getattr(self._on_demand, "_current", None)
            if (
                isinstance(current_on_demand, IndexedMedia)
                and not _path_is_usable(current_on_demand.location.path)
            ):
                return current_on_demand, "ondemand"

            try:
                decision = self._actions.runtime.status()
            except (ChannelRuntimeError, ValueError):
                return None
            if decision.viewer_selection.origin == "offair":
                return None
            media = decision.viewer_selection.media
            if not _path_is_usable(media.location.path):
                return media, "television"
            return None

        def _retire_missing_media(self, media: IndexedMedia) -> str:
            path = media.location.path
            root = media.location.source_root
            if not root.exists():
                # A disconnected removable/network source is temporary. Do not
                # persist every row as offline merely because the mount is gone.
                root = root.expanduser().resolve(strict=False)
                self._temporarily_unavailable_roots.add(root)
                logger.warning(
                    "Media source temporarily unavailable; excluding it from this runtime root=%s",
                    root,
                )
                return f"Media source temporarily unavailable: {root}"

            changed = _mark_location_offline(self._library, path)
            logger.warning(
                "Media location unavailable; marked offline path=%s changed=%s",
                path,
                changed,
            )
            return f"Media unavailable and removed from active playback: {path.name}"

        def _publish_temporary_unavailable(self, message: str) -> dict[str, object]:
            try:
                self._actions.suspend_decoder()
            except (PlaybackError, ValueError):
                pass

            self._playback = {
                "active": False,
                "temporaryUnavailable": True,
                "message": message,
            }
            home = dict(self._home_television)
            home["active"] = False
            home["stateLabel"] = "CHANNEL TEMPORARILY UNAVAILABLE"
            home["playbackError"] = ""
            home["temporaryUnavailable"] = True
            self._home_television = home
            self.playbackChanged.emit()
            self.homeTelevisionChanged.emit()
            return {
                "ok": False,
                "message": message,
                "playback": self._playback,
            }

        def _reload_resilient_lineup(self, *, restore_if_active, propagate_playback_error=False):
            self._request_media_recovery(restore_if_active=restore_if_active)
            return False  # Adoption is asynchronous; returned roots remain pending until it succeeds.

        def _recover_on_demand_media(self, media):
            message = self._retire_missing_media(media)
            self._on_demand.stop()
            self._on_demand_view = {"active": False}
            self.onDemandChanged.emit()
            self._request_media_recovery(restore_if_active=False)
            return {"ok": False, "pending": True, "message": f"{message}. Updating available media…"}

        def _recover_television_media(self, media):
            message = self._retire_missing_media(media)
            number=self._actions.runtime.current_channel
            if number is not None:
                self._recovery_force_channels.add(number)
            result = self._publish_temporary_unavailable(f"{message}. Checking available programming…")
            self._request_media_recovery(restore_if_active=True)
            return {**result, 'pending': True}

        def _publish_playback_failure(self, exc: Exception) -> dict[str, object]:
            if self._media_recovery_active or not isinstance(exc, PlaybackError):
                return base_controller._publish_playback_failure(self, exc)

            target = self._missing_media_target()
            if target is None:
                return base_controller._publish_playback_failure(self, exc)

            media, mode = target
            self._media_recovery_active = True
            try:
                if mode == "ondemand":
                    return self._recover_on_demand_media(media)
                return self._recover_television_media(media)
            except (ChannelRuntimeError, PlaybackError, ValueError) as recovery_exc:
                logger.exception("Automatic media recovery could not complete")
                return base_controller._publish_playback_failure(
                    self,
                    recovery_exc,
                )
            finally:
                self._media_recovery_active = False

        @Slot(int, result="QVariantMap")
        def playLibraryIndex(self, index: int) -> dict[str, object]:
            selected = int(index)
            if 0 <= selected < len(self._library_media):
                media = self._library_media[selected]
                if not _path_is_usable(media.location.path):
                    return self._recover_on_demand_media(media)
                self._pending_on_demand_media = media
                try:
                    return super().playLibraryIndex(selected)
                finally:
                    self._pending_on_demand_media = None
            return super().playLibraryIndex(selected)

        @Slot()
        def refresh(self) -> None:
            super().refresh()
            if self._media_recovery_active or not self._temporarily_unavailable_roots:
                return

            returned = {
                root
                for root in self._temporarily_unavailable_roots
                if root.exists()
            }
            if not returned:
                return

            try:
                restored = self._reload_resilient_lineup(
                    restore_if_active=bool(
                        self._playback.get("active")
                        or self._playback.get("temporaryUnavailable")
                    ),
                )
                if not restored:
                    logger.warning(
                        "Returned media source is visible but lineup restoration is still pending"
                    )
                    return
                self._temporarily_unavailable_roots.difference_update(returned)
                logger.info(
                    "Restored media source(s) after they became available again: %s",
                    ", ".join(str(root) for root in sorted(returned, key=str)),
                )
            except (ChannelRuntimeError, PlaybackError, ValueError):
                logger.exception(
                    "Returned media source was detected but lineup restore could not complete"
                )

        @Slot(object)
        def _on_library_scan_completed(self, summary):
            # Indexing has finished; prepare cards and only changed runtimes off Qt.
            self._set_library_scan(active=False, phase='ready', current=int(summary.discovered),
                total=int(summary.discovered), fileName='', message=(
                    f'Scan complete — {summary.discovered} files • {summary.new_assets} new • {summary.cache_hits} unchanged'))
            self._request_media_recovery(restore_if_active=bool(
                self._playback.get('active') or self._playback.get('temporaryUnavailable')))


    broadcaster_qt_module.BroadcasterCouchController = ResilientBroadcasterController
    logger.info("Installed self-healing media availability support")
