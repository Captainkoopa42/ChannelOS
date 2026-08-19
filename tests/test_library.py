from __future__ import annotations

from pathlib import Path

from channelos.library import MediaLibrary
from channelos.probe import NullMediaProbe
from channelos.scanner import MediaScanner


def test_media_identity_survives_move(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    original = media_root / "episode.mp4"
    original.write_bytes(b"same owned media" * 100)

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())

    first = scanner.scan(media_root)
    assert first.discovered == 1
    assert first.new_assets == 1
    indexed = library.list_online_media()
    assert len(indexed) == 1
    asset_id = indexed[0].asset.asset_id

    moved = media_root / "Season 1" / "episode.mp4"
    moved.parent.mkdir()
    original.rename(moved)

    second = scanner.scan(media_root)
    assert second.discovered == 1
    assert second.known_assets == 1
    assert library.count_assets() == 1

    locations = library.locations_for_asset(asset_id)
    assert len(locations) == 2
    assert {location.online for location in locations} == {False, True}
    assert [location.path for location in locations if location.online] == [moved.resolve()]


def test_unchanged_file_uses_scan_cache(tmp_path: Path) -> None:
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"movie bytes")
    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())

    first = scanner.scan(media)
    second = scanner.scan(media)

    assert first.hashed == 1
    assert second.hashed == 0
    assert second.cache_hits == 1
