from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PlaybackError(RuntimeError):
    """Base error for ChannelOS playback backends."""


class PlaybackUnavailableError(PlaybackError):
    """Raised when an optional playback backend is not installed or usable."""


VLC_RUNTIME_ENV = "CHANNELOS_VLC_DIR"
IS_WINDOWS = os.name == "nt"


@dataclass(frozen=True, slots=True)
class NativeVideoSurface:
    """A native child-window target that a playback backend may render into."""

    platform: str
    window_id: int

    def __post_init__(self) -> None:
        if self.platform not in {"windows", "x11", "macos"}:
            raise ValueError(f"unsupported native video platform: {self.platform!r}")
        if not isinstance(self.window_id, int) or isinstance(self.window_id, bool) or self.window_id <= 0:
            raise ValueError("native video window_id must be a positive integer")


VIDEO_ASPECT_CHOICES = ("auto", "16:9", "4:3", "21:9", "2.35:1", "1.85:1", "16:10", "5:4", "1:1")
VIDEO_FIT_CHOICES = ("fit", "fill", "stretch")
VIDEO_OVERSCAN_CHOICES = (0, 2, 4, 6, 8)
VIDEO_DEINTERLACE_CHOICES = ("auto", "off", "yadif", "yadif2x", "bob", "blend", "linear")
VIDEO_HARDWARE_DECODING_CHOICES = ("auto", "off")
VIDEO_LEVEL_CHOICES = (50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150)


@dataclass(frozen=True, slots=True)
class VideoSettings:
    """Viewer picture preferences applied to every programme.

    ``aspect_ratio`` overrides the source's display shape. ``fit`` decides how
    that shape meets the screen: letterbox (fit), crop to fill, or stretch.
    ``overscan_percent`` trims noisy edges from captured broadcasts.
    """

    aspect_ratio: str = "auto"
    fit: str = "fit"
    overscan_percent: int = 0
    deinterlace: str = "auto"
    hardware_decoding: str = "auto"
    brightness: int = 100
    contrast: int = 100
    saturation: int = 100

    def __post_init__(self) -> None:
        checks = (
            (self.aspect_ratio, VIDEO_ASPECT_CHOICES, "aspect ratio"),
            (self.fit, VIDEO_FIT_CHOICES, "picture fit"),
            (self.overscan_percent, VIDEO_OVERSCAN_CHOICES, "overscan"),
            (self.deinterlace, VIDEO_DEINTERLACE_CHOICES, "deinterlace"),
            (self.hardware_decoding, VIDEO_HARDWARE_DECODING_CHOICES, "hardware decoding"),
            (self.brightness, VIDEO_LEVEL_CHOICES, "brightness"),
            (self.contrast, VIDEO_LEVEL_CHOICES, "contrast"),
            (self.saturation, VIDEO_LEVEL_CHOICES, "saturation"),
        )
        for value, choices, name in checks:
            if value not in choices:
                raise ValueError(f"unsupported {name}: {value!r}")

    @property
    def adjusts_picture(self) -> bool:
        return (self.brightness, self.contrast, self.saturation) != (100, 100, 100)


def _ratio(text: str) -> float:
    left, right = str(text).split(":")
    return float(left) / float(right)


def video_crop_geometry(source_width: int, source_height: int, display_ratio: float,
                        target_ratio: float | None, overscan_percent: int) -> str | None:
    """Return a libVLC pixel crop ``WxH+X+Y``, or ``None`` for no crop.

    ``display_ratio`` is the shape the source is shown at (forced or native),
    ``target_ratio`` the shape to fill (``None`` keeps the whole picture).
    The overscan trim is applied on every edge after the fill crop.
    """

    if source_width <= 0 or source_height <= 0:
        return None
    width, height = float(source_width), float(source_height)
    if target_ratio and display_ratio > 0:
        # Horizontal pixels per displayed unit differ when the ratio is forced.
        pixel_stretch = (width / height) / display_ratio
        if display_ratio > target_ratio:
            width = height * target_ratio * pixel_stretch
        elif display_ratio < target_ratio:
            height = width / (target_ratio * pixel_stretch)
    keep = 1.0 - 2.0 * overscan_percent / 100.0
    width, height = width * keep, height * keep
    crop_w, crop_h = int(round(width)), int(round(height))
    if crop_w >= source_width and crop_h >= source_height:
        return None
    x = (source_width - crop_w) // 2
    y = (source_height - crop_h) // 2
    return f"{crop_w}x{crop_h}+{x}+{y}"


