from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlsplit
from xml.etree import ElementTree

from .guide import GuideService
from .runtime import BroadcastSelection, ChannelRuntime, require_aware_utc, utc_now


MPEG_TS_CONTENT_TYPE = "video/mp2t"
M3U_CONTENT_TYPE = "application/vnd.apple.mpegurl; charset=utf-8"
XMLTV_CONTENT_TYPE = "application/xml; charset=utf-8"
_CHANNEL_PATH = re.compile(r"^/channel/([0-9]{1,4})(?:\.ts)?$")


class JellyfinAdapterError(RuntimeError):
    """Raised when the optional Jellyfin Live TV boundary cannot serve a request."""


def _clean_m3u_value(value: str) -> str:
    return " ".join(value.replace('"', "'").splitlines()).strip()


def _xmltv_channel_id(runtime: ChannelRuntime) -> str:
    # Numeric channel identity is authoritative and does not change when the
    # presentation width or display name changes.
    return f"channelos.{runtime.channel_number}"


def _xmltv_timestamp(value: datetime) -> str:
    return require_aware_utc(value).strftime("%Y%m%d%H%M%S %z")


class JellyfinLiveTvAdapter:
    """Project ChannelOS schedule truth into Jellyfin-compatible M3U and XMLTV."""

    def __init__(
        self,
        runtimes: tuple[ChannelRuntime, ...],
        *,
        advertise_url: str,
    ) -> None:
        if not runtimes:
            raise JellyfinAdapterError("Jellyfin Live TV requires at least one channel")

        parsed = urlsplit(advertise_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise JellyfinAdapterError(
                "advertise URL must be an absolute http:// or https:// URL"
            )
        if parsed.query or parsed.fragment:
            raise JellyfinAdapterError("advertise URL cannot contain a query or fragment")
        if parsed.path not in {"", "/"}:
            raise JellyfinAdapterError("advertise URL cannot contain a path")

        by_number: dict[int, ChannelRuntime] = {}
        for runtime in runtimes:
            if runtime.channel_number in by_number:
                raise JellyfinAdapterError(
                    f"duplicate channel number: {runtime.channel_number}"
                )
            by_number[runtime.channel_number] = runtime

        self.runtimes = tuple(by_number[number] for number in sorted(by_number))
        self.runtime_by_number = by_number
        self.guide = GuideService(self.runtimes)
        self.advertise_url = advertise_url.rstrip("/")

    def render_m3u(self) -> bytes:
        lines = ["#EXTM3U"]
        for runtime in self.runtimes:
            channel = runtime.channel.definition
            name = _clean_m3u_value(channel.name)
            lines.append(
                '#EXTINF:-1 '
                f'tvg-id="{_xmltv_channel_id(runtime)}" '
                f'tvg-chno="{channel.display_number}" '
                f'tvg-name="{name}" '
                f'group-title="ChannelOS",{name}'
            )
            lines.append(
                f"{self.advertise_url}/channel/{channel.display_number}.ts"
            )
        return ("\n".join(lines) + "\n").encode("utf-8")

    def render_xmltv(
        self,
        *,
        at: datetime | None = None,
        past_hours: float = 6.0,
        future_hours: float = 72.0,
    ) -> bytes:
        if past_hours < 0:
            raise JellyfinAdapterError("XMLTV past hours cannot be negative")
        if future_hours <= 0:
            raise JellyfinAdapterError("XMLTV future hours must be greater than zero")

        reference = require_aware_utc(at or utc_now())
        horizon = self.guide.horizon(
            reference - timedelta(hours=float(past_hours)),
            reference + timedelta(hours=float(future_hours)),
            generated_at=reference,
        )

        root = ElementTree.Element(
            "tv",
            {
                "generator-info-name": "ChannelOS",
                "source-info-name": "ChannelOS Broadcast Clock",
            },
        )

        for runtime in self.runtimes:
            channel = runtime.channel.definition
            node = ElementTree.SubElement(
                root,
                "channel",
                {"id": _xmltv_channel_id(runtime)},
            )
            ElementTree.SubElement(node, "display-name").text = channel.name
            ElementTree.SubElement(node, "display-name").text = channel.display_number

        runtime_by_number = {
            runtime.channel_number: runtime for runtime in self.runtimes
        }
        for row in horizon.rows:
            runtime = runtime_by_number[row.channel_number]
            channel = runtime.channel.definition
            for program in row.programs:
                node = ElementTree.SubElement(
                    root,
                    "programme",
                    {
                        "start": _xmltv_timestamp(program.start_utc),
                        "stop": _xmltv_timestamp(program.end_utc),
                        "channel": _xmltv_channel_id(runtime),
                    },
                )
                ElementTree.SubElement(node, "title", {"lang": "en"}).text = (
                    program.display_label
                )
                description = channel.description or (
                    f"Scheduled by ChannelOS using {program.programming_mode} programming."
                )
                ElementTree.SubElement(node, "desc", {"lang": "en"}).text = description
                ElementTree.SubElement(node, "category", {"lang": "en"}).text = (
                    "ChannelOS"
                )
                ElementTree.SubElement(
                    node,
                    "length",
                    {"units": "seconds"},
                ).text = str(int(round(program.duration_seconds)))

        ElementTree.indent(root, space="  ")
        return ElementTree.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
        )


