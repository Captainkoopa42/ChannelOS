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


def test_bundled_vlc_precedes_developer_override(monkeypatch, tmp_path: Path) -> None:
    bundled = _make_vlc_runtime(tmp_path / "bundled")
    override = _make_vlc_runtime(tmp_path / "override")
    registered: list[str] = []

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


class _FakePlayer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def set_hwnd(self, handle: int) -> None:
        self.calls.append(("windows", handle))

    def set_xwindow(self, handle: int) -> None:
        self.calls.append(("x11", handle))

    def set_nsobject(self, handle: int) -> None:
        self.calls.append(("macos", handle))


@pytest.mark.parametrize("platform", ["windows", "x11", "macos"])
def test_libvlc_routes_native_surface_to_platform_method(platform: str) -> None:
    backend = object.__new__(playback.LibVLCBackend)
    player = _FakePlayer()
    backend._player = player

    backend.attach_video_surface(playback.NativeVideoSurface(platform, 4242))

    assert player.calls == [(platform, 4242)]