@dataclass(frozen=True, slots=True)
class AudioOutputDevice:
    """One audio destination exposed by the active playback backend."""

    device_id: str
    name: str


def resolve_audio_output_device_id(
    saved_device_id: str,
    available_devices: tuple[AudioOutputDevice, ...],
) -> str:
    """Return a usable saved destination or the system-default identifier."""

    selected = str(saved_device_id)
    if not selected:
        return ""
    return (
        selected
        if any(device.device_id == selected for device in available_devices)
        else ""
    )


def _bundled_vlc_runtime_candidates() -> tuple[Path, ...]:
    """Return ChannelOS-owned libVLC locations in product-first order."""

    executable_root = Path(sys.executable).resolve().parent
    package_root = Path(__file__).resolve().parent
    source_root = Path(__file__).resolve().parents[2]
    return (
        executable_root / "runtime" / "vlc",
        package_root / "runtime" / "vlc",
        source_root / "runtime" / "vlc",
    )


def _vlc_runtime_candidates() -> tuple[Path, ...]:
    candidates = list(_bundled_vlc_runtime_candidates())
    override = os.environ.get(VLC_RUNTIME_ENV)
    if override:
        candidates.append(Path(override).expanduser())

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        key = os.path.normcase(str(resolved))
        if key not in seen:
            unique.append(resolved)
            seen.add(key)
    return tuple(unique)


def _prepare_windows_vlc_runtime() -> tuple[Any | None, Path | None]:
    """Make a ChannelOS-owned or explicitly supplied libVLC visible to Windows."""

    if not IS_WINDOWS:
        return None, None

    for candidate in _vlc_runtime_candidates():
        if not (candidate / "libvlc.dll").is_file():
            continue

        plugins = candidate / "plugins"
        if plugins.is_dir():
            os.environ["VLC_PLUGIN_PATH"] = str(plugins)
        # python-vlc can explicitly CDLL('.\\libvlc.dll'), bypassing the DLL
        # directory registered below. Give its binding the absolute primary
        # library as well as the dependency/plugin search paths.
        os.environ["PYTHON_VLC_LIB_PATH"] = str(candidate / "libvlc.dll")
        os.environ["PYTHON_VLC_MODULE_PATH"] = str(candidate)

        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is not None:
            return add_dll_directory(str(candidate)), candidate

        current_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(candidate) + os.pathsep + current_path
        return None, candidate

    return None, None


class PlaybackBackend(ABC):
    """Backend-neutral playback contract used by ChannelOS runtime code."""

    @abstractmethod
    def load(self, path: str | Path) -> None: ...

    @abstractmethod
    def play(self) -> None: ...

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def seek(self, seconds: float) -> None:
        """Seek to an absolute media time in seconds."""

    @abstractmethod
    def get_position(self) -> float:
        """Return the current absolute media time in seconds."""

    @abstractmethod
    def set_volume(self, percent: int) -> None: ...

    @abstractmethod
    def get_volume(self) -> int: ...

    @abstractmethod
    def set_muted(self, muted: bool) -> None: ...

    @abstractmethod
    def get_muted(self) -> bool: ...

    @abstractmethod
    def set_rate(self, rate: float) -> None: ...

    def has_ended(self) -> bool:
        """Return whether the current media reached its natural end."""

        return False

    def playback_error(self) -> str | None:
        """Return an asynchronous decoder failure, when one has occurred."""

        return None

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        """Attach a native presentation target when this backend supports embedding."""

        raise PlaybackUnavailableError(
            f"{type(self).__name__} does not support an embedded native video surface"
        )

    def list_audio_output_devices(self) -> tuple[AudioOutputDevice, ...]:
        """Return selectable audio destinations, excluding the system default."""

        return ()

    def set_audio_output_device(self, device_id: str | None) -> None:
        """Select an audio destination, or the operating-system default with ``None``."""

        if device_id:
            raise PlaybackUnavailableError(
                f"{type(self).__name__} does not support audio-output selection"
            )

    def set_transition_level(self, level: float) -> None:
        """Apply an independent audio/video fade envelope, preserving user settings."""
        if level != 1.0:
            raise PlaybackUnavailableError(f"{type(self).__name__} does not support fades")

    def set_video_settings(self, settings: VideoSettings) -> None:
        """Apply viewer picture preferences. Backends without video ignore them."""

    def set_surface_size(self, width: int, height: int) -> None:
        """Report the native video surface size, used to fill or stretch."""


