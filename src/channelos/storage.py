from __future__ import annotations

import os
import sqlite3
import warnings
from pathlib import Path

SQLITE_BUSY_TIMEOUT_MS = 5_000


class DatabaseVersionError(RuntimeError):
    """Raised when a database cannot be safely opened by this ChannelOS build."""


def database_path_is_local(database_path: str | Path) -> bool:
    """Return whether SQLite WAL is appropriate for this database path.

    SQLite's WAL journal is intentionally avoided for UNC/network-looking paths.
    The check is textual so Windows paths can also be covered by tests on Linux.
    """

    raw = os.fspath(database_path).strip()
    folded = raw.casefold()
    return not (
        folded.startswith("file:")
        or raw.startswith("\\\\")
        or raw.startswith("//")
    )


def configure_sqlite_connection(
    connection: sqlite3.Connection,
    database_path: str | Path,
    *,
    foreign_keys: bool = False,
) -> str:
    """Apply ChannelOS connection safety settings and return the journal mode."""

    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")

    requested_mode = "WAL" if database_path_is_local(database_path) else "DELETE"
    try:
        row = connection.execute(
            f"PRAGMA journal_mode = {requested_mode}"
        ).fetchone()
        actual_mode = "" if row is None else str(row[0]).casefold()
    except sqlite3.DatabaseError as exc:
        if requested_mode == "WAL":
            warnings.warn(
                f"SQLite WAL was unavailable for {database_path}; "
                f"continuing with the existing journal mode ({exc})",
                RuntimeWarning,
                stacklevel=2,
            )
        row = connection.execute("PRAGMA journal_mode").fetchone()
        actual_mode = "" if row is None else str(row[0]).casefold()

    if requested_mode == "WAL" and actual_mode != "wal":
        warnings.warn(
            f"SQLite returned journal_mode={actual_mode or 'unknown'} for "
            f"{database_path}; ChannelOS will continue without WAL",
            RuntimeWarning,
            stacklevel=2,
        )
    return actual_mode


def _validate_identifier(value: str) -> str:
    if not value or not value.replace("_", "").isalnum():
        raise ValueError(f"invalid SQLite identifier: {value!r}")
    return value


def inspect_database_version(
    database_path: str | Path,
    *,
    meta_table: str,
) -> int | None:
    """Read a schema version without modifying the database.

    ``None`` means a new/empty database. An existing legacy database with user
    tables but no version marker is reported as version 0.
    """

    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return None

    table = _validate_identifier(meta_table)
    connection = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if not tables:
            return None
        if table not in tables:
            return 0
        row = connection.execute(
            f"SELECT value FROM {table} WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise DatabaseVersionError(
            f"{path} has an invalid schema_version value: {row[0]!r}"
        ) from exc


def backup_database_once(database_path: str | Path) -> Path:
    """Create one consistent ``.bak`` snapshot without overwriting an older one."""

    path = Path(database_path)
    backup_path = Path(f"{path}.bak")
    if backup_path.exists():
        return backup_path

    source = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000)
    destination = sqlite3.connect(
        backup_path,
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000,
    )
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup_path


def prepare_database(
    database_path: str | Path,
    *,
    meta_table: str,
    supported_version: int,
) -> int | None:
    """Fail closed on future schemas and back up an older schema before writes."""

    current = inspect_database_version(database_path, meta_table=meta_table)
    if current is not None and current > supported_version:
        raise DatabaseVersionError(
            f"{database_path} uses schema version {current}, but this ChannelOS "
            f"build only supports version {supported_version}. Update ChannelOS "
            "before opening this database. No changes were made."
        )
    if current is not None and current < supported_version:
        backup_database_once(database_path)
    return current
