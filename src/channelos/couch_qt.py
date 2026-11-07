from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Property, QCoreApplication, QEvent, QTimer, QUrl, Signal, Slot, Qt, SIGNAL
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeyEvent, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog

from .artwork import MediaArtworkCache
from .control import ControlCommand, ControlIntent
from .controller_qt import QtControllerInput
from .couch_actions import CouchActions
from .couch_model import GUIDE_REACH, _floor_to_half_hour, build_couch_snapshot, clamp_guide_start
from .diagnostics import LOG_DIRECTORY_ENV
from .guide import GuideError, GuideService
from .library import IndexedMedia, MediaLibrary
from .on_demand import OnDemandSession, OnDemandState
from .portable import host_data_directory
from .settings import PortableSettingsStore
from .playback import (
    AudioOutputDevice,
    NativeVideoSurface,
    PlaybackError,
    resolve_audio_output_device_id,
)
from .runtime import (
    ChannelRuntimeError,
    OnDemandWatchState,
    TelevisionRuntime,
    TuneDecision,
    utc_now,
)
from .settings import (
    ARTWORK_CACHE_LIMIT_CHOICES_MB,
    BOOT_VIDEO_CHOICES,
    LOADING_STYLE_CHOICES,
    PERFORMANCE_PROFILES,
    SKIP_BACK_CHOICES,
    SKIP_FORWARD_CHOICES,
    THEME_CHOICES,
    VIDEO_SETTING_CHOICES,
    CouchSettings,
    SettingsStore,
)
from .television import TelevisionSession
from .profiles import PROFILE_IDS, PROFILE_NAMES, VOLUME_LIMITS, ProfileStore, valid_pin
from .themes import (
    CUSTOM_PREFIX,
    PRESETS,
    ROLE_HINTS,
    ROLE_LABELS,
    ROLE_NAMES,
    CustomTheme,
    ThemeStore,
    derive_palette,
)
from .window_startup import NativeWindowSnapshot, NativeWindowStartupGate

logger = logging.getLogger(__name__)

# Settings-screen name -> (CouchSettings field, readable label).
VIDEO_SETTING_NAMES = {
    "videoAspectRatio": ("video_aspect_ratio", "Aspect ratio"),
    "videoFit": ("video_fit", "Picture fit"),
    "videoOverscan": ("video_overscan_percent", "Overscan trim"),
    "videoDeinterlace": ("video_deinterlace", "Deinterlace"),
    "videoHardwareDecoding": ("video_hardware_decoding", "Hardware decoding"),
    "videoBrightness": ("video_brightness", "Brightness"),
    "videoContrast": ("video_contrast", "Contrast"),
    "videoSaturation": ("video_saturation", "Saturation"),
}
VIDEO_VALUE_LABELS = {
    "auto": "Auto", "fit": "Fit (letterbox)", "fill": "Fill (crop edges)", "stretch": "Stretch",
    "off": "Off", "yadif": "Yadif", "yadif2x": "Yadif 2x", "bob": "Bob", "blend": "Blend", "linear": "Linear",
}
THEME_LABELS = {"channelos": "ChannelOS", "chromespace": "ChromeSpace"}
BOOT_VIDEO_LABELS = {"static": "TV Static", "custom": "My Video", "off": "Off"}
LOADING_STYLE_LABELS = {"classic": "Classic", "bar": "Fill Bar", "tv": "Dancing TV"}
BOOT_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".mpg", ".mpeg", ".gif"}


def video_value_label(field: str, value: object) -> str:
    if field == "video_overscan_percent":
        return "Off" if not value else f"{value}%"
    if field in {"video_brightness", "video_contrast", "video_saturation"}:
        return f"{value}%"
    if field == "video_hardware_decoding":
        return "Auto (GPU)" if value == "auto" else "Off (CPU)"
    return VIDEO_VALUE_LABELS.get(str(value), str(value))


def _resolved_audio_output_rows(
    discovered: tuple[AudioOutputDevice, ...],
    selected_device_id: str,
) -> tuple[list[dict[str, object]], str]:
    """Build stable Settings rows and fall back from a missing saved device."""

    devices: list[dict[str, object]] = [
        {
            "deviceId": "",
            "name": "System Default",
            "available": True,
        }
    ]
    known = {""}
    for device in discovered:
        if device.device_id in known:
            continue
        devices.append(
            {
                "deviceId": device.device_id,
                "name": device.name,
                "available": True,
            }
        )
        known.add(device.device_id)

    return devices, resolve_audio_output_device_id(
        selected_device_id,
        discovered,
    )


