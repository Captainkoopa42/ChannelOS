from __future__ import annotations

from pathlib import Path

import pytest

import channelos.playback as playback


def _make_vlc_runtime(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "libvlc.dll").write_bytes(b"")
    (root / "plugins").mkdir()
    return root.resolve()


def test_windows_vlc_override_registers_runtime(monkeypatch, tmp_path: Path) -> None:
    runtime = _make_vlc_runtime(tmp_path / "vlc")
    sentinel = object()
    registered: list[str] = []

    monkeypatch.setenv("PYTHON_VLC_LIB_PATH", "")
    monkeypatch.setenv("PYTHON_VLC_MODULE_PATH", "")
    monkeypatch.setattr(playback, "IS_WINDOWS", True)
    monkeypatch.setattr(playback, "_bundled_vlc_runtime_candidates", lambda: ())
    monkeypatch.setenv(playback.VLC_RUNTIME_ENV, str(runtime))
    monkeypatch.setattr(
        playback.os,
        "add_dll_directory",
        lambda path: registered.append(path) or sentinel,
        raising=False,
    )

    handle, selected = playback._prepare_windows_vlc_runtime()

    assert handle is sentinel
    assert selected == runtime
    assert registered == [str(runtime)]
    assert playback.os.environ["VLC_PLUGIN_PATH"] == str(runtime / "plugins")
    assert playback.os.environ["PYTHON_VLC_LIB_PATH"] == str(runtime / "libvlc.dll")
    assert playback.os.environ["PYTHON_VLC_MODULE_PATH"] == str(runtime)


def test_bundled_vlc_precedes_developer_override(monkeypatch, tmp_path: Path) -> None:
    bundled = _make_vlc_runtime(tmp_path / "bundled")
    override = _make_vlc_runtime(tmp_path / "override")
    registered: list[str] = []

    monkeypatch.setenv("PYTHON_VLC_LIB_PATH", "")
    monkeypatch.setenv("PYTHON_VLC_MODULE_PATH", "")
    monkeypatch.setattr(playback, "IS_WINDOWS", True)
    monkeypatch.setattr(playback, "_bundled_vlc_runtime_candidates", lambda: (bundled,))
    monkeypatch.setenv(playback.VLC_RUNTIME_ENV, str(override))
    monkeypatch.setattr(
        playback.os,
        "add_dll_directory",
        lambda path: registered.append(path) or object(),
        raising=False,
    )

    _, selected = playback._prepare_windows_vlc_runtime()

    assert selected == bundled
    assert registered == [str(bundled)]


def test_non_windows_does_not_modify_runtime(monkeypatch) -> None:
    monkeypatch.setattr(playback, "IS_WINDOWS", False)

    handle, selected = playback._prepare_windows_vlc_runtime()

    assert handle is None
    assert selected is None


def test_native_video_surface_validates_platform_and_handle() -> None:
    assert playback.NativeVideoSurface("windows", 123).window_id == 123

    with pytest.raises(ValueError, match="unsupported native video platform"):
        playback.NativeVideoSurface("wayland", 123)

    with pytest.raises(ValueError, match="positive integer"):
        playback.NativeVideoSurface("windows", 0)


def test_libvlc_rejects_a_missing_media_path_before_decoder_start(
    tmp_path: Path,
) -> None:
    backend = object.__new__(playback.LibVLCBackend)

    with pytest.raises(playback.PlaybackError, match="Media file is unavailable"):
        backend.load(tmp_path / "moved-movie.mkv")


class _FakePlayer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_hwnd(self, handle: int) -> None:
        self.calls.append(("windows", handle))

    def set_xwindow(self, handle: int) -> None:
        self.calls.append(("x11", handle))

    def set_nsobject(self, handle: int) -> None:
        self.calls.append(("macos", handle))

    def video_set_aspect_ratio(self, ratio) -> None:
        self.calls.append(("aspect", ratio))

    def video_set_crop_geometry(self, geometry) -> None:
        self.calls.append(("crop", geometry))

    def video_set_scale(self, scale: float) -> None:
        self.calls.append(("scale", scale))

    def play(self) -> int:
        self.calls.append(("play", None))
        return 0

    def get_state(self):
        return "error"


