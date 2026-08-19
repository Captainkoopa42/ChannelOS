from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .guide import GuideError, GuideService
from .library import MediaLibrary
from .loader import load_channel
from .models import ChannelValidationError
from .playback import LibVLCBackend, PlaybackError, PlaybackUnavailableError
from .probe import FFprobeMediaProbe, MediaProbeError, NullMediaProbe
from .resolve import ChannelResolutionError, resolve_channel
from .runtime import (
    ChannelRuntime,
    ChannelRuntimeError,
    ReturnChoiceRequired,
    RuntimeStore,
    TelevisionRuntime,
    require_aware_utc,
    utc_now,
)
from .scanner import MediaScanner
from .television import TelevisionSession
from .tuner import TuneSession

DEFAULT_DATABASE = Path(".channelos") / "library.db"
DEFAULT_RUNTIME_DATABASE = Path(".channelos") / "runtime.db"


def _add_database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"library database path (default: {DEFAULT_DATABASE})",
    )


def _add_runtime_database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-db",
        type=Path,
        default=DEFAULT_RUNTIME_DATABASE,
        help=f"runtime state database path (default: {DEFAULT_RUNTIME_DATABASE})",
    )


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        return require_aware_utc(parsed)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO-8601 with a timezone, e.g. 2026-08-19T05:00:00+00:00"
        ) from exc


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

    tune = sub.add_parser("tune", help="Tune one channel through the Phase 0 playback harness.")
    tune.add_argument("path", type=Path, help="channel YAML file")
    _add_database_argument(tune)
    tune.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve and print what would play without starting libVLC",
    )

    broadcast = sub.add_parser(
        "broadcast",
        help="Show what a persistent channel is broadcasting at a wall-clock instant.",
    )
    broadcast.add_argument("path", type=Path, help="channel YAML file")
    _add_database_argument(broadcast)
    _add_runtime_database_argument(broadcast)
    broadcast.add_argument(
        "--at",
        type=_parse_timestamp,
        help="optional ISO-8601 instant; defaults to the current time",
    )

    guide = sub.add_parser(
        "guide",
        help="Print a Phase 2 Guide horizon generated from persistent channel schedules.",
    )
    guide.add_argument("paths", nargs="+", type=Path, help="one or more channel YAML files")
    _add_database_argument(guide)
    _add_runtime_database_argument(guide)
    guide.add_argument(
        "--from",
        dest="from_time",
        type=_parse_timestamp,
        help="optional ISO-8601 horizon start; defaults to the current time",
    )
    guide.add_argument(
        "--hours",
        type=float,
        default=2.0,
        help="Guide horizon length in hours (default: 2)",
    )
    guide.add_argument(
        "--why",
        action="store_true",
        help="include the deterministic scheduling explanation for each program",
    )

    tv = sub.add_parser(
        "tv",
        help="Run the Phase 1 multi-channel television control harness.",
    )
    tv.add_argument("paths", nargs="+", type=Path, help="one or more channel YAML files")
    _add_database_argument(tv)
    _add_runtime_database_argument(tv)
    tv.add_argument(
        "--return-behavior",
        choices=("live", "resume", "ask"),
        default="live",
        help="behavior when returning to a channel with saved viewer continuity",
    )

    return parser


def _load_channel_or_report(path: Path):
    try:
        return load_channel(path)
    except ChannelValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None


def _resolve_or_report(path: Path, library: MediaLibrary):
    channel = _load_channel_or_report(path)
    if channel is None:
        return None
    resolved = resolve_channel(channel, library)
    if not resolved.media:
        print(
            f"ERROR: Channel {channel.display_number} — {channel.name} has no indexed online media. "
            "Scan its source folders first.",
            file=sys.stderr,
        )
        return None
    return resolved


