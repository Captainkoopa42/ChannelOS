from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from channelos import probe
from channelos.probe import FFprobeMediaProbe, MediaProbeError


def test_ffprobe_has_a_bounded_inspection_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    media = tmp_path / "program.mp4"
    media.write_bytes(b"media")
    monkeypatch.setattr(probe.shutil, "which", lambda _name: "ffprobe")

    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ffprobe", timeout=0.1)

    monkeypatch.setattr(probe.subprocess, "run", time_out)

    with pytest.raises(MediaProbeError, match="timed out.*program.mp4"):
        FFprobeMediaProbe(timeout_seconds=0.1).probe(media)
