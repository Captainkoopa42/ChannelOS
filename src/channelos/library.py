from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .probe import MediaProbeResult
from .storage import (
    SQLITE_BUSY_TIMEOUT_MS,
    configure_sqlite_connection,
    prepare_database,
)

SCHEMA_VERSION = 2
HASH_CHUNK_SIZE = 4 * 1024 * 1024


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_path(path: str | Path) -> tuple[str, str]:
    resolved = Path(path).expanduser().resolve(strict=False)
    text = str(resolved)
    return text, os.path.normcase(os.path.normpath(text))


def sha256_file(
    path: Path,
    chunk_size: int = HASH_CHUNK_SIZE,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            if should_cancel is not None and should_cancel():
                raise InterruptedError("media hashing cancelled")
            digest.update(chunk)
    return digest.hexdigest()


def media_asset_id(content_sha256: str) -> str:
    return f"sha256:{content_sha256.lower()}"


class _ClosingSQLiteConnection(sqlite3.Connection):
    """Context-managed sqlite connection that actually releases its OS handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


@dataclass(frozen=True, slots=True)
class MediaAsset:
    asset_id: str
    content_sha256: str
    size_bytes: int
    duration_seconds: float | None
    container_format: str | None


@dataclass(frozen=True, slots=True)
class MediaLocation:
    path: Path
    path_key: str
    asset_id: str
    source_root: Path
    online: bool


@dataclass(frozen=True, slots=True)
class IndexedMedia:
    asset: MediaAsset
    location: MediaLocation


@dataclass(frozen=True, slots=True)
class MediaSource:
    """One user-selected media root tracked by the canonical library index."""

    source_root: Path
    source_root_key: str
    status: str
    discovered_count: int
    location_count: int
    online_location_count: int
    asset_count: int
    last_scan_started_at: str | None
    last_scan_finished_at: str | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class SourceRemovalResult:
    source_root: Path
    removed_locations: int
    pruned_assets: int


class MediaLibrary:
    """SQLite-backed local index. It references user media; it never owns the files."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        prepare_database(
            self.database_path,
            meta_table="library_meta",
            supported_version=SCHEMA_VERSION,
        )
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000,
            factory=_ClosingSQLiteConnection,
        )
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(
            connection,
            self.database_path,
            foreign_keys=True,
        )
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS library_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS media_assets (
                    asset_id TEXT PRIMARY KEY,
                    content_sha256 TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    duration_seconds REAL,
                    container_format TEXT,
                    probe_json TEXT,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS media_locations (
                    path_key TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    source_root_key TEXT NOT NULL,
                    source_root TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    online INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(asset_id) REFERENCES media_assets(asset_id)
                );

                CREATE INDEX IF NOT EXISTS idx_media_locations_asset
                    ON media_locations(asset_id);
                CREATE INDEX IF NOT EXISTS idx_media_locations_root
                    ON media_locations(source_root_key, online);

                CREATE TABLE IF NOT EXISTS media_sources (
                    source_root_key TEXT PRIMARY KEY,
                    source_root TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    discovered_count INTEGER NOT NULL DEFAULT 0,
                    last_scan_started_at TEXT,
                    last_scan_finished_at TEXT,
                    last_error TEXT
                );
                """
            )
            # Existing databases already contain source roots implicitly in
            # media_locations. Promote them to first-class source records without
            # rewriting media identity or file ownership state.
            connection.execute(
                """
                INSERT OR IGNORE INTO media_sources(
                    source_root_key,
                    source_root,
                    status,
                    discovered_count,
                    last_scan_started_at,
                    last_scan_finished_at,
                    last_error
                )
                SELECT
                    source_root_key,
                    MAX(source_root),
                    'ready',
                    COUNT(*),
                    NULL,
                    MAX(last_seen_at),
                    NULL
                FROM media_locations
                GROUP BY source_root_key
                """
            )
            connection.execute(
                """
                INSERT INTO library_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def _upsert_source_state(
        self,
        source_root: str | Path,
        *,
        status: str,
        discovered_count: int,
        scan_started_at: str | None = None,
        scan_finished_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        source_text, source_key = normalize_path(source_root)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO media_sources(
                    source_root_key,
                    source_root,
                    status,
                    discovered_count,
                    last_scan_started_at,
                    last_scan_finished_at,
                    last_error
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_root_key) DO UPDATE SET
                    source_root = excluded.source_root,
                    status = excluded.status,
                    discovered_count = excluded.discovered_count,
                    last_scan_started_at = COALESCE(
                        excluded.last_scan_started_at,
                        media_sources.last_scan_started_at
                    ),
                    last_scan_finished_at = excluded.last_scan_finished_at,
                    last_error = excluded.last_error
                """,
                (
                    source_key,
                    source_text,
                    status,
                    max(0, int(discovered_count)),
                    scan_started_at,
                    scan_finished_at,
                    last_error,
                ),
            )

    def begin_source_scan(
        self,
        source_root: str | Path,
        *,
        discovered_count: int,
    ) -> None:
        self._upsert_source_state(
            source_root,
            status="indexing",
            discovered_count=discovered_count,
            scan_started_at=utc_now_text(),
            scan_finished_at=None,
            last_error=None,
        )

    def complete_source_scan(
        self,
        source_root: str | Path,
        *,
        discovered_count: int,
    ) -> None:
        self._upsert_source_state(
            source_root,
            status="ready",
            discovered_count=discovered_count,
            scan_finished_at=utc_now_text(),
            last_error=None,
        )

    def cancel_source_scan(
        self,
        source_root: str | Path,
        *,
        discovered_count: int,
    ) -> None:
        self._upsert_source_state(
            source_root,
            status="cancelled",
            discovered_count=discovered_count,
            scan_finished_at=utc_now_text(),
            last_error=None,
        )

    def fail_source_scan(
        self,
        source_root: str | Path,
        *,
        discovered_count: int,
        message: str,
    ) -> None:
        self._upsert_source_state(
            source_root,
            status="error",
            discovered_count=discovered_count,
            scan_finished_at=utc_now_text(),
            last_error=str(message),
        )

    def mark_source_offline(self, source_root: str | Path) -> None:
        """Compatibility helper for callers that deliberately invalidate a root."""

        _, source_key = normalize_path(source_root)
        with self.connect() as connection:
            connection.execute(
                "UPDATE media_locations SET online = 0 WHERE source_root_key = ?",
                (source_key,),
            )

    def reconcile_source(
        self,
        source_root: str | Path,
        seen_paths: Iterable[str | Path],
    ) -> None:
        """Apply source membership only after a complete successful scan.

        A cancelled or failed scan therefore cannot make unprocessed library
        entries disappear merely because the user stopped an in-progress job.
        """

        _, source_key = normalize_path(source_root)
        seen_keys = [normalize_path(path)[1] for path in seen_paths]

        with self.connect() as connection:
            connection.execute(
                "CREATE TEMP TABLE scan_seen_paths(path_key TEXT PRIMARY KEY)"
            )
            if seen_keys:
                connection.executemany(
                    "INSERT OR IGNORE INTO scan_seen_paths(path_key) VALUES(?)",
                    ((key,) for key in seen_keys),
                )
            connection.execute(
                """
                UPDATE media_locations
                SET online = CASE
                    WHEN EXISTS(
                        SELECT 1
                        FROM scan_seen_paths s
                        WHERE s.path_key = media_locations.path_key
                    ) THEN 1
                    ELSE 0
                END
                WHERE source_root_key = ?
                """,
                (source_key,),
            )

    def cached_asset_for_unchanged_path(self, path: Path) -> MediaAsset | None:
        _, path_key = normalize_path(path)
        try:
            stat = path.stat()
        except OSError:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT a.*
                FROM media_locations l
                JOIN media_assets a ON a.asset_id = l.asset_id
                WHERE l.path_key = ? AND l.size_bytes = ? AND l.mtime_ns = ?
                """,
                (path_key, stat.st_size, stat.st_mtime_ns),
            ).fetchone()
        if row is None:
            return None
        return self._asset_from_row(row)

    def upsert_file(
        self,
        path: Path,
        source_root: Path,
        *,
        content_sha256: str,
        probe: MediaProbeResult,
    ) -> tuple[MediaAsset, bool]:
        path_text, path_key = normalize_path(path)
        source_text, source_key = normalize_path(source_root)
        stat = path.stat()
        now = utc_now_text()
        asset_id = media_asset_id(content_sha256)

        with self.connect() as connection:
            existed = (
                connection.execute(
                    "SELECT 1 FROM media_assets WHERE asset_id = ?", (asset_id,)
                ).fetchone()
                is not None
            )
            connection.execute(
                """
                INSERT INTO media_assets(
                    asset_id, content_sha256, size_bytes, duration_seconds,
                    container_format, probe_json, first_seen_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    size_bytes = excluded.size_bytes,
                    duration_seconds = COALESCE(excluded.duration_seconds, media_assets.duration_seconds),
                    container_format = COALESCE(excluded.container_format, media_assets.container_format),
                    probe_json = COALESCE(excluded.probe_json, media_assets.probe_json),
                    updated_at = excluded.updated_at
                """,
                (
                    asset_id,
                    content_sha256,
                    stat.st_size,
                    probe.duration_seconds,
                    probe.container_format,
                    probe.raw_json,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO media_locations(
                    path_key, path, asset_id, source_root_key, source_root,
                    size_bytes, mtime_ns, online, last_seen_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(path_key) DO UPDATE SET
                    path = excluded.path,
                    asset_id = excluded.asset_id,
                    source_root_key = excluded.source_root_key,
                    source_root = excluded.source_root,
                    size_bytes = excluded.size_bytes,
                    mtime_ns = excluded.mtime_ns,
                    online = 1,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    path_key,
                    path_text,
                    asset_id,
                    source_key,
                    source_text,
                    stat.st_size,
                    stat.st_mtime_ns,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM media_assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        assert row is not None
        return self._asset_from_row(row), not existed

    def mark_seen_cached(self, path: Path, source_root: Path) -> None:
        path_text, path_key = normalize_path(path)
        source_text, source_key = normalize_path(source_root)
        stat = path.stat()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE media_locations
                SET path = ?, source_root_key = ?, source_root = ?, size_bytes = ?,
                    mtime_ns = ?, online = 1, last_seen_at = ?
                WHERE path_key = ?
                """,
                (
                    path_text,
                    source_key,
                    source_text,
                    stat.st_size,
                    stat.st_mtime_ns,
                    utc_now_text(),
                    path_key,
                ),
            )

    def list_online_media(self) -> list[IndexedMedia]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.asset_id, a.content_sha256, a.size_bytes AS asset_size_bytes,
                    a.duration_seconds, a.container_format,
                    l.path, l.path_key, l.source_root, l.online
                FROM media_locations l
                JOIN media_assets a ON a.asset_id = l.asset_id
                WHERE l.online = 1
                ORDER BY l.path_key
                """
            ).fetchall()
        return [self._indexed_from_row(row) for row in rows]

    def list_online_media_for_source(
        self,
        source_root: str | Path,
    ) -> list[IndexedMedia]:
        """Load online rows for one indexed source without scanning all media."""

        _, source_key = normalize_path(source_root)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.asset_id, a.content_sha256, a.size_bytes AS asset_size_bytes,
                    a.duration_seconds, a.container_format,
                    l.path, l.path_key, l.source_root, l.online
                FROM media_locations l
                JOIN media_assets a ON a.asset_id = l.asset_id
                WHERE l.online = 1 AND l.source_root_key = ?
                ORDER BY l.path_key
                """,
                (source_key,),
            ).fetchall()
        return [self._indexed_from_row(row) for row in rows]

    def list_online_source_roots(self) -> tuple[Path, ...]:
        """Return distinct online source roots using the location index only."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_root
                FROM media_locations
                WHERE online = 1
                GROUP BY source_root_key
                ORDER BY source_root_key
                """
            ).fetchall()
        return tuple(Path(row["source_root"]) for row in rows)

    def list_sources(self) -> list[MediaSource]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.source_root,
                    s.source_root_key,
                    s.status,
                    s.discovered_count,
                    s.last_scan_started_at,
                    s.last_scan_finished_at,
                    s.last_error,
                    COUNT(l.path_key) AS location_count,
                    COALESCE(SUM(CASE WHEN l.online = 1 THEN 1 ELSE 0 END), 0)
                        AS online_location_count,
                    COUNT(DISTINCT l.asset_id) AS asset_count
                FROM media_sources s
                LEFT JOIN media_locations l
                    ON l.source_root_key = s.source_root_key
                GROUP BY
                    s.source_root_key,
                    s.source_root,
                    s.status,
                    s.discovered_count,
                    s.last_scan_started_at,
                    s.last_scan_finished_at,
                    s.last_error
                ORDER BY s.source_root
                """
            ).fetchall()

        return [
            MediaSource(
                source_root=Path(row["source_root"]),
                source_root_key=row["source_root_key"],
                status=row["status"],
                discovered_count=int(row["discovered_count"]),
                location_count=int(row["location_count"]),
                online_location_count=int(row["online_location_count"]),
                asset_count=int(row["asset_count"]),
                last_scan_started_at=row["last_scan_started_at"],
                last_scan_finished_at=row["last_scan_finished_at"],
                last_error=row["last_error"],
            )
            for row in rows
        ]

    def remove_source_from_index(
        self,
        source_root: str | Path,
    ) -> SourceRemovalResult:
        """Forget one source without touching any file on disk."""

        source_text, source_key = normalize_path(source_root)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM media_locations WHERE source_root_key = ?",
                (source_key,),
            ).fetchone()
            removed_locations = int(row["n"])

            connection.execute(
                "DELETE FROM media_locations WHERE source_root_key = ?",
                (source_key,),
            )
            connection.execute(
                "DELETE FROM media_sources WHERE source_root_key = ?",
                (source_key,),
            )

            orphan_row = connection.execute(
                """
                SELECT COUNT(*) AS n
                FROM media_assets a
                WHERE NOT EXISTS(
                    SELECT 1 FROM media_locations l WHERE l.asset_id = a.asset_id
                )
                """
            ).fetchone()
            pruned_assets = int(orphan_row["n"])
            connection.execute(
                """
                DELETE FROM media_assets
                WHERE NOT EXISTS(
                    SELECT 1
                    FROM media_locations l
                    WHERE l.asset_id = media_assets.asset_id
                )
                """
            )

        return SourceRemovalResult(
            source_root=Path(source_text),
            removed_locations=removed_locations,
            pruned_assets=pruned_assets,
        )

    def locations_for_asset(self, asset_id: str) -> list[MediaLocation]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT path, path_key, asset_id, source_root, online
                FROM media_locations WHERE asset_id = ? ORDER BY path_key
                """,
                (asset_id,),
            ).fetchall()
        return [
            MediaLocation(
                path=Path(row["path"]),
                path_key=row["path_key"],
                asset_id=row["asset_id"],
                source_root=Path(row["source_root"]),
                online=bool(row["online"]),
            )
            for row in rows
        ]

    def count_assets(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM media_assets").fetchone()
        return int(row["n"])

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> MediaAsset:
        return MediaAsset(
            asset_id=row["asset_id"],
            content_sha256=row["content_sha256"],
            size_bytes=int(row["size_bytes"]),
            duration_seconds=row["duration_seconds"],
            container_format=row["container_format"],
        )

    @staticmethod
    def _indexed_from_row(row: sqlite3.Row) -> IndexedMedia:
        asset = MediaAsset(
            asset_id=row["asset_id"],
            content_sha256=row["content_sha256"],
            size_bytes=int(row["asset_size_bytes"]),
            duration_seconds=row["duration_seconds"],
            container_format=row["container_format"],
        )
        location = MediaLocation(
            path=Path(row["path"]),
            path_key=row["path_key"],
            asset_id=row["asset_id"],
            source_root=Path(row["source_root"]),
            online=bool(row["online"]),
        )
        return IndexedMedia(asset=asset, location=location)
