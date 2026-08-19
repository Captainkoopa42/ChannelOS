from __future__ import annotations

from pathlib import Path

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
