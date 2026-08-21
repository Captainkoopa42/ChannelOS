from __future__ import annotations

from channelos.library import MediaLibrary
from channelos.probe import NullMediaProbe
from channelos.scanner import MediaScanner, ScanProgress


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
