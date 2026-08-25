from __future__ import annotations

import sys
from pathlib import Path

from .playback import PlaybackUnavailableError, _prepare_windows_vlc_runtime
from .probe import MediaProbeError, MediaProbeResult


class LibVLCMediaProbe:
    """Read basic local-file metadata with ChannelOS's bundled libVLC runtime.

    The normal development scanner prefers ffprobe because it exposes richer
    technical metadata. The packaged Windows path cannot assume an external
    FFmpeg installation, so it uses the libVLC runtime that ChannelOS already
    ships for playback to obtain the duration required by scheduling.
    """

    def __init__(self) -> None:
        self._dll_directory_handle, self._runtime_dir = _prepare_windows_vlc_runtime()
        try:
            import vlc  # type: ignore
        except (ImportError, OSError) as exc:
            raise PlaybackUnavailableError(
                "ChannelOS could not load its bundled libVLC runtime for media inspection"
            ) from exc

        self._vlc = vlc
        try:
            self._instance = vlc.Instance("--quiet", "--no-video-title-show")
        except Exception as exc:
            raise PlaybackUnavailableError(
                "ChannelOS could not initialize libVLC for media inspection"
            ) from exc

    def probe(self, path: Path) -> MediaProbeResult:
        media_path = Path(path).expanduser().resolve(strict=False)
        try:
            media = self._instance.media_new_path(str(media_path))
            # libvlc_media_parse() is synchronous in VLC 3.x. It is deprecated
            # upstream in favor of the async parser, but remains the smallest
            # deterministic choice for this local packaged-media inspection.
            media.parse()
            duration_ms = int(media.get_duration() or 0)
        except Exception as exc:
            raise MediaProbeError(
                f"libVLC could not inspect {media_path.name}: {exc}"
            ) from exc

        if duration_ms <= 0:
            raise MediaProbeError(
                f"libVLC could not determine a usable duration for {media_path.name}"
            )

        container = media_path.suffix.lstrip(".").lower() or None
        return MediaProbeResult(
            duration_seconds=duration_ms / 1000.0,
            container_format=container,
        )


class _UnavailablePackagedProbe:
    """Turn a missing packaged runtime into a visible scan failure."""

    def __init__(self, message: str) -> None:
        self.message = str(message)

    def probe(self, path: Path) -> MediaProbeResult:
        raise MediaProbeError(
            f"ChannelOS cannot inspect {Path(path).name}: {self.message}"
        )


def install_packaged_media_scan_support(broadcaster_qt) -> None:
    """Use bundled libVLC for Library scans in a frozen Windows package.

    Development/source launches keep the normal ffprobe adapter. A packaged
    user should not have to install FFmpeg merely to add another folder and then
    program that media into a channel.
    """

    if not getattr(sys, "frozen", False):
        return

    base_scanner = broadcaster_qt.MediaScanner
    if getattr(base_scanner, "_channelos_packaged_probe_enabled", False):
        return

    class PackagedMediaScanner(base_scanner):
        _channelos_packaged_probe_enabled = True

        def __init__(
            self,
            library,
            probe=None,
            *,
            fail_on_probe_error: bool = False,
        ) -> None:
            if probe is None:
                try:
                    probe = LibVLCMediaProbe()
                except PlaybackUnavailableError as exc:
                    probe = _UnavailablePackagedProbe(str(exc))
                # Scheduling requires duration. Do not silently index media that
                # the packaged broadcaster cannot yet schedule.
                fail_on_probe_error = True
            super().__init__(
                library,
                probe=probe,
                fail_on_probe_error=fail_on_probe_error,
            )

    broadcaster_qt.MediaScanner = PackagedMediaScanner