@pytest.mark.parametrize("platform", ["windows", "x11", "macos"])
def test_libvlc_routes_native_surface_to_platform_method(platform: str) -> None:
    backend = object.__new__(playback.LibVLCBackend)
    player = _FakePlayer()
    backend._player = player

    backend.attach_video_surface(playback.NativeVideoSurface(platform, 4242))

    assert player.calls == [
        (platform, 4242),
        ("aspect", None),
        ("crop", None),
        ("scale", 0.0),
    ]


def test_libvlc_reapplies_source_aspect_fit_when_playback_starts() -> None:
    backend = object.__new__(playback.LibVLCBackend)
    player = _FakePlayer()
    backend._player = player

    backend.play()

    assert player.calls == [
        ("play", None),
        ("aspect", None),
        ("crop", None),
        ("scale", 0.0),
    ]


def test_libvlc_reports_asynchronous_decoder_failure(tmp_path: Path) -> None:
    backend = object.__new__(playback.LibVLCBackend)
    backend._player = _FakePlayer()
    backend._vlc = type(
        "FakeVlc",
        (),
        {"State": type("State", (), {"Error": "error"})},
    )
    backend._loaded_path = tmp_path / "movie.mkv"

    assert "could not open or decode" in str(backend.playback_error())
    assert str(backend._loaded_path) in str(backend.playback_error())


def test_libvlc_does_not_latch_transient_zero_video_output_as_an_error(
    tmp_path: Path,
) -> None:
    class NoVideoPlayer:
        def get_state(self):
            return "playing"

        def has_vout(self):
            return 0

    backend = object.__new__(playback.LibVLCBackend)
    backend._player = NoVideoPlayer()
    backend._vlc = type(
        "FakeVlc",
        (),
        {"State": type("State", (), {"Error": "error", "Playing": "playing"})},
    )
    backend._loaded_path = tmp_path / "movie.mkv"

    assert backend.playback_error() is None


def test_missing_saved_audio_output_falls_back_to_system_default() -> None:
    devices = (
        playback.AudioOutputDevice("speakers-id", "Desktop Speakers"),
        playback.AudioOutputDevice("headphones-id", "USB Headphones"),
    )

    assert (
        playback.resolve_audio_output_device_id("headphones-id", devices)
        == "headphones-id"
    )
    assert playback.resolve_audio_output_device_id("unplugged-id", devices) == ""
    assert playback.resolve_audio_output_device_id("", devices) == ""


class _AudioDeviceNode:
    def __init__(self, device: bytes, description: bytes, next_node=None) -> None:
        self.device = device
        self.description = description
        self.next = next_node


class _AudioDevicePointer:
    def __init__(self, node: _AudioDeviceNode) -> None:
        self.contents = node


class _FakeAudioPlayer:
    def __init__(self, head=None) -> None:
        self.head = head
        self.selections: list[tuple[None, str | None]] = []

    def audio_output_device_enum(self):
        return self.head

    def audio_output_device_set(self, module, device_id) -> None:
        self.selections.append((module, device_id))


def test_libvlc_enumerates_and_releases_audio_output_devices() -> None:
    headphones = _AudioDevicePointer(
        _AudioDeviceNode(b"headphones-id", b"USB Headphones")
    )
    speakers = _AudioDevicePointer(
        _AudioDeviceNode(b"speakers-id", b"Desktop Speakers", headphones)
    )
    released = []
    backend = object.__new__(playback.LibVLCBackend)
    backend._player = _FakeAudioPlayer(speakers)
    backend._vlc = type(
        "FakeVlc",
        (),
        {
            "libvlc_audio_output_device_list_release": staticmethod(
                lambda head: released.append(head)
            )
        },
    )

    assert backend.list_audio_output_devices() == (
        playback.AudioOutputDevice("speakers-id", "Desktop Speakers"),
        playback.AudioOutputDevice("headphones-id", "USB Headphones"),
    )
    assert released == [speakers]