def _format_guide_time(value: datetime) -> str:
    return require_aware_utc(value).isoformat(timespec="seconds")


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
        library = MediaLibrary(args.db)
        resolved = _resolve_or_report(args.path, library)
        if resolved is None:
            return 3
        channel = resolved.definition

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

        print("ChannelOS Phase 0 control console. Type 'help' for controls; 'quit' to stop.")
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

    if args.command == "broadcast":
        library = MediaLibrary(args.db)
        resolved = _resolve_or_report(args.path, library)
        if resolved is None:
            return 3
        store = RuntimeStore(args.state_db)
        try:
            runtime = ChannelRuntime.open(resolved, store, now=args.at)
            selection = runtime.broadcast_at(args.at)
        except ChannelRuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 5

        channel = resolved.definition
        print(f"Channel {channel.display_number} — {channel.name}")
        print(f"Broadcast: {selection.media.location.path}")
        print(f"Media ID: {selection.media.asset.asset_id}")
        print(f"Seek: {selection.offset_seconds:.3f}s")
        print(f"Program start: {selection.program_started_at.isoformat()}")
        print(f"Program end: {selection.program_ends_at.isoformat()}")
        print(f"Schedule epoch: {runtime.epoch_utc.isoformat()}")
        return 0

    if args.command == "guide":
        if args.hours <= 0:
            print("ERROR: --hours must be greater than zero", file=sys.stderr)
            return 2

        library = MediaLibrary(args.db)
        store = RuntimeStore(args.state_db)
        opened: list[ChannelRuntime] = []
        try:
            for path in args.paths:
                resolved = _resolve_or_report(path, library)
                if resolved is None:
                    return 3
                opened.append(ChannelRuntime.open(resolved, store))

            service = GuideService(tuple(opened))
            generated_at = utc_now()
            start = args.from_time or generated_at
            end = start + timedelta(hours=float(args.hours))
            horizon = service.horizon(start, end, generated_at=generated_at)
        except (ChannelRuntimeError, GuideError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 5

        print(f"Guide generated: {_format_guide_time(horizon.generated_at_utc)}")
        print(
            f"Window: {_format_guide_time(horizon.start_utc)} -> "
            f"{_format_guide_time(horizon.end_utc)}"
        )

        runtime_by_number = {runtime.channel_number: runtime for runtime in opened}
        for row in horizon.rows:
            runtime = runtime_by_number[row.channel_number]
            channel = runtime.channel.definition
            now_next = service.now_next(row.channel_number, at=horizon.generated_at_utc)
            print()
            print(f"Channel {channel.display_number} — {row.channel_name}")
            print(f"  NOW:  {now_next.now.display_label}")
            print(f"  NEXT: {now_next.next.display_label}")
            for program in row.programs:
                if program.is_current:
                    state = "NOW"
                elif program.is_past:
                    state = "PAST"
                elif program.schedule_id == now_next.next.schedule_id:
                    state = "NEXT"
                else:
                    state = "FUTURE"
                print(
                    f"  {_format_guide_time(program.start_utc)} -> "
                    f"{_format_guide_time(program.end_utc)}  [{state}]  {program.display_label}"
                )
                if args.why:
                    for step in program.explanation:
                        print(f"      why: {step}")
        return 0

    if args.command == "tv":
        library = MediaLibrary(args.db)
        store = RuntimeStore(args.state_db)
        opened: list[ChannelRuntime] = []
        try:
            for path in args.paths:
                resolved = _resolve_or_report(path, library)
                if resolved is None:
                    return 3
                opened.append(ChannelRuntime.open(resolved, store))
            television = TelevisionRuntime(tuple(opened), store)
            backend = LibVLCBackend()
            session = TelevisionSession(television, backend)

            start_channel = television.current_channel or television.channel_numbers[0]
            first = session.tune(
                start_channel,
                return_behavior=args.return_behavior,
            )
        except (ChannelRuntimeError, PlaybackUnavailableError, PlaybackError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 5

        print(session.describe(first))
        print(
            "Phase 1 TV console: TUNE 007, CHANNEL_UP, CHANNEL_DOWN, PREVIOUS_CHANNEL, "
            "PAUSE, PLAY, SKIP_BACK [s], SKIP_FORWARD [s], GO_LIVE, STATUS, HELP, QUIT"
        )
        try:
            while True:
                try:
                    command = input("channelos-tv> ").strip()
                except EOFError:
                    command = "QUIT"
                if not command:
                    continue
                upper = command.upper()
                if upper in {"QUIT", "EXIT"}:
                    session.stop()
                    break
                if upper == "HELP":
                    print(
                        "TUNE 007 | CHANNEL_UP | CHANNEL_DOWN | PREVIOUS_CHANNEL | "
                        "PAUSE | PLAY | SKIP_BACK [seconds] | SKIP_FORWARD [seconds] | "
                        "GO_LIVE | STATUS | QUIT"
                    )
                    continue
                try:
                    result = session.execute(
                        command,
                        return_behavior=args.return_behavior,
                    )
                except (ValueError, ChannelRuntimeError, ReturnChoiceRequired, PlaybackError) as exc:
                    print(f"ERROR: {exc}")
                    continue
                if result:
                    print(result)
        except KeyboardInterrupt:
            print("\nStopping.")
            session.stop()
        return 0

    return 1
