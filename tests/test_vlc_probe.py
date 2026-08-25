from __future__ import annotations

from types import SimpleNamespace

from channelos import vlc_probe


class FakeScanner:
    def __init__(self, library, probe=None, *, fail_on_probe_error=False) -> None:
        self.library = library
        self.probe = probe
        self.fail_on_probe_error = fail_on_probe_error


def test_source_launch_keeps_normal_scanner(monkeypatch) -> None:
    monkeypatch.delattr(vlc_probe.sys, "frozen", raising=False)
    module = SimpleNamespace(MediaScanner=FakeScanner)

    vlc_probe.install_packaged_media_scan_support(module)

    assert module.MediaScanner is FakeScanner


def test_frozen_launch_uses_bundled_probe_and_requires_metadata(monkeypatch) -> None:
    marker = object()
    monkeypatch.setattr(vlc_probe.sys, "frozen", True, raising=False)
    monkeypatch.setattr(vlc_probe, "LibVLCMediaProbe", lambda: marker)
    module = SimpleNamespace(MediaScanner=FakeScanner)

    vlc_probe.install_packaged_media_scan_support(module)
    scanner = module.MediaScanner("library")

    assert scanner.probe is marker
    assert scanner.fail_on_probe_error is True
    assert getattr(module.MediaScanner, "_channelos_packaged_probe_enabled") is True