def test_libvlc_selects_explicit_or_system_default_audio_output() -> None:
    backend = object.__new__(playback.LibVLCBackend)
    player = _FakeAudioPlayer()
    backend._player = player

    backend.set_audio_output_device("headphones-id")
    backend.set_audio_output_device(None)

    assert player.selections == [
        (None, "headphones-id"),
        (None, None),
    ]


def test_video_crop_geometry_fills_trims_and_respects_forced_ratios() -> None:
    crop = playback.video_crop_geometry
    # Fit with no overscan: no crop at all.
    assert crop(1920, 1080, 16 / 9, None, 0) is None
    # 4:3 source filling a 16:9 screen loses top and bottom.
    assert crop(640, 480, 4 / 3, 16 / 9, 0) == "640x360+0+60"
    # 16:9 source filling a 4:3 screen loses the sides.
    assert crop(1920, 1080, 16 / 9, 4 / 3, 0) == "1440x1080+240+0"
    # Overscan trims every edge.
    assert crop(720, 480, 4 / 3, None, 4) == "662x442+29+19"
    # Anamorphic 720x480 forced to 16:9 fills a 16:9 screen without cropping.
    assert crop(720, 480, 16 / 9, 16 / 9, 0) is None


class _VideoPlayer(_FakePlayer):
    def __init__(self, size=(640, 480)) -> None:
        super().__init__()
        self.size = size

    def video_get_size(self, _index):
        return self.size

    def video_set_adjust_int(self, option, value) -> None:
        self.calls.append(("adjust", (option, value)))

    def video_set_adjust_float(self, option, value) -> None:
        self.calls.append(("level", (option, round(value, 3))))

    def video_set_deinterlace(self, mode) -> None:
        self.calls.append(("deinterlace", mode))


def _video_backend(player):
    from types import SimpleNamespace
    backend = object.__new__(playback.LibVLCBackend)
    backend._player = player
    backend._vlc = SimpleNamespace(VideoAdjustOption=SimpleNamespace(Enable=0, Contrast=1, Brightness=2, Saturation=4))
    backend._transition_level = 1.0
    return backend


def test_libvlc_applies_aspect_fill_stretch_and_picture_levels() -> None:
    player = _VideoPlayer((640, 480))
    backend = _video_backend(player)
    backend.set_surface_size(1920, 1080)
    backend.set_video_settings(playback.VideoSettings(aspect_ratio="4:3", fit="fill", brightness=120,
                                                     deinterlace="yadif"))
    calls = dict(player.calls)
    assert calls["aspect"] == "4:3" and calls["crop"] == "640x360+0+60" and calls["scale"] == 0.0
    assert ("adjust", (0, 1)) in player.calls and ("level", (2, 1.2)) in player.calls
    assert calls["deinterlace"] == "yadif"
    player.calls.clear()
    backend.set_video_settings(playback.VideoSettings(fit="stretch"))
    calls = dict(player.calls)
    assert calls["aspect"] == "1920:1080" and calls["crop"] is None
    assert ("adjust", (0, 0)) in player.calls
    # Defaults clear every override, exactly like before video settings existed.
    player.calls.clear()
    backend.set_video_settings(playback.VideoSettings())
    assert [c for c in player.calls if c[0] in {"aspect", "crop", "scale"}] == [
        ("aspect", None), ("crop", None), ("scale", 0.0)]


def test_libvlc_waits_for_source_size_before_cropping() -> None:
    player = _VideoPlayer((0, 0))
    backend = _video_backend(player)
    backend._vlc.State = type("State", (), {"Error": "error"})
    backend._loaded_path = None
    backend.set_video_settings(playback.VideoSettings(overscan_percent=4))
    assert dict(player.calls)["crop"] is None
    player.size = (720, 480)
    player.calls.clear()
    backend.playback_error()  # periodic poll
    assert dict(player.calls)["crop"] == "662x442+29+19"


def test_libvlc_media_options_cover_deinterlace_and_hardware_decoding() -> None:
    backend = object.__new__(playback.LibVLCBackend)
    backend._video_settings = playback.VideoSettings(deinterlace="bob", hardware_decoding="off")
    assert backend._media_options() == (":deinterlace=1", ":deinterlace-mode=bob", ":avcodec-hw=none")
    backend._video_settings = playback.VideoSettings()
    assert backend._media_options() == ()
