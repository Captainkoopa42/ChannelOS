from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class MediaProbeError(RuntimeError):
    """Raised when a media probe is available but cannot inspect a file."""


@dataclass(frozen=True, slots=True)
class MediaProbeResult:
    duration_seconds: float | None = None
    container_format: str | None = None
    raw_json: str | None = None


class MediaProbe(Protocol):
    def probe(self, path: Path) -> MediaProbeResult:
        """Return technical information for one media file."""


class NullMediaProbe:
    """Probe implementation used when technical probing is intentionally disabled."""

    def probe(self, path: Path) -> MediaProbeResult:
        return MediaProbeResult()


class FFprobeMediaProbe:
    """Technical metadata probe backed by the external ffprobe executable."""

    def __init__(self, executable: str = "ffprobe", *, required: bool = False) -> None:
        self.executable = executable
        self.required = required

    def probe(self, path: Path) -> MediaProbeResult:
        executable = shutil.which(self.executable)
        if executable is None:
            if self.required:
                raise MediaProbeError(
                    "ffprobe was not found. Install FFmpeg/ffprobe or scan without --require-probe."
                )
            return MediaProbeResult()

        command = [
            executable,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise MediaProbeError(f"could not run ffprobe for {path}: {exc}") from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit code {completed.returncode}"
            raise MediaProbeError(f"ffprobe failed for {path}: {detail}")

        try:
            payload: dict[str, Any] = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise MediaProbeError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc

        format_info = payload.get("format")
        duration: float | None = None
        container: str | None = None
        if isinstance(format_info, dict):
            raw_duration = format_info.get("duration")
            if raw_duration is not None:
                try:
                    duration = float(raw_duration)
                except (TypeError, ValueError):
                    duration = None
            raw_container = format_info.get("format_name")
            if isinstance(raw_container, str) and raw_container.strip():
                container = raw_container.strip()

        return MediaProbeResult(
            duration_seconds=duration,
            container_format=container,
            raw_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
