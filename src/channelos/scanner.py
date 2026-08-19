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

    def scan(self, source: str | Path) -> ScanSummary:
        source_path = Path(source).expanduser().resolve(strict=False)
        if not source_path.exists():
            raise FileNotFoundError(f"media source does not exist: {source_path}")

        source_root = source_path
        self.library.mark_source_offline(source_root)

        discovered = hashed = cache_hits = new_assets = known_assets = probe_errors = 0
        for path in self._iter_media_files(source_path):
            discovered += 1
            cached = self.library.cached_asset_for_unchanged_path(path)
            if cached is not None:
                self.library.mark_seen_cached(path, source_root)
                cache_hits += 1
                known_assets += 1
                continue

            digest = sha256_file(path)
            hashed += 1
            try:
                probe_result = self.probe.probe(path)
            except MediaProbeError:
                if self.fail_on_probe_error:
                    raise
                probe_result = MediaProbeResult()
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
