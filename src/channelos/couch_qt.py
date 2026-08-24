from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QEvent, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog

from .artwork import MediaArtworkCache
from .control import ControlCommand, ControlIntent
from .couch_actions import CouchActions
from .couch_model import build_couch_snapshot
from .guide import GuideError, GuideService
from .library import IndexedMedia, MediaLibrary
from .on_demand import OnDemandSession, OnDemandState
from .playback import NativeVideoSurface, PlaybackError
from .runtime import (
    ChannelRuntimeError,
    OnDemandWatchState,
    TelevisionRuntime,
    TuneDecision,
    utc_now,
)
from .scanner import MediaScanner, ScanProgress, ScanSummary
from .settings import (
    SKIP_BACK_CHOICES,
    SKIP_FORWARD_CHOICES,
    CouchSettings,
    SettingsStore,
)
from .television import TelevisionSession
from .window_startup import NativeWindowSnapshot, NativeWindowStartupGate


class CouchController(QObject):
    """Qt-facing adapter over ChannelOS Guide data and television control intents."""

    snapshotChanged = Signal()
    playbackChanged = Signal()
    homeTelevisionChanged = Signal()
    libraryChanged = Signal()
    libraryArtworkResolved = Signal(str, str)
    onDemandChanged = Signal()
    settingsChanged = Signal()

    def __init__(
        self,
        service: GuideService,
        television: TelevisionRuntime,
        library: MediaLibrary,
    ) -> None:
        super().__init__()
        self._service = service
        self._library = library
        self._runtime_store = television.store
        self._artwork_cache = MediaArtworkCache(
            self._library.database_path.parent / "artwork"
        )
        self._artwork_urls: dict[str, str] = {}
        self._artwork_pending: set[str] = set()
        self._artwork_unavailable: set[str] = set()
        self._artwork_queue: queue.Queue[
            tuple[str, Path, float]
        ] = queue.Queue()
        self._artwork_worker: threading.Thread | None = None
        self._artwork_publish_timer = QTimer(self)
        self._artwork_publish_timer.setSingleShot(True)
        self._artwork_publish_timer.setInterval(80)
        self._artwork_publish_timer.timeout.connect(
            self._publish_library_artwork
        )
        self.libraryArtworkResolved.connect(self._accept_library_artwork)
        self._actions = CouchActions(service, television)
        self._on_demand = OnDemandSession()
        self._last_on_demand_saved_at = 0.0
        self._last_on_demand_saved_signature: tuple[
            str,
            float,
            bool,
        ] | None = None
        self._library_media: list[IndexedMedia] = []
        self._library_snapshot = self._build_library_snapshot()
        self._on_demand_view: dict[str, object] = {"active": False}
        self._snapshot = build_couch_snapshot(service)
        self._playback: dict[str, object] = {"active": False}
        self._home_television = self._build_home_television_view()
        self._surface_ready = False
        self._surface_error = "embedded video surface has not been created"
        self._settings_store = SettingsStore(
            self._runtime_store.database_path.with_name("settings.json")
        )
        self._settings = self._settings_store.load()
        self._volume = self._settings.volume_percent
        self._muted = self._settings.muted

    def _build_library_snapshot(self) -> dict[str, object]:
        online = self._library.list_online_media()
        unique: list[IndexedMedia] = []
        seen_assets: set[str] = set()

        for media in online:
            if media.asset.asset_id in seen_assets:
                continue
            seen_assets.add(media.asset.asset_id)
            unique.append(media)

        self._library_media = unique

        sources = {
            str(media.location.source_root)
            for media in online
        }

        watches = {
            watch.asset_id: watch
            for watch in self._runtime_store.list_on_demand_watch()
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
                    "artworkUrl": self._artwork_urls.get(
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

        return {
            "count": len(items),
            "locationCount": len(online),
            "sourceCount": len(sources),
            "items": items,
        }

    @staticmethod
    def _on_demand_state_view(
        state: OnDemandState,
    ) -> dict[str, object]:
        return {
            "active": bool(state.active),
            "assetId": state.asset_id,
            "title": state.title,
            "path": "" if state.path is None else str(state.path),
            "durationSeconds": float(state.duration_seconds),
            "positionSeconds": float(state.position_seconds),
            "paused": bool(state.paused),
            "ended": bool(state.ended),
        }

    @Property("QVariantMap", notify=snapshotChanged)
    def snapshot(self) -> dict[str, object]:
        return self._snapshot

    @Property("QVariantMap", notify=playbackChanged)
    def playback(self) -> dict[str, object]:
        return self._playback

    @Property("QVariantMap", notify=homeTelevisionChanged)
    def homeTelevision(self) -> dict[str, object]:
        return self._home_television

    @Property("QVariantMap", notify=libraryChanged)
    def librarySnapshot(self) -> dict[str, object]:
        return self._library_snapshot

    @Property("QVariantMap", notify=onDemandChanged)
    def onDemand(self) -> dict[str, object]:
        return self._on_demand_view

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self) -> dict[str, object]:
        return {
            "volumePercent": self._settings.volume_percent,
            "muted": self._settings.muted,
            "skipBackSeconds": self._settings.skip_back_seconds,
            "skipForwardSeconds": self._settings.skip_forward_seconds,
        }

    @Slot()
    def refresh(self) -> None:
        self._snapshot = build_couch_snapshot(self._service)
        self._home_television = self._build_home_television_view()
        self.snapshotChanged.emit()
        self.homeTelevisionChanged.emit()

    @Slot()
    def refreshLibrary(self) -> None:
        # A user may have added a sidecar image since the previous visit. Retry
        # unresolved visible cards on an explicit Library refresh.
        self._artwork_cache.clear_discovery_cache()
        self._artwork_unavailable.clear()
        self._library_snapshot = self._build_library_snapshot()
        self.libraryChanged.emit()

    @Slot(str, result=str)
    def requestLibraryArtwork(self, asset_id: str) -> str:
        target = str(asset_id)
        known = self._artwork_urls.get(target, "")
        if known:
            return known
        if target in self._artwork_pending or target in self._artwork_unavailable:
            return ""

        media = next(
            (
                item
                for item in self._library_media
                if item.asset.asset_id == target
            ),
            None,
        )
        if media is None:
            self._artwork_unavailable.add(target)
            return ""

        self._artwork_pending.add(target)
        self._artwork_queue.put(
            (
                target,
                media.location.path,
                float(media.asset.duration_seconds or 0.0),
            )
        )
        if self._artwork_worker is None:
            self._artwork_worker = threading.Thread(
                target=self._resolve_library_artwork,
                name="channelos-artwork",
                daemon=True,
            )
            self._artwork_worker.start()
        return ""

    def _resolve_library_artwork(self) -> None:
        while True:
            asset_id, media_path, duration = self._artwork_queue.get()
            try:
                resolved = self._artwork_cache.resolve(
                    media_path,
                    asset_id,
                    duration,
                )
                self.libraryArtworkResolved.emit(
                    asset_id,
                    "" if resolved is None else str(resolved),
                )
            except Exception:
                # Artwork is optional presentation. A failure must never take
                # down Library browsing or replace the established fallback.
                self.libraryArtworkResolved.emit(asset_id, "")
            finally:
                self._artwork_queue.task_done()

    @Slot(str, str)
    def _accept_library_artwork(self, asset_id: str, resolved_path: str) -> None:
        self._artwork_pending.discard(asset_id)
        if resolved_path:
            self._artwork_urls[asset_id] = QUrl.fromLocalFile(
                resolved_path
            ).toString()
            self._artwork_publish_timer.start()
        else:
            self._artwork_unavailable.add(asset_id)

    @Slot()
    def _publish_library_artwork(self) -> None:
        self._library_snapshot = self._build_library_snapshot()
        self.libraryChanged.emit()

    @Slot()
    def refreshPlayback(self) -> None:
        if self._on_demand.active:
            return
        if self._actions.last_decision is None:
            return
        try:
            decision = self._actions.sync()
        except (ChannelRuntimeError, PlaybackError, ValueError):
            return

        self._playback = self._decision_view(decision)
        self._home_television = self._home_view_from_decision(decision)
        self.playbackChanged.emit()
        self.homeTelevisionChanged.emit()

    @Slot()
    def refreshOnDemand(self) -> None:
        if not self._on_demand.active:
            return
        state = self._on_demand.state()
        self._persist_on_demand_state(state)
        self._on_demand_view = self._on_demand_state_view(state)
        self.onDemandChanged.emit()

    def _persist_on_demand_state(
        self,
        state: OnDemandState,
        *,
        force: bool = False,
    ) -> OnDemandWatchState | None:
        if not state.active or not state.asset_id:
            return None

        now_monotonic = time.monotonic()
        signature = (
            state.asset_id,
            round(float(state.position_seconds), 1),
            bool(state.ended),
        )
        if (
            not force
            and (
                state.paused
                or signature == self._last_on_demand_saved_signature
                or now_monotonic - self._last_on_demand_saved_at < 5.0
            )
        ):
            return None

        saved = self._runtime_store.save_on_demand_watch(
            state.asset_id,
            state.position_seconds,
            state.duration_seconds,
            completed=state.ended,
        )
        self._last_on_demand_saved_at = now_monotonic
        self._last_on_demand_saved_signature = signature
        return saved

    def scan_media_folder(
        self,
        path: str | Path,
        *,
        on_progress: Callable[[ScanProgress], None] | None = None,
    ) -> ScanSummary:
        """Index one user-selected media source into the existing local library."""

        scanner = MediaScanner(self._library)
        summary = scanner.scan(path, on_progress=on_progress)
        self.refreshLibrary()
        return summary

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self._actions.attach_video_surface(surface)
        self._on_demand.attach_video_surface(surface)
        self._surface_ready = True
        self._surface_error = ""

    @Slot()
    def startHomePlayback(self) -> None:
        """Start the remembered/default television feed after the UI is visible."""

        if (
            not self._surface_ready
            or self._on_demand.active
            or bool(self._playback.get("active"))
        ):
            return
        try:
            decision = self._actions.continue_watching(default_channel=1)
        except (ChannelRuntimeError, PlaybackError, ValueError):
            # No saved television continuity and no real CH001 means Home stays
            # on its presentation-only static state.
            return
        self._publish(decision)

    def set_video_surface_error(self, message: str) -> None:
        self._surface_ready = False
        self._surface_error = message

    def _home_view_from_decision(
        self,
        decision: TuneDecision,
    ) -> dict[str, object]:
        view = self._decision_view(decision)
        view["mode"] = "current"
        view["isUnassigned"] = False
        view["stateLabel"] = "WATCHING"
        view["continueLabel"] = "Continue Watching"
        return view

    def _build_home_television_view(self) -> dict[str, object]:
        runtime = self._actions.runtime

        if runtime.current_channel is not None:
            try:
                return self._home_view_from_decision(runtime.status())
            except ChannelRuntimeError:
                pass

        if runtime.previous_channel is not None:
            try:
                previous = runtime.saved_status(runtime.previous_channel)
            except ChannelRuntimeError:
                previous = None
            if previous is not None:
                view = self._decision_view(previous)
                view["active"] = False
                view["mode"] = "previous"
                view["isUnassigned"] = False
                view["stateLabel"] = "CONTINUE WATCHING"
                view["continueLabel"] = "Continue Watching"
                view["paused"] = True
                return view

        if 1 in runtime.channels:
            at = utc_now()
            channel = runtime.channels[1]
            selected = channel.broadcast_at(at)
            definition = channel.channel.definition
            next_program = self._service.now_next(1, at=at).next
            return {
                "active": False,
                "mode": "default",
                "isUnassigned": False,
                "stateLabel": "DEFAULT CHANNEL",
                "continueLabel": "Watch Channel 001",
                "channelNumber": 1,
                "displayNumber": definition.display_number,
                "channelName": definition.name,
                "title": selected.media.location.path.stem,
                "assetId": selected.media.asset.asset_id,
                "offsetSeconds": float(selected.offset_seconds),
                "lagSeconds": 0.0,
                "isLive": True,
                "paused": False,
                "viewerTimeMs": int(at.timestamp() * 1000),
                "programStartMs": int(
                    selected.program_started_at.timestamp() * 1000
                ),
                "programEndMs": int(
                    selected.program_ends_at.timestamp() * 1000
                ),
                "nextTitle": next_program.display_label,
                "nextStartMs": int(next_program.start_utc.timestamp() * 1000),
                "nextEndMs": int(next_program.end_utc.timestamp() * 1000),
            }

        return {
            "active": False,
            "mode": "static",
            "isUnassigned": True,
            "stateLabel": "UNASSIGNED",
            "continueLabel": "Set Up Channel 001",
            "channelNumber": 1,
            "displayNumber": "001",
            "channelName": "ChannelOS",
            "title": "NO PROGRAMMING",
            "lagSeconds": 0.0,
            "isLive": False,
            "paused": False,
            "programStartMs": 0,
            "programEndMs": 0,
            "nextTitle": "",
            "nextStartMs": 0,
            "nextEndMs": 0,
        }

    def _decision_view(self, decision: TuneDecision) -> dict[str, object]:
        selected = decision.viewer_selection
        definition = self._actions.runtime.channels[decision.channel_number].channel.definition
        next_program = self._service.now_next(
            decision.channel_number,
            at=decision.viewer_time_utc,
        ).next
        return {
            "active": True,
            "channelNumber": decision.channel_number,
            "displayNumber": definition.display_number,
            "channelName": decision.channel_name,
            "title": selected.media.location.path.stem,
            "assetId": selected.media.asset.asset_id,
            "offsetSeconds": float(selected.offset_seconds),
            "lagSeconds": float(decision.lag_seconds),
            "isLive": bool(decision.is_live),
            "paused": bool(self._actions.paused),
            "viewerTimeMs": int(decision.viewer_time_utc.timestamp() * 1000),
            "programStartMs": int(selected.program_started_at.timestamp() * 1000),
            "programEndMs": int(selected.program_ends_at.timestamp() * 1000),
            "nextTitle": next_program.display_label,
            "nextStartMs": int(next_program.start_utc.timestamp() * 1000),
            "nextEndMs": int(next_program.end_utc.timestamp() * 1000),
        }

    def _publish(self, decision: TuneDecision) -> dict[str, object]:
        self._actions.set_volume(self._volume)
        self._actions.set_muted(self._muted)
        self._playback = self._decision_view(decision)
        self._home_television = self._home_view_from_decision(decision)
        self.playbackChanged.emit()
        self.homeTelevisionChanged.emit()
        return {
            "ok": True,
            "message": TelevisionSession.describe(decision),
            "playback": self._playback,
        }

    @staticmethod
    def _error(exc: Exception) -> dict[str, object]:
        return {"ok": False, "message": str(exc)}

    def activate_selection(self, row_index: int, program_index: int) -> dict[str, object]:
        rows = self._snapshot.get("rows", [])
        if not isinstance(rows, list) or not 0 <= row_index < len(rows):
            return {"ok": False, "message": "Guide selection is no longer available; refresh the Guide"}
        row = rows[row_index]
        programs = row.get("programs", []) if isinstance(row, dict) else []
        if not isinstance(programs, list) or not 0 <= program_index < len(programs):
            return {"ok": False, "message": "Guide program is no longer available; refresh the Guide"}
        program = programs[program_index]
        if not isinstance(program, dict):
            return {"ok": False, "message": "Guide program data is invalid"}
        return self.activateProgram(
            str(program.get("scheduleId", "")),
            int(program.get("channelNumber", row.get("channelNumber", 0))),
            float(program.get("startMs", 0.0)),
        )

    @Slot(str, int, float, result="QVariantMap")
    def activateProgram(
        self,
        schedule_id: str,
        channel_number: int,
        approximate_start_ms: float,
    ) -> dict[str, object]:
        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}
        try:
            decision = self._actions.activate_program(
                schedule_id,
                int(channel_number),
                float(approximate_start_ms),
            )
            return self._publish(decision)
        except (GuideError, ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(int, result="QVariantMap")
    def playLibraryIndex(self, index: int) -> dict[str, object]:
        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}

        selected = int(index)
        if not 0 <= selected < len(self._library_media):
            return {
                "ok": False,
                "message": "Library selection is no longer available",
            }

        try:
            self._actions.suspend_decoder()
            media = self._library_media[selected]
            watch = self._runtime_store.load_on_demand_watch(
                media.asset.asset_id
            )
            resume_seconds = (
                watch.position_seconds
                if watch is not None and watch.resumable
                else 0.0
            )
            state = self._on_demand.play_media(
                media,
                start_seconds=resume_seconds,
            )
            self._last_on_demand_saved_at = 0.0
            self._last_on_demand_saved_signature = None
            self._persist_on_demand_state(state, force=True)
            self._on_demand.set_volume(self._volume)
            self._on_demand.set_muted(self._muted)
            self._on_demand_view = self._on_demand_state_view(state)
            self.onDemandChanged.emit()

            return {
                "ok": True,
                "message": (
                    f"Resuming {state.title} at {resume_seconds:.0f}s"
                    if resume_seconds > 0.0
                    else f"On Demand - {state.title}"
                ),
                "onDemand": self._on_demand_view,
            }

        except (PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def toggleOnDemandPause(self) -> dict[str, object]:
        try:
            state = self._on_demand.toggle_pause()
            self._persist_on_demand_state(state, force=True)
            self._on_demand_view = self._on_demand_state_view(state)
            self.onDemandChanged.emit()

            return {
                "ok": True,
                "message": (
                    "On Demand paused"
                    if state.paused
                    else "On Demand playing"
                ),
            }

        except (PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(float, result="QVariantMap")
    def skipOnDemand(self, delta_seconds: float) -> dict[str, object]:
        try:
            state = self._on_demand.skip(float(delta_seconds))
            self._persist_on_demand_state(state, force=True)
            self._on_demand_view = self._on_demand_state_view(state)
            self.onDemandChanged.emit()

            return {
                "ok": True,
                "message": f"On Demand @ {state.position_seconds:.1f}s",
            }

        except (PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def stopOnDemand(self) -> dict[str, object]:
        if self._on_demand.active:
            self._persist_on_demand_state(
                self._on_demand.state(),
                force=True,
            )
        self._on_demand.stop()
        self._on_demand_view = {"active": False}
        self.onDemandChanged.emit()
        self.refreshLibrary()
        return {"ok": True, "message": "On Demand stopped"}

    @Slot(result="QVariantMap")
    def togglePause(self) -> dict[str, object]:
        try:
            decision = self._actions.play() if self._actions.paused else self._actions.pause()
            return self._publish(decision)
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def goLive(self) -> dict[str, object]:
        try:
            return self._publish(self._actions.go_live())
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(float, result="QVariantMap")
    def skip(self, delta_seconds: float) -> dict[str, object]:
        try:
            return self._publish(self._actions.skip(float(delta_seconds)))
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(int, result="QVariantMap")
    def changeChannel(self, direction: int) -> dict[str, object]:
        try:
            if int(direction) > 0:
                decision = self._actions.channel_up()
            elif int(direction) < 0:
                decision = self._actions.channel_down()
            else:
                raise ValueError("channel direction must be -1 or 1")
            return self._publish(decision)
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(int, result="QVariantMap")
    def tuneChannel(self, channel_number: int) -> dict[str, object]:
        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}
        try:
            return self._publish(
                self._actions.tune(int(channel_number))
            )
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def previousChannel(self) -> dict[str, object]:
        try:
            return self._publish(self._actions.previous_channel())
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def continueWatching(self) -> dict[str, object]:
        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}
        try:
            return self._publish(
                self._actions.continue_watching(default_channel=1)
            )
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def enterLiveFromHome(self) -> dict[str, object]:
        """Expand an already-playing Home feed without restarting or seeking it."""

        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}

        decision = self._actions.reuse_current_playback()
        if (
            bool(self._playback.get("active"))
            and not bool(self._playback.get("paused"))
            and not self._on_demand.active
            and decision is not None
        ):
            return {
                "ok": True,
                "message": "",
                "playback": self._playback,
                "reused": True,
            }

        # Preserve Continue Watching semantics when Home does not already have
        # a running live-TV feed (including resuming a paused Viewer Clock).
        return self.continueWatching()

    def _apply_audio_state(self) -> None:
        if self._on_demand.active:
            self._on_demand.set_volume(self._volume)
            self._on_demand.set_muted(self._muted)
        elif self._actions.last_decision is not None:
            self._actions.set_volume(self._volume)
            self._actions.set_muted(self._muted)

    def _save_settings(self, settings: CouchSettings) -> None:
        self._settings_store.save(settings)
        self._settings = settings
        self._volume = settings.volume_percent
        self._muted = settings.muted
        self.settingsChanged.emit()

    @staticmethod
    def _cycle_choice(
        current: int,
        choices: tuple[int, ...],
        direction: int,
    ) -> int:
        index = choices.index(current)
        return choices[(index + (1 if direction > 0 else -1)) % len(choices)]

    @Slot(int, result="QVariantMap")
    def changeVolume(self, delta: int) -> dict[str, object]:
        try:
            volume = max(
                0,
                min(100, self._volume + int(delta)),
            )
            self._save_settings(
                replace(
                    self._settings,
                    volume_percent=volume,
                    muted=False,
                )
            )
            self._apply_audio_state()
            return {
                "ok": True,
                "message": f"Volume {self._volume}%",
                "volume": self._volume,
                "muted": self._muted,
                "settings": self.settings,
            }
        except (OSError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def toggleMute(self) -> dict[str, object]:
        try:
            self._save_settings(
                replace(self._settings, muted=not self._muted)
            )
            self._apply_audio_state()
            return {
                "ok": True,
                "message": (
                    "Muted"
                    if self._muted
                    else f"Volume {self._volume}%"
                ),
                "volume": self._volume,
                "muted": self._muted,
                "settings": self.settings,
            }
        except (OSError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(str, int, result="QVariantMap")
    def adjustSetting(self, name: str, direction: int) -> dict[str, object]:
        step = 1 if int(direction) >= 0 else -1
        if name == "volume":
            return self.changeVolume(step * 5)
        if name == "muted":
            return self.toggleMute()

        try:
            if name == "skipBack":
                value = self._cycle_choice(
                    self._settings.skip_back_seconds,
                    SKIP_BACK_CHOICES,
                    step,
                )
                settings = replace(
                    self._settings,
                    skip_back_seconds=value,
                )
                message = f"Skip back {value} seconds"
            elif name == "skipForward":
                value = self._cycle_choice(
                    self._settings.skip_forward_seconds,
                    SKIP_FORWARD_CHOICES,
                    step,
                )
                settings = replace(
                    self._settings,
                    skip_forward_seconds=value,
                )
                message = f"Skip forward {value} seconds"
            else:
                raise ValueError(f"unknown setting: {name}")

            self._save_settings(settings)
            return {
                "ok": True,
                "message": message,
                "settings": self.settings,
            }
        except (OSError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def resetSettings(self) -> dict[str, object]:
        try:
            self._save_settings(CouchSettings())
            self._apply_audio_state()
            return {
                "ok": True,
                "message": "Settings restored to ChannelOS defaults",
                "volume": self._volume,
                "muted": self._muted,
                "settings": self.settings,
            }
        except (OSError, PlaybackError) as exc:
            return self._error(exc)

    def stop(self) -> None:
        if self._on_demand.active:
            self._persist_on_demand_state(
                self._on_demand.state(),
                force=True,
            )
        self._on_demand.stop()
        self._actions.stop()


class CouchKeyFilter(QObject):
    """Translate couch/keyboard controls independently of QML focus ownership."""

    def __init__(self, controller: CouchController, window: QObject) -> None:
        super().__init__(window)
        self._controller = controller
        self._window = window
        self._hud_generation = 0
        self._audio_generation = 0
        self._channel_generation = 0
        self._channel_digits = ""

    def _show_live_hud(self) -> None:
        # Show the Live information layer after tuning or transport/channel
        # interaction, then clear it after a television-like grace period.
        # Generation IDs make repeated input restart the timeout cleanly.
        self._hud_generation += 1
        generation = self._hud_generation
        self._window.setProperty("liveHudVisible", True)

        def hide() -> None:
            if (
                generation == self._hud_generation
                and str(self._window.property("screen")) == "live"
            ):
                self._window.setProperty("liveHudVisible", False)

        QTimer.singleShot(10000, hide)

    def _show_audio_hud(self, result: dict[str, object]) -> None:
        if not bool(result.get("ok")):
            return

        self._audio_generation += 1
        generation = self._audio_generation
        self._window.setProperty(
            "volumePercent",
            int(result.get("volume", 100)),
        )
        self._window.setProperty(
            "muted",
            bool(result.get("muted", False)),
        )
        self._window.setProperty("audioHudVisible", True)

        def hide() -> None:
            if generation == self._audio_generation:
                self._window.setProperty("audioHudVisible", False)

        QTimer.singleShot(2200, hide)

    def _handle_audio_intent(self, intent: ControlIntent) -> bool:
        if intent is ControlIntent.VOLUME_UP:
            result = self._controller.changeVolume(5)
        elif intent is ControlIntent.VOLUME_DOWN:
            result = self._controller.changeVolume(-5)
        elif intent is ControlIntent.MUTE:
            result = self._controller.toggleMute()
        else:
            return False

        self._notify(result)
        self._show_audio_hud(result)
        return True

    @staticmethod
    def command_for_key(key: int) -> ControlCommand | None:
        """Translate one Qt keyboard/media key without applying UI behavior."""

        digits = {
            Qt.Key.Key_0: 0,
            Qt.Key.Key_1: 1,
            Qt.Key.Key_2: 2,
            Qt.Key.Key_3: 3,
            Qt.Key.Key_4: 4,
            Qt.Key.Key_5: 5,
            Qt.Key.Key_6: 6,
            Qt.Key.Key_7: 7,
            Qt.Key.Key_8: 8,
            Qt.Key.Key_9: 9,
        }
        if key in digits:
            return ControlCommand.digit(digits[key])

        bindings = {
            Qt.Key.Key_Plus: ControlIntent.VOLUME_UP,
            Qt.Key.Key_Equal: ControlIntent.VOLUME_UP,
            Qt.Key.Key_VolumeUp: ControlIntent.VOLUME_UP,
            Qt.Key.Key_Minus: ControlIntent.VOLUME_DOWN,
            Qt.Key.Key_VolumeDown: ControlIntent.VOLUME_DOWN,
            Qt.Key.Key_M: ControlIntent.MUTE,
            Qt.Key.Key_VolumeMute: ControlIntent.MUTE,
            Qt.Key.Key_MediaPlay: ControlIntent.PLAY,
            Qt.Key.Key_MediaPause: ControlIntent.PAUSE,
            Qt.Key.Key_MediaTogglePlayPause: ControlIntent.PLAY_PAUSE,
            Qt.Key.Key_G: ControlIntent.GUIDE,
            Qt.Key.Key_H: ControlIntent.HOME,
            Qt.Key.Key_Escape: ControlIntent.BACK,
            Qt.Key.Key_Backspace: ControlIntent.BACK,
            Qt.Key.Key_Back: ControlIntent.BACK,
            Qt.Key.Key_Up: ControlIntent.UP,
            Qt.Key.Key_Down: ControlIntent.DOWN,
            Qt.Key.Key_Left: ControlIntent.LEFT,
            Qt.Key.Key_Right: ControlIntent.RIGHT,
            Qt.Key.Key_Return: ControlIntent.SELECT,
            Qt.Key.Key_Enter: ControlIntent.SELECT,
            Qt.Key.Key_Space: ControlIntent.SELECT,
            Qt.Key.Key_Home: ControlIntent.GUIDE_NOW,
            Qt.Key.Key_L: ControlIntent.GO_LIVE,
            Qt.Key.Key_P: ControlIntent.PREVIOUS_CHANNEL,
            Qt.Key.Key_A: ControlIntent.ADD_MEDIA_SOURCE,
            Qt.Key.Key_B: ControlIntent.CHANNELS,
            Qt.Key.Key_I: ControlIntent.INFO,
            Qt.Key.Key_S: ControlIntent.SETTINGS,
        }
        optional_consumer_bindings = {
            "Key_ChannelUp": ControlIntent.CHANNEL_UP,
            "Key_ChannelDown": ControlIntent.CHANNEL_DOWN,
            "Key_Guide": ControlIntent.GUIDE,
            "Key_Info": ControlIntent.INFO,
            "Key_Settings": ControlIntent.SETTINGS,
            "Key_Select": ControlIntent.SELECT,
            "Key_Exit": ControlIntent.BACK,
            "Key_MediaPrevious": ControlIntent.SKIP_BACK,
            "Key_MediaNext": ControlIntent.SKIP_FORWARD,
            "Key_PowerOff": ControlIntent.POWER,
            "Key_HomePage": ControlIntent.HOME,
        }
        for attribute, consumer_intent in optional_consumer_bindings.items():
            consumer_key = getattr(Qt.Key, attribute, None)
            if consumer_key is not None:
                bindings[consumer_key] = consumer_intent
        intent = bindings.get(key)
        return None if intent is None else ControlCommand(intent)

    def _commit_channel_entry(self) -> None:
        digits = self._channel_digits
        if not digits:
            return

        self._channel_digits = ""
        self._channel_generation += 1
        self._window.setProperty("channelEntry", "")

        came_from_on_demand = (
            str(self._window.property("screen")) == "ondemand"
        )
        if came_from_on_demand:
            self._controller.stopOnDemand()
            self._window.setProperty("screen", "live")
            QApplication.processEvents()

        result = self._controller.tuneChannel(int(digits))
        self._notify(result)

        if bool(result.get("ok")):
            self._show_live_hud()
        elif came_from_on_demand:
            self._window.setProperty("screen", "library")

    def _queue_channel_digit(self, digit: str) -> None:
        if len(self._channel_digits) >= 4:
            self._channel_digits = ""

        self._channel_digits += digit
        self._window.setProperty(
            "channelEntry",
            self._channel_digits,
        )
        self._channel_generation += 1
        generation = self._channel_generation

        if len(self._channel_digits) >= 4:
            self._commit_channel_entry()
            return

        def commit_if_current() -> None:
            if (
                generation == self._channel_generation
                and self._channel_digits
                and str(self._window.property("screen")) in {"live", "ondemand"}
            ):
                self._commit_channel_entry()

        QTimer.singleShot(1300, commit_if_current)

    def _notify(self, result: dict[str, object]) -> None:
        message = str(result.get("message", ""))
        if not message:
            return
        self._window.setProperty("statusMessage", message)
        QTimer.singleShot(4200, lambda: self._window.setProperty("statusMessage", ""))

    def _rows(self) -> list[dict[str, object]]:
        rows = self._controller.snapshot.get("rows", [])
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _current_program_index(self, row_index: int) -> int:
        rows = self._rows()
        if not 0 <= row_index < len(rows):
            return -1
        programs = rows[row_index].get("programs", [])
        if not isinstance(programs, list):
            return -1
        for index, program in enumerate(programs):
            if isinstance(program, dict) and bool(program.get("isCurrent")):
                return index
        return 0 if programs else -1

    def _select_row(self, row_index: int) -> None:
        rows = self._rows()
        if not rows:
            return
        selected = max(0, min(len(rows) - 1, row_index))
        self._window.setProperty("selectedRow", selected)
        self._window.setProperty("selectedProgram", self._current_program_index(selected))

    def _select_guide_anchor(self) -> None:
        rows = self._rows()
        if not rows:
            return

        home = self._controller.homeTelevision
        target = int(home.get("channelNumber", 1))
        for index, row in enumerate(rows):
            if int(row.get("channelNumber", -1)) == target:
                self._select_row(index)
                return

        self._select_row(0)

    def _select_program_delta(self, delta: int) -> None:
        rows = self._rows()
        row_index = int(self._window.property("selectedRow"))
        if not 0 <= row_index < len(rows):
            return
        programs = rows[row_index].get("programs", [])
        if not isinstance(programs, list) or not programs:
            return
        current = int(self._window.property("selectedProgram"))
        selected = max(0, min(len(programs) - 1, current + delta))
        self._window.setProperty("selectedProgram", selected)

    def _library_items(self) -> list[dict[str, object]]:
        items = self._controller.librarySnapshot.get("items", [])
        if not isinstance(items, list):
            return []
        return [
            item
            for item in items
            if isinstance(item, dict)
        ]

    def _select_library(self, index: int) -> None:
        items = self._library_items()
        if not items:
            self._window.setProperty("selectedLibrary", 0)
            return

        self._window.setProperty(
            "selectedLibrary",
            max(0, min(len(items) - 1, int(index))),
        )

    def _choose_and_scan_media_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            None,
            "Choose a ChannelOS media folder",
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return

        progress_dialog = QProgressDialog()
        progress_dialog.setWindowTitle("ChannelOS — Index Media")
        progress_dialog.setLabelText("Discovering supported media files…")
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setRange(0, 1)
        progress_dialog.setValue(0)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dialog.show()
        QApplication.processEvents()

        def on_progress(progress: ScanProgress) -> None:
            maximum = max(1, progress.total)
            progress_dialog.setRange(0, maximum)
            progress_dialog.setValue(min(progress.current, maximum))
            if progress.path is None:
                progress_dialog.setLabelText(
                    f"Found {progress.total} supported media file(s). Preparing index…"
                )
            else:
                progress_dialog.setLabelText(
                    f"Indexing {progress.current} of {progress.total}\n{progress.path.name}"
                )
            QApplication.processEvents()

        try:
            summary = self._controller.scan_media_folder(folder, on_progress=on_progress)
        except (FileNotFoundError, OSError, ValueError) as exc:
            progress_dialog.close()
            self._notify({"message": f"Media scan failed — {exc}"})
            return

        progress_dialog.setValue(max(1, summary.discovered))
        progress_dialog.close()
        total_assets = self._controller._library.count_assets()
        self._notify(
            {
                "message": (
                    f"Library scan complete — {summary.discovered} files • "
                    f"{summary.new_assets} new • {summary.cache_hits} unchanged • "
                    f"{total_assets} total assets"
                )
            }
        )

    def _open_guide(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._controller.refresh()
        self._window.setProperty("screen", "guide")
        self._select_guide_anchor()
        return True

    def _open_library(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._controller.refreshLibrary()
        self._window.setProperty("screen", "library")
        self._select_library(
            int(self._window.property("selectedLibrary"))
        )
        return True

    def _open_settings(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._window.setProperty("screen", "settings")
        return True

    def _open_previous_channel_from_home(self) -> bool:
        self._window.setProperty("screen", "live")
        QApplication.processEvents()
        result = self._controller.previousChannel()
        self._notify(result)
        if bool(result.get("ok")):
            self._show_live_hud()
        else:
            self._go_home()
        return True

    def _activate_home_menu_selection(self, selection: int) -> bool:
        if selection == 1:
            return self._open_guide()
        if selection == 2:
            return self._open_library()
        if selection == 0:
            home = self._controller.homeTelevision
            if str(home.get("mode", "static")) == "static":
                self._notify(
                    {
                        "message": (
                            "Channel 001 is unassigned - create "
                            "Channel 001 in Broadcaster to start watching"
                        )
                    }
                )
                return True

            self._window.setProperty("screen", "live")
            QApplication.processEvents()
            result = self._controller.enterLiveFromHome()
            self._notify(result)
            if bool(result.get("ok")):
                self._show_live_hud()
            else:
                self._window.setProperty("screen", "home")
            return True
        if selection == 3:
            if self.dispatch_command(ControlCommand(ControlIntent.CHANNELS)):
                return True
            self._notify(
                {"message": "Channel management is unavailable in this launcher"}
            )
            return True
        if selection == 4:
            return self._open_settings()
        return False

    @Slot(int)
    def activateHomeMenu(self, selection: int) -> None:
        selected = max(0, min(4, int(selection)))
        self._window.setProperty("homeFocusArea", 0)
        self._window.setProperty("homeSelection", selected)
        self._activate_home_menu_selection(selected)

    @Slot(int)
    def activateHomeCard(self, selection: int) -> None:
        selected = max(0, min(3, int(selection)))
        self._window.setProperty("homeFocusArea", 1)
        self._window.setProperty("homeCardSelection", selected)
        if selected == 0:
            self._open_guide()
        elif selected == 1:
            self._open_library()
        elif selected == 2:
            self._open_previous_channel_from_home()
        else:
            self.dispatch_command(ControlCommand(ControlIntent.CHANNELS))

    def _adjust_selected_setting(self, direction: int) -> bool:
        selection = int(self._window.property("settingsSelection"))
        names = ("volume", "muted", "skipBack", "skipForward")
        if not 0 <= selection < len(names):
            return False
        result = self._controller.adjustSetting(names[selection], direction)
        self._notify(result)
        if "volume" in result:
            self._window.setProperty(
                "volumePercent",
                int(result.get("volume", 100)),
            )
            self._window.setProperty(
                "muted",
                bool(result.get("muted", False)),
            )
        return True

    def _go_home(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._window.setProperty("screen", "home")
        QApplication.processEvents()
        return True

    @staticmethod
    def _transport_should_toggle(
        intent: ControlIntent,
        *,
        paused: bool,
    ) -> bool:
        if intent in {ControlIntent.SELECT, ControlIntent.PLAY_PAUSE}:
            return True
        if intent is ControlIntent.PLAY:
            return paused
        if intent is ControlIntent.PAUSE:
            return not paused
        return False

    def dispatch_command(self, command: ControlCommand) -> bool:
        """Interpret a transport-neutral intent in the current UI context."""

        intent = command.intent
        screen = str(self._window.property("screen"))

        if intent is ControlIntent.POWER:
            QGuiApplication.quit()
            return True

        if intent is ControlIntent.HOME:
            return self._go_home()

        if intent is ControlIntent.GUIDE:
            if screen == "guide":
                self._controller.refresh()
                self._select_row(
                    int(self._window.property("selectedRow"))
                )
                return True
            return self._open_guide()

        if intent is ControlIntent.LIBRARY:
            return self._open_library()

        if intent is ControlIntent.SETTINGS:
            return self._open_settings()

        if intent is ControlIntent.TUNE:
            if screen == "ondemand":
                self._controller.stopOnDemand()
            self._window.setProperty("screen", "live")
            QApplication.processEvents()
            result = self._controller.tuneChannel(int(command.value or 0))
            self._notify(result)
            if bool(result.get("ok")):
                self._show_live_hud()
            return True

        if screen in {"live", "ondemand"} and self._handle_audio_intent(intent):
            return True

        if screen == "home":
            if intent is ControlIntent.BACK:
                QGuiApplication.quit()
                return True
            if intent is ControlIntent.UP:
                if int(self._window.property("homeFocusArea")) == 1:
                    self._window.setProperty("homeFocusArea", 0)
                    self._window.setProperty("homeSelection", 4)
                    return True
                current = int(self._window.property("homeSelection"))
                self._window.setProperty("homeSelection", max(0, current - 1))
                return True
            if intent is ControlIntent.DOWN:
                if int(self._window.property("homeFocusArea")) == 1:
                    return True
                current = int(self._window.property("homeSelection"))
                if current >= 4:
                    self._window.setProperty("homeFocusArea", 1)
                else:
                    self._window.setProperty("homeSelection", current + 1)
                return True
            if intent is ControlIntent.LEFT:
                if int(self._window.property("homeFocusArea")) == 1:
                    current = int(self._window.property("homeCardSelection"))
                    self._window.setProperty(
                        "homeCardSelection",
                        max(0, current - 1),
                    )
                    return True
                return False
            if intent is ControlIntent.RIGHT:
                if int(self._window.property("homeFocusArea")) == 1:
                    current = int(self._window.property("homeCardSelection"))
                    self._window.setProperty(
                        "homeCardSelection",
                        min(3, current + 1),
                    )
                    return True
                return False
            if intent is ControlIntent.SELECT:
                if int(self._window.property("homeFocusArea")) == 1:
                    self.activateHomeCard(
                        int(self._window.property("homeCardSelection"))
                    )
                    return True
                return self._activate_home_menu_selection(
                    int(self._window.property("homeSelection"))
                )
            return False

        if screen == "settings":
            if intent is ControlIntent.BACK:
                return self._go_home()
            if intent is ControlIntent.UP:
                current = int(self._window.property("settingsSelection"))
                self._window.setProperty(
                    "settingsSelection",
                    max(0, current - 1),
                )
                return True
            if intent is ControlIntent.DOWN:
                current = int(self._window.property("settingsSelection"))
                self._window.setProperty(
                    "settingsSelection",
                    min(4, current + 1),
                )
                return True
            if intent in {ControlIntent.LEFT, ControlIntent.RIGHT}:
                direction = -1 if intent is ControlIntent.LEFT else 1
                return self._adjust_selected_setting(direction)
            if intent is ControlIntent.SELECT:
                selection = int(self._window.property("settingsSelection"))
                if selection == 4:
                    result = self._controller.resetSettings()
                    self._notify(result)
                    self._window.setProperty(
                        "volumePercent",
                        int(result.get("volume", 100)),
                    )
                    self._window.setProperty(
                        "muted",
                        bool(result.get("muted", False)),
                    )
                    return True
                return self._adjust_selected_setting(1)
            return False

        if screen == "library":
            if intent is ControlIntent.BACK:
                self._window.setProperty("screen", "home")
                return True

            if intent is ControlIntent.ADD_MEDIA_SOURCE:
                self._choose_and_scan_media_folder()
                self._select_library(
                    int(self._window.property("selectedLibrary"))
                )
                return True

            if intent is ControlIntent.UP:
                self._select_library(
                    int(self._window.property("selectedLibrary")) - 1
                )
                return True

            if intent is ControlIntent.DOWN:
                self._select_library(
                    int(self._window.property("selectedLibrary")) + 1
                )
                return True

            if intent is ControlIntent.SELECT:
                if not self._library_items():
                    self._notify(
                        {
                            "message": (
                                "Library is empty - press A "
                                "to add a media folder"
                            )
                        }
                    )
                    return True

                self._window.setProperty("screen", "ondemand")
                QApplication.processEvents()

                result = self._controller.playLibraryIndex(
                    int(self._window.property("selectedLibrary"))
                )
                self._notify(result)

                if not bool(result.get("ok")):
                    self._window.setProperty("screen", "library")

                return True

            return False

        if screen == "guide":
            if intent is ControlIntent.BACK:
                self._window.setProperty("screen", "home")
                return True
            if intent is ControlIntent.UP:
                self._select_row(int(self._window.property("selectedRow")) - 1)
                return True
            if intent is ControlIntent.DOWN:
                self._select_row(int(self._window.property("selectedRow")) + 1)
                return True
            if intent is ControlIntent.LEFT:
                self._select_program_delta(-1)
                return True
            if intent is ControlIntent.RIGHT:
                self._select_program_delta(1)
                return True
            if intent is ControlIntent.GUIDE_NOW:
                row_index = int(self._window.property("selectedRow"))
                self._window.setProperty("selectedProgram", self._current_program_index(row_index))
                return True
            if intent is ControlIntent.SELECT:
                rows = self._rows()
                row_index = int(self._window.property("selectedRow"))
                if (
                    0 <= row_index < len(rows)
                    and bool(rows[row_index].get("isUnassigned"))
                ):
                    self._notify(
                        {
                            "message": (
                                "Channel 001 is unassigned - create Channel 001 "
                                "in Broadcaster to replace the static slot"
                            )
                        }
                    )
                    return True

                # Make the native video target visible before libVLC creates its
                # Windows video output. Some D3D11 paths will happily play audio
                # into a hidden HWND but never present frames after it is shown.
                self._window.setProperty("screen", "live")
                QApplication.processEvents()
                result = self._controller.activate_selection(
                    int(self._window.property("selectedRow")),
                    int(self._window.property("selectedProgram")),
                )
                self._notify(result)
                if not bool(result.get("ok")):
                    self._window.setProperty("screen", "guide")
                else:
                    self._show_live_hud()
                return True
            return False

        if screen == "ondemand":
            if intent is ControlIntent.DIGIT:
                self._queue_channel_digit(str(int(command.value or 0)))
                return True

            if self._channel_digits and intent is ControlIntent.SELECT:
                self._commit_channel_entry()
                return True

            if intent in {ControlIntent.CHANNEL_UP, ControlIntent.CHANNEL_DOWN}:
                self._controller.stopOnDemand()
                self._window.setProperty("screen", "live")
                QApplication.processEvents()
                delta = 1 if intent is ControlIntent.CHANNEL_UP else -1
                result = self._controller.changeChannel(delta)
                self._notify(result)
                if bool(result.get("ok")):
                    self._show_live_hud()
                else:
                    self._window.setProperty("screen", "library")
                return True

            if intent is ControlIntent.PREVIOUS_CHANNEL:
                self._controller.stopOnDemand()
                self._window.setProperty("screen", "live")
                QApplication.processEvents()

                result = self._controller.previousChannel()
                self._notify(result)

                if bool(result.get("ok")):
                    self._show_live_hud()
                else:
                    self._window.setProperty("screen", "library")
                return True

            if intent is ControlIntent.BACK:
                self._controller.stopOnDemand()
                self._window.setProperty("screen", "library")
                return True

            if intent in {
                ControlIntent.SELECT,
                ControlIntent.PLAY,
                ControlIntent.PAUSE,
                ControlIntent.PLAY_PAUSE,
            }:
                paused = bool(self._controller.onDemand.get("paused", False))
                if not self._transport_should_toggle(intent, paused=paused):
                    return True
                self._notify(
                    self._controller.toggleOnDemandPause()
                )
                return True

            if intent in {ControlIntent.LEFT, ControlIntent.REWIND, ControlIntent.SKIP_BACK}:
                self._notify(
                    self._controller.skipOnDemand(
                        -float(
                            self._controller.settings.get(
                                "skipBackSeconds",
                                10,
                            )
                        )
                    )
                )
                return True

            if intent in {
                ControlIntent.RIGHT,
                ControlIntent.FAST_FORWARD,
                ControlIntent.SKIP_FORWARD,
            }:
                self._notify(
                    self._controller.skipOnDemand(
                        float(
                            self._controller.settings.get(
                                "skipForwardSeconds",
                                30,
                            )
                        )
                    )
                )
                return True

            return False

        if screen != "live":
            return False

        if intent is ControlIntent.DIGIT:
            self._queue_channel_digit(str(int(command.value or 0)))
            return True

        if self._channel_digits and intent is ControlIntent.SELECT:
            self._commit_channel_entry()
            return True

        if intent is ControlIntent.BACK:
            return self._open_guide()
        if intent in {
            ControlIntent.SELECT,
            ControlIntent.PLAY,
            ControlIntent.PAUSE,
            ControlIntent.PLAY_PAUSE,
        }:
            paused = bool(self._controller.playback.get("paused", False))
            if not self._transport_should_toggle(intent, paused=paused):
                return True
            self._notify(self._controller.togglePause())
            self._show_live_hud()
            return True
        if intent in {ControlIntent.LEFT, ControlIntent.REWIND, ControlIntent.SKIP_BACK}:
            self._notify(
                self._controller.skip(
                    -float(
                        self._controller.settings.get(
                            "skipBackSeconds",
                            10,
                        )
                    )
                )
            )
            self._show_live_hud()
            return True
        if intent in {
            ControlIntent.RIGHT,
            ControlIntent.FAST_FORWARD,
            ControlIntent.SKIP_FORWARD,
        }:
            self._notify(
                self._controller.skip(
                    float(
                        self._controller.settings.get(
                            "skipForwardSeconds",
                            30,
                        )
                    )
                )
            )
            self._show_live_hud()
            return True
        if intent in {ControlIntent.UP, ControlIntent.CHANNEL_UP}:
            self._notify(self._controller.changeChannel(1))
            self._show_live_hud()
            return True
        if intent in {ControlIntent.DOWN, ControlIntent.CHANNEL_DOWN}:
            self._notify(self._controller.changeChannel(-1))
            self._show_live_hud()
            return True
        if intent is ControlIntent.GO_LIVE:
            self._notify(self._controller.goLive())
            self._show_live_hud()
            return True
        if intent is ControlIntent.PREVIOUS_CHANNEL:
            self._notify(self._controller.previousChannel())
            self._show_live_hud()
            return True
        if intent is ControlIntent.INFO:
            self._show_live_hud()
            return True
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        command = self.command_for_key(event.key())
        if command is None:
            return False
        return self.dispatch_command(command)


def _native_video_platform() -> str:
    platform_name = QGuiApplication.platformName().lower()
    if "windows" in platform_name:
        return "windows"
    if platform_name == "xcb":
        return "x11"
    if platform_name == "cocoa":
        return "macos"
    raise RuntimeError(
        f"Qt platform {platform_name!r} does not yet expose a supported native libVLC video target"
    )


def _start_home_video_when_ready(
    controller: CouchController,
    window: QWindow,
    video_window: QWindow,
) -> NativeWindowStartupGate:
    """Attach and start Home video after Qt realizes the native child window."""

    home_video_required = controller.homeTelevision.get("mode") != "static"

    def report_startup(message: str) -> None:
        # Use stdout so Windows PowerShell can capture diagnostics without
        # wrapping each line in a misleading NativeCommandError record.
        print(f"[ChannelOS Home video] {message}", flush=True)

    def sample_native_windows() -> NativeWindowSnapshot:
        return NativeWindowSnapshot(
            host_visible=bool(window.isVisible()),
            host_exposed=bool(window.isExposed()),
            video_visible=bool(video_window.isVisible()),
            video_exposed=bool(video_window.isExposed()),
            video_width=int(video_window.width()),
            video_height=int(video_window.height()),
            video_required=home_video_required,
        )

    def attach_surface_and_start_home() -> None:
        # Delay winId() until the QML WindowContainer has been shown and given
        # Qt/Windows an opportunity to realize the native child. Forcing the
        # handle before the host window was visible was part of the boot race.
        try:
            surface = NativeVideoSurface(
                _native_video_platform(),
                int(video_window.winId()),
            )
            controller.attach_video_surface(surface)
        except (RuntimeError, ValueError) as exc:
            controller.set_video_surface_error(str(exc))
            report_startup(f"surface attachment failed: {exc}")
            return

        report_startup(
            f"attached native surface {surface.window_id}; requesting Home playback"
        )
        controller.startHomePlayback()

    startup_gate = NativeWindowStartupGate(
        sample=sample_native_windows,
        schedule=QTimer.singleShot,
        start=attach_surface_and_start_home,
        report=report_startup,
    )
    startup_gate.begin()
    return startup_gate


def _attach_settings_overlay(
    engine: QQmlApplicationEngine,
    window: QObject,
) -> QQuickItem:
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parent / "qml" / "SettingsScreen.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    if component.isError():
        messages = "; ".join(error.toString() for error in component.errors())
        raise RuntimeError(f"SettingsScreen.qml could not be loaded: {messages}")
    item = component.create(engine.rootContext())
    if not isinstance(item, QQuickItem):
        if item is not None:
            item.deleteLater()
        raise RuntimeError("SettingsScreen.qml could not be created")
    item.setProperty("hostWindow", window)
    item.setParent(window)
    item.setParentItem(window.contentItem())
    item.setZ(95)
    return item



def run_qt(
    service: GuideService,
    television: TelevisionRuntime,
    library: MediaLibrary,
    *,
    windowed: bool = False,
) -> int:
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    app.setApplicationName("ChannelOS")
    app.setOrganizationName("ChannelOS")

    controller = CouchController(service, television, library)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("channelOS", controller)

    # Qt 6.8+ provides WindowContainer specifically for embedding a QWindow into
    # a Qt Quick scene. Let it own native parenting/geometry instead of manually
    # parenting a bare QWindow to the QQuickWindow, which proved unreliable on
    # the Windows D3D11/libVLC path.
    video_window = QWindow()
    video_window.setFlag(Qt.WindowType.FramelessWindowHint, True)
    video_window.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    engine.rootContext().setContextProperty("channelOSVideoWindow", video_window)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    roots = engine.rootObjects()
    if not roots:
        return 7

    window = roots[0]

    settings_item = _attach_settings_overlay(engine, window)

    key_filter = CouchKeyFilter(controller, window)
    app.installEventFilter(key_filter)
    window.homeMenuActivated.connect(key_filter.activateHomeMenu)
    window.homeCardActivated.connect(key_filter.activateHomeCard)

    # Keep Python-owned Qt wrappers alive for the duration of the QML window.
    window._channelos_key_filter = key_filter
    window._channelos_video_window = video_window
    window._channelos_settings_item = settings_item

    # The channel continues broadcasting independently of UI input.
    # Poll the Viewer Clock often enough that short-form captures hand off
    # cleanly at their scheduled boundaries.
    playback_timer = QTimer(window)
    playback_timer.setInterval(250)
    playback_timer.timeout.connect(controller.refreshPlayback)
    playback_timer.timeout.connect(controller.refreshOnDemand)
    playback_timer.start()
    window._channelos_playback_timer = playback_timer

    app.aboutToQuit.connect(controller.stop)

    if windowed:
        window.showNormal()
    else:
        window.showFullScreen()

    window._channelos_home_startup_gate = _start_home_video_when_ready(
        controller,
        window,
        video_window,
    )

    if not owns_application:
        return 0
    return int(app.exec())
