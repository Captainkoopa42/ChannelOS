from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
from pathlib import Path


ARTWORK_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
GENERIC_ARTWORK_STEMS = (
    "poster",
    "cover",
    "folder",
    "fanart",
    "thumb",
    "thumbnail",
)


class MediaArtworkCache:
    """Resolve local sidecar art or lazily cache a video frame.

    Artwork is presentation data only. The canonical media index and the user's
    original files are never modified, and failure simply means the UI keeps its
    deterministic format-card fallback.
    """

    def __init__(
        self,
        cache_directory: str | Path,
        *,
        ffmpeg_executable: str | Path | None = None,
    ) -> None:
        self.cache_directory = Path(cache_directory)
        self._configured_ffmpeg = (
            None if ffmpeg_executable is None else Path(ffmpeg_executable)
        )
        self._directory_entries: dict[Path, dict[str, Path]] = {}
        self._directory_lock = threading.RLock()

    def clear_discovery_cache(self) -> None:
        """Allow newly added sidecar art to be found on the next request."""

        with self._directory_lock:
            self._directory_entries.clear()

    @staticmethod
    def _usable_file(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _asset_key(asset_id: str) -> str:
        candidate = str(asset_id).partition(":")[2] or str(asset_id)
        if candidate and all(
            character in "0123456789abcdefABCDEF"
            for character in candidate
        ):
            return candidate.lower()
        return hashlib.sha256(str(asset_id).encode("utf-8")).hexdigest()

    def cache_path(self, asset_id: str) -> Path:
        return self.cache_directory / f"{self._asset_key(asset_id)}.jpg"

    def find_sidecar(self, media_path: str | Path) -> Path | None:
        media = Path(media_path)
        with self._directory_lock:
            entries = self._directory_entries.get(media.parent)
            if entries is None:
                try:
                    entries = {
                        entry.name.casefold(): entry
                        for entry in media.parent.iterdir()
                        if entry.is_file()
                    }
                except OSError:
                    return None
                self._directory_entries[media.parent] = entries

        stems = (media.stem, *GENERIC_ARTWORK_STEMS)
        for stem in stems:
            for extension in ARTWORK_EXTENSIONS:
                candidate = entries.get(f"{stem}{extension}".casefold())
                if candidate is not None and self._usable_file(candidate):
                    return candidate
        return None

    def _find_ffmpeg(self) -> Path | None:
        if self._configured_ffmpeg is not None:
            if self._usable_file(self._configured_ffmpeg):
                return self._configured_ffmpeg
            return None

        configured = os.environ.get("CHANNELOS_FFMPEG", "").strip()
        if configured:
            candidate = Path(configured).expanduser()
            if self._usable_file(candidate):
                return candidate

        discovered = shutil.which("ffmpeg")
        if discovered:
            return Path(discovered)

        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            probe_path = Path(ffprobe)
            sibling_name = (
                "ffmpeg.exe"
                if probe_path.suffix.lower() == ".exe"
                else "ffmpeg"
            )
            sibling = probe_path.with_name(sibling_name)
            if self._usable_file(sibling):
                return sibling
        return None

    @staticmethod
    def _seek_seconds(duration_seconds: float) -> float:
        duration = max(0.0, float(duration_seconds or 0.0))
        if duration <= 0.0:
            return 5.0
        return min(
            max(5.0, duration * 0.08),
            max(0.0, duration - 1.0),
            300.0,
        )

    def extract_thumbnail(
        self,
        media_path: str | Path,
        asset_id: str,
        duration_seconds: float,
    ) -> Path | None:
        executable = self._find_ffmpeg()
        if executable is None:
            return None

        destination = self.cache_path(asset_id)
        if self._usable_file(destination):
            return destination

        try:
            self.cache_directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None

        temporary = destination.with_name(
            f".{destination.stem}.{threading.get_ident()}.tmp.jpg"
        )
        command = [
            str(executable),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{self._seek_seconds(duration_seconds):.3f}",
            "-i",
            str(Path(media_path)),
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2",
            "-q:v",
            "3",
            "-y",
            str(temporary),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0 or not self._usable_file(temporary):
                return None
            temporary.replace(destination)
            return destination
        except (OSError, subprocess.SubprocessError):
            return None
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def resolve(
        self,
        media_path: str | Path,
        asset_id: str,
        duration_seconds: float,
    ) -> Path | None:
        sidecar = self.find_sidecar(media_path)
        if sidecar is not None:
            return sidecar

        cached = self.cache_path(asset_id)
        if self._usable_file(cached):
            return cached

        return self.extract_thumbnail(media_path, asset_id, duration_seconds)
