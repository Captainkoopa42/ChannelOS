from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from channelos.broadcaster import BroadcasterService
from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import NullMediaProbe
from channelos.resolve import resolve_channel
from channelos.runtime import RuntimeStore
from channelos.scanner import MediaScanner
from channelos.storage import (
    DatabaseVersionError,
    SQLITE_BUSY_TIMEOUT_MS,
    configure_sqlite_connection,
    database_path_is_local,
)


def _write_version_database(path: Path, table: str, version: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"CREATE TABLE {table}(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            f"INSERT INTO {table}(key, value) VALUES('schema_version', ?)",
            (str(version),),
        )


@pytest.mark.parametrize(
    ("factory", "meta_table"),
    [
        (MediaLibrary, "library_meta"),
        (RuntimeStore, "runtime_meta"),
    ],
)
def test_future_database_versions_fail_closed_without_writes(
    tmp_path: Path,
    factory,
    meta_table: str,
) -> None:
    database = tmp_path / f"{meta_table}.db"
    _write_version_database(database, meta_table, 999)
    before = database.read_bytes()

    with pytest.raises(DatabaseVersionError, match="No changes were made"):
        factory(database)

    assert database.read_bytes() == before
    assert not Path(f"{database}.bak").exists()


@pytest.mark.parametrize(
    ("factory", "meta_table"),
    [
        (MediaLibrary, "library_meta"),
        (RuntimeStore, "runtime_meta"),
    ],
)
def test_older_database_is_backed_up_once_before_upgrade(
    tmp_path: Path,
    factory,
    meta_table: str,
) -> None:
    database = tmp_path / f"old-{meta_table}.db"
    _write_version_database(database, meta_table, 1)

    factory(database)

    backup = Path(f"{database}.bak")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        backed_up_version = connection.execute(
            f"SELECT value FROM {meta_table} WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert backed_up_version == "1"

    backup_bytes = backup.read_bytes()
    factory(database)
    assert backup.read_bytes() == backup_bytes


@pytest.mark.parametrize("factory", [MediaLibrary, RuntimeStore])
def test_local_database_uses_wal_and_finite_busy_timeout(
    tmp_path: Path,
    factory,
) -> None:
    store = factory(tmp_path / f"{factory.__name__}.db")
    with store.connect() as connection:
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert str(journal).casefold() == "wal"
    assert int(timeout) == SQLITE_BUSY_TIMEOUT_MS


def test_network_looking_database_path_avoids_wal(tmp_path: Path) -> None:
    database = tmp_path / "simulated-network.db"
    with sqlite3.connect(database) as connection:
        journal = configure_sqlite_connection(
            connection,
            r"\\server\share\channelos.db",
        )
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert not database_path_is_local(r"\\server\share\channelos.db")
    assert not database_path_is_local("file://server/share/channelos.db")
    assert journal == "delete"
    assert int(timeout) == SQLITE_BUSY_TIMEOUT_MS


def test_tuning_pair_rolls_back_together_on_second_write_failure(
    tmp_path: Path,
) -> None:
    store = RuntimeStore(tmp_path / "runtime.db")
    store.set_tuning(7, 12)
    with store.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_previous_channel
            BEFORE INSERT ON runtime_meta
            WHEN NEW.key = 'previous_channel'
            BEGIN
                SELECT RAISE(ABORT, 'simulated second write failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="second write failure"):
        store.set_tuning(22, 7)

    assert store.get_tuning() == (7, 12)


def test_resolution_and_source_options_do_not_load_the_whole_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "first.mp4").write_bytes(b"first")
    (second / "second.mp4").write_bytes(b"second")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())
    scanner.scan(first)
    scanner.scan(second)

    def reject_full_snapshot():
        raise AssertionError("the full online-media snapshot must not be loaded")

    monkeypatch.setattr(library, "list_online_media", reject_full_snapshot)

    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": 7,
            "name": "First only",
            "sources": [{"path": str(first)}],
            "programming": {"mode": "sequential"},
        }
    )
    resolved = resolve_channel(definition, library)
    assert [item.location.path.name for item in resolved.media] == ["first.mp4"]

    broadcaster = BroadcasterService((), tmp_path / "channels", library)
    assert set(broadcaster.source_options()) == {
        str(first.resolve()),
        str(second.resolve()),
    }


def test_home_add_media_uses_the_shared_background_scan_entrypoint() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "channelos"
        / "couch_qt.py"
    ).read_text(encoding="utf-8")
    method = source.split(
        "    def _choose_and_scan_media_folder(self) -> None:",
        maxsplit=1,
    )[1].split("    def _cancel_home_media_scan", maxsplit=1)[0]

    assert 'getattr(self._controller, "startMediaScan", None)' in method
    assert "scan_media_folder" not in method
    assert "processEvents" not in method
    assert "WindowModality.NonModal" in method


def test_artwork_publication_patches_cards_without_rebuilding_library() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "channelos"
        / "couch_qt.py"
    ).read_text(encoding="utf-8")
    method = source.split(
        "    def _publish_library_artwork(self) -> None:",
        maxsplit=1,
    )[1].split("    @Slot()", maxsplit=1)[0]

    assert "self._artwork_pending" in method
    assert 'item["artworkUrl"]' in method
    assert "_build_library_snapshot" not in method
