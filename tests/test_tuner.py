from __future__ import annotations

from pathlib import Path

from channelos.library import IndexedMedia, MediaAsset, MediaLocation
from channelos.models import ChannelDefinition
from channelos.resolve import ResolvedChannel
from channelos.tuner import TuneSession


class FakeBackend:
    def __init__(self) -> None:
        self.loaded: Path | None = None
        self.position = 10.0
        self.volume = 50
        self.muted = False
        self.rate = 1.0
        self.events: list[str] = []

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
        self.volume = percent

    def get_volume(self):
        return self.volume

    def set_muted(self, muted):
        self.muted = muted

    def get_muted(self):
        return self.muted

    def set_rate(self, rate):
        self.rate = rate


def make_channel(path: Path) -> ResolvedChannel:
    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": 7,
            "name": "Sci-Fi",
            "sources": [{"path": str(path.parent)}],
            "programming": {"mode": "sequential"},
        }
    )
    asset = MediaAsset("sha256:test", "test", 1, None, None)
    location = MediaLocation(path, str(path), asset.asset_id, path.parent, True)
    return ResolvedChannel(definition, (IndexedMedia(asset, location),))


def test_tune_session_routes_controls_through_backend(tmp_path: Path) -> None:
    media_path = tmp_path / "movie.mp4"
    backend = FakeBackend()
    session = TuneSession(make_channel(media_path), backend)  # type: ignore[arg-type]

    assert session.start() == media_path
    assert backend.events[:2] == ["load", "play"]
    assert session.execute("pause") == "paused"
    assert session.execute("play") == "playing"
    assert session.execute("volume 80") == "volume 80%"
    assert backend.volume == 80
    assert session.execute("mute") == "muted"
    assert backend.muted is True
    assert session.execute("skip 30") == "position 40.000s"
    assert backend.position == 40.0
    assert session.execute("rate 2") == "rate 2x"
    assert backend.rate == 2.0
