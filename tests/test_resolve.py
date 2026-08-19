from __future__ import annotations

from pathlib import Path

from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import NullMediaProbe
from channelos.resolve import resolve_channel
from channelos.scanner import MediaScanner


def test_channel_resolves_only_media_under_its_sources(tmp_path: Path) -> None:
    sci_fi = tmp_path / "Sci-Fi"
    comedy = tmp_path / "Comedy"
    sci_fi.mkdir()
    comedy.mkdir()
    (sci_fi / "a.mp4").write_bytes(b"a")
    (sci_fi / "b.mkv").write_bytes(b"b")
    (comedy / "c.mp4").write_bytes(b"c")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, NullMediaProbe())
    scanner.scan(sci_fi)
    scanner.scan(comedy)

    channel = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": 7,
            "name": "Sci-Fi",
            "sources": [{"path": str(sci_fi)}],
            "programming": {"mode": "sequential"},
        }
    )

    resolved = resolve_channel(channel, library)
    assert [item.location.path.name for item in resolved.media] == ["a.mp4", "b.mkv"]