class LibVLCBackend(PlaybackBackend):
    """Reference playback backend using python-vlc over the native libVLC library."""

    def __init__(self, *instance_options: str) -> None:
        self._dll_directory_handle, self._runtime_dir = _prepare_windows_vlc_runtime()

        try:
            import vlc  # type: ignore
        except (ImportError, OSError) as exc:
            raise PlaybackUnavailableError(
                "libVLC could not be loaded. Packaged ChannelOS builds should include "
                "runtime/vlc; source builds may set CHANNELOS_VLC_DIR to a directory "
                "containing libvlc.dll and its plugins."
            ) from exc

        self._vlc: Any = vlc
        self._loaded_path: Path | None = None
        self._user_volume: int | None = None
        self._user_muted: bool | None = None
        self._transition_level = 1.0
        self._video_settings = VideoSettings()
        self._surface_size: tuple[int, int] | None = None
        self._pending_source_size = False
        try:
            self._instance = vlc.Instance(*instance_options)
            self._player = self._instance.media_player_new()
        except Exception as exc:
            location = (
                f" from {self._runtime_dir}"
                if self._runtime_dir is not None
                else ""
            )
            raise PlaybackUnavailableError(
                f"libVLC could not be initialized{location}."
            ) from exc

    def attach_video_surface(self, surface: NativeVideoSurface) -> None:
        """Point libVLC at a ChannelOS-owned native child window."""

        handle = int(surface.window_id)
        try:
            if surface.platform == "windows":
                self._player.set_hwnd(handle)
            elif surface.platform == "x11":
                self._player.set_xwindow(handle)
            elif surface.platform == "macos":
                self._player.set_nsobject(handle)
            else:  # guarded by NativeVideoSurface, retained for defensive callers
                raise PlaybackUnavailableError(
                    f"libVLC does not support native video platform {surface.platform!r}"
                )
            self._fit_source_aspect_to_surface()
        except (AttributeError, TypeError, ValueError) as exc:
            raise PlaybackUnavailableError(
                f"libVLC could not attach the {surface.platform} video surface"
            ) from exc

    def _fit_source_aspect_to_surface(self) -> None:
        """Apply the viewer's picture shape to the current video output.

        libVLC keeps video-output overrides on the media player, so every
        programme gets the complete set again: a prior crop or forced ratio must
        never leak into the next one. With default settings this clears all
        overrides and uses autoscale (scale 0): the whole picture fits inside
        the surface and any unused area becomes letterboxing.
        """

        settings = getattr(self, "_video_settings", None) or VideoSettings()
        aspect = None if settings.aspect_ratio == "auto" else settings.aspect_ratio
        surface = getattr(self, "_surface_size", None)
        surface_ratio = surface[0] / surface[1] if surface and surface[1] > 0 else None
        if settings.fit == "stretch" and surface:
            aspect = f"{surface[0]}:{surface[1]}"
        crop = None
        needs_source = settings.overscan_percent > 0 or (settings.fit == "fill" and surface_ratio)
        source = self._source_size() if needs_source else (0, 0)
        if needs_source and source[0] > 0:
            display = _ratio(aspect) if aspect and settings.fit != "stretch" else source[0] / source[1]
            target = surface_ratio if settings.fit == "fill" else None
            crop = video_crop_geometry(source[0], source[1], display, target, settings.overscan_percent)
        # Remember whether the source size was still unknown, so polling can
        # apply the crop once the decoder reports dimensions.
        self._pending_source_size = bool(needs_source and source[0] <= 0)
        self._player.video_set_aspect_ratio(aspect)
        self._player.video_set_crop_geometry(crop)
        self._player.video_set_scale(0.0)
        self._apply_picture()
        self._apply_deinterlace()

    def _source_size(self) -> tuple[int, int]:
        try:
            size = self._player.video_get_size(0)
        except Exception:
            return (0, 0)
        if not size or len(size) != 2:
            return (0, 0)
        return int(size[0] or 0), int(size[1] or 0)

    def _apply_picture(self) -> None:
        settings = getattr(self, "_video_settings", None) or VideoSettings()
        level = getattr(self, "_transition_level", 1.0)
        try:
            option = self._vlc.VideoAdjustOption
            enabled = level < 1.0 or settings.adjusts_picture
            self._player.video_set_adjust_int(option.Enable, int(enabled))
            if enabled:
                # libVLC adjust: brightness and contrast 0..2, saturation 0..3.
                self._player.video_set_adjust_float(option.Brightness, level * settings.brightness / 100.0)
                self._player.video_set_adjust_float(option.Contrast, settings.contrast / 100.0)
                self._player.video_set_adjust_float(option.Saturation, settings.saturation / 100.0)
        except AttributeError:
            pass

    def _apply_deinterlace(self) -> None:
        mode = (getattr(self, "_video_settings", None) or VideoSettings()).deinterlace
        if mode == "auto":
            return  # libVLC's automatic detection applies through media defaults
        try:
            self._player.video_set_deinterlace(None if mode == "off" else mode)
        except (AttributeError, TypeError):
            pass

    def set_video_settings(self, settings: VideoSettings) -> None:
        self._video_settings = settings
        self._fit_source_aspect_to_surface()

    def set_surface_size(self, width: int, height: int) -> None:
        size = (int(width), int(height))
        if size[0] <= 0 or size[1] <= 0 or size == getattr(self, "_surface_size", None):
            return
        self._surface_size = size
        settings = getattr(self, "_video_settings", None) or VideoSettings()
        if settings.fit != "fit" or settings.overscan_percent:
            self._fit_source_aspect_to_surface()

    def _media_options(self) -> tuple[str, ...]:
        settings = getattr(self, "_video_settings", None) or VideoSettings()
        options = []
        if settings.deinterlace == "off":
            options.append(":deinterlace=0")
        elif settings.deinterlace != "auto":
            options += [":deinterlace=1", f":deinterlace-mode={settings.deinterlace}"]
        if settings.hardware_decoding == "off":
            options.append(":avcodec-hw=none")
        return tuple(options)

    def load(self, path: str | Path) -> None:
        media_path = Path(path).expanduser().resolve(strict=False)
        if not media_path.is_file():
            raise PlaybackError(
                "Media file is unavailable: "
                f"{media_path}. Restore the file or re-scan its Library folder."
            )
        try:
            with media_path.open("rb"):
                pass
        except OSError as exc:
            raise PlaybackError(
                f"Media file cannot be read: {media_path} ({exc})"
            ) from exc
        media = self._instance.media_new_path(str(media_path))
        for option in self._media_options():
            media.add_option(option)
        self._player.set_media(media)
        self._loaded_path = media_path

    def play(self) -> None:
        result = self._player.play()
        if isinstance(result, int) and result < 0:
            raise PlaybackError("libVLC could not start playback")
        # Reapply after play() as libVLC can create a fresh video output when a
        # programme changes or playback resumes after natural end-of-file.
        self._fit_source_aspect_to_surface()

    def pause(self) -> None:
        if hasattr(self._player, "set_pause"):
            self._player.set_pause(1)
        else:
            self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def seek(self, seconds: float) -> None:
        milliseconds = max(0, int(seconds * 1000))
        result = self._player.set_time(milliseconds)
        if isinstance(result, int) and result < 0:
            raise PlaybackError(f"libVLC could not seek to {seconds:.3f}s")

    def get_position(self) -> float:
        milliseconds = self._player.get_time()
        if milliseconds is None or milliseconds < 0:
            return 0.0
        return float(milliseconds) / 1000.0

    def has_ended(self) -> bool:
        try:
            return self._player.get_state() == self._vlc.State.Ended
        except Exception:
            return False

    def playback_error(self) -> str | None:
        # Audio outputs are recreated asynchronously as streams change. Keep
        # user intent through silent clips and machines without an audio device.
        self._apply_audio_settings()
        if getattr(self, "_pending_source_size", False) and self._source_size()[0] > 0:
            self._fit_source_aspect_to_surface()
        try:
            state = self._player.get_state()
        except Exception:
            return None
        target = (
            str(self._loaded_path)
            if self._loaded_path is not None
            else "the selected media"
        )
        if state == self._vlc.State.Error:
            return (
                f"libVLC could not open or decode {target}. "
                "Verify the file still plays in VLC, then re-scan its Library folder."
            )

        # A zero vout count is not a decoder error by itself. Qt deliberately
        # hides the native video child on management screens, and libVLC can
        # also recreate its vout briefly during seeks and window transitions.
        # Treat only libVLC's explicit Error state as fatal so a transient or
        # intentionally hidden surface cannot latch playback off.
        return None

    def set_volume(self, percent: int) -> None:
        if not 0 <= percent <= 100:
            raise ValueError("volume must be from 0 through 100 percent")
        self._user_volume = percent
        result = self._player.audio_set_volume(round(percent * self._transition_level))
        if isinstance(result, int) and result < 0:
            raise PlaybackError(f"libVLC rejected volume {percent}")

    def get_volume(self) -> int:
        if self._user_volume is not None:
            return self._user_volume
        value = self._player.audio_get_volume()
        return max(0, int(value))

    def set_transition_level(self, level: float) -> None:
        import math
        if not math.isfinite(level) or not 0 <= level <= 1:
            raise ValueError("transition level must be from zero through one")
        volume = self.get_volume()
        self._transition_level = level
        self.set_volume(volume)
        # A single decoder fades through black (adjust brightness scales with
        # the level); the viewer's own picture levels are kept underneath.
        self._apply_picture()

    def set_muted(self, muted: bool) -> None:
        self._user_muted = bool(muted)
        self._player.audio_set_mute(self._user_muted)

    def get_muted(self) -> bool:
        if getattr(self, "_user_muted", None) is not None:
            return self._user_muted
        value = self._player.audio_get_mute()
        return bool(value) if value is not None and value >= 0 else False

    def _apply_audio_settings(self) -> None:
        if getattr(self, "_user_volume", None) is not None:
            self._player.audio_set_volume(round(self._user_volume * self._transition_level))
        if getattr(self, "_user_muted", None) is not None:
            self._player.audio_set_mute(self._user_muted)

    @staticmethod
    def _decode_vlc_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def list_audio_output_devices(self) -> tuple[AudioOutputDevice, ...]:
        """Enumerate libVLC audio destinations and release its native list."""

        try:
            head = self._player.audio_output_device_enum()
        except (AttributeError, TypeError, ValueError) as exc:
            raise PlaybackUnavailableError(
                "libVLC could not enumerate audio output devices"
            ) from exc

        if not head:
            return ()

        devices: list[AudioOutputDevice] = []
        seen: set[str] = set()
        node = head
        try:
            # libVLC returns a null-terminated native linked list. The limit is
            # defensive protection against a malformed third-party audio module.
            for _ in range(512):
                if not node:
                    break
                current = node.contents
                device_id = self._decode_vlc_text(current.device)
                name = self._decode_vlc_text(current.description)
                if device_id and device_id not in seen:
                    devices.append(
                        AudioOutputDevice(
                            device_id=device_id,
                            name=name or device_id,
                        )
                    )
                    seen.add(device_id)
                node = current.next
        except (AttributeError, TypeError, ValueError) as exc:
            raise PlaybackUnavailableError(
                "libVLC returned an invalid audio output device list"
            ) from exc
        finally:
            release = getattr(
                self._vlc,
                "libvlc_audio_output_device_list_release",
                None,
            )
            if release is not None:
                release(head)

        return tuple(devices)

    def set_audio_output_device(self, device_id: str | None) -> None:
        """Switch libVLC immediately; ``None`` follows the system default."""

        selected = None if not device_id else str(device_id)
        try:
            # Passing no module lets libVLC route the identifier to the active
            # audio output. libVLC 3 exposes no useful success return here.
            self._player.audio_output_device_set(None, selected)
        except (AttributeError, TypeError, ValueError) as exc:
            raise PlaybackUnavailableError(
                "libVLC could not select the requested audio output device"
            ) from exc

    def set_rate(self, rate: float) -> None:
        if rate <= 0:
            raise ValueError("playback rate must be positive")
        result = self._player.set_rate(float(rate))
        if isinstance(result, int) and result < 0:
            raise PlaybackError(f"libVLC rejected playback rate {rate}")
