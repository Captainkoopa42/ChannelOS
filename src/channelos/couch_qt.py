from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QEvent, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog

from .artwork import MediaArtworkCache
from .couch_actions import CouchActions
from .couch_model import build_couch_snapshot
from .guide import GuideError, GuideService
from .library import IndexedMedia, MediaLibrary
from .on_demand import OnDemandSession, OnDemandState
from .playback import NativeVideoSurface, PlaybackError
from .runtime import ChannelRuntimeError, TelevisionRuntime, TuneDecision, utc_now
from .scanner import MediaScanner, ScanProgress, ScanSummary
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

    def __init__(
        self,
        service: GuideService,
        television: TelevisionRuntime,
        library: MediaLibrary,
    ) -> None:
        super().__init__()
        self._service = service
        self._library = library
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
        self._library_media: list[IndexedMedia] = []
        self._library_snapshot = self._build_library_snapshot()
        self._on_demand_view: dict[str, object] = {"active": False}
        self._snapshot = build_couch_snapshot(service)
        self._playback: dict[str, object] = {"active": False}
        self._home_television = self._build_home_television_view()
        self._surface_ready = False
        self._surface_error = "embedded video surface has not been created"
        self._volume = 100
        self._muted = False

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

        items: list[dict[str, object]] = []
        for media in unique:
            path = media.location.path
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
        self._on_demand_view = self._on_demand_state_view(
            self._on_demand.state()
        )
        self.onDemandChanged.emit()

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
            state = self._on_demand.play_media(
                self._library_media[selected]
            )
            self._on_demand.set_volume(self._volume)
            self._on_demand.set_muted(self._muted)
            self._on_demand_view = self._on_demand_state_view(state)
            self.onDemandChanged.emit()

            return {
                "ok": True,
                "message": f"On Demand - {state.title}",
                "onDemand": self._on_demand_view,
            }

        except (PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def toggleOnDemandPause(self) -> dict[str, object]:
        try:
            state = self._on_demand.toggle_pause()
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
        self._on_demand.stop()
        self._on_demand_view = {"active": False}
        self.onDemandChanged.emit()
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

    @Slot(int, result="QVariantMap")
    def changeVolume(self, delta: int) -> dict[str, object]:
        try:
            self._volume = max(
                0,
                min(100, self._volume + int(delta)),
            )
            self._muted = False
            self._apply_audio_state()
            return {
                "ok": True,
                "message": f"Volume {self._volume}%",
                "volume": self._volume,
                "muted": self._muted,
            }
        except (PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def toggleMute(self) -> dict[str, object]:
        try:
            self._muted = not self._muted
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
            }
        except (PlaybackError, ValueError) as exc:
            return self._error(exc)

    def stop(self) -> None:
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

    def _handle_audio_key(self, key: int) -> bool:
        if key in {Qt.Key.Key_Plus, Qt.Key.Key_Equal}:
            result = self._controller.changeVolume(5)
        elif key == Qt.Key.Key_Minus:
            result = self._controller.changeVolume(-5)
        elif key == Qt.Key.Key_M:
            result = self._controller.toggleMute()
        else:
            return False

        self._notify(result)
        self._show_audio_hud(result)
        return True

    @staticmethod
    def _digit_for_key(key: int) -> str | None:
        keys = {
            Qt.Key.Key_0: "0",
            Qt.Key.Key_1: "1",
            Qt.Key.Key_2: "2",
            Qt.Key.Key_3: "3",
            Qt.Key.Key_4: "4",
            Qt.Key.Key_5: "5",
            Qt.Key.Key_6: "6",
            Qt.Key.Key_7: "7",
            Qt.Key.Key_8: "8",
            Qt.Key.Key_9: "9",
        }
        return keys.get(key)

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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False

        key = event.key()
        screen = str(self._window.property("screen"))

        if screen == "home":
            if key == Qt.Key.Key_G:
                self._controller.refresh()
                self._window.setProperty("screen", "guide")
                self._select_guide_anchor()
                return True
            if key in {Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
                QGuiApplication.quit()
                return True
            if key == Qt.Key.Key_Up:
                current = int(self._window.property("homeSelection"))
                self._window.setProperty("homeSelection", max(0, current - 1))
                return True
            if key == Qt.Key.Key_Down:
                current = int(self._window.property("homeSelection"))
                self._window.setProperty("homeSelection", min(4, current + 1))
                return True
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                selection = int(self._window.property("homeSelection"))
                if selection == 1:
                    self._controller.refresh()
                    self._window.setProperty("screen", "guide")
                    self._select_guide_anchor()
                elif selection == 2:
                    self._controller.refreshLibrary()
                    self._window.setProperty("screen", "library")
                    self._select_library(
                        int(self._window.property("selectedLibrary"))
                    )
                elif selection == 0:
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
                    else:
                        self._window.setProperty("screen", "live")
                        QApplication.processEvents()
                        result = self._controller.enterLiveFromHome()
                        self._notify(result)
                        if bool(result.get("ok")):
                            self._show_live_hud()
                        else:
                            self._window.setProperty("screen", "home")
                else:
                    self._notify({"message": "This section is reserved for a later couch UI slice"})
                return True
            return False

        if screen == "library":
            if key in {Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
                self._window.setProperty("screen", "home")
                return True

            if key == Qt.Key.Key_A:
                self._choose_and_scan_media_folder()
                self._select_library(
                    int(self._window.property("selectedLibrary"))
                )
                return True

            if key == Qt.Key.Key_Up:
                self._select_library(
                    int(self._window.property("selectedLibrary")) - 1
                )
                return True

            if key == Qt.Key.Key_Down:
                self._select_library(
                    int(self._window.property("selectedLibrary")) + 1
                )
                return True

            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
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
            if key == Qt.Key.Key_G:
                self._controller.refresh()
                self._select_row(int(self._window.property("selectedRow")))
                return True
            if key in {Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
                self._window.setProperty("screen", "home")
                return True
            if key == Qt.Key.Key_Up:
                self._select_row(int(self._window.property("selectedRow")) - 1)
                return True
            if key == Qt.Key.Key_Down:
                self._select_row(int(self._window.property("selectedRow")) + 1)
                return True
            if key == Qt.Key.Key_Left:
                self._select_program_delta(-1)
                return True
            if key == Qt.Key.Key_Right:
                self._select_program_delta(1)
                return True
            if key == Qt.Key.Key_Home:
                row_index = int(self._window.property("selectedRow"))
                self._window.setProperty("selectedProgram", self._current_program_index(row_index))
                return True
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
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
            digit = self._digit_for_key(key)
            if digit is not None:
                self._queue_channel_digit(digit)
                return True

            if (
                self._channel_digits
                and key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            ):
                self._commit_channel_entry()
                return True

            if self._handle_audio_key(key):
                return True

            if key == Qt.Key.Key_P:
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

            if key in {Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
                self._controller.stopOnDemand()
                self._window.setProperty("screen", "library")
                return True

            if key == Qt.Key.Key_Space:
                self._notify(
                    self._controller.toggleOnDemandPause()
                )
                return True

            if key == Qt.Key.Key_Left:
                self._notify(
                    self._controller.skipOnDemand(-10.0)
                )
                return True

            if key == Qt.Key.Key_Right:
                self._notify(
                    self._controller.skipOnDemand(30.0)
                )
                return True

            return False

        if screen != "live":
            return False

        digit = self._digit_for_key(key)
        if digit is not None:
            self._queue_channel_digit(digit)
            return True

        if (
            self._channel_digits
            and key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
        ):
            self._commit_channel_entry()
            return True

        if self._handle_audio_key(key):
            return True

        if key in {Qt.Key.Key_G, Qt.Key.Key_Escape, Qt.Key.Key_Backspace}:
            self._controller.refresh()
            self._window.setProperty("screen", "guide")
            self._select_guide_anchor()
            return True
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self._notify(self._controller.togglePause())
            self._show_live_hud()
            return True
        if key == Qt.Key.Key_Left:
            self._notify(self._controller.skip(-10.0))
            self._show_live_hud()
            return True
        if key == Qt.Key.Key_Right:
            self._notify(self._controller.skip(30.0))
            self._show_live_hud()
            return True
        if key == Qt.Key.Key_Up:
            self._notify(self._controller.changeChannel(1))
            self._show_live_hud()
            return True
        if key == Qt.Key.Key_Down:
            self._notify(self._controller.changeChannel(-1))
            self._show_live_hud()
            return True
        if key == Qt.Key.Key_L:
            self._notify(self._controller.goLive())
            self._show_live_hud()
            return True
        if key == Qt.Key.Key_P:
            self._notify(self._controller.previousChannel())
            self._show_live_hud()
            return True
        return False


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

    key_filter = CouchKeyFilter(controller, window)
    app.installEventFilter(key_filter)

    # Keep Python-owned Qt wrappers alive for the duration of the QML window.
    window._channelos_key_filter = key_filter
    window._channelos_video_window = video_window

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
