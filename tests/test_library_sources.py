from __future__ import annotations

from pathlib import Path

import pytest

from channelos.library import MediaLibrary
from channelos.probe import NullMediaProbe
from channelos.scanner import MediaScanner, ScanCancelled


def _write_media(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_discover_is_preflight_only(tmp_path: Path) -> None:
    root = tmp_path / "media"
    _write_media(root / "one.mp4", b"one")
    _write_media(root / "ignore.txt", b"not media")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())

    discovered = scanner.discover(root)

    assert discovered == ((root / "one.mp4").resolve(),)
    assert library.list_sources() == []
    assert library.list_online_media() == []


def test_successful_scan_creates_first_class_source_record(tmp_path: Path) -> None:
    root = tmp_path / "shows"
    _write_media(root / "one.mp4", b"one")
    _write_media(root / "two.mkv", b"two")

    library = MediaLibrary(tmp_path / "library.db")
    summary = MediaScanner(library, NullMediaProbe()).scan(root)

    assert summary.discovered == 2
    sources = library.list_sources()
    assert len(sources) == 1
    source = sources[0]
    assert source.source_root == root.resolve()
    assert source.status == "ready"
    assert source.discovered_count == 2
    assert source.location_count == 2
    assert source.online_location_count == 2
    assert source.asset_count == 2
    assert source.last_scan_finished_at is not None
    assert source.last_error is None


def test_cancelled_rescan_preserves_last_successful_membership(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    first = _write_media(root / "one.mp4", b"one")
    second = _write_media(root / "two.mp4", b"two")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())
    scanner.scan(root)

    # The file disappeared after the last good scan. A cancelled rescan must not
    # commit a half-reconciled view that silently removes it from the index.
    second.unlink()

    with pytest.raises(ScanCancelled):
        scanner.scan(root, should_cancel=lambda: True)

    online = library.list_online_media()
    assert {item.location.path for item in online} == {
        first.resolve(),
        second.resolve(),
    }
    sources = library.list_sources()
    assert len(sources) == 1
    assert sources[0].status == "cancelled"


def test_successful_rescan_reconciles_missing_files(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    first = _write_media(root / "one.mp4", b"one")
    second = _write_media(root / "two.mp4", b"two")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())
    scanner.scan(root)

    second.unlink()
    scanner.scan(root)

    online = library.list_online_media()
    assert [item.location.path for item in online] == [first.resolve()]


def test_remove_source_forgets_index_but_never_deletes_media(tmp_path: Path) -> None:
    root = tmp_path / "owned-media"
    media = _write_media(root / "movie.mp4", b"owned bytes")

    library = MediaLibrary(tmp_path / "library.db")
    MediaScanner(library, NullMediaProbe()).scan(root)

    result = library.remove_source_from_index(root)

    assert result.source_root == root.resolve()
    assert result.removed_locations == 1
    assert result.pruned_assets == 1
    assert media.exists()
    assert media.read_bytes() == b"owned bytes"
    assert library.list_sources() == []
    assert library.list_online_media() == []
    assert library.count_assets() == 0


def test_remove_one_source_preserves_shared_asset_referenced_elsewhere(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _write_media(root_a / "same.mp4", b"same bytes")
    _write_media(root_b / "same.mp4", b"same bytes")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())
    scanner.scan(root_a)
    scanner.scan(root_b)

    result = library.remove_source_from_index(root_a)

    assert result.removed_locations == 1
    assert result.pruned_assets == 0
    assert library.count_assets() == 1
    assert [item.location.source_root for item in library.list_online_media()] == [
        root_b.resolve()
    ]
