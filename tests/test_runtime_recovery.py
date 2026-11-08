from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import MediaProbeResult
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore
from channelos.scanner import MediaScanner

UTC = timezone.utc


class ConstantDurationProbe:
    def probe(self, path: Path) -> MediaProbeResult:
        return MediaProbeResult(duration_seconds=30.0, container_format=path.suffix.lstrip("."))


def test_missing_file_recovery_keeps_the_clock_and_drops_the_file_at_the_next_program(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    first_path = media_dir / "a.mp4"
    missing_path = media_dir / "b.mp4"
    first_path.write_bytes(b"a")
    missing_path.write_bytes(b"b")

    library = MediaLibrary(tmp_path / "library.db")
    scanner = MediaScanner(library, ConstantDurationProbe())
    scanner.scan(media_dir)

    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": 7,
            "name": "Recovery Test",
            "sources": [{"path": str(media_dir)}],
            "programming": {"mode": "sequential"},
        }
    )
    store = RuntimeStore(tmp_path / "runtime.db")
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    original = ChannelRuntime.open(resolve_channel(definition, library), store, now=epoch)
    assert len(original.channel.media) == 2

    missing_path.unlink()
    scanner.scan(media_dir)
    recovered_at = epoch + timedelta(minutes=10)
    recovered = ChannelRuntime.open(
        resolve_channel(definition, library),
        store,
        now=recovered_at,
    )

    assert len(recovered.channel.media) == 1
    assert recovered.channel.media[0].location.path == first_path
    # A deleted file is library maintenance, not a restart: the clock stays,
    # the program airing now finishes its slot, and from the next program
    # boundary only the remaining file plays.
    assert recovered.signature == original.signature
    assert recovered.epoch_utc == epoch
    airing = recovered.broadcast_at(recovered_at)
    assert airing.program_started_at == original.broadcast_at(recovered_at).program_started_at
    after = airing.program_ends_at + timedelta(seconds=1)
    for step in range(4):
        assert recovered.broadcast_at(after + timedelta(seconds=30 * step)).media.location.path == first_path