class CouchController(QObject):
    """Qt-facing adapter over ChannelOS Guide data and television control intents."""

    snapshotChanged = Signal()
    playbackChanged = Signal()
    homeTelevisionChanged = Signal()
    libraryChanged = Signal()
    libraryArtworkChanged = Signal('QVariantMap')
    libraryWatchChanged = Signal('QVariantMap')
    artworkEvicted = Signal(object)
    artworkCacheCleared = Signal('QVariantMap')
    libraryArtworkResolved = Signal(str, str, bool)
    onDemandChanged = Signal()
    settingsChanged = Signal()
    themeChanged = Signal()
    themesChanged = Signal()
    profileChanged = Signal()

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
        self._artwork_paths: dict[str, Path] = {}
        self._artwork_assets_by_path = {}
        self._artwork_pending: set[str] = set()
        self._artwork_unavailable: set[str] = set()
        self._artwork_dirty_assets: set[str] = set()
        self._artwork_queue: queue.Queue[tuple] = queue.LifoQueue()
        self._artwork_epoch = 0
        self._artwork_stopped = False
        self._artwork_worker: threading.Thread | None = None
        self._artwork_publish_timer = QTimer(self)
        self._artwork_publish_timer.setSingleShot(True)
        self._artwork_publish_timer.setInterval(120)
        self._artwork_publish_timer.timeout.connect(
            self._publish_library_artwork
        )
        self.libraryArtworkResolved.connect(self._accept_library_artwork)
        self.artworkEvicted.connect(self._accept_evicted_artwork)
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
        self._index_library_cards()
        self._library_revision = self._library_projection_revision()
        self._on_demand_view: dict[str, object] = {"active": False}
        # None follows the current half hour; otherwise the Guide window stays
        # on this absolute start while the user browses other times.
        self._guide_anchor = None
        self._snapshot = self._build_guide_snapshot()
        self._playback: dict[str, object] = {"active": False}
        self._home_television = self._build_home_television_view()
        self._surface_ready = False
        self._surface_error = "embedded video surface has not been created"
        self._settings_store = SettingsStore(
            self._runtime_store.database_path.with_name("settings.json")
        )
        if self._library.portable:
            self._settings_store = PortableSettingsStore(
                self._settings_store.path, self._library.portable,
                host_data_directory() / 'portable-devices' / (self._library.portable.setup_id + '.json'),
            )
        self._settings = self._settings_store.load()
        self._theme_store = ThemeStore(self._settings_store.path.parent / "themes")
        self._profile_store = ProfileStore(self._settings_store.path.parent / "profiles.json")
        self._profiles = self._profile_store.load()
        if self._profile_channel_filter() is not None:
            self._actions.set_channel_filter(self._profile_channel_filter())
            self._service = self._actions.service
        self._theme_preview: dict[str, object] | None = None
        self._theme_palette_cache: dict[str, dict[str, str]] = {}
        if self._settings.theme.startswith("custom-") and self._theme_store.get(self._settings.theme) is None:
            self._settings = replace(self._settings, theme="channelos")
        selected_audio_device = self._settings.audio_output_device_id
        self._audio_output_devices: list[dict[str, object]] = [
            {
                "deviceId": "",
                "name": "System Default",
                "available": True,
            }
        ]
        if selected_audio_device:
            self._audio_output_devices.append(
                {
                    "deviceId": selected_audio_device,
                    "name": "Saved device (currently unavailable)",
                    "available": False,
                }
            )
        self._actions.set_audio_output_device(selected_audio_device or None)
        self._on_demand.set_audio_output_device(selected_audio_device or None)
        self._actions.set_video_settings(self._settings.video)
        self._on_demand.set_video_settings(self._settings.video)
        cache_stats = None if getattr(self, '_defer_initial_views', False) else self._artwork_cache.stats()
        self._artwork_cache_bytes = 0 if cache_stats is None else cache_stats.size_bytes
        self._artwork_cache_files = 0 if cache_stats is None else cache_stats.file_count
        self._volume = self._settings.volume_percent
        self._muted = self._settings.muted

    def _build_library_snapshot(self) -> dict[str, object]:
        if getattr(self, '_defer_initial_views', False):
            return {'count': 0, 'locationCount': 0, 'sourceCount': 0, 'items': [], 'sources': []}
        from .library_view import build_library_view
        snapshot, self._library_media = build_library_view(self._library, self._runtime_store, self._artwork_urls)
        return snapshot

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
            "audioOutputDeviceId": self._settings.audio_output_device_id,
            "audioOutputDeviceName": self._audio_output_device_name(),
            "audioOutputDevices": self._audio_output_devices,
            "skipBackSeconds": self._settings.skip_back_seconds,
            "skipForwardSeconds": self._settings.skip_forward_seconds,
            "controllerEnabled": self._settings.controller_enabled,
            "performanceProfile": self._settings.performance_profile,
            "generateVideoThumbnails": (
                self._settings.generate_video_thumbnails
            ),
            "artworkCacheLimitMb": self._settings.artwork_cache_limit_mb,
            "backgroundArtworkDuringPlayback": (
                self._settings.background_artwork_during_playback
            ),
            "reducedMotion": self._settings.reduced_motion,
            "thumbnailWidth": self._settings.thumbnail_width,
            "ffmpegThreads": self._settings.ffmpeg_threads,
            "artworkCacheBytes": self._artwork_cache_bytes,
            "artworkCacheFiles": self._artwork_cache_files,
            **{
                name: video_value_label(field, getattr(self._settings, field))
                for name, (field, _label) in VIDEO_SETTING_NAMES.items()
            },
            "theme": self._settings.theme,
            "themeName": self._theme_name(self._settings.theme),
            "bootVideo": self._settings.boot_video,
            "bootVideoLabel": BOOT_VIDEO_LABELS[self._settings.boot_video],
            "bootVideoFile": self._settings.boot_video_file,
            "bootVideoSound": self._settings.boot_video_sound,
            "loadingStyle": self._settings.loading_style,
            "loadingStyleLabel": LOADING_STYLE_LABELS[self._settings.loading_style],
        }

    def _audio_output_device_name(self) -> str:
        selected = self._settings.audio_output_device_id
        for device in self._audio_output_devices:
            if str(device["deviceId"]) == selected:
                return str(device["name"])
        return "System Default" if not selected else "Unavailable device"

    @Slot(result="QVariantMap")
    def openDiagnosticLogs(self) -> dict[str, object]:
        configured = os.environ.get(LOG_DIRECTORY_ENV)
        logs_directory = (
            Path(configured)
            if configured
            else self._runtime_store.database_path.parent / "logs"
        )
        try:
            logs_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.exception("Diagnostic log directory could not be created")
            return self._error(exc)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_directory))):
            logger.error("The operating system did not open the diagnostic log folder")
            return {
                "ok": False,
                "message": f"Diagnostic logs are stored in {logs_directory}",
            }
        logger.info("Diagnostic log folder opened")
        return {
            "ok": True,
            "message": "Opened the ChannelOS diagnostic log folder",
        }

    @Slot(result="QVariantMap")
    def refreshAudioOutputDevices(self) -> dict[str, object]:
        """Refresh libVLC audio destinations without blocking Settings access."""

        try:
            discovered = self._actions.list_audio_output_devices()
            devices, effective_device_id = _resolved_audio_output_rows(
                discovered,
                self._settings.audio_output_device_id,
            )
        except (OSError, PlaybackError, ValueError) as exc:
            return {
                "ok": False,
                "message": f"Audio outputs could not be refreshed: {exc}",
                "settings": self.settings,
            }

        selected = self._settings.audio_output_device_id
        message = ""
        if selected != effective_device_id:
            settings = replace(
                self._settings,
                audio_output_device_id=effective_device_id,
            )
            try:
                self._settings_store.save(settings)
                self._settings = settings
                self._actions.set_audio_output_device(None)
                self._on_demand.set_audio_output_device(None)
            except (OSError, PlaybackError, ValueError) as exc:
                return {
                    "ok": False,
                    "message": f"Audio fallback could not be applied: {exc}",
                    "settings": self.settings,
                }
            message = (
                "The saved audio output is unavailable; using System Default."
            )

        self._audio_output_devices = devices
        self.settingsChanged.emit()
        return {
            "ok": True,
            "message": message,
            "settings": self.settings,
        }

    @Slot()
    def refresh(self) -> None:
        self._snapshot = self._build_guide_snapshot()
        self._home_television = self._build_home_television_view()
        self.snapshotChanged.emit()
        self.homeTelevisionChanged.emit()

    def _build_guide_snapshot(self):
        now = utc_now()
        return build_couch_snapshot(self._service, at=now, start=self._guide_window_start(now))

    def _guide_window_start(self, now):
        live = _floor_to_half_hour(now)
        anchor = getattr(self, "_guide_anchor", None)
        if anchor is None:
            return live
        start = clamp_guide_start(anchor, now)
        if start == live:
            # Browsing back to the present follows the clock again.
            self._guide_anchor = None
        return start

    def reset_guide_window(self) -> None:
        """Return the Guide to now without rebuilding (callers refresh)."""
        self._guide_anchor = None

    @Slot(float, result="QVariantMap")
    def shiftGuideWindow(self, minutes: float) -> dict[str, object]:
        """Page the Guide window by whole half hours within the two-week reach."""
        now = utc_now()
        current = self._guide_window_start(now)
        requested = current + timedelta(minutes=float(minutes))
        start = clamp_guide_start(requested, now)
        clamped = start != _floor_to_half_hour(requested)
        self._guide_anchor = None if start == _floor_to_half_hour(now) else start
        if start != current:
            self._snapshot = self._build_guide_snapshot()
            self.snapshotChanged.emit()
        result = {"ok": start != current, "clamped": clamped,
                  "startMs": int(start.timestamp() * 1000), "isLive": self._guide_anchor is None}
        if clamped:
            days = int(GUIDE_REACH.total_seconds() // 86400)
            result["message"] = f"The Guide shows {days} days back and ahead"
        return result

    @Slot(result="QVariantMap")
    def guideWindowToNow(self) -> dict[str, object]:
        moved = self._guide_anchor is not None
        self._guide_anchor = None
        if moved:
            self._snapshot = self._build_guide_snapshot()
            self.snapshotChanged.emit()
        return {"ok": True, "moved": moved}

    @Slot()
    def refreshLibrary(self) -> None:
        # A user may have added a sidecar image since the previous visit. Retry
        # unresolved visible cards on an explicit Library refresh.
        self._artwork_cache.clear_discovery_cache()
        self._artwork_unavailable.clear()
        revision = self._library_projection_revision()
        if revision == self._library_revision:
            return
        self._library_snapshot = self._build_library_snapshot()
        self._index_library_cards()
        self._library_revision = self._library_projection_revision()
        self.libraryChanged.emit()

    def _library_projection_revision(self):
        broadcaster = getattr(self, "_broadcaster", None)
        definitions = tuple((record.channel_number, record.definition) for record in broadcaster.records) if broadcaster else ()
        return self._library.revision(), definitions

    def _index_library_cards(self):
        self._library_cards = {str(item['assetId']): item for item in self._library_snapshot.get('items', ())}
        self._library_media_by_id = {item.asset.asset_id: item for item in self._library_media}

    @Slot(str, result=str)
    def requestLibraryArtwork(self, asset_id: str) -> str:
        target = str(asset_id)
        known = self._artwork_urls.get(target, "")
        if known:
            return known
        if target in self._artwork_pending or target in self._artwork_unavailable:
            return ""

        media = self._library_media_by_id.get(target)
        if media is None:
            self._artwork_unavailable.add(target)
            return ""

        self._artwork_pending.add(target)
        self._artwork_queue.put(
            (
                target,
                media.location.path,
                float(media.asset.duration_seconds or 0.0),
                self._artwork_epoch,
            )
        )
        self._start_artwork_worker()
        return ""

    def _start_artwork_worker(self):
        if self._artwork_worker is None:
            self._artwork_worker = threading.Thread(
                target=self._resolve_library_artwork,
                name="channelos-artwork",
                daemon=True,
            )
            self._artwork_worker.start()

    @Slot(bool)
    def setLibraryArtworkActive(self, active):
        if not active:
            self._artwork_epoch += 1
            self._artwork_pending.clear()

    def _resolve_library_artwork(self) -> None:
        while True:
            job = self._artwork_queue.get()
            asset_id, media_path, duration = job[:3]
            try:
                if self._artwork_stopped:
                    return
                if asset_id == '__clear__':
                    change = self._artwork_cache.clear_generated()
                    self._artwork_cache_bytes = change.remaining.size_bytes
                    self._artwork_cache_files = change.remaining.file_count
                    self.artworkEvicted.emit(change.removed_paths)
                    self.artworkCacheCleared.emit({'ok': True, 'message': f'Cleared {change.removed_files} generated thumbnails.',
                        'removedFiles': change.removed_files, 'removedBytes': change.removed_bytes})
                    continue
                if not asset_id:
                    change = self._artwork_cache.prune(int(duration) * 1024 * 1024)
                    self._artwork_cache_bytes = change.remaining.size_bytes
                    self._artwork_cache_files = change.remaining.file_count
                    self.artworkEvicted.emit(change.removed_paths)
                    continue
                if len(job) == 4 and job[3] != self._artwork_epoch:
                    continue
                settings = self._settings
                playback_active = (
                    self._on_demand.active
                    or bool(self._playback.get("active"))
                )
                deferred = bool(
                    settings.generate_video_thumbnails
                    and playback_active
                    and not settings.background_artwork_during_playback
                )
                resolved = self._artwork_cache.resolve(
                    media_path,
                    asset_id,
                    duration,
                    allow_generate=(
                        settings.generate_video_thumbnails and not deferred
                    ),
                    max_width=settings.thumbnail_width,
                    ffmpeg_threads=settings.ffmpeg_threads,
                )
                if (
                    resolved is not None
                    and resolved.parent == self._artwork_cache.cache_directory
                    and self._artwork_cache._is_generated_cache_file(resolved)
                ):
                    change = self._artwork_cache.prune(
                        settings.artwork_cache_limit_mb * 1024 * 1024
                    )
                    if not resolved.exists():
                        resolved = None
                    self._artwork_cache_bytes = change.remaining.size_bytes
                    self._artwork_cache_files = change.remaining.file_count
                    if change.removed_paths:
                        self.artworkEvicted.emit(change.removed_paths)
                if self._artwork_stopped:
                    return
                self.libraryArtworkResolved.emit(
                    asset_id,
                    "" if resolved is None else str(resolved),
                    deferred,
                )
            except Exception as exc:
                # Artwork is optional presentation. A failure must never take
                # down Library browsing or replace the established fallback.
                if not self._artwork_stopped:
                    if asset_id == '__clear__':
                        self.artworkCacheCleared.emit({'ok': False, 'message': str(exc)})
                    else:
                        self.libraryArtworkResolved.emit(asset_id, "", False)
            finally:
                self._artwork_queue.task_done()

    @Slot(str, str, bool)
    def _accept_library_artwork(
        self,
        asset_id: str,
        resolved_path: str,
        retryable: bool,
    ) -> None:
        self._artwork_pending.discard(asset_id)
        artwork_changed = False
        resolved = Path(resolved_path) if resolved_path else None
        if resolved is not None and resolved.exists():
            previous = self._artwork_paths.get(asset_id)
            if previous is not None and previous != resolved:
                self._artwork_assets_by_path.pop(previous, None)
            self._artwork_paths[asset_id] = resolved
            self._artwork_assets_by_path[resolved] = asset_id
            self._artwork_urls[asset_id] = QUrl.fromLocalFile(
                resolved_path
            ).toString()
            self._artwork_dirty_assets.add(asset_id)
            artwork_changed = True
        elif not retryable:
            self._artwork_unavailable.add(asset_id)
        if artwork_changed and not self._artwork_publish_timer.isActive():
            self._artwork_publish_timer.start()

    @Slot(object)
    def _accept_evicted_artwork(self, paths):
        for path in paths:
            asset_id = self._artwork_assets_by_path.pop(path, None)
            if asset_id and self._artwork_paths.get(asset_id) == path:
                self._artwork_paths.pop(asset_id, None)
                self._artwork_urls.pop(asset_id, None)
                self._artwork_dirty_assets.add(asset_id)
        if self._artwork_dirty_assets and not self._artwork_publish_timer.isActive():
            self._artwork_publish_timer.start()
        self.settingsChanged.emit()

    @Slot()
    def _publish_library_artwork(self) -> None:
        # Publish a bounded batch while other artwork requests are still pending.
        # Presentation changes never invalidate the Library's catalog projection.
        dirty = set(self._artwork_dirty_assets)
        self._artwork_dirty_assets.clear()
        if not dirty:
            return

        patches = {asset_id: self._artwork_urls.get(asset_id, '') for asset_id in dirty}
        for asset_id, url in patches.items():
            if asset_id in self._library_cards:
                self._library_cards[asset_id]['artworkUrl'] = url
        self.libraryArtworkChanged.emit(patches)
        self.settingsChanged.emit()

    @Slot()
    def refreshPlayback(self) -> None:
        if self._on_demand.active:
            return
        if self._actions.last_decision is None:
            return
        try:
            decision = self._actions.sync()
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            self._publish_playback_failure(exc)
            return

        self._playback = self._decision_view(decision)
        self._home_television = self._home_view_from_decision(decision, view=self._playback)
        self.playbackChanged.emit()
        self.homeTelevisionChanged.emit()

    @Slot()
    def refreshOnDemand(self) -> None:
        if not self._on_demand.active:
            return
        try:
            state = self._on_demand.state()
        except PlaybackError as exc:
            self._publish_playback_failure(exc)
            return
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
        card = self._library_cards.get(saved.asset_id)
        if card is not None:
            patch = {
                'continueWatching': saved.resumable,
                'watchPositionSeconds': saved.position_seconds,
                'watchProgress': saved.progress_fraction,
                'lastWatchedAt': saved.last_watched_at.isoformat(),
            }
            card.update(patch)
            self.libraryWatchChanged.emit({saved.asset_id: patch})
        return saved

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        self._actions.attach_video_surface(surface)
        self._on_demand.attach_video_surface(surface)
        self._surface_ready = True
        self._surface_error = ""
        # Validate a persisted audio destination before the first media load.
        # A disconnected headset must not leave an otherwise healthy startup
        # silently routed to a device that no longer exists.
        self.refreshAudioOutputDevices()

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
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            self._publish_playback_failure(exc)
            return
        self._publish(decision)

    def set_video_surface_error(self, message: str) -> None:
        self._surface_ready = False
        self._surface_error = message
        self._publish_playback_failure(
            PlaybackError(f"Native video surface is unavailable: {message}")
        )

    def _home_view_from_decision(
        self,
        decision: TuneDecision,
        *, view=None,
    ) -> dict[str, object]:
        view = dict(self._decision_view(decision) if view is None else view)
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
                "aheadSeconds": 0.0,
                "isAhead": False,
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

        broadcaster = getattr(self, "_broadcaster", None)
        if not runtime.channel_numbers and broadcaster is not None and broadcaster.records:
            definition = broadcaster.records[0].definition
            return {"active": False, "mode": "static", "isUnassigned": False,
                    "unavailable": True, "stateLabel": "MEDIA UNAVAILABLE",
                    "continueLabel": "Reconnect media in Library", "channelNumber": definition.channel,
                    "displayNumber": definition.display_number, "channelName": definition.name,
                    "title": "MEDIA UNAVAILABLE", "paused": False,
                    "message": "No channel media is available. Reconnect or scan a source in Library."}

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
            "aheadSeconds": 0.0,
            "isAhead": False,
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
        event = selected.event
        parent_title = ""
        if event.parent_program_asset_id:
            for program in self._actions.runtime.channels[decision.channel_number].channel.media:
                if program.asset.asset_id == event.parent_program_asset_id:
                    parent_title = program.location.path.stem
                    break
        break_start = break_end = None
        runtime = self._actions.runtime.channels[decision.channel_number]
        if event.break_id and runtime.break_store:
            plan = runtime.break_store.load_plan(event.break_id)
            if plan:
                break_start = plan.scheduled_at
                break_end = plan.scheduled_at + timedelta(seconds=plan.duration_seconds)
        return {
            "active": True,
            "breakStartMs": int(break_start.timestamp() * 1000) if break_start else 0,
            "breakEndMs": int(break_end.timestamp() * 1000) if break_end else 0,
            "breakRemainingSeconds": max(0.0, (break_end - decision.viewer_time_utc).total_seconds()) if break_end else 0,
            "channelNumber": decision.channel_number,
            "displayNumber": definition.display_number,
            "channelName": decision.channel_name,
            "title": selected.media.location.path.stem,
            "eventType": event.event_type,
            "isAdvertisement": event.event_type in {"advertisement", "transition"},
            "breakId": event.break_id or "",
            "parentProgramTitle": parent_title,
            "assetId": selected.media.asset.asset_id,
            "offsetSeconds": float(selected.offset_seconds),
            "lagSeconds": max(0.0, float(decision.lag_seconds)),
            "aheadSeconds": float(decision.ahead_seconds),
            "isAhead": bool(decision.is_ahead),
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
        self._home_television = self._home_view_from_decision(decision, view=self._playback)
        self.playbackChanged.emit()
        self.homeTelevisionChanged.emit()
        return {
            "ok": True,
            "message": TelevisionSession.describe(decision),
            "playback": self._playback,
        }

    def _publish_playback_failure(self, exc: Exception) -> dict[str, object]:
        """Expose decoder failures instead of leaving a blank native surface."""

        message = str(exc)
        if (
            not bool(self._playback.get("active"))
            and str(self._playback.get("error", "")) == message
        ):
            return {
                "ok": False,
                "message": message,
                "playback": self._playback,
            }
        logger.error(
            "Playback unavailable: %s",
            message,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        failed = dict(self._playback)
        failed["active"] = False
        failed["error"] = message
        self._playback = failed

        home = dict(self._home_television)
        home["playbackError"] = message
        home["stateLabel"] = "PLAYBACK UNAVAILABLE"
        self._home_television = home

        self.playbackChanged.emit()
        self.homeTelevisionChanged.emit()
        return {"ok": False, "message": message, "playback": failed}

    def _action_error(self, exc: Exception) -> dict[str, object]:
        if isinstance(exc, PlaybackError):
            return self._publish_playback_failure(exc)
        return self._error(exc)

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
        if schedule_id.startswith('channelos:pending:'):
            return {'ok': False, 'message': 'This Guide row is still loading. Try again in a moment.'}
        if schedule_id.startswith('channelos:guide-error:'):
            return {'ok': False, 'message': 'This schedule could not load. Refresh the Guide to retry.'}
        if any(definition.channel == channel_number for definition in self._service.unavailable_channels):
            return {"ok": False, "message": "This channel's media is unavailable. Reconnect or scan its source in Library."}
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
            return self._action_error(exc)

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
            if "error" in self._playback:
                self._playback = {"active": False}
                self.playbackChanged.emit()
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
            return self._action_error(exc)

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
            return self._action_error(exc)

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
            return self._action_error(exc)

    @Slot(result="QVariantMap")
    def stopOnDemand(self) -> dict[str, object]:
        if self._on_demand.active:
            try:
                self._persist_on_demand_state(
                    self._on_demand.state(),
                    force=True,
                )
            except PlaybackError:
                # Returning Home must remain available even when the decoder
                # has already failed and cannot provide a final playhead.
                pass
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
            return self._action_error(exc)

    @Slot(result="QVariantMap")
    def goLive(self) -> dict[str, object]:
        try:
            return self._publish(self._actions.go_live())
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._action_error(exc)

    @Slot(float, result="QVariantMap")
    def skip(self, delta_seconds: float) -> dict[str, object]:
        try:
            return self._publish(self._actions.skip(float(delta_seconds)))
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._action_error(exc)

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
            return self._action_error(exc)

    @Slot(int, result="QVariantMap")
    def tuneChannel(self, channel_number: int) -> dict[str, object]:
        if any(definition.channel == channel_number for definition in self._service.unavailable_channels):
            return {"ok": False, "message": "This channel's media is unavailable. Reconnect or scan its source in Library."}
        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}
        try:
            return self._publish(
                self._actions.tune(int(channel_number))
            )
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._action_error(exc)

    @Slot(result="QVariantMap")
    def previousChannel(self) -> dict[str, object]:
        try:
            return self._publish(self._actions.previous_channel())
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._action_error(exc)

    @Slot(result="QVariantMap")
    def continueWatching(self) -> dict[str, object]:
        if not self._surface_ready:
            return {"ok": False, "message": self._surface_error}
        try:
            return self._publish(
                self._actions.continue_watching(default_channel=1)
            )
        except (ChannelRuntimeError, PlaybackError, ValueError) as exc:
            return self._action_error(exc)

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
        previous = self._settings
        if previous == settings:
            return
        self._settings_store.save(settings)
        self._settings = settings
        self._volume = settings.volume_percent
        self._muted = settings.muted
        if (previous.generate_video_thumbnails, previous.thumbnail_width, previous.background_artwork_during_playback) != (settings.generate_video_thumbnails, settings.thumbnail_width, settings.background_artwork_during_playback):
            self._artwork_unavailable.clear()
        if previous.video != settings.video:
            self._actions.set_video_settings(settings.video)
            self._on_demand.set_video_settings(settings.video)
        if previous.artwork_cache_limit_mb != settings.artwork_cache_limit_mb:
            # Cache maintenance belongs to the existing serial artwork worker.
            self._artwork_queue.put(('', Path(), settings.artwork_cache_limit_mb))
            self._start_artwork_worker()
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
            limit = self._profiles.current.volume_limit
            volume = max(
                0,
                min(limit, self._volume + int(delta)),
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
            if name in VIDEO_SETTING_NAMES:
                field, label = VIDEO_SETTING_NAMES[name]
                choices, _default = VIDEO_SETTING_CHOICES[field]
                value = self._cycle_choice(getattr(self._settings, field), choices, step)
                settings = replace(self._settings, **{field: value})
                message = f"{label}: {video_value_label(field, value)}"
                if field in {"video_deinterlace", "video_hardware_decoding"}:
                    message += " (from the next program)"
                self._save_settings(settings)
                return {"ok": True, "message": message, "settings": self.settings}
            if name == "bootVideo":
                choices = tuple(c for c in BOOT_VIDEO_CHOICES if c != "custom" or self._boot_video_path())
                current = self._settings.boot_video if self._settings.boot_video in choices else "static"
                value = self._cycle_choice(current, choices, step)
                self._save_settings(replace(self._settings, boot_video=value))
                hint = "" if self._boot_video_path() else " (choose a video to add My Video)"
                return {"ok": True, "message": f"Boot video: {BOOT_VIDEO_LABELS[value]}{hint}", "settings": self.settings}
            if name == "bootVideoSound":
                value = not self._settings.boot_video_sound
                self._save_settings(replace(self._settings, boot_video_sound=value))
                return {"ok": True, "message": f"Boot video sound: {'On' if value else 'Off'}", "settings": self.settings}
            if name == "loadingStyle":
                value = self._cycle_choice(self._settings.loading_style, LOADING_STYLE_CHOICES, step)
                self._save_settings(replace(self._settings, loading_style=value))
                return {"ok": True, "message": f"Loading style: {LOADING_STYLE_LABELS[value]}", "settings": self.settings}
            if name == "theme":
                choices = tuple(THEME_CHOICES) + tuple(t.theme_id for t in self._theme_store.load())
                current = self._settings.theme if self._settings.theme in choices else "channelos"
                value = self._cycle_choice(current, choices, step)
                self._save_settings(replace(self._settings, theme=value))
                self.themeChanged.emit()
                return {"ok": True, "message": f"Theme: {self._theme_name(value)}", "settings": self.settings}
            if name == "performanceProfile":
                value = self._cycle_choice(
                    self._settings.performance_profile,
                    PERFORMANCE_PROFILES,
                    step,
                )
                settings = self._settings.with_performance_profile(value)
                message = f"Performance profile: {value.title()}"
            elif name == "audioOutput":
                current = self._settings.audio_output_device_id
                choices = tuple(
                    str(device["deviceId"])
                    for device in self._audio_output_devices
                    if bool(device["available"])
                    or str(device["deviceId"]) == current
                )
                if current not in choices:
                    current = ""
                index = choices.index(current)
                value = choices[(index + step) % len(choices)]
                settings = replace(
                    self._settings,
                    audio_output_device_id=value,
                )
                device_name = next(
                    str(device["name"])
                    for device in self._audio_output_devices
                    if str(device["deviceId"]) == value
                )
                message = f"Audio output: {device_name}"
            elif name == "skipBack":
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
            elif name == "generateVideoThumbnails":
                value = not self._settings.generate_video_thumbnails
                settings = replace(
                    self._settings,
                    performance_profile="custom",
                    generate_video_thumbnails=value,
                )
                message = (
                    "Generated video thumbnails on"
                    if value
                    else "Generated video thumbnails off"
                )
            elif name == "artworkCacheLimit":
                value = self._cycle_choice(
                    self._settings.artwork_cache_limit_mb,
                    ARTWORK_CACHE_LIMIT_CHOICES_MB,
                    step,
                )
                settings = replace(
                    self._settings,
                    performance_profile="custom",
                    artwork_cache_limit_mb=value,
                )
                message = (
                    "Artwork cache unlimited"
                    if value == 0
                    else f"Artwork cache limited to {value} MB"
                )
            elif name == "backgroundArtworkDuringPlayback":
                value = not self._settings.background_artwork_during_playback
                settings = replace(
                    self._settings,
                    performance_profile="custom",
                    background_artwork_during_playback=value,
                )
                message = (
                    "Background artwork during playback on"
                    if value
                    else "Background artwork waits until playback stops"
                )
            elif name == "reducedMotion":
                value = not self._settings.reduced_motion
                settings = replace(
                    self._settings,
                    performance_profile="custom",
                    reduced_motion=value,
                )
                message = "Reduced motion on" if value else "Reduced motion off"
            elif name == "controllerEnabled":
                value = not self._settings.controller_enabled
                settings = replace(
                    self._settings,
                    controller_enabled=value,
                )
                message = (
                    "Controller input on"
                    if value
                    else "Controller input off - use keyboard or mouse to turn it back on"
                )
            else:
                raise ValueError(f"unknown setting: {name}")

            self._save_settings(settings)
            if name == "audioOutput":
                selected = settings.audio_output_device_id or None
                self._actions.set_audio_output_device(selected)
                self._on_demand.set_audio_output_device(selected)
            return {
                "ok": True,
                "message": message,
                "settings": self.settings,
            }
        except (OSError, PlaybackError, ValueError) as exc:
            return self._error(exc)

    @Slot(result="QVariantMap")
    def clearArtworkCache(self) -> dict[str, object]:
        """Clear generated thumbnails without touching media or sidecar art."""

        try:
            change = self._artwork_cache.clear_generated()
            self._artwork_unavailable.clear()
            self._artwork_cache_bytes = change.remaining.size_bytes
            self._artwork_cache_files = change.remaining.file_count
            self._accept_evicted_artwork(change.removed_paths)
            self._publish_library_artwork()
            return {
                "ok": True,
                "message": (
                    f"Cleared {change.removed_files} generated thumbnails "
                    f"({change.removed_bytes / (1024 * 1024):.1f} MB). "
                    "Media and sidecar images were untouched."
                ),
                "removedFiles": change.removed_files,
                "removedBytes": change.removed_bytes,
                "settings": self.settings,
            }
        except OSError as exc:
            return self._error(exc)

    @Slot(result='QVariantMap')
    def beginArtworkCacheClear(self):
        self._artwork_epoch += 1
        self._artwork_pending.clear()
        self._artwork_unavailable.clear()
        self._artwork_queue.put(('__clear__', Path(), 0))
        self._start_artwork_worker()
        return {'ok': True, 'pending': True, 'message': 'Clearing generated thumbnails…'}

    # --- Themes -------------------------------------------------------------

    def _theme_name(self, theme_id: str) -> str:
        if theme_id in THEME_LABELS:
            return THEME_LABELS[theme_id]
        theme = self._theme_store.get(theme_id)
        return theme.name if theme else "ChannelOS"

    def _image_url(self, name: str) -> str:
        path = self._theme_store.image_path(name)
        return QUrl.fromLocalFile(str(path)).toString() if path else ""

    def _custom_spec(self, theme: CustomTheme) -> dict[str, object]:
        key = json.dumps(theme.to_mapping(), sort_keys=True)
        palette = self._theme_palette_cache.get(key)
        if palette is None:
            palette = derive_palette(theme.roles, panel_opacity=theme.panel_opacity if theme.wallpaper else 100)
            self._theme_palette_cache = {key: palette}  # active + one preview is enough
        return {"name": theme.theme_id, "palette": palette, "wallpaper": self._image_url(theme.wallpaper),
                "wallpaperFit": theme.wallpaper_fit, "wallpaperOpacity": theme.wallpaper_opacity}

    @Property("QVariantMap", notify=themeChanged)
    def themeSpec(self) -> dict[str, object]:
        """What Theme.qml shows now: a saved theme, or a Theme Builder preview."""
        if self._theme_preview is not None:
            return self._theme_preview
        theme_id = self._settings.theme
        if theme_id.startswith(CUSTOM_PREFIX):
            theme = self._theme_store.get(theme_id)
            if theme is not None:
                return self._custom_spec(theme)
            theme_id = "channelos"
        return {"name": theme_id, "palette": {}, "wallpaper": "", "wallpaperFit": "fill", "wallpaperOpacity": 100}

    @Property("QVariantList", notify=themesChanged)
    def themes(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = [
            {"id": theme_id, "name": THEME_LABELS[theme_id], "builtin": True, "roles": dict(PRESETS[theme_id]),
             "wallpaper": "", "wallpaperUrl": "", "wallpaperFit": "fill", "wallpaperOpacity": 100, "panelOpacity": 100}
            for theme_id in THEME_CHOICES
        ]
        for theme in self._theme_store.load():
            row = theme.to_mapping()
            row.update(builtin=False, wallpaperUrl=self._image_url(theme.wallpaper))
            rows.append(row)
        return rows

    @Property("QVariantList", constant=True)
    def themeRoles(self) -> list[dict[str, str]]:
        return [{"key": name, "label": ROLE_LABELS[name], "hint": ROLE_HINTS[name]} for name in ROLE_NAMES]

    @Slot(str, result="QVariantMap")
    def previewTheme(self, draft_json: str) -> dict[str, object]:
        """Show an unsaved Theme Builder draft across the whole app."""
        try:
            draft = CustomTheme.from_mapping(json.loads(draft_json))
        except (TypeError, ValueError) as exc:
            return {"ok": False, "message": str(exc)}
        self._theme_preview = self._custom_spec(draft)
        self.themeChanged.emit()
        return {"ok": True}

    @Slot()
    def endThemePreview(self) -> None:
        if self._theme_preview is not None:
            self._theme_preview = None
            self.themeChanged.emit()

    @Slot(str, bool, result="QVariantMap")
    def saveTheme(self, draft_json: str, use: bool) -> dict[str, object]:
        try:
            theme = self._theme_store.save(json.loads(draft_json))
            if use:
                self._save_settings(replace(self._settings, theme=theme.theme_id))
        except (OSError, TypeError, ValueError) as exc:
            return self._error(exc)
        self._theme_preview = None
        self.themesChanged.emit()
        self.themeChanged.emit()
        message = f"Saved theme {theme.name}" + (" and switched to it" if use else "")
        return {"ok": True, "id": theme.theme_id, "message": message, "settings": self.settings}

    @Slot(str, result="QVariantMap")
    def useTheme(self, theme_id: str) -> dict[str, object]:
        if theme_id not in THEME_CHOICES and self._theme_store.get(theme_id) is None:
            return {"ok": False, "message": "That theme no longer exists"}
        try:
            self._save_settings(replace(self._settings, theme=theme_id))
        except OSError as exc:
            return self._error(exc)
        self._theme_preview = None
        self.themeChanged.emit()
        return {"ok": True, "message": f"Theme: {self._theme_name(theme_id)}", "settings": self.settings}

    @Slot(str, result="QVariantMap")
    def deleteTheme(self, theme_id: str) -> dict[str, object]:
        if not theme_id.startswith(CUSTOM_PREFIX):
            return {"ok": False, "message": "Built-in themes cannot be deleted"}
        name = self._theme_name(theme_id)
        try:
            self._theme_store.delete(theme_id)
            if self._settings.theme == theme_id:
                self._save_settings(replace(self._settings, theme="channelos"))
        except OSError as exc:
            return self._error(exc)
        self.themesChanged.emit()
        self.themeChanged.emit()
        return {"ok": True, "message": f"Deleted theme {name}", "settings": self.settings}

    @Slot(result="QVariantMap")
    def chooseThemeImage(self) -> dict[str, object]:
        """Pick a wallpaper; it is copied into the setup's themes folder."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Choose a theme image", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return {"ok": False, "cancelled": True, "message": ""}
        return self.importThemeImage(path)

    @Slot(str, result="QVariantMap")
    def importThemeImage(self, path: str) -> dict[str, object]:
        try:
            name = self._theme_store.import_image(path)
        except (OSError, ValueError) as exc:
            return self._error(exc)
        return {"ok": True, "file": name, "url": self._image_url(name), "message": "Image added"}

    # --- Profiles -------------------------------------------------------------

    def _profile_channel_filter(self):
        channels = self._profiles.current.channels
        return None if channels is None else frozenset(channels)

    def profile_allows_screen(self, screen: str) -> bool:
        return self._profiles.current.allows_screen(screen)

    @Property("QVariantMap", notify=profileChanged)
    def profile(self) -> dict[str, object]:
        current = self._profiles.current
        return dict(current.to_mapping(), id=current.profile_id, name=current.name, hasPin=self._profiles.has_pin)

    @Property("QVariantList", notify=profileChanged)
    def profiles(self) -> list[dict[str, object]]:
        return [dict(self._profiles.profiles[pid].to_mapping(), id=pid, name=PROFILE_NAMES[pid],
                     active=pid == self._profiles.active) for pid in PROFILE_IDS]

    @Property("QVariantList", notify=profileChanged)
    def profileChannelChoices(self) -> list[dict[str, object]]:
        """Every channel in the setup, for choosing what a profile shows."""
        return [{"number": number, "name": record.definition.name}
                for number, record in sorted((r.channel_number, r) for r in self._broadcaster_records())]

    def _broadcaster_records(self):
        broadcaster = getattr(self, "_broadcaster", None)
        if broadcaster is not None:
            return tuple(broadcaster.records)
        return tuple(type("Record", (), {"channel_number": r.channel_number, "definition": r.channel.definition})
                     for r in self._actions.full_channels.values())

    def _apply_profile(self) -> None:
        """Install the active profile: lineup, volume limit, then views."""
        self._actions.set_channel_filter(self._profile_channel_filter())
        self._service = self._actions.service
        limit = self._profiles.current.volume_limit
        if self._volume > limit:
            self._save_settings(replace(self._settings, volume_percent=limit))
            try:
                self._apply_audio_state()
            except (OSError, PlaybackError, ValueError):
                logger.exception("Volume limit could not be applied")
        self.refresh()
        self.profileChanged.emit()

    @Slot(str, result="QVariantMap")
    def setProfilePin(self, pin: str) -> dict[str, object]:
        if self._profiles.current.locked:
            return {"ok": False, "message": "Leave this profile to change the PIN"}
        try:
            self._profiles = self._profile_store.save(ProfileStore.with_pin(self._profiles, str(pin)))
        except (OSError, ValueError) as exc:
            return self._error(exc)
        self.profileChanged.emit()
        return {"ok": True, "message": "PIN saved. Locked profiles now need it to leave."}

    @Slot(str, result="QVariantMap")
    def activateProfile(self, profile_id: str) -> dict[str, object]:
        if profile_id not in PROFILE_IDS:
            return {"ok": False, "message": "Unknown profile"}
        if self._profiles.current.locked and profile_id != self._profiles.active:
            return {"ok": False, "needPin": True, "message": "Enter the PIN to leave this profile"}
        target = self._profiles.profiles[profile_id]
        if target.locked and not self._profiles.has_pin:
            return {"ok": False, "message": "Set a PIN first (Settings → Profiles), so you can leave again"}
        if target.locked and target.channels == ():
            return {"ok": False, "message": f"Choose channels for {target.name} first"}
        from dataclasses import replace as dc_replace
        try:
            self._profiles = self._profile_store.save(dc_replace(self._profiles, active=profile_id))
        except OSError as exc:
            return self._error(exc)
        self._apply_profile()
        return {"ok": True, "message": f"{target.name} profile is on", "profile": self.profile}

    @Slot(str, result="QVariantMap")
    def unlockProfile(self, pin: str) -> dict[str, object]:
        """The PIN pad: the right PIN leaves a locked profile for Home."""
        if not self._profiles.current.locked:
            return {"ok": True, "message": ""}
        if not self._profiles.check_pin(str(pin)):
            return {"ok": False, "message": "Wrong PIN"}
        from dataclasses import replace as dc_replace
        name = self._profiles.current.name
        try:
            self._profiles = self._profile_store.save(dc_replace(self._profiles, active="home"))
        except OSError as exc:
            return self._error(exc)
        self._apply_profile()
        return {"ok": True, "message": f"Left {name}. Home profile is on."}

    @Slot(str, str, result="QVariantMap")
    def updateProfile(self, profile_id: str, changes_json: str) -> dict[str, object]:
        if self._profiles.current.locked:
            return {"ok": False, "message": "Leave this profile to edit profiles"}
        try:
            changes = json.loads(changes_json)
            if not isinstance(changes, dict):
                raise ValueError("Profile changes must be an object")
            self._profiles = self._profile_store.save(ProfileStore.updated(self._profiles, profile_id, changes))
        except (OSError, TypeError, ValueError) as exc:
            return self._error(exc)
        self.profileChanged.emit()
        return {"ok": True, "message": f"{PROFILE_NAMES.get(profile_id, profile_id)} profile saved",
                "profile": dict(self._profiles.profiles[profile_id].to_mapping(), id=profile_id)}

    @Property("QVariantList", constant=True)
    def profileVolumeLimits(self) -> list[int]:
        return list(VOLUME_LIMITS)

    # --- Boot video -----------------------------------------------------------

    def _boot_directory(self) -> Path:
        return self._settings_store.path.parent / "boot"

    def _boot_video_path(self) -> Path | None:
        name = self._settings.boot_video_file
        path = self._boot_directory() / name if name else None
        return path if path is not None and path.is_file() else None

    @Slot(result="QVariantMap")
    def chooseBootVideo(self) -> dict[str, object]:
        """Pick a boot video; it is copied into the setup's boot folder."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Choose a boot video", str(Path.home()),
            "Videos (*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.wmv *.mpg *.mpeg *.gif)")
        if not path:
            return {"ok": False, "cancelled": True, "message": ""}
        return self.importBootVideo(path)

    @Slot(str, result="QVariantMap")
    def importBootVideo(self, path: str) -> dict[str, object]:
        import shutil
        import uuid
        source = Path(path)
        try:
            if source.suffix.lower() not in BOOT_VIDEO_SUFFIXES:
                raise ValueError("Choose a video file such as MP4, MKV, WebM or MOV")
            if not source.is_file():
                raise ValueError(f"Video not found: {source}")
            if source.stat().st_size > 500 * 1024 * 1024:
                raise ValueError("That video is over 500 MB. Choose a shorter boot video.")
            directory = self._boot_directory()
            directory.mkdir(parents=True, exist_ok=True)
            name = f"boot-{uuid.uuid4().hex[:10]}{source.suffix.lower()}"
            shutil.copyfile(source, directory / name)
            previous = self._boot_video_path()
            self._save_settings(replace(self._settings, boot_video="custom", boot_video_file=name))
            if previous is not None and previous.name != name:
                previous.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            return self._error(exc)
        return {"ok": True, "message": f"Boot video set: {source.name}", "settings": self.settings}

    @Slot(result="QVariantMap")
    def bootPreview(self) -> dict[str, object]:
        """What the Settings preview plays: the boot video URL, if any."""
        path = self._boot_video_path() if self._settings.boot_video == "custom" else None
        return {"video": self._settings.boot_video, "url": QUrl.fromLocalFile(str(path)).toString() if path else "",
                "loadingStyle": self._settings.loading_style}

    @Slot(int, int)
    def setVideoSurfaceSize(self, width: int, height: int) -> None:
        """The native video window resized: fill/stretch follow its shape."""
        if int(width) <= 0 or int(height) <= 0:
            return
        self._actions.set_surface_size(int(width), int(height))
        self._on_demand.set_surface_size(int(width), int(height))

    @Slot(result="QVariantMap")
    def resetSettings(self) -> dict[str, object]:
        try:
            self._save_settings(CouchSettings())
            self._theme_preview = None
            self.themeChanged.emit()
            self._actions.set_audio_output_device(None)
            self._on_demand.set_audio_output_device(None)
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
        self._artwork_stopped = True
        self._artwork_queue.put(('', Path(), 0))
        if self._on_demand.active:
            self._persist_on_demand_state(
                self._on_demand.state(),
                force=True,
            )
        self._on_demand.stop()
        self._actions.stop()
        for runtime in self._actions.runtime.channels.values():
            if runtime.break_store is not None:
                runtime.break_store.close()


def connect_screen_changed(window, callback) -> None:
    """Connect the QML page notification rather than QWindow's monitor signal.

    Main.qml's string `screen` has a no-argument notify signal, while PySide's
    attribute resolves to the inherited screenChanged(QScreen*) overload.
    """
    if isinstance(window, QObject):
        meta = window.metaObject()
        index = meta.indexOfProperty("screen")
        if index >= 0:
            prop = meta.property(index)
            if prop.hasNotifySignal():
                signature = bytes(prop.notifySignal().methodSignature()).decode()
                QObject.connect(window, SIGNAL(signature), callback)
                return
    changed = getattr(window, "screenChanged", None)
    if changed is not None:
        changed.connect(callback)


_FOCUS_NAVIGATION_INTENTS = frozenset({
    ControlIntent.UP, ControlIntent.DOWN, ControlIntent.LEFT, ControlIntent.RIGHT, ControlIntent.SELECT})


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
        self._home_scan_dialog: QProgressDialog | None = None
        connect_screen_changed(window, self._channel_entry_screen_changed)
        connect_screen_changed(window, self._guard_profile_screen)
        self._allowed_screen = "home"
        self._profile_checked = None
        profile_changed = getattr(controller, "profileChanged", None)
        if profile_changed is not None:
            profile_changed.connect(self._profile_changed)
            # A Lobby setup boots straight to its channel once video can play.
            QTimer.singleShot(800, lambda: self._enter_profile_start(attempts=40))
        scan_changed = getattr(controller, "libraryScanChanged", None)
        if scan_changed is not None:
            scan_changed.connect(self._update_home_scan_dialog)

    # --- Profiles -------------------------------------------------------------

    def _current_profile(self):
        profiles = getattr(self._controller, "_profiles", None)
        return profiles.current if profiles is not None else None

    def _show_pin_pad(self, reason: str = "") -> None:
        profile = self._current_profile()
        name = profile.name if profile is not None else "this profile"
        self._window.setProperty("pinPadTitle", f"Enter PIN to leave {name}")
        self._window.setProperty("pinPadReason", reason)
        self._window.setProperty("pinPadVisible", True)

    def _profile_guard(self, command: ControlCommand) -> bool:
        """Locked profiles: ignore what they forbid, or ask for the PIN.

        Returns True when the command was consumed here.
        """
        if self._profile_checked is True:
            return False  # BroadcasterKeyFilter checked this command already
        if bool(self._window.property("pinPadVisible")):
            digit = command.value if command.intent is ControlIntent.DIGIT else -1
            QMetaObject.invokeMethod(self._window, "handlePinIntent", Qt.ConnectionType.DirectConnection,
                                     Q_ARG("QVariant", command.intent.value), Q_ARG("QVariant", digit))
            return True
        profile = self._current_profile()
        if profile is None or not profile.locked:
            return False
        intent = command.intent
        screen = str(self._window.property("screen"))
        channel_intents = {ControlIntent.CHANNEL_UP, ControlIntent.CHANNEL_DOWN, ControlIntent.PREVIOUS_CHANNEL,
                           ControlIntent.DIGIT, ControlIntent.TUNE}
        seek_intents = {ControlIntent.SKIP_BACK, ControlIntent.SKIP_FORWARD, ControlIntent.REWIND,
                        ControlIntent.FAST_FORWARD}
        if intent is ControlIntent.SETTINGS or intent is ControlIntent.CHANNELS:
            self._show_pin_pad()
            return True
        if intent is ControlIntent.POWER:
            self._show_pin_pad("Closing ChannelOS needs the PIN")
            return True
        if intent is ControlIntent.HOME and not profile.home:
            self._show_pin_pad()
            return True
        if intent is ControlIntent.BACK and screen in {"live", "ondemand"} and not profile.home:
            return True  # Lobby stays on its channel
        if intent is ControlIntent.GUIDE and not profile.guide:
            self._notify({"message": f"The Guide is off in {profile.name}"})
            return True
        if intent is ControlIntent.LIBRARY and not profile.ondemand:
            self._notify({"message": f"On Demand is off in {profile.name}"})
            return True
        if intent in channel_intents and not profile.change_channels:
            self._notify({"message": f"Changing channels is off in {profile.name}"})
            return True
        if intent in seek_intents and not profile.seek and screen in {"live", "ondemand"}:
            self._notify({"message": f"Skipping is off in {profile.name}"})
            return True
        return False

    def _guard_profile_screen(self) -> None:
        """Whatever opened a screen (key, click, QML), a locked profile
        sends it back and asks for the PIN."""
        screen = str(self._window.property("screen"))
        profile = self._current_profile()
        if profile is None or profile.allows_screen(screen):
            self._allowed_screen = screen
            return
        fallback = self._allowed_screen if profile.allows_screen(self._allowed_screen) else (
            "home" if profile.home else "live")
        QTimer.singleShot(0, lambda: self._window.setProperty("screen", fallback))
        self._show_pin_pad()

    @Slot(str)
    def submitPin(self, pin: str) -> None:
        result = self._controller.unlockProfile(pin)
        if bool(result.get("ok")):
            self._window.setProperty("pinPadVisible", False)
            self._notify(result)
        else:
            QMetaObject.invokeMethod(self._window, "pinRejected", Qt.ConnectionType.DirectConnection,
                                     Q_ARG("QVariant", str(result.get("message", "Wrong PIN"))))

    def _profile_changed(self) -> None:
        self._controller.refresh()
        profile = self._current_profile()
        if profile is None:
            return
        screen = str(self._window.property("screen"))
        if not profile.allows_screen(screen):
            self._window.setProperty("screen", "home" if profile.home else "live")
        self._enter_profile_start(attempts=10)

    def _enter_profile_start(self, attempts: int) -> None:
        """Profiles without Home (Lobby) play their channel full screen."""
        profile = self._current_profile()
        if profile is None or profile.home:
            return
        if not getattr(self._controller, "_surface_ready", False):
            if attempts > 0:
                QTimer.singleShot(1000, lambda: self._enter_profile_start(attempts - 1))
            return
        numbers = sorted(getattr(self._controller._actions.runtime, "channels", {}) or {})
        if not numbers:
            return
        target = profile.boot_channel if profile.boot_channel in numbers else numbers[0]
        playback = self._controller.playback if isinstance(self._controller.playback, dict) else {}
        if bool(playback.get("active")) and int(playback.get("channelNumber", -1)) == target:
            self._window.setProperty("screen", "live")
            return
        self._window.setProperty("screen", "live")
        QApplication.processEvents()
        self._notify(self._controller.tuneChannel(target))

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
            Qt.Key.Key_Back: ControlIntent.BACK,
            Qt.Key.Key_Up: ControlIntent.UP,
            Qt.Key.Key_Down: ControlIntent.DOWN,
            Qt.Key.Key_Left: ControlIntent.LEFT,
            Qt.Key.Key_Right: ControlIntent.RIGHT,
            Qt.Key.Key_Return: ControlIntent.SELECT,
            Qt.Key.Key_Enter: ControlIntent.SELECT,
            Qt.Key.Key_Space: ControlIntent.SELECT,
            Qt.Key.Key_Home: ControlIntent.GUIDE_NOW,
            Qt.Key.Key_PageUp: ControlIntent.REWIND,
            Qt.Key.Key_PageDown: ControlIntent.FAST_FORWARD,
            Qt.Key.Key_Comma: ControlIntent.SKIP_BACK,
            Qt.Key.Key_Period: ControlIntent.SKIP_FORWARD,
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
            "Key_MediaRewind": ControlIntent.REWIND,
            "Key_MediaFastForward": ControlIntent.FAST_FORWARD,
            "Key_PowerOff": ControlIntent.POWER,
            "Key_HomePage": ControlIntent.HOME,
        }
        for attribute, consumer_intent in optional_consumer_bindings.items():
            consumer_key = getattr(Qt.Key, attribute, None)
            if consumer_key is not None:
                bindings[consumer_key] = consumer_intent
        intent = bindings.get(key)
        return None if intent is None else ControlCommand(intent)

    def _cancel_channel_entry(self) -> None:
        self._channel_digits = ""
        self._channel_generation += 1
        self._window.setProperty("channelEntry", "")

    def _channel_entry_screen_changed(self) -> None:
        if str(self._window.property("screen")) not in {"live", "ondemand"}:
            self._cancel_channel_entry()

    def _commit_channel_entry(self) -> None:
        digits = self._channel_digits
        if not digits:
            return

        self._cancel_channel_entry()

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
            if generation != self._channel_generation:
                return
            if str(self._window.property("screen")) not in {"live", "ondemand"}:
                self._cancel_channel_entry()
            elif self._channel_digits:
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
        focus = self._guide_focus_ms()
        if focus:
            return self._program_index_at(programs, focus)
        for index, program in enumerate(programs):
            if isinstance(program, dict) and bool(program.get("isCurrent")):
                return index
        return 0 if programs else -1

    @staticmethod
    def _program_index_at(programs: list, focus_ms: float) -> int:
        """Index of the program airing at ``focus_ms``, else the nearest one."""
        best, distance = (0 if programs else -1), None
        for index, program in enumerate(programs):
            if not isinstance(program, dict):
                continue
            start = float(program.get("startMs", 0))
            end = float(program.get("endMs", 0))
            if start <= focus_ms < end:
                return index
            gap = min(abs(start - focus_ms), abs(end - focus_ms))
            if distance is None or gap < distance:
                best, distance = index, gap
        return best

    def _guide_focus_ms(self) -> float:
        try:
            return float(self._window.property("guideFocusMs") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _set_guide_focus(self, focus_ms: float) -> None:
        self._window.setProperty("guideFocusMs", float(focus_ms))
        # The time focus, not a remembered program, decides the next selection.
        self._window.setProperty("guideSelectionScheduleId", "")

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

    def _selected_programs(self) -> list:
        rows = self._rows()
        row_index = int(self._window.property("selectedRow"))
        if not 0 <= row_index < len(rows):
            return []
        programs = rows[row_index].get("programs", [])
        return programs if isinstance(programs, list) else []

    def _guide_live(self) -> bool:
        return bool(self._controller.snapshot.get("isLiveWindow", True))

    def _select_program_delta(self, delta: int) -> None:
        programs = self._selected_programs()
        if not programs:
            return
        current = int(self._window.property("selectedProgram"))
        target = current + delta
        if not 0 <= target < len(programs):
            self._scroll_guide_edge(programs, delta)
            return
        self._window.setProperty("selectedProgram", target)
        if not self._guide_live():
            # Away from now, Up/Down keep this column instead of jumping to "now".
            program = programs[target]
            start = float(program.get("startMs", 0)) if isinstance(program, dict) else 0.0
            self._window.setProperty("guideFocusMs", max(start, self._horizon_ms()[0]) + 1)

    def _horizon_ms(self) -> tuple[float, float]:
        snapshot = self._controller.snapshot
        return float(snapshot.get("horizonStartMs", 0)), float(snapshot.get("horizonEndMs", 0))

    def _shift_guide_to(self, start_ms: float, focus_ms: float) -> bool:
        shift = getattr(self._controller, "shiftGuideWindow", None)
        if shift is None:
            return False
        horizon_start, _horizon_end = self._horizon_ms()
        minutes = (start_ms - horizon_start) / 60_000
        self._set_guide_focus(focus_ms)
        result = shift(minutes)
        if not bool(result.get("ok")):
            if result.get("message"):
                self._notify({"message": str(result["message"])})
            return False
        self._select_row(int(self._window.property("selectedRow")))
        return True

    def _scroll_guide_edge(self, programs: list, delta: int) -> None:
        """Left past the first or Right past the last program pages time."""
        half_hour = 1_800_000
        horizon_start, horizon_end = self._horizon_ms()
        if delta < 0:
            first = programs[0] if isinstance(programs[0], dict) else {}
            focus = min(float(first.get("startMs", horizon_start)), horizon_start) - 1
            # Show the earlier program near the right, keeping context visible.
            start = min(horizon_start - half_hour, (focus - 2 * 3_600_000) // half_hour * half_hour)
        else:
            last = programs[-1] if isinstance(programs[-1], dict) else {}
            focus = max(float(last.get("endMs", horizon_end)), horizon_end) + 1
            start = max(horizon_start + half_hour, (focus - 3_600_000) // half_hour * half_hour)
        self._shift_guide_to(start, focus)

    def _page_guide(self, minutes: float) -> None:
        horizon_start, _horizon_end = self._horizon_ms()
        programs = self._selected_programs()
        index = int(self._window.property("selectedProgram"))
        offset = 0.0
        if 0 <= index < len(programs) and isinstance(programs[index], dict):
            offset = max(0.0, float(programs[index].get("startMs", horizon_start)) - horizon_start)
        start = horizon_start + minutes * 60_000
        self._shift_guide_to(start, start + offset + 1)

    def _guide_at_now(self) -> bool:
        if not self._guide_live() or self._guide_focus_ms():
            return False
        row_index = int(self._window.property("selectedRow"))
        programs = self._selected_programs()
        index = int(self._window.property("selectedProgram"))
        return (0 <= index < len(programs) and isinstance(programs[index], dict)
                and bool(programs[index].get("isCurrent"))) or (not programs and row_index >= 0)

    @Slot()
    def activateGuideLive(self) -> None:
        """Guide LIVE: first press returns to now; pressed at now, watch live.

        Watching live tunes the selected channel at its live point. If that
        channel is already playing behind (or ahead of) live, it catches up.
        """
        if str(self._window.property("screen")) != "guide":
            return
        if not self._guide_at_now():
            self._guide_to_now()
            self._notify({"message": "Guide is at now - press LIVE again to watch live"})
            return
        rows = self._rows()
        row_index = int(self._window.property("selectedRow"))
        if not 0 <= row_index < len(rows):
            return
        row = rows[row_index]
        if bool(row.get("isUnassigned")):
            self._notify({"message": "Channel 001 is unassigned - create Channel 001 in Broadcaster to replace the static slot"})
            return
        channel = int(row.get("channelNumber", 0))
        playback = self._controller.playback if isinstance(self._controller.playback, dict) else {}
        same_channel = int(playback.get("channelNumber", -1)) == channel and not bool(playback.get("isUnassigned"))
        # Show the native video surface before libVLC creates its output.
        self._window.setProperty("screen", "live")
        QApplication.processEvents()
        if same_channel:
            result = self._controller.goLive() if not bool(playback.get("isLive")) else {"ok": True, "message": "Watching live"}
        else:
            result = self._controller.tuneChannel(channel)
        self._notify(result)
        if not bool(result.get("ok")):
            self._window.setProperty("screen", "guide")
        else:
            self._show_live_hud()

    def _guide_to_now(self) -> None:
        to_now = getattr(self._controller, "guideWindowToNow", None)
        self._window.setProperty("guideFocusMs", 0.0)
        self._window.setProperty("guideSelectionScheduleId", "")
        if to_now is not None:
            to_now()
        row_index = int(self._window.property("selectedRow"))
        self._window.setProperty("selectedProgram", self._current_program_index(row_index))

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

        start_scan = getattr(self._controller, "startMediaScan", None)
        cancel_scan = getattr(self._controller, "cancelMediaScan", None)
        if not callable(start_scan) or not callable(cancel_scan):
            self._notify(
                {
                    "message": (
                        "Background Library scanning is unavailable in this launcher"
                    )
                }
            )
            return

        progress_dialog = QProgressDialog()
        progress_dialog.setWindowTitle("ChannelOS — Index Media")
        progress_dialog.setLabelText("Discovering supported media files…")
        progress_dialog.setCancelButtonText("Cancel")
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setRange(0, 0)
        progress_dialog.setWindowModality(Qt.WindowModality.NonModal)
        progress_dialog.canceled.connect(self._cancel_home_media_scan)
        self._home_scan_dialog = progress_dialog
        progress_dialog.show()
        result = start_scan(folder)
        if not bool(result.get("ok")):
            progress_dialog.close()
            self._home_scan_dialog = None
            self._notify(result)

    def _cancel_home_media_scan(self) -> None:
        dialog = self._home_scan_dialog
        cancel_scan = getattr(self._controller, "cancelMediaScan", None)
        if dialog is None or not callable(cancel_scan):
            return
        result = cancel_scan()
        if bool(result.get("ok")):
            dialog.setLabelText("Cancelling after the current file operation…")
            dialog.setCancelButton(None)
            dialog.show()
        else:
            self._notify(result)

    def _update_home_scan_dialog(self) -> None:
        dialog = self._home_scan_dialog
        if dialog is None:
            return

        state = getattr(self._controller, "libraryScan", {})
        if not isinstance(state, dict):
            return

        current = max(0, int(state.get("current", 0)))
        total = max(0, int(state.get("total", 0)))
        if total <= 0:
            dialog.setRange(0, 0)
        else:
            dialog.setRange(0, total)
            dialog.setValue(min(current, total))

        message = str(state.get("message", "Indexing media…"))
        filename = str(state.get("fileName", ""))
        dialog.setLabelText(
            message if not filename else f"{message}\n{filename}"
        )

        if bool(state.get("active")):
            return

        dialog.close()
        self._home_scan_dialog = None
        if message:
            self._notify({"message": message})

    def _open_guide(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._window.setProperty("infoVisible", False)
        reset = getattr(self._controller, "reset_guide_window", None)
        if reset is not None:
            reset()
        self._window.setProperty("guideFocusMs", 0.0)
        self._controller.refresh()
        self._window.setProperty("screen", "guide")
        self._select_guide_anchor()
        return True

    def _open_library(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._window.setProperty("infoVisible", False)
        self._window.setProperty("screen", "library")
        self._select_library(
            int(self._window.property("selectedLibrary"))
        )
        return True

    def _open_settings(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._window.setProperty("infoVisible", False)
        refresh = self._controller.refreshAudioOutputDevices()
        if not bool(refresh.get("ok")):
            self._notify(refresh)
        self._window.setProperty("screen", "settings")
        return True

    def _open_previous_channel_from_home(self) -> bool:
        self._window.setProperty("infoVisible", False)
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
                        "message": home.get("message") or (
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

    def _go_home(self) -> bool:
        if str(self._window.property("screen")) == "ondemand":
            self._controller.stopOnDemand()
        self._window.setProperty("infoVisible", False)
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

        if self._profile_guard(command):
            return True
        intent = command.intent
        screen = str(self._window.property("screen"))
        if intent in {ControlIntent.TUNE, ControlIntent.CHANNEL_UP,
                      ControlIntent.CHANNEL_DOWN, ControlIntent.PREVIOUS_CHANNEL,
                      ControlIntent.HOME, ControlIntent.GUIDE,
                      ControlIntent.LIBRARY, ControlIntent.SETTINGS, ControlIntent.CHANNELS}:
            self._cancel_channel_entry()

        if intent is ControlIntent.POWER:
            QGuiApplication.quit()
            return True

        info_screens = {"home", "guide", "library", "live", "ondemand"}
        if intent is ControlIntent.INFO and screen in info_screens:
            opening = not bool(self._window.property("infoVisible"))
            self._window.setProperty("infoVisible", opening)
            if opening and screen == "live":
                self._window.setProperty("liveHudVisible", False)
            return True

        if bool(self._window.property("infoVisible")):
            if intent is ControlIntent.BACK:
                self._window.setProperty("infoVisible", False)
                return True
            if screen in {"live", "ondemand"} and self._handle_audio_intent(intent):
                return True
            if intent not in {
                ControlIntent.HOME,
                ControlIntent.GUIDE,
                ControlIntent.LIBRARY,
                ControlIntent.SETTINGS,
                ControlIntent.TUNE,
            }:
                return True
            self._window.setProperty("infoVisible", False)

        if intent is ControlIntent.HOME:
            return self._go_home()

        if intent is ControlIntent.GUIDE:
            if screen == "guide":
                # G inside the Guide is "Go to Now": back to the live window.
                self._controller.refresh()
                self._guide_to_now()
                return True
            return self._open_guide()

        if intent is ControlIntent.LIBRARY:
            return self._open_library()

        if intent is ControlIntent.SETTINGS:
            return self._open_settings()

        if intent is ControlIntent.TUNE:
            if screen == "ondemand":
                self._controller.stopOnDemand()
            self._window.setProperty("infoVisible", False)
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
            # SettingsScreen.qml owns its tabs, rows and the Theme Builder.
            settings_item = getattr(self._window, "_channelos_settings_item", None)
            if settings_item is None:
                return self._go_home() if intent is ControlIntent.BACK else False
            if bool(settings_item.property("focusNavigation")) and intent in _FOCUS_NAVIGATION_INTENTS:
                return self.navigate_focus(intent)
            if intent is ControlIntent.DIGIT:
                # Digits type into the Settings PIN pad when it is open.
                QMetaObject.invokeMethod(settings_item, "handleDigit", Qt.ConnectionType.DirectConnection,
                                         Q_ARG("QVariant", int(command.value or 0)))
                return True
            QMetaObject.invokeMethod(settings_item, "handleControllerIntent",
                                     Qt.ConnectionType.DirectConnection,
                                     Q_ARG("QVariant", intent.value))
            return True

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
                self._guide_to_now()
                return True
            if intent is ControlIntent.GO_LIVE:
                self.activateGuideLive()
                return True
            if intent in {ControlIntent.REWIND, ControlIntent.FAST_FORWARD}:
                self._page_guide(-180 if intent is ControlIntent.REWIND else 180)
                return True
            if intent in {ControlIntent.SKIP_BACK, ControlIntent.SKIP_FORWARD}:
                self._page_guide(-1440 if intent is ControlIntent.SKIP_BACK else 1440)
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
                programs = self._selected_programs()
                program_index = int(self._window.property("selectedProgram"))
                program = programs[program_index] if 0 <= program_index < len(programs) else {}
                if isinstance(program, dict) and bool(program.get("isOffAir")):
                    self._notify({"message": "Nothing aired here - this channel's schedule starts later"})
                    return True
                if isinstance(program, dict) and bool(program.get("isFuture")):
                    self._notify({"message": "That program hasn't aired yet - press Home for Now"})
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
        return False

    def navigate_focus(self, intent: ControlIntent) -> bool:
        """Drive Qt's own focus chain from a remote or controller.

        Up/Down (and Left/Right on ordinary controls) move like Shift+Tab/Tab;
        Left/Right adjust sliders, lists and spin boxes; Select presses the
        focused control. The keys are synthesized, so every control keeps its
        normal keyboard behavior and signals.
        """
        focus = QGuiApplication.focusObject()
        adjustable = focus is not None and any(
            focus.inherits(name) for name in ("QQuickSlider", "QQuickComboBox", "QQuickSpinBox", "QQuickRangeSlider"))
        modifiers = Qt.KeyboardModifier.NoModifier
        if intent is ControlIntent.SELECT:
            key = Qt.Key.Key_Return if self._text_entry_has_focus() or (
                focus is not None and focus.inherits("QQuickComboBox")) else Qt.Key.Key_Space
        elif adjustable and intent in (ControlIntent.LEFT, ControlIntent.RIGHT):
            key = Qt.Key.Key_Left if intent is ControlIntent.LEFT else Qt.Key.Key_Right
        else:
            key = Qt.Key.Key_Tab
            if intent in (ControlIntent.UP, ControlIntent.LEFT):
                modifiers = Qt.KeyboardModifier.ShiftModifier
        target = QGuiApplication.focusWindow() or self._window
        self._synthesizing = True
        try:
            QCoreApplication.sendEvent(target, QKeyEvent(QEvent.Type.KeyPress, key, modifiers))
            QCoreApplication.sendEvent(target, QKeyEvent(QEvent.Type.KeyRelease, key, modifiers))
        finally:
            self._synthesizing = False
        return True

    @staticmethod
    def _text_entry_has_focus() -> bool:
        """True while a text box (hex field, name, search…) is being typed in."""
        focus = QGuiApplication.focusObject()
        if focus is None:
            return False
        if any(focus.inherits(name) for name in ("QQuickTextInput", "QQuickTextEdit")):
            return not bool(focus.property("readOnly"))
        class_name = focus.metaObject().className().lower()
        return any(marker in class_name for marker in ("textinput", "textfield", "textedit", "textarea"))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or getattr(self, "_synthesizing", False):
            return False
        if self._text_entry_has_focus() and event.key() not in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            # Typing belongs to the text box: letters, digits, Backspace,
            # arrows and Enter never become remote commands while editing.
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
    window.installEventFilter(key_filter)
    window.homeMenuActivated.connect(key_filter.activateHomeMenu)
    window.guideLiveActivated.connect(key_filter.activateGuideLive)
    window.pinSubmitted.connect(key_filter.submitPin)
    # Fill and stretch follow the video surface's shape.
    def report_video_size(*_args) -> None:
        controller.setVideoSurfaceSize(video_window.width(), video_window.height())
    video_window.widthChanged.connect(report_video_size)
    video_window.heightChanged.connect(report_video_size)
    window.homeCardActivated.connect(key_filter.activateHomeCard)

    # Keep Python-owned Qt wrappers alive for the duration of the QML window.
    window._channelos_key_filter = key_filter
    window._channelos_video_window = video_window
    window._channelos_settings_item = settings_item

    controller_input = QtControllerInput(
        window,
        key_filter.dispatch_command,
        enabled=lambda: bool(
            controller.settings.get("controllerEnabled", True)
        ),
    )
    window._channelos_controller_input = controller_input

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
    app.aboutToQuit.connect(controller_input.stop)

    if windowed:
        window.showNormal()
    else:
        window.showFullScreen()

    controller_input.start()

    window._channelos_home_startup_gate = _start_home_video_when_ready(
        controller,
        window,
        video_window,
    )

    if not owns_application:
        return 0
    return int(app.exec())
