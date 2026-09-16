from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Slot

from .couch_actions import CouchActions
from .couch_model import build_couch_snapshot
from .guide import GuideService
from .library import IndexedMedia, MediaLibrary, normalize_path
from .playback import PlaybackError
from .resolve import ResolvedChannel, resolve_channel
from .runtime import ChannelRuntime, ChannelRuntimeError, TelevisionRuntime

logger = logging.getLogger(__name__)

_MAX_RECOVERY_ATTEMPTS = 8


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

    _, path_key = normalize_path(path)
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
) -> tuple[IndexedMedia, ...]:
    """Exclude disconnected source roots without persisting them as deleted/offline.

    A USB/network source may simply be absent for this launch. Its indexed rows
    stay online in the database so reconnecting the source does not require
    rebuilding identity, metadata, schedules, or watch history.
    """

    root_available: dict[str, bool] = {}
    selected: list[IndexedMedia] = []
    for media in resolved.media:
        root = media.location.source_root
        _, root_key = normalize_path(root)
        available = root_available.get(root_key)
        if available is None:
            available = root.exists()
            root_available[root_key] = available
        if available:
            selected.append(media)
    return tuple(selected)


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


def _resolved_runtime(
    definition,
    library: MediaLibrary,
    store,
) -> ChannelRuntime | None:
    """Resolve one channel against media that is usable for this launch."""

    resolved = resolve_channel(definition, library)
    available = _transient_available_media(resolved)
    if not available:
        return None

    resolved = replace(resolved, media=available)
    resolved = _degrade_calendar_for_available_media(resolved)

    try:
        return ChannelRuntime.open(resolved, store)
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
        )


def _runtime_asset_sets(controller: Any) -> dict[int, set[str]]:
    return {
        int(number): {
            media.asset.asset_id
            for media in runtime.channel.media
        }
        for number, runtime in controller._actions.runtime.channels.items()
    }


def _desired_asset_sets(controller: Any) -> dict[int, set[str]]:
    desired: dict[int, set[str]] = {}
    for record in controller._broadcaster.records:
        resolved = resolve_channel(record.definition, controller._library)
        available = _transient_available_media(resolved)
        if available:
            desired[int(record.definition.channel)] = {
                media.asset.asset_id for media in available
            }
    return desired


def _lineup_needs_refresh(controller: Any) -> bool:
    try:
        return _runtime_asset_sets(controller) != _desired_asset_sets(controller)
    except (OSError, ValueError):
        return False


