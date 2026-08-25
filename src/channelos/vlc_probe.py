from __future__ import annotations

from pathlib import Path

from .playback import PlaybackUnavailableError, _prepare_windows_vlc_runtime
from .probe import MediaProbeError, MediaProbeResult


class LibVLCMediaProbe:
    """Read basic local-file metadata with ChannelOS's bundled libVLC runtime.

    The normal development scanner prefers ffprobe because it exposes richer
    technical metadata. The packaged Windows first-run path cannot assume an
    external FFmpeg installation, so it uses the libVLC runtime that ChannelOS
    already ships for playback to obtain the duration required by scheduling.
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
            # deterministic choice for this one-time packaged setup path.
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
