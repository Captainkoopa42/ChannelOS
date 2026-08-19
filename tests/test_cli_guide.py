from __future__ import annotations

import hashlib
import json
from pathlib import Path

from channelos.cli import main
from channelos.library import MediaLibrary
from channelos.probe import MediaProbeResult


def _write_channel(
    tmp_path: Path,
    library: MediaLibrary,
    *,
    channel_number: int,
    durations: tuple[float, ...],
    mode: str = "sequential",
) -> Path:
    media_dir = tmp_path / f"channel-{channel_number}"
    media_dir.mkdir()

    for index, duration in enumerate(durations):
        path = media_dir / f"clip-{index}.mp4"
        payload = f"channel-{channel_number}-clip-{index}".encode()
        path.write_bytes(payload)
        library.upsert_file(
            path,
            media_dir,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            probe=MediaProbeResult(
                duration_seconds=duration,
                container_format="mp4",
            ),
        )

    channel_path = tmp_path / f"channel-{channel_number}.yaml"
    channel_path.write_text(
        "\n".join(
            (
                'schema_version: "0.1"',
                f"channel: {channel_number}",
                f"name: Channel {channel_number}",
                "sources:",
                f"  - path: {json.dumps(str(media_dir))}",
                "programming:",
                f"  mode: {mode}",
                "  avoid_repeat_days: 0",
                "presentation:",
                "  number_width: 3",
                "",
            )
        ),
        encoding="utf-8",
    )
    return channel_path


def test_guide_command_prints_multi_channel_horizon_and_now_next(
    tmp_path: Path,
    capsys,
) -> None:
    library_path = tmp_path / "library.db"
    runtime_path = tmp_path / "runtime.db"
    library = MediaLibrary(library_path)
    channel_7 = _write_channel(
        tmp_path,
        library,
        channel_number=7,
        durations=(30.0, 45.0),
    )
    channel_12 = _write_channel(
        tmp_path,
        library,
        channel_number=12,
        durations=(20.0, 20.0, 20.0),
        mode="shuffle",
    )

    result = main(
        [
            "guide",
            str(channel_12),
            str(channel_7),
            "--db",
            str(library_path),
            "--state-db",
            str(runtime_path),
            "--from",
            "2026-08-19T16:00:00+00:00",
            "--hours",
            "0.05",
            "--why",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Window: 2026-08-19T16:00:00+00:00 -> 2026-08-19T16:03:00+00:00" in output
    assert output.index("Channel 007 — Channel 7") < output.index("Channel 012 — Channel 12")
    assert "  NOW:" in output
    assert "  NEXT:" in output
    assert "why: sequential programming" in output
    assert "why: deterministic shuffle programming" in output
    assert "clip-" in output


def test_guide_command_rejects_non_positive_horizon(capsys) -> None:
    result = main(["guide", "channel.yaml", "--hours", "0"])

    assert result == 2
    assert "--hours must be greater than zero" in capsys.readouterr().err
