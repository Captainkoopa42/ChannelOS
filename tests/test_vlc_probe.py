from __future__ import annotations

from types import SimpleNamespace

import pytest

from channelos import vlc_probe


class FakeScanner:
    def __init__(self, library, probe=None, *, fail_on_probe_error=False) -> None:
        self.library = library
        self.probe = probe
        self.fail_on_probe_error = fail_on_probe_error


class FakeEventManager:
    def __init__(self) -> None:
        self.callback = None
        self.detached = False

    def event_attach(self, _event_type, callback) -> None:
        self.callback = callback

    def event_detach(self, _event_type) -> None:
        self.detached = True


class FakeMedia:
    def __init__(self, *, complete: bool) -> None:
        self.manager = FakeEventManager()
        self.complete = complete
        self.stopped = False

    def event_manager(self):
        return self.manager

    def parse_with_options(self, _flags, _timeout_ms):
        if self.complete:
            self.manager.callback(None)
        return 0

    def parse_stop(self) -> None:
        self.stopped = True

    def get_parsed_status(self):
        return "done"

    def get_duration(self):
        return 12_500


def _probe_with_fake_media(media: FakeMedia) -> vlc_probe.LibVLCMediaProbe:
    probe = object.__new__(vlc_probe.LibVLCMediaProbe)
    probe._parse_timeout_seconds = 0.1
    probe._instance = SimpleNamespace(media_new_path=lambda _path: media)
    probe._vlc = SimpleNamespace(
        EventType=SimpleNamespace(MediaParsedChanged="parsed"),
        MediaParseFlag=SimpleNamespace(local="local"),
        MediaParsedStatus=SimpleNamespace(done="done"),
    )
    return probe


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


def test_packaged_probe_uses_bounded_async_parse(tmp_path) -> None:
    media = FakeMedia(complete=True)
    probe = _probe_with_fake_media(media)

    result = probe.probe(tmp_path / "program.mp4")

    assert result.duration_seconds == 12.5
    assert result.container_format == "mp4"
    assert media.manager.detached is True


def test_packaged_probe_can_cancel_native_inspection(tmp_path) -> None:
    media = FakeMedia(complete=False)
    probe = _probe_with_fake_media(media)

    with pytest.raises(InterruptedError, match="cancelled"):
        probe.probe_cancellable(
            tmp_path / "program.mp4",
            should_cancel=lambda: True,
        )

    assert media.stopped is True
    assert media.manager.detached is True
