from __future__ import annotations

import hashlib
import heapq
import time
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .portable import find_setup


ARTWORK_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
GENERIC_ARTWORK_STEMS = (
    "poster",
    "cover",
    "folder",
    "fanart",
    "thumb",
    "thumbnail",
)


@dataclass(frozen=True, slots=True)
class ArtworkCacheStats:
    file_count: int = 0
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ArtworkCacheChange:
    removed_files: int = 0
    removed_bytes: int = 0
    remaining: ArtworkCacheStats = ArtworkCacheStats()
    removed_paths: tuple[Path, ...] = ()


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
        self._portable = find_setup(self.cache_directory)
        self._configured_ffmpeg = (
            None if ffmpeg_executable is None else Path(ffmpeg_executable)
        )
        self._directory_entries: dict[Path, dict[str, Path]] = {}
        self._directory_lock = threading.RLock()
        self._cache_lock = threading.RLock()
        self._generation = 0
        self._entries = None
        self._cache_bytes = 0
        self._oldest = []
        self._directory_stamp = None
        self._last_inventory = 0.0

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
        if len(candidate) == 64 and all(
            character in "0123456789abcdefABCDEF"
            for character in candidate
        ):
            return candidate.lower()
        return hashlib.sha256(str(asset_id).encode("utf-8")).hexdigest()

    def cache_path(self, asset_id: str) -> Path:
        return self.cache_directory / f"{self._asset_key(asset_id)}.jpg"

    @staticmethod
    def _is_generated_cache_file(path: Path) -> bool:
        return (
            path.suffix.casefold() == ".jpg"
            and len(path.stem) == 64
            and all(character in "0123456789abcdef" for character in path.stem)
        )

    def _generated_cache_files(self) -> list[Path]:
        try:
            return [
                path
                for path in self.cache_directory.iterdir()
                if path.is_file() and self._is_generated_cache_file(path)
            ]
        except OSError:
            return []

    def _stamp(self):
        try:
            stat = self.cache_directory.stat()
            return stat.st_mtime_ns, stat.st_ino
        except OSError:
            return None

    def _inventory(self):
        stamp = self._stamp()
        if self._entries is not None and stamp == self._directory_stamp and time.monotonic() - self._last_inventory < 60:
            return
        entries = {}
        for path in self._generated_cache_files():
            try:
                stat = path.stat()
                entries[path] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                pass
        self._entries = entries
        self._cache_bytes = sum(size for _, size in entries.values())
        self._oldest = [(stamp, str(path), size) for path, (stamp, size) in entries.items()]
        heapq.heapify(self._oldest)
        self._directory_stamp = stamp
        self._last_inventory = time.monotonic()

    def _register(self, path):
        if self._entries is None:
            return
        stat = path.stat()
        previous = self._entries.get(path)
        if previous:
            self._cache_bytes -= previous[1]
        self._entries[path] = stat.st_mtime_ns, stat.st_size
        self._cache_bytes += stat.st_size
        heapq.heappush(self._oldest, (stat.st_mtime_ns, str(path), stat.st_size))
        if len(self._oldest) > max(64, 2 * len(self._entries)):
            self._oldest = [(stamp, str(item), size) for item, (stamp, size) in self._entries.items()]
            heapq.heapify(self._oldest)
        self._directory_stamp = self._stamp()

    def stats(self) -> ArtworkCacheStats:
        with self._cache_lock:
            self._inventory()
            return ArtworkCacheStats(len(self._entries), self._cache_bytes)

    def clear_generated(self) -> ArtworkCacheChange:
        """Remove generated thumbnails, retaining sidecars and in-flight protection."""
        with self._cache_lock:
            if self._portable:
                self._portable.check_available()
            self._generation += 1
            self._entries = None  # Explicit Clear reconciles externally changed files too.
            self._inventory()
            removed, size = [], 0
            for path, (_, count) in tuple(self._entries.items()):
                try:
                    path.unlink()
                    removed.append(path)
                    size += count
                    self._entries.pop(path)
                    self._cache_bytes -= count
                except OSError:
                    pass
            self._directory_stamp = self._stamp()
            self._oldest = [(stamp, str(path), size) for path, (stamp, size) in self._entries.items()]
            heapq.heapify(self._oldest)
            return ArtworkCacheChange(len(removed), size, ArtworkCacheStats(len(self._entries), self._cache_bytes), tuple(removed))

    def prune(self, max_bytes: int) -> ArtworkCacheChange:
        """Use one maintained inventory instead of rescanning on each cache hit."""
        limit = max(0, int(max_bytes))
        with self._cache_lock:
            if self._portable:
                self._portable.check_available()
            self._inventory()
            removed, size = [], 0
            failed = []
            while limit and self._cache_bytes > limit and self._oldest:
                stamp, text, count = heapq.heappop(self._oldest)
                path = Path(text)
                if self._entries.get(path) != (stamp, count):
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    failed.append((stamp, text, count))
                    continue
                self._entries.pop(path)
                self._cache_bytes -= count
                removed.append(path)
                size += count
            for entry in failed:
                heapq.heappush(self._oldest, entry)
            self._directory_stamp = self._stamp()
            return ArtworkCacheChange(len(removed), size, ArtworkCacheStats(len(self._entries), self._cache_bytes), tuple(removed))

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
        *,
        max_width: int = 640,
        ffmpeg_threads: int = 0,
    ) -> Path | None:
        executable = self._find_ffmpeg()
        if executable is None:
            return None

        destination = self.cache_path(asset_id)
        if self._usable_file(destination):
            return destination

        try:
            if self._portable:
                self._portable.check_available()
            self.cache_directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None

        temporary = destination.with_name(
            f".{destination.stem}.{threading.get_ident()}.tmp.jpg"
        )
        with self._cache_lock:
            generation = self._generation

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
        ]
        if int(ffmpeg_threads) > 0:
            command.extend(["-threads", str(int(ffmpeg_threads))])
        command.extend([
            "-frames:v",
            "1",
            "-vf",
            f"scale={max(64, int(max_width))}:-2",
            "-q:v",
            "3",
            "-y",
            str(temporary),
        ])
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
            with self._cache_lock:
                if self._portable:
                    self._portable.check_available()
                if generation != self._generation:
                    return None
                temporary.replace(destination)
                self._register(destination)
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
        *,
        allow_generate: bool = True,
        max_width: int = 640,
        ffmpeg_threads: int = 0,
    ) -> Path | None:
        sidecar = self.find_sidecar(media_path)
        if sidecar is not None:
            return sidecar

        cached = self.cache_path(asset_id)
        if self._usable_file(cached):
            return cached

        if not allow_generate:
            return None

        return self.extract_thumbnail(
            media_path,
            asset_id,
            duration_seconds,
            max_width=max_width,
            ffmpeg_threads=ffmpeg_threads,
        )
