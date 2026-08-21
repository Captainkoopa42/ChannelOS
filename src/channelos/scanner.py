from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .library import MediaLibrary, sha256_file
from .probe import FFprobeMediaProbe, MediaProbe, MediaProbeError, MediaProbeResult

SUPPORTED_MEDIA_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogv",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}


class ScanCancelled(RuntimeError):
    """Raised when a caller cooperatively cancels an in-progress media scan."""


@dataclass(frozen=True, slots=True)
class ScanSummary:
    discovered: int = 0
    hashed: int = 0
    cache_hits: int = 0
    metadata_enriched: int = 0
    new_assets: int = 0
    known_assets: int = 0
    probe_errors: int = 0


@dataclass(frozen=True, slots=True)
class ScanProgress:
    """One user-facing checkpoint while a media source is being indexed."""

    current: int
    total: int
    path: Path | None = None

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 1.0
        return min(1.0, max(0.0, self.current / self.total))


ScanProgressCallback = Callable[[ScanProgress], None]
ScanCancellationCheck = Callable[[], bool]


class MediaScanner:
    def __init__(
        self,
        library: MediaLibrary,
        probe: MediaProbe | None = None,
        *,
        fail_on_probe_error: bool = False,
    ) -> None:
        self.library = library
        self.probe = probe if probe is not None else FFprobeMediaProbe()
        self.fail_on_probe_error = fail_on_probe_error

    def _probe(self, path: Path) -> tuple[MediaProbeResult, bool]:
        """Probe one file and report whether a non-fatal probe error occurred."""

        try:
            return self.probe.probe(path), False
        except MediaProbeError:
            if self.fail_on_probe_error:
                raise
            return MediaProbeResult(), True

    @staticmethod
    def _adds_technical_data(cached, result: MediaProbeResult) -> bool:
        return (
            (cached.duration_seconds is None and result.duration_seconds is not None)
            or (cached.container_format is None and result.container_format is not None)
        )

    @staticmethod
    def _report(
        callback: ScanProgressCallback | None,
        *,
        current: int,
        total: int,
        path: Path | None,
    ) -> None:
        if callback is not None:
            callback(ScanProgress(current=current, total=total, path=path))

    @staticmethod
    def _cancel_requested(check: ScanCancellationCheck | None) -> bool:
        return bool(check is not None and check())

    @classmethod
    def _raise_if_cancelled(cls, check: ScanCancellationCheck | None) -> None:
        if cls._cancel_requested(check):
            raise ScanCancelled("media scan cancelled")

    def discover(self, source: str | Path) -> tuple[Path, ...]:
        """Return supported media paths without mutating the library index."""

        source_path = Path(source).expanduser().resolve(strict=False)
        if not source_path.exists():
            raise FileNotFoundError(f"media source does not exist: {source_path}")
        return tuple(self._iter_media_files(source_path))

    def scan(
        self,
        source: str | Path,
        *,
        on_progress: ScanProgressCallback | None = None,
        should_cancel: ScanCancellationCheck | None = None,
    ) -> ScanSummary:
        source_path = Path(source).expanduser().resolve(strict=False)
        media_files = self.discover(source_path)
        total = len(media_files)

        self.library.begin_source_scan(
            source_path,
            discovered_count=total,
        )
        self._report(on_progress, current=0, total=total, path=None)

        discovered = hashed = cache_hits = metadata_enriched = 0
        new_assets = known_assets = probe_errors = 0

        try:
            self._raise_if_cancelled(should_cancel)

            for index, path in enumerate(media_files, start=1):
                self._raise_if_cancelled(should_cancel)
                discovered += 1
                cached = self.library.cached_asset_for_unchanged_path(path)
                if cached is not None:
                    cache_hits += 1
                    known_assets += 1

                    # A content cache hit must not permanently freeze an asset at
                    # the metadata quality of its first scan. If a file was
                    # originally indexed with --no-probe (or while ffprobe was
                    # unavailable), a later technical scan can enrich it using
                    # the already-trusted content hash instead of re-reading it.
                    if cached.duration_seconds is None or cached.container_format is None:
                        probe_result, probe_failed = self._probe(path)
                        if probe_failed:
                            probe_errors += 1
                        if self._adds_technical_data(cached, probe_result):
                            self.library.upsert_file(
                                path,
                                source_path,
                                content_sha256=cached.content_sha256,
                                probe=probe_result,
                            )
                            metadata_enriched += 1
                        else:
                            self.library.mark_seen_cached(path, source_path)
                    else:
                        self.library.mark_seen_cached(path, source_path)
                    self._report(
                        on_progress,
                        current=index,
                        total=total,
                        path=path,
                    )
                    continue

                try:
                    digest = sha256_file(
                        path,
                        should_cancel=should_cancel,
                    )
                except InterruptedError as exc:
                    raise ScanCancelled("media scan cancelled") from exc

                hashed += 1
                self._raise_if_cancelled(should_cancel)
                probe_result, probe_failed = self._probe(path)
                if probe_failed:
                    probe_errors += 1

                _, created = self.library.upsert_file(
                    path,
                    source_path,
                    content_sha256=digest,
                    probe=probe_result,
                )
                if created:
                    new_assets += 1
                else:
                    known_assets += 1
                self._report(
                    on_progress,
                    current=index,
                    total=total,
                    path=path,
                )

            self._raise_if_cancelled(should_cancel)
            self.library.reconcile_source(source_path, media_files)
            self.library.complete_source_scan(
                source_path,
                discovered_count=total,
            )

        except ScanCancelled:
            self.library.cancel_source_scan(
                source_path,
                discovered_count=total,
            )
            raise
        except Exception as exc:
            self.library.fail_source_scan(
                source_path,
                discovered_count=total,
                message=str(exc),
            )
            raise

        return ScanSummary(
            discovered=discovered,
            hashed=hashed,
            cache_hits=cache_hits,
            metadata_enriched=metadata_enriched,
            new_assets=new_assets,
            known_assets=known_assets,
            probe_errors=probe_errors,
        )

    @staticmethod
    def _iter_media_files(source: Path):
        if source.is_file():
            if source.suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS:
                yield source
            return

        for path in sorted(source.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS:
                yield path
