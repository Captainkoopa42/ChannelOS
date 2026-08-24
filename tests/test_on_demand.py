from __future__ import annotations

from pathlib import Path

import pytest

from channelos.library import IndexedMedia, MediaAsset, MediaLocation
from channelos.on_demand import OnDemandSession
from channelos.playback import NativeVideoSurface, PlaybackBackend


class FakeBackend(PlaybackBackend):
    def __init__(self) -> None:
        self.surface = None
        self.loaded = None
        self.position = 0.0
        self.ended = False
        self.volume = 50
        self.muted = False
        self.events = []

    def attach_video_surface(self, surface):
        self.surface = surface
        self.events.append("surface")

    def load(self, path):
        self.loaded = Path(path)
        self.ended = False
        self.position = 0.0
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

    def has_ended(self):
        return self.ended

    def set_volume(self, percent):
        self.volume = int(percent)

    def get_volume(self):
        return self.volume

    def set_muted(self, muted):
        self.muted = bool(muted)

    def get_muted(self):
        return self.muted

    def set_rate(self, rate):
        pass


def make_media(tmp_path, duration=120.0):
    path = tmp_path / "owned-video.mp4"
    path.write_bytes(b"channelos")

    asset = MediaAsset(
        asset_id="sha256:on-demand-test",
        content_sha256="on-demand-test",
        size_bytes=path.stat().st_size,
        duration_seconds=duration,
        container_format="mp4",
    )

    location = MediaLocation(
        path=path,
        path_key=str(path),
        asset_id=asset.asset_id,
        source_root=tmp_path,
        online=True,
    )

    return IndexedMedia(
        asset=asset,
        location=location,
    )


def test_on_demand_uses_native_surface_and_owned_media(tmp_path):
    backend = FakeBackend()

    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    surface = NativeVideoSurface(
        "windows",
        4242,
    )

    session.attach_video_surface(surface)

    state = session.play_media(
        make_media(tmp_path)
    )

    assert state.active
    assert state.title == "owned-video"
    assert backend.surface == surface
    assert backend.loaded == tmp_path / "owned-video.mp4"
    assert backend.events[:4] == [
        "surface",
        "load",
        "play",
        "seek",
    ]


def test_on_demand_pause_resume_and_seek(tmp_path):
    backend = FakeBackend()

    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    session.play_media(
        make_media(
            tmp_path,
            duration=40.0,
        )
    )

    assert session.toggle_pause().paused
    assert backend.events[-1] == "pause"

    assert not session.toggle_pause().paused
    assert backend.events[-1] == "play"

    assert session.skip(12.0).position_seconds == pytest.approx(12.0)
    assert session.skip(100.0).position_seconds == pytest.approx(40.0)
    assert session.skip(-100.0).position_seconds == pytest.approx(0.0)


def test_on_demand_can_start_from_a_saved_position(tmp_path):
    backend = FakeBackend()
    session = OnDemandSession(backend_factory=lambda: backend)

    state = session.play_media(
        make_media(tmp_path, duration=120.0),
        start_seconds=42.5,
    )

    assert backend.events[-1] == "seek"
    assert backend.position == pytest.approx(42.5)
    assert state.position_seconds == pytest.approx(42.5)


def test_on_demand_stop_clears_media(tmp_path):
    backend = FakeBackend()

    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    session.play_media(
        make_media(tmp_path)
    )

    session.stop()

    assert not session.active
    assert not session.state().active
    assert backend.events[-1] == "stop"


def test_rewind_from_ended_media_restarts_decoder(tmp_path):
    backend = FakeBackend()
    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    session.play_media(
        make_media(
            tmp_path,
            duration=40.0,
        )
    )

    # Reproduce a backend reaching its natural end.
    backend.position = 0.0
    backend.ended = True

    state = session.skip(-10.0)

    assert backend.events[-4:] == ["stop", "load", "play", "seek"]
    assert backend.position == pytest.approx(30.0)
    assert not state.paused


def test_play_from_ended_media_restarts_from_beginning(tmp_path):
    backend = FakeBackend()
    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    session.play_media(
        make_media(
            tmp_path,
            duration=40.0,
        )
    )

    backend.position = 0.0
    backend.ended = True
    backend.events.clear()

    session.toggle_pause()

    assert backend.events == ["stop", "load", "play"]
    assert backend.position == pytest.approx(0.0)
    assert not backend.ended
    assert not session.paused


def test_ended_rewind_rebuilds_decoder_pipeline(tmp_path):
    backend = FakeBackend()
    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    session.play_media(
        make_media(
            tmp_path,
            duration=40.0,
        )
    )

    backend.position = 0.0
    backend.ended = True
    backend.events.clear()

    state = session.skip(-10.0)

    assert backend.events == [
        "stop",
        "load",
        "play",
        "seek",
    ]
    assert backend.position == pytest.approx(30.0)
    assert not backend.ended
    assert not state.paused


def test_ended_play_rebuilds_decoder_from_start(tmp_path):
    backend = FakeBackend()
    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    session.play_media(
        make_media(
            tmp_path,
            duration=40.0,
        )
    )

    backend.position = 0.0
    backend.ended = True
    backend.events.clear()

    state = session.toggle_pause()

    assert backend.events == [
        "stop",
        "load",
        "play",
    ]
    assert backend.position == pytest.approx(0.0)
    assert not backend.ended
    assert not state.paused



def test_on_demand_volume_and_mute_use_playback_backend(tmp_path):
    backend = FakeBackend()
    session = OnDemandSession(
        backend_factory=lambda: backend
    )

    session.play_media(make_media(tmp_path))

    assert session.set_volume(70) == 70
    assert backend.volume == 70

    assert session.set_muted(True)
    assert backend.muted