def install_media_resilience_support(broadcaster_qt_module: Any) -> None:
    """Make missing/moved/disconnected media a recoverable runtime condition."""

    base_controller = broadcaster_qt_module.BroadcasterCouchController
    if getattr(base_controller, "_channelos_media_resilience_enabled", False):
        return

    class ResilientBroadcasterController(base_controller):
        _channelos_media_resilience_enabled = True

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._media_recovery_active = False
            self._pending_on_demand_media: IndexedMedia | None = None

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

        def _reload_resilient_lineup(
            self,
            *,
            restore_if_active: bool,
            propagate_playback_error: bool = False,
        ) -> bool:
            """Rebuild television from currently usable media without editing channels."""

            old_runtime = self._actions.runtime
            prior_channel = old_runtime.current_channel
            prior_paused = bool(self._actions.paused)
            should_restore = bool(
                restore_if_active
                and not self._on_demand.active
                and self._surface_ready
                and prior_channel is not None
            )

            runtimes: list[ChannelRuntime] = []
            unavailable_channels: list[str] = []
            for record in self._broadcaster.records:
                try:
                    runtime = _resolved_runtime(
                        record.definition,
                        self._library,
                        self._runtime_store,
                    )
                except ChannelRuntimeError as exc:
                    logger.warning(
                        "Channel %s temporarily unavailable while rebuilding lineup: %s",
                        record.definition.display_number,
                        exc,
                    )
                    runtime = None
                if runtime is None:
                    unavailable_channels.append(record.definition.display_number)
                    continue
                runtimes.append(runtime)

            if not runtimes:
                logger.warning(
                    "No channels currently have usable media; preserving definitions and metadata"
                )
                if restore_if_active:
                    self._publish_temporary_unavailable(
                        "This channel's media is temporarily unavailable. "
                        "ChannelOS will use it again when the media returns."
                    )
                return False

            service = GuideService(tuple(runtimes))
            television = TelevisionRuntime(tuple(runtimes), self._runtime_store)
            actions = CouchActions(service, television)
            actions.set_audio_output_device(
                self._settings.audio_output_device_id or None
            )
            if self._video_surface is not None:
                actions.attach_video_surface(self._video_surface)

            restore_channel: int | None = None
            if should_restore:
                if prior_channel in television.channels:
                    restore_channel = int(prior_channel)
                else:
                    restore_channel = int(television.channel_numbers[0])
                    prior_paused = False

            previous_actions = self._actions
            previous_actions.stop()

            self._service = service
            self._actions = actions
            self._snapshot = build_couch_snapshot(service)
            self._home_television = self._build_home_television_view()
            self._broadcaster_snapshot = self._build_broadcaster_snapshot()
            self.snapshotChanged.emit()
            self.homeTelevisionChanged.emit()
            self.broadcasterChanged.emit()

            if unavailable_channels:
                logger.warning(
                    "Temporarily excluded channel(s) without usable media: %s",
                    ", ".join(unavailable_channels),
                )

            if restore_channel is None:
                self._playback = {"active": False}
                self.playbackChanged.emit()
                return True

            try:
                decision = actions.restore_after_lineup_change(
                    restore_channel,
                    paused=prior_paused,
                )
                self._publish(decision)
            except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
                if propagate_playback_error and isinstance(exc, PlaybackError):
                    raise
                base_controller._publish_playback_failure(self, exc)
            return True

        def _recover_on_demand_media(
            self,
            media: IndexedMedia,
        ) -> dict[str, object]:
            message = self._retire_missing_media(media)
            self._on_demand.stop()
            self._on_demand_view = {"active": False}
            self.onDemandChanged.emit()
            self.refreshLibrary()
            if _lineup_needs_refresh(self):
                self._reload_resilient_lineup(
                    restore_if_active=False,
                )
            logger.info("Recovered missing On Demand media without a playback error screen")
            return {
                "ok": False,
                "message": (
                    f"{message}. ChannelOS kept your watch history and updated the Library."
                ),
            }

        def _recover_television_media(
            self,
            media: IndexedMedia,
        ) -> dict[str, object]:
            last_message = "Media is temporarily unavailable"
            current = media

            for _attempt in range(_MAX_RECOVERY_ATTEMPTS):
                last_message = self._retire_missing_media(current)
                self.refreshLibrary()
                try:
                    rebuilt = self._reload_resilient_lineup(
                        restore_if_active=True,
                        propagate_playback_error=True,
                    )
                except PlaybackError:
                    target = self._missing_media_target()
                    if target is not None and target[1] == "television":
                        current = target[0]
                        continue
                    raise

                if not rebuilt:
                    return self._publish_temporary_unavailable(
                        "This channel's media is temporarily unavailable. "
                        "ChannelOS preserved the channel and will use the media again when it returns."
                    )

                if bool(self._playback.get("active")):
                    logger.info(
                        "Recovered unavailable television media and continued playback"
                    )
                    return {
                        "ok": True,
                        "recovered": True,
                        "message": f"{last_message}; ChannelOS continued with available programming.",
                        "playback": self._playback,
                    }

                return self._publish_temporary_unavailable(last_message)

            return self._publish_temporary_unavailable(
                "ChannelOS found several unavailable programs in a row. "
                "The channel was preserved and will recover when its media returns."
            )

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

        @Slot(object)
        def _on_library_scan_completed(self, summary) -> None:
            super()._on_library_scan_completed(summary)
            if not _lineup_needs_refresh(self):
                return
            try:
                self._reload_resilient_lineup(
                    restore_if_active=bool(
                        self._playback.get("active")
                        or self._playback.get("temporaryUnavailable")
                    ),
                )
                logger.info(
                    "Rebuilt television lineup after Library availability changed"
                )
            except (ChannelRuntimeError, PlaybackError, ValueError):
                # The successful Library scan remains authoritative even if an
                # unrelated decoder/runtime problem prevents immediate reload.
                logger.exception(
                    "Library scan completed but live lineup refresh could not complete"
                )

    broadcaster_qt_module.BroadcasterCouchController = ResilientBroadcasterController
    logger.info("Installed self-healing media availability support")
