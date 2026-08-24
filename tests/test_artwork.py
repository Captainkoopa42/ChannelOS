from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from channelos.artwork import MediaArtworkCache


def test_exact_sidecar_art_takes_priority_over_generic_art(tmp_path: Path) -> None:
    media = tmp_path / "My Movie.mkv"
    media.write_bytes(b"video")
    exact = tmp_path / "MY MOVIE.PNG"
    exact.write_bytes(b"exact")
    generic = tmp_path / "poster.jpg"
    generic.write_bytes(b"generic")

    cache = MediaArtworkCache(tmp_path / "cache")

    assert cache.resolve(media, "sha256:abc", 120.0) == exact
    assert not (tmp_path / "cache").exists()


def test_generic_folder_art_is_used_when_exact_art_is_absent(tmp_path: Path) -> None:
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"video")
    cover = tmp_path / "cover.webp"
    cover.write_bytes(b"cover")

    cache = MediaArtworkCache(tmp_path / "cache")

    assert cache.resolve(media, "sha256:def", 60.0) == cover


def test_cached_thumbnail_is_reused_without_ffmpeg(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    cache = MediaArtworkCache(tmp_path / "cache")
    cached = cache.cache_path("sha256:1234")
    cached.parent.mkdir()
    cached.write_bytes(b"jpeg")

    assert cache.resolve(media, "sha256:1234", 60.0) == cached


def test_missing_artwork_and_ffmpeg_leave_the_fallback_untouched(
    tmp_path: Path,
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    cache = MediaArtworkCache(
        tmp_path / "cache",
        ffmpeg_executable=tmp_path / "missing-ffmpeg",
    )

    assert cache.resolve(media, "sha256:5678", 60.0) is None
    assert not cache.cache_directory.exists()


def test_discovery_cache_can_be_cleared_for_new_sidecar_art(
    tmp_path: Path,
) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    cache = MediaArtworkCache(
        tmp_path / "cache",
        ffmpeg_executable=tmp_path / "missing-ffmpeg",
    )
    assert cache.resolve(media, "sha256:5678", 60.0) is None

    cover = tmp_path / "clip.jpg"
    cover.write_bytes(b"new art")
    assert cache.resolve(media, "sha256:5678", 60.0) is None

    cache.clear_discovery_cache()
    assert cache.resolve(media, "sha256:5678", 60.0) == cover


def test_ffmpeg_thumbnail_is_written_to_the_local_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"video")
    executable = tmp_path / "ffmpeg"
    executable.write_bytes(b"executable")
    cache = MediaArtworkCache(
        tmp_path / "cache",
        ffmpeg_executable=executable,
    )

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    resolved = cache.resolve(media, "sha256:9abc", 7200.0)

    assert resolved == cache.cache_path("sha256:9abc")
    assert resolved.read_bytes() == b"jpeg"


def test_generation_can_be_disabled_without_hiding_sidecars_or_cache(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.mp4"
    first.write_bytes(b"video")
    sidecar = tmp_path / "first.jpg"
    sidecar.write_bytes(b"sidecar")
    second = tmp_path / "second.mp4"
    second.write_bytes(b"video")
    cache = MediaArtworkCache(tmp_path / "cache")
    cached = cache.cache_path("second")
    cached.parent.mkdir()
    cached.write_bytes(b"cached")

    assert cache.resolve(first, "first", 30, allow_generate=False) == sidecar
    assert cache.resolve(second, "second", 30, allow_generate=False) == cached
    assert cache.resolve(tmp_path / "missing.mp4", "third", 30, allow_generate=False) is None


def test_clear_generated_never_removes_unrecognized_or_sidecar_images(
    tmp_path: Path,
) -> None:
    cache = MediaArtworkCache(tmp_path / "cache")
    generated = cache.cache_path("movie")
    generated.parent.mkdir()
    generated.write_bytes(b"generated")
    unrelated = cache.cache_directory / "family-photo.jpg"
    unrelated.write_bytes(b"keep")
    sidecar = tmp_path / "poster.jpg"
    sidecar.write_bytes(b"keep too")

    change = cache.clear_generated()

    assert change.removed_files == 1
    assert change.removed_bytes == len(b"generated")
    assert not generated.exists()
    assert unrelated.read_bytes() == b"keep"
    assert sidecar.read_bytes() == b"keep too"
    assert change.remaining.file_count == 0


def test_prune_removes_oldest_generated_thumbnails_first(tmp_path: Path) -> None:
    cache = MediaArtworkCache(tmp_path / "cache")
    oldest = cache.cache_path("oldest")
    middle = cache.cache_path("middle")
    newest = cache.cache_path("newest")
    oldest.parent.mkdir()
    for position, path in enumerate((oldest, middle, newest), start=1):
        path.write_bytes(b"1234")
        os.utime(path, (position, position))

    change = cache.prune(8)

    assert change.removed_files == 1
    assert not oldest.exists()
    assert middle.exists()
    assert newest.exists()
    assert change.remaining.size_bytes == 8


def test_thumbnail_generation_respects_width_and_thread_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"video")
    executable = tmp_path / "ffmpeg"
    executable.write_bytes(b"executable")
    cache = MediaArtworkCache(
        tmp_path / "cache",
        ffmpeg_executable=executable,
    )
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        Path(command[-1]).write_bytes(b"jpeg")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cache.resolve(
        media,
        "movie",
        90,
        max_width=320,
        ffmpeg_threads=1,
    ) is not None
    assert "scale=320:-2" in captured
    assert captured[captured.index("-threads") + 1] == "1"


def test_cache_clear_cancels_an_in_progress_thumbnail_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"video")
    executable = tmp_path / "ffmpeg"
    executable.write_bytes(b"executable")
    cache = MediaArtworkCache(
        tmp_path / "cache",
        ffmpeg_executable=executable,
    )
    thumbnail_ready = threading.Event()
    release_ffmpeg = threading.Event()
    resolved: list[Path | None] = []

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"jpeg")
        thumbnail_ready.set()
        assert release_ffmpeg.wait(timeout=3)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    worker = threading.Thread(
        target=lambda: resolved.append(cache.resolve(media, "movie", 90))
    )
    worker.start()
    assert thumbnail_ready.wait(timeout=3)

    cache.clear_generated()
    release_ffmpeg.set()
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert resolved == [None]
    assert not cache.cache_path("movie").exists()
