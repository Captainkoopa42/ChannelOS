from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import channelos.cli as cli
from channelos.library import MediaLibrary
from channelos.probe import MediaProbeResult

UTC = timezone.utc


class FakeBackend:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.loaded: Path | None = None
        self.position = 0.0

    def load(self, path):
        self.loaded = Path(path)
        self.events.append("load")

    def play(self):
        self.events.append("play")

    def pause(self):
        self.events.append("pause")

    def stop(self):
        self.events.append("stop")

    def seek(self, seconds):
        self.position = float(seconds)
        self.events.append("seek")

    def get_position(self):
        return self.position

    def set_volume(self, percent):
        return None

    def get_volume(self):
        return 50

    def set_muted(self, muted):
        return None

    def get_muted(self):
        return False

    def set_rate(self, rate):
        return None


def make_indexed_channel(tmp_path: Path) -> tuple[Path, Path]:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    database = tmp_path / "library.db"
    library = MediaLibrary(database)

    for index, duration in enumerate((30.0, 30.0)):
        path = media_dir / f"{index:02d}.mp4"
        payload = f"clip-{index}".encode()
        path.write_bytes(payload)
        library.upsert_file(
            path,
            media_dir,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            probe=MediaProbeResult(duration_seconds=duration, container_format="mp4"),
        )

    channel = tmp_path / "channel.yaml"
    channel.write_text(
        "\n".join(
            [
                'schema_version: "0.1"',
                "channel: 7",
                "name: Runtime Test",
                "sources:",
                f"  - path: '{media_dir}'",
                "programming:",
                "  mode: sequential",
                "presentation:",
                "  number_width: 3",
            ]
        ),
        encoding="utf-8",
    )
    return channel, database


def test_broadcast_cli_uses_persistent_epoch_between_invocations(tmp_path: Path, capsys) -> None:
    channel, database = make_indexed_channel(tmp_path)
    state = tmp_path / "runtime.db"
    epoch = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    assert (
        cli.main(
            [
                "broadcast",
                str(channel),
                "--db",
                str(database),
                "--state-db",
                str(state),
                "--at",
                epoch.isoformat(),
            ]
        )
        == 0
    )
    first = capsys.readouterr().out
    assert "Channel 007 — Runtime Test" in first
    assert "00.mp4" in first
    assert "Seek: 0.000s" in first

    assert (
        cli.main(
            [
                "broadcast",
                str(channel),
                "--db",
                str(database),
                "--state-db",
                str(state),
                "--at",
                (epoch + timedelta(seconds=42)).isoformat(),
            ]
        )
        == 0
    )
    second = capsys.readouterr().out
    assert "01.mp4" in second
    assert "Seek: 12.000s" in second
    assert f"Schedule epoch: {epoch.isoformat()}" in second


def test_tv_cli_routes_startup_through_phase1_session(tmp_path: Path, monkeypatch, capsys) -> None:
    channel, database = make_indexed_channel(tmp_path)
    backend = FakeBackend()
    monkeypatch.setattr(cli, "LibVLCBackend", lambda: backend)
    monkeypatch.setattr("builtins.input", lambda _prompt: "QUIT")

    result = cli.main(
        [
            "tv",
            str(channel),
            "--db",
            str(database),
            "--state-db",
            str(tmp_path / "runtime.db"),
        ]
    )

    assert result == 0
    assert backend.loaded is not None
    assert backend.events[:3] == ["load", "play", "seek"]
    assert backend.events[-1] == "stop"
    output = capsys.readouterr().out
    assert "Channel 007 — Runtime Test" in output
    assert "Phase 1 TV console" in output
