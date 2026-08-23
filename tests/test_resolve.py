from __future__ import annotations

from pathlib import Path

from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import NullMediaProbe
from channelos.resolve import resolve_channel
from channelos.scanner import MediaScanner


def _channel(
    number: int,
    name: str,
    sources: list[Path],
    *,
    preserve_episode_order: bool = False,
) -> ChannelDefinition:
    return ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": number,
            "name": name,
            "sources": [{"path": str(path)} for path in sources],
            "programming": {
                "mode": "sequential",
                "preserve_episode_order": preserve_episode_order,
            },
        }
    )


def _scan(library: MediaLibrary, *roots: Path) -> None:
    scanner = MediaScanner(library, NullMediaProbe())
    for root in roots:
        scanner.scan(root)


def test_channel_resolves_only_media_under_its_sources(tmp_path: Path) -> None:
    sci_fi = tmp_path / "Sci-Fi"
    comedy = tmp_path / "Comedy"
    sci_fi.mkdir()
    comedy.mkdir()
    (sci_fi / "a.mp4").write_bytes(b"a")
    (sci_fi / "b.mkv").write_bytes(b"b")
    (comedy / "c.mp4").write_bytes(b"c")

    library = MediaLibrary(tmp_path / "library.db")
    _scan(library, sci_fi, comedy)

    channel = _channel(7, "Sci-Fi", [sci_fi])

    resolved = resolve_channel(channel, library)
    assert [item.location.path.name for item in resolved.media] == [
        "a.mp4",
        "b.mkv",
    ]


def test_default_sequential_keeps_legacy_global_path_order(
    tmp_path: Path,
) -> None:
    zulu_first = tmp_path / "Zulu First Source"
    alpha_second = tmp_path / "Alpha Second Source"
    zulu_first.mkdir()
    alpha_second.mkdir()
    (zulu_first / "z.mp4").write_bytes(b"z")
    (alpha_second / "a.mp4").write_bytes(b"a")

    library = MediaLibrary(tmp_path / "library.db")
    _scan(library, zulu_first, alpha_second)

    channel = _channel(
        8,
        "Legacy Order",
        [zulu_first, alpha_second],
        preserve_episode_order=False,
    )

    resolved = resolve_channel(channel, library)
    assert [item.location.path.name for item in resolved.media] == [
        "a.mp4",
        "z.mp4",
    ]


def test_preserved_sequence_respects_declared_source_order(
    tmp_path: Path,
) -> None:
    zulu_first = tmp_path / "Zulu First Source"
    alpha_second = tmp_path / "Alpha Second Source"
    zulu_first.mkdir()
    alpha_second.mkdir()
    (zulu_first / "z.mp4").write_bytes(b"z")
    (alpha_second / "a.mp4").write_bytes(b"a")

    library = MediaLibrary(tmp_path / "library.db")
    _scan(library, zulu_first, alpha_second)

    channel = _channel(
        9,
        "Source Order",
        [zulu_first, alpha_second],
        preserve_episode_order=True,
    )

    resolved = resolve_channel(channel, library)
    assert [item.location.path.name for item in resolved.media] == [
        "z.mp4",
        "a.mp4",
    ]


def test_preserved_sequence_understands_common_episode_markers(
    tmp_path: Path,
) -> None:
    shows = tmp_path / "Show"
    shows.mkdir()
    names = [
        "Show S01E10 Finale.mkv",
        "Show S01E02 Second.mkv",
        "Show S01E01 Pilot.mkv",
    ]
    for index, name in enumerate(names):
        (shows / name).write_bytes(f"episode-{index}".encode())

    library = MediaLibrary(tmp_path / "library.db")
    _scan(library, shows)

    channel = _channel(
        10,
        "Episode Order",
        [shows],
        preserve_episode_order=True,
    )

    resolved = resolve_channel(channel, library)
    assert [item.location.path.name for item in resolved.media] == [
        "Show S01E01 Pilot.mkv",
        "Show S01E02 Second.mkv",
        "Show S01E10 Finale.mkv",
    ]


def test_preserved_sequence_orders_middle_earth_by_release_year(
    tmp_path: Path,
) -> None:
    hobbit = tmp_path / (
        "The Hobbit Trilogy 2012-2014 EXTENDED REMASTERED "
        "1080p BluRay HEVC x265 5.1 BONE"
    )
    lotr = tmp_path / (
        "The Lord of the Rings Trilogy 2002 EXTENDED REMASTERED "
        "1080p BluRay HEVC x265 5.1 BONE"
    )
    hobbit.mkdir()
    lotr.mkdir()

    hobbit_names = [
        "The Hobbit An Unexpected Journey 2012 EXTENDED REMASTERED.mkv",
        "The Hobbit The Battle of the Five Armies 2014 EXTENDED REMASTERED.mkv",
        "The Hobbit The Desolation of Smaug 2013 EXTENDED REMASTERED.mkv",
    ]
    lotr_names = [
        "The Lord of the Rings The Fellowship of the Ring 2001 EXTENDED REMASTERED.mkv",
        "The Lord of the Rings The Return of the King 2003 EXTENDED REMASTERED.mkv",
        "The Lord of the Rings The Two Towers 2002 EXTENDED REMASTERED.mkv",
    ]

    for index, name in enumerate(hobbit_names):
        (hobbit / name).write_bytes(f"hobbit-{index}".encode())
    for index, name in enumerate(lotr_names):
        (lotr / name).write_bytes(f"lotr-{index}".encode())

    library = MediaLibrary(tmp_path / "library.db")
    _scan(library, hobbit, lotr)

    channel = _channel(
        666,
        "LOTR",
        [hobbit, lotr],
        preserve_episode_order=True,
    )

    resolved = resolve_channel(channel, library)
    assert [item.location.path.name for item in resolved.media] == [
        "The Hobbit An Unexpected Journey 2012 EXTENDED REMASTERED.mkv",
        "The Hobbit The Desolation of Smaug 2013 EXTENDED REMASTERED.mkv",
        "The Hobbit The Battle of the Five Armies 2014 EXTENDED REMASTERED.mkv",
        "The Lord of the Rings The Fellowship of the Ring 2001 EXTENDED REMASTERED.mkv",
        "The Lord of the Rings The Two Towers 2002 EXTENDED REMASTERED.mkv",
        "The Lord of the Rings The Return of the King 2003 EXTENDED REMASTERED.mkv",
    ]
