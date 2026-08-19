from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .library import MediaLibrary
from .loader import load_channel
from .models import ChannelValidationError
from .playback import LibVLCBackend, PlaybackError, PlaybackUnavailableError
from .probe import FFprobeMediaProbe, MediaProbeError, NullMediaProbe
from .resolve import ChannelResolutionError, resolve_channel
from .scanner import MediaScanner
from .tuner import TuneSession

DEFAULT_DATABASE = Path(".channelos") / "library.db"


def _add_database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"library database path (default: {DEFAULT_DATABASE})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channelos",
        description="ChannelOS local-first personal television prototype.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a channel definition.")
    validate.add_argument("path", type=Path)

    show = sub.add_parser("show", help="Validate and summarize a channel definition.")
    show.add_argument("path", type=Path)

    scan = sub.add_parser("scan", help="Index a local media file or directory.")
    scan.add_argument("source", type=Path)
    _add_database_argument(scan)
    scan.add_argument(
        "--no-probe",
        action="store_true",
        help="skip ffprobe technical metadata inspection",
    )
    scan.add_argument(
        "--require-probe",
        action="store_true",
        help="fail the scan if ffprobe is unavailable or cannot inspect a file",
    )

    library = sub.add_parser("library", help="List indexed online media.")
    _add_database_argument(library)

    resolve = sub.add_parser("resolve", help="Resolve a channel against the media index.")
    resolve.add_argument("path", type=Path, help="channel YAML file")
    _add_database_argument(resolve)

    tune = sub.add_parser("tune", help="Tune a channel through the reference playback backend.")
    tune.add_argument("path", type=Path, help="channel YAML file")
    _add_database_argument(tune)
    tune.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve and print what would play without starting libVLC",
    )

    return parser


def _load_channel_or_report(path: Path):
    try:
        return load_channel(path)
    except ChannelValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command in {"validate", "show"}:
        channel = _load_channel_or_report(args.path)
        if channel is None:
            return 2

        if args.command == "validate":
            print(f"OK: Channel {channel.display_number} — {channel.name}")
            return 0

        print(f"Channel {channel.display_number} — {channel.name}")
        if channel.description:
            print(channel.description)
        print(f"Programming: {channel.programming.mode}")
        print(f"Sources: {len(channel.sources)}")
        for source in channel.sources:
            print(f"  - {source.path}")
        return 0

    if args.command == "scan":
        library = MediaLibrary(args.db)
        if args.no_probe:
            probe = NullMediaProbe()
        else:
            probe = FFprobeMediaProbe(required=args.require_probe)
        scanner = MediaScanner(
            library,
            probe,
            fail_on_probe_error=args.require_probe,
        )
        try:
            summary = scanner.scan(args.source)
        except (FileNotFoundError, MediaProbeError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(
            "Scan complete: "
            f"discovered={summary.discovered} hashed={summary.hashed} "
            f"cache_hits={summary.cache_hits} new_assets={summary.new_assets} "
            f"known_assets={summary.known_assets} probe_errors={summary.probe_errors}"
        )
        return 0

    if args.command == "library":
        library = MediaLibrary(args.db)
        items = library.list_online_media()
        if not items:
            print("Library is empty.")
            return 0
        for item in items:
            duration = (
                f"{item.asset.duration_seconds:.3f}s"
                if item.asset.duration_seconds is not None
                else "duration=?"
            )
            print(f"{item.asset.asset_id}  {duration}  {item.location.path}")
        return 0

    if args.command in {"resolve", "tune"}:
        channel = _load_channel_or_report(args.path)
        if channel is None:
            return 2
        library = MediaLibrary(args.db)
        resolved = resolve_channel(channel, library)
        if not resolved.media:
            print(
                f"ERROR: Channel {channel.display_number} — {channel.name} has no indexed online media. "
                "Scan its source folders first.",
                file=sys.stderr,
            )
            return 3

        if args.command == "resolve":
            print(
                f"Channel {channel.display_number} — {channel.name}: "
                f"{len(resolved.media)} unique indexed asset(s)"
            )
            for item in resolved.media:
                print(f"  {item.asset.asset_id}  {item.location.path}")
            return 0

        selected = resolved.first
        print(f"Tuning Channel {channel.display_number} — {channel.name}")
        print(f"Selected: {selected.location.path}")
        print(f"Media ID: {selected.asset.asset_id}")
        if args.dry_run:
            return 0

        try:
            backend = LibVLCBackend()
            session = TuneSession(resolved, backend)
            session.start()
        except (PlaybackUnavailableError, PlaybackError, ChannelResolutionError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 4

        print("ChannelOS control console. Type 'help' for controls; 'quit' to stop.")
        try:
            while True:
                try:
                    command = input("channelos> ").strip()
                except EOFError:
                    command = "quit"
                if not command:
                    continue
                try:
                    result = session.execute(command)
                except (ValueError, PlaybackError) as exc:
                    print(f"ERROR: {exc}")
                    continue
                if result:
                    print(result)
                if command.lower() in {"quit", "exit", "stop"}:
                    break
        except KeyboardInterrupt:
            print("\nStopping.")
            backend.stop()
        return 0

    return 1
