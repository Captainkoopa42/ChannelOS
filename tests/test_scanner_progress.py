from __future__ import annotations

import pytest

from channelos.library import MediaLibrary
from channelos.probe import NullMediaProbe
from channelos.scanner import MediaScanner, ScanCancelled, ScanProgress


def test_scan_reports_stable_progress_and_cache_hits(tmp_path) -> None:
    media_root = tmp_path / "captures"
    media_root.mkdir()
    (media_root / "alpha.mp4").write_bytes(b"alpha")
    (media_root / "beta.mkv").write_bytes(b"beta")
    (media_root / "notes.txt").write_text("not media", encoding="utf-8")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())
    progress: list[ScanProgress] = []

    summary = scanner.scan(media_root, on_progress=progress.append)

    assert summary.discovered == 2
    assert summary.hashed == 2
    assert summary.new_assets == 2
    assert progress[0] == ScanProgress(current=0, total=2, path=None)
    assert [event.current for event in progress] == [0, 1, 2]
    assert [event.path.name for event in progress[1:]] == ["alpha.mp4", "beta.mkv"]
    assert progress[-1].fraction == 1.0

    cached_progress: list[ScanProgress] = []
    cached = scanner.scan(media_root, on_progress=cached_progress.append)

    assert cached.discovered == 2
    assert cached.hashed == 0
    assert cached.cache_hits == 2
    assert cached_progress[-1].current == cached_progress[-1].total == 2


def test_cancelled_rescan_preserves_the_last_successful_source_membership(
    tmp_path,
) -> None:
    media_root = tmp_path / "captures"
    media_root.mkdir()
    alpha = media_root / "alpha.mp4"
    beta = media_root / "beta.mkv"
    alpha.write_bytes(b"alpha")
    beta.write_bytes(b"beta")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())
    scanner.scan(media_root)
    beta.unlink()

    with pytest.raises(ScanCancelled):
        scanner.scan(media_root, should_cancel=lambda: True)

    assert [
        item.location.path.name
        for item in library.list_online_media()
    ] == ["alpha.mp4", "beta.mkv"]
    source = library.list_sources()[0]
    assert source.status == "cancelled"
