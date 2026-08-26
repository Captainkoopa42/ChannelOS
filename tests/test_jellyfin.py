from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import pytest

from channelos.jellyfin import (
    FFmpegMpegTsStreamer,
    JellyfinAdapterError,
    JellyfinLiveTvAdapter,
    JellyfinLiveTvHttpServer,
)
from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import MediaProbeResult
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore

UTC = timezone.utc


def _open_runtime(
    tmp_path: Path,
    *,
    channel_number: int,
    channel_name: str,
    durations: tuple[float, ...],
    epoch: datetime,
) -> ChannelRuntime:
    media_dir = tmp_path / f"jellyfin-{channel_number}"
    media_dir.mkdir()
    library = MediaLibrary(tmp_path / "library.db")

    for index, duration in enumerate(durations):
        path = media_dir / f"program-{index}.mp4"
        payload = f"jellyfin-{channel_number}-{index}".encode()
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

    definition = ChannelDefinition.from_mapping(
        {
            "schema_version": "0.1",
            "channel": channel_number,
            "name": channel_name,
            "description": f"The {channel_name} schedule.",
            "sources": [{"path": str(media_dir)}],
            "programming": {"mode": "sequential"},
            "presentation": {"number_width": 3},
        }
    )
    resolved = resolve_channel(definition, library)
    return ChannelRuntime.open(
        resolved,
        RuntimeStore(tmp_path / "runtime.db"),
        now=epoch,
    )


def test_m3u_and_xmltv_share_stable_channel_ids_and_broadcast_schedule(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    runtime_12 = _open_runtime(
        tmp_path,
        channel_number=12,
        channel_name='Cartoons "After Dark"',
        durations=(20.0, 40.0),
        epoch=epoch,
    )
    runtime_7 = _open_runtime(
        tmp_path,
        channel_number=7,
        channel_name="Sci-Fi",
        durations=(30.0, 45.0),
        epoch=epoch,
    )
    adapter = JellyfinLiveTvAdapter(
        (runtime_12, runtime_7),
        advertise_url="http://127.0.0.1:4242/",
    )

    m3u = adapter.render_m3u().decode("utf-8")
    assert m3u.startswith("#EXTM3U\n")
    assert m3u.index('tvg-id="channelos.7"') < m3u.index(
        'tvg-id="channelos.12"'
    )
    assert 'tvg-chno="007"' in m3u
    assert 'tvg-name="Cartoons \'After Dark\'"' in m3u
    assert "http://127.0.0.1:4242/channel/007.ts" in m3u

    at = epoch + timedelta(seconds=35)
    xml = adapter.render_xmltv(at=at, past_hours=0, future_hours=0.02)
    root = ElementTree.fromstring(xml)
    assert [node.attrib["id"] for node in root.findall("channel")] == [
        "channelos.7",
        "channelos.12",
    ]

    channel_7_programs = [
        node
        for node in root.findall("programme")
        if node.attrib["channel"] == "channelos.7"
    ]
    direct = runtime_7.broadcast_at(at)
    assert channel_7_programs[0].attrib["start"] == "20260826120030 +0000"
    assert channel_7_programs[0].attrib["stop"] == "20260826120115 +0000"
    assert channel_7_programs[0].findtext("title") == direct.media.location.path.stem
    assert channel_7_programs[0].findtext("desc") == "The Sci-Fi schedule."


def test_adapter_rejects_non_http_advertise_urls(tmp_path: Path) -> None:
    epoch = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    runtime = _open_runtime(
        tmp_path,
        channel_number=7,
        channel_name="Sci-Fi",
        durations=(30.0,),
        epoch=epoch,
    )

    with pytest.raises(JellyfinAdapterError, match="absolute http"):
        JellyfinLiveTvAdapter((runtime,), advertise_url="127.0.0.1:4242")

    with pytest.raises(JellyfinAdapterError, match="cannot contain a path"):
        JellyfinLiveTvAdapter(
            (runtime,),
            advertise_url="http://127.0.0.1:4242/live-tv",
        )


class _FakeStreamer:
    def __init__(self) -> None:
        self.channels: list[int] = []

    def preflight(self, runtime: ChannelRuntime) -> None:
        return None

    def iter_channel(self, runtime: ChannelRuntime):
        self.channels.append(runtime.channel_number)
        yield b"fake-mpeg-ts"


def test_http_server_publishes_discovery_guide_and_channel_stream(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    runtime = _open_runtime(
        tmp_path,
        channel_number=7,
        channel_name="Sci-Fi",
        durations=(30.0, 45.0),
        epoch=epoch,
    )
    adapter = JellyfinLiveTvAdapter(
        (runtime,),
        advertise_url="http://127.0.0.1:4242",
    )
    streamer = _FakeStreamer()
    server = JellyfinLiveTvHttpServer(
        ("127.0.0.1", 0),
        adapter,
        streamer,
        guide_past_hours=0,
        guide_future_hours=1,
        now=lambda: epoch + timedelta(seconds=5),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with urlopen(f"{base_url}/channels.m3u", timeout=3) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "application/vnd.apple.mpegurl"
            assert b"channelos.7" in response.read()

        with urlopen(f"{base_url}/guide.xml", timeout=3) as response:
            assert response.status == 200
            root = ElementTree.fromstring(response.read())
            assert root.find("channel").attrib["id"] == "channelos.7"

        with urlopen(f"{base_url}/channel/007.ts", timeout=3) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "video/mp2t"
            assert response.read() == b"fake-mpeg-ts"
        assert streamer.channels == [7]

        head = Request(f"{base_url}/channel/7.ts", method="HEAD")
        with urlopen(head, timeout=3) as response:
            assert response.status == 200
            assert response.read() == b""

        with pytest.raises(HTTPError) as missing:
            urlopen(f"{base_url}/channel/99.ts", timeout=3)
        assert missing.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_ffmpeg_command_seeks_to_broadcast_offset_and_emits_mpeg_ts(
    tmp_path: Path,
) -> None:
    epoch = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    runtime = _open_runtime(
        tmp_path,
        channel_number=7,
        channel_name="Sci-Fi",
        durations=(30.0, 45.0),
        epoch=epoch,
    )
    selection = runtime.broadcast_at(epoch + timedelta(seconds=42))
    streamer = FFmpegMpegTsStreamer("ffmpeg")

    command = streamer.command_for(
        selection,
        remaining_seconds=33.0,
        output_timestamp_seconds=12.5,
    )

    assert command[command.index("-ss") + 1] == "12.000000"
    assert command[command.index("-i") + 1] == str(
        selection.media.location.path
    )
    assert command[command.index("-t") + 1] == "45.500000"
    assert command[command.index("-vf") + 1] == (
        "setpts=PTS-STARTPTS+12.500000/TB"
    )
    assert command[command.index("-af") + 1] == (
        "asetpts=PTS-STARTPTS+12.500000/TB"
    )
    assert command[-3:] == ["-f", "mpegts", "pipe:1"]
