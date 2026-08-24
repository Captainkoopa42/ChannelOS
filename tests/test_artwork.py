from __future__ import annotations

import subprocess
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