class ChannelStreamer(Protocol):
    def preflight(self, runtime: ChannelRuntime) -> None:
        """Raise when this runtime cannot currently produce a stream."""

    def iter_channel(self, runtime: ChannelRuntime) -> Iterator[bytes]:
        """Yield a live MPEG-TS representation of one ChannelOS Broadcast Clock."""


class FFmpegMpegTsStreamer:
    """Transcode the current Broadcast Clock selection into a live MPEG-TS stream.

    One FFmpeg process is used per scheduled occurrence. Every process emits the
    same H.264/AAC transport format and receives a monotonically increasing MPEG-TS
    timestamp offset, allowing the HTTP connection to continue across program
    boundaries without creating background decoders for untuned channels.
    """

    def __init__(
        self,
        executable: str | Path = "ffmpeg",
        *,
        chunk_size: int = 64 * 1024,
        now: Callable[[], datetime] = utc_now,
        max_programs: int | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("stream chunk size must be greater than zero")
        if max_programs is not None and max_programs <= 0:
            raise ValueError("max_programs must be greater than zero when provided")
        self.executable = str(executable)
        self.chunk_size = int(chunk_size)
        self.now = now
        self.max_programs = max_programs

    def resolved_executable(self) -> str:
        found = shutil.which(self.executable)
        if found is None:
            raise JellyfinAdapterError(
                "FFmpeg was not found. Install FFmpeg or pass --ffmpeg with its path."
            )
        return found

    def preflight(self, runtime: ChannelRuntime) -> None:
        self.resolved_executable()
        selection = runtime.broadcast_at(self.now())
        if not selection.media.location.path.is_file():
            raise JellyfinAdapterError(
                "scheduled media is no longer available: "
                f"{selection.media.location.path}"
            )

    def command_for(
        self,
        selection: BroadcastSelection,
        *,
        remaining_seconds: float,
        output_timestamp_seconds: float,
    ) -> list[str]:
        if remaining_seconds <= 0:
            raise JellyfinAdapterError("cannot stream a completed program occurrence")

        timestamp = max(0.0, output_timestamp_seconds)
        output_end = timestamp + remaining_seconds

        return [
            self.resolved_executable(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-ss",
            f"{max(0.0, selection.offset_seconds):.6f}",
            "-i",
            str(selection.media.location.path),
            "-t",
            f"{output_end:.6f}",
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-vf",
            f"setpts=PTS-STARTPTS+{timestamp:.6f}/TB",
            "-af",
            f"asetpts=PTS-STARTPTS+{timestamp:.6f}/TB",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "60",
            "-keyint_min",
            "60",
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-mpegts_flags",
            "+resend_headers",
            "-muxdelay",
            "0",
            "-muxpreload",
            "0",
            "-f",
            "mpegts",
            "pipe:1",
        ]

    def iter_channel(self, runtime: ChannelRuntime) -> Iterator[bytes]:
        connection_started_at = require_aware_utc(self.now())
        programs_streamed = 0
        next_output_timestamp = 0.0

        while self.max_programs is None or programs_streamed < self.max_programs:
            selected_at = require_aware_utc(self.now())
            selection = runtime.broadcast_at(selected_at)
            media_path = selection.media.location.path
            if not media_path.is_file():
                raise JellyfinAdapterError(
                    f"scheduled media is no longer available: {media_path}"
                )

            remaining = (selection.program_ends_at - selected_at).total_seconds()
            if remaining <= 0:
                continue
            output_timestamp = max(
                next_output_timestamp,
                (selected_at - connection_started_at).total_seconds(),
            )
            command = self.command_for(
                selection,
                remaining_seconds=remaining,
                output_timestamp_seconds=output_timestamp,
            )
            next_output_timestamp = output_timestamp + remaining
            segment_wall_started = time.monotonic()
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise JellyfinAdapterError(f"could not start FFmpeg: {exc}") from exc
            emitted = False
            try:
                assert process.stdout is not None
                while chunk := process.stdout.read(self.chunk_size):
                    emitted = True
                    yield chunk
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            if process.returncode not in {0, -15}:
                raise JellyfinAdapterError(
                    "FFmpeg could not encode the scheduled media "
                    f"{media_path.name!r} (exit {process.returncode})"
                )
            if not emitted:
                raise JellyfinAdapterError(
                    f"FFmpeg produced no stream data for {media_path.name!r}"
                )

            # FFmpeg's input read-rate clock can begin with a small startup
            # burst after a seek. Do not reopen the same schedule tail (or run
            # ahead into future programs) while the Broadcast Clock is still in
            # this occurrence. Normal correction is well below one second; a
            # larger gap indicates a broken live-pacing path and should close
            # the tuner request instead of buffering far into the future.
            elapsed = time.monotonic() - segment_wall_started
            pacing_gap = remaining - elapsed
            if pacing_gap > 2.0:
                raise JellyfinAdapterError(
                    "FFmpeg did not maintain live input pacing for "
                    f"{media_path.name!r}"
                )
            if pacing_gap > 0:
                time.sleep(pacing_gap)
            programs_streamed += 1


class JellyfinLiveTvHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        adapter: JellyfinLiveTvAdapter,
        streamer: ChannelStreamer,
        *,
        guide_past_hours: float = 6.0,
        guide_future_hours: float = 72.0,
        max_streams: int = 2,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if guide_past_hours < 0:
            raise ValueError("guide_past_hours cannot be negative")
        if guide_future_hours <= 0:
            raise ValueError("guide_future_hours must be greater than zero")
        if max_streams <= 0:
            raise ValueError("max_streams must be greater than zero")

        self.adapter = adapter
        self.streamer = streamer
        self.guide_past_hours = float(guide_past_hours)
        self.guide_future_hours = float(guide_future_hours)
        self.stream_slots = threading.BoundedSemaphore(int(max_streams))
        self.max_streams = int(max_streams)
        self.now = now
        super().__init__(server_address, JellyfinLiveTvRequestHandler)


class JellyfinLiveTvRequestHandler(BaseHTTPRequestHandler):
    server: JellyfinLiveTvHttpServer
    server_version = "ChannelOS-LiveTV/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # Keep the source CLI useful while avoiding the default reverse-DNS style
        # decoration. The request itself is still visible for diagnosis.
        print(f"Jellyfin adapter: {self.address_string()} - {format % args}")

    def do_HEAD(self) -> None:
        self._dispatch(head_only=True)

    def do_GET(self) -> None:
        self._dispatch(head_only=False)

    def _dispatch(self, *, head_only: bool) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/":
            body = (
                "ChannelOS Jellyfin Live TV adapter\n"
                f"M3U: {self.server.adapter.advertise_url}/channels.m3u\n"
                f"XMLTV: {self.server.adapter.advertise_url}/guide.xml\n"
            ).encode("utf-8")
            self._send_bytes(200, "text/plain; charset=utf-8", body, head_only)
            return

        if path == "/health.json":
            body = json.dumps(
                {
                    "status": "ok",
                    "channels": [
                        runtime.channel_number
                        for runtime in self.server.adapter.runtimes
                    ],
                    "max_streams": self.server.max_streams,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_bytes(200, "application/json; charset=utf-8", body, head_only)
            return

        if path == "/channels.m3u":
            self._send_bytes(
                200,
                M3U_CONTENT_TYPE,
                self.server.adapter.render_m3u(),
                head_only,
            )
            return

        if path == "/guide.xml":
            body = self.server.adapter.render_xmltv(
                at=self.server.now(),
                past_hours=self.server.guide_past_hours,
                future_hours=self.server.guide_future_hours,
            )
            self._send_bytes(200, XMLTV_CONTENT_TYPE, body, head_only)
            return

        match = _CHANNEL_PATH.fullmatch(path)
        if match is not None:
            self._stream_channel(int(match.group(1)), head_only=head_only)
            return

        self._send_error(404, "Unknown ChannelOS Live TV endpoint", head_only)

    def _stream_channel(self, channel_number: int, *, head_only: bool) -> None:
        runtime = self.server.adapter.runtime_by_number.get(channel_number)
        if runtime is None:
            self._send_error(404, f"Unknown channel {channel_number}", head_only)
            return
        if head_only:
            self.send_response(200)
            self.send_header("Content-Type", MPEG_TS_CONTENT_TYPE)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            return

        acquired = self.server.stream_slots.acquire(blocking=False)
        if not acquired:
            self._send_error(503, "ChannelOS stream limit reached", head_only=False)
            return

        try:
            try:
                self.server.streamer.preflight(runtime)
            except JellyfinAdapterError as exc:
                self._send_error(503, str(exc), head_only=False)
                return

            self.send_response(200)
            self.send_header("Content-Type", MPEG_TS_CONTENT_TYPE)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            try:
                for chunk in self.server.streamer.iter_channel(runtime):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            except JellyfinAdapterError as exc:
                self.log_error("channel %s stream failed: %s", channel_number, exc)
        finally:
            self.server.stream_slots.release()

    def _send_bytes(
        self,
        status: int,
        content_type: str,
        body: bytes,
        head_only: bool,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_error(self, status: int, message: str, head_only: bool) -> None:
        body = (message + "\n").encode("utf-8")
        self._send_bytes(status, "text/plain; charset=utf-8", body, head_only)
