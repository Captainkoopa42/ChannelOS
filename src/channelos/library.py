from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .probe import MediaProbeResult

SCHEMA_VERSION = 1
HASH_CHUNK_SIZE = 4 * 1024 * 1024


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_path(path: str | Path) -> tuple[str, str]:
    resolved = Path(path).expanduser().resolve(strict=False)
    text = str(resolved)
    return text, os.path.normcase(os.path.normpath(text))


def sha256_file(path: Path, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def media_asset_id(content_sha256: str) -> str:
    return f"sha256:{content_sha256.lower()}"


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


class MediaLibrary:
    """SQLite-backed local index. It references user media; it never owns the files."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO library_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def mark_source_offline(self, source_root: str | Path) -> None:
        _, source_key = normalize_path(source_root)
        with self.connect() as connection:
            connection.execute(
                "UPDATE media_locations SET online = 0 WHERE source_root_key = ?",
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
