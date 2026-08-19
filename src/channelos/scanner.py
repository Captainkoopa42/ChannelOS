from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True, slots=True)
class ScanSummary:
    discovered: int = 0
    hashed: int = 0
    cache_hits: int = 0
    metadata_enriched: int = 0
    new_assets: int = 0
    known_assets: int = 0
    probe_errors: int = 0


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

    def scan(self, source: str | Path) -> ScanSummary:
        source_path = Path(source).expanduser().resolve(strict=False)
        if not source_path.exists():
            raise FileNotFoundError(f"media source does not exist: {source_path}")

        source_root = source_path
        self.library.mark_source_offline(source_root)

        discovered = hashed = cache_hits = metadata_enriched = 0
        new_assets = known_assets = probe_errors = 0
        for path in self._iter_media_files(source_path):
            discovered += 1
            cached = self.library.cached_asset_for_unchanged_path(path)
            if cached is not None:
                cache_hits += 1
                known_assets += 1

                # A content cache hit must not permanently freeze an asset at the
                # metadata quality of its first scan. If a file was originally
                # indexed with --no-probe (or while ffprobe was unavailable), a
                # later technical scan can enrich it using the already-trusted
                # content hash instead of reading and hashing the whole file again.
                if cached.duration_seconds is None or cached.container_format is None:
                    probe_result, probe_failed = self._probe(path)
                    if probe_failed:
                        probe_errors += 1
                    if self._adds_technical_data(cached, probe_result):
                        self.library.upsert_file(
                            path,
                            source_root,
                            content_sha256=cached.content_sha256,
                            probe=probe_result,
                        )
                        metadata_enriched += 1
                    else:
                        self.library.mark_seen_cached(path, source_root)
                else:
                    self.library.mark_seen_cached(path, source_root)
                continue

            digest = sha256_file(path)
            hashed += 1
            probe_result, probe_failed = self._probe(path)
            if probe_failed:
                probe_errors += 1

            _, created = self.library.upsert_file(
                path,
                source_root,
                content_sha256=digest,
                probe=probe_result,
            )
            if created:
                new_assets += 1
            else:
                known_assets += 1

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
