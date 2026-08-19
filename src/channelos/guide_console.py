from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .guide import GuideController, GuideError, GuideProgram, GuideService
from .library import MediaLibrary
from .loader import load_channel
from .models import ChannelValidationError
from .playback import LibVLCBackend, PlaybackError, PlaybackUnavailableError
from .resolve import resolve_channel
from .runtime import ChannelRuntime, ChannelRuntimeError, RuntimeStore, TelevisionRuntime, require_aware_utc, utc_now
from .television import TelevisionSession

DEFAULT_DATABASE = Path(".channelos") / "library.db"
DEFAULT_RUNTIME_DATABASE = Path(".channelos") / "runtime.db"


@dataclass(frozen=True, slots=True)
class GuideConsoleSnapshot:
    generated_at_utc: datetime
    programs: tuple[GuideProgram, ...]
    next_schedule_ids: frozenset[str]


class GuideConsole:
    """Interactive engineering harness over the Guide/service/control boundary."""

    def __init__(
        self,
        service: GuideService,
        television: TelevisionSession,
        *,
        lookback_seconds: float = 60.0,
        horizon_seconds: float = 180.0,
    ) -> None:
        if lookback_seconds < 0:
            raise ValueError("lookback_seconds cannot be negative")
        if horizon_seconds <= 0:
            raise ValueError("horizon_seconds must be greater than zero")
        self.service = service
        self.television = television
        self.controller = GuideController(service, television)
        self.lookback_seconds = float(lookback_seconds)
        self.horizon_seconds = float(horizon_seconds)
        self.snapshot: GuideConsoleSnapshot | None = None

    def refresh(self, *, at: datetime | None = None) -> GuideConsoleSnapshot:
        reference = require_aware_utc(at or utc_now())
        horizon = self.service.horizon(
            reference - timedelta(seconds=self.lookback_seconds),
            reference + timedelta(seconds=self.horizon_seconds),
            generated_at=reference,
        )
        programs = tuple(program for row in horizon.rows for program in row.programs)
        next_ids = frozenset(
            self.service.now_next(number, at=reference).next.schedule_id
            for number in self.service.channel_numbers
        )
        self.snapshot = GuideConsoleSnapshot(
            generated_at_utc=reference,
            programs=programs,
            next_schedule_ids=next_ids,
        )
        return self.snapshot

    def render(self, snapshot: GuideConsoleSnapshot | None = None) -> str:
        current = snapshot or self.snapshot
        if current is None:
            raise GuideError("Guide snapshot is empty; REFRESH first")

        lines = [
            f"Guide snapshot: {current.generated_at_utc.isoformat(timespec='seconds')}",
            "Select an entry with TUNE <index> or BEGIN <index>.",
        ]
        for index, program in enumerate(current.programs):
            if program.is_current:
                state = "NOW"
            elif program.is_past:
                state = "PAST"
            elif program.schedule_id in current.next_schedule_ids:
                state = "NEXT"
            else:
                state = "FUTURE"
            lines.append(
                f"[{index:03d}] CH {program.channel_number:03d} [{state:<6}] "
                f"{program.start_utc.isoformat(timespec='seconds')} -> "
                f"{program.end_utc.isoformat(timespec='seconds')}  {program.display_label}"
            )
        return "\n".join(lines)

    def _program(self, index_text: str) -> GuideProgram:
        if self.snapshot is None:
            raise GuideError("Guide snapshot is empty; REFRESH first")
        try:
            index = int(index_text)
        except ValueError as exc:
            raise GuideError("Guide selection index must be numeric") from exc
        if index < 0 or index >= len(self.snapshot.programs):
            raise GuideError(f"Guide selection index {index} is out of range; REFRESH to see valid entries")
        return self.snapshot.programs[index]

    def execute(self, intent: str, *, at: datetime | None = None) -> str:
        reference = require_aware_utc(at or utc_now())
        parts = intent.strip().split()
        if not parts:
            return ""
        command = parts[0].upper()

        if command == "REFRESH" and len(parts) == 1:
            return self.render(self.refresh(at=reference))
        if command == "TUNE" and len(parts) == 2:
            decision = self.controller.tune(self._program(parts[1]), at=reference)
            return self.television.describe(decision)
        if command in {"BEGIN", "WATCH_FROM_BEGINNING"} and len(parts) == 2:
            decision = self.controller.watch_from_beginning(self._program(parts[1]), at=reference)
            return self.television.describe(decision)

        # Once a Guide action has selected playback, keep using the same television
        # intent path that the Phase 1 harness and future remote protocol use.
        return self.television.execute(intent, now=reference)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m channelos.guide_console",
        description="Interactive Phase 2 Guide action harness.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="one or more channel YAML files")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"library database path (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--state-db",
        type=Path,
        default=DEFAULT_RUNTIME_DATABASE,
        help=f"runtime state database path (default: {DEFAULT_RUNTIME_DATABASE})",
    )
    parser.add_argument(
        "--lookback-seconds",
        type=float,
        default=60.0,
        help="past schedule retained in each snapshot (default: 60 seconds)",
    )
    parser.add_argument(
        "--horizon-seconds",
        type=float,
        default=180.0,
        help="future schedule shown in each snapshot (default: 180 seconds)",
    )
    return parser


def _open_runtimes(paths: list[Path], library: MediaLibrary, store: RuntimeStore) -> tuple[ChannelRuntime, ...]:
    opened: list[ChannelRuntime] = []
    for path in paths:
        try:
            definition = load_channel(path)
        except ChannelValidationError as exc:
            raise GuideError(str(exc)) from exc
        resolved = resolve_channel(definition, library)
        if not resolved.media:
            raise GuideError(
                f"Channel {definition.display_number} — {definition.name} has no indexed online media. "
                "Scan its source folders first."
            )
        opened.append(ChannelRuntime.open(resolved, store))
    return tuple(opened)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.lookback_seconds < 0:
        print("ERROR: --lookback-seconds cannot be negative", file=sys.stderr)
        return 2
    if args.horizon_seconds <= 0:
        print("ERROR: --horizon-seconds must be greater than zero", file=sys.stderr)
        return 2

    library = MediaLibrary(args.db)
    store = RuntimeStore(args.state_db)
    try:
        runtimes = _open_runtimes(args.paths, library, store)
        service = GuideService(runtimes)
        television_runtime = TelevisionRuntime(runtimes, store)
        backend = LibVLCBackend()
        television = TelevisionSession(television_runtime, backend)
        console = GuideConsole(
            service,
            television,
            lookback_seconds=args.lookback_seconds,
            horizon_seconds=args.horizon_seconds,
        )
        print(console.render(console.refresh()))
    except (GuideError, ChannelRuntimeError, PlaybackUnavailableError, PlaybackError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5

    print(
        "Commands: REFRESH | TUNE <index> | BEGIN <index> | PAUSE | PLAY | "
        "SKIP_BACK [s] | SKIP_FORWARD [s] | GO_LIVE | STATUS | HELP | QUIT"
    )
    try:
        while True:
            try:
                command = input("channelos-guide> ").strip()
            except EOFError:
                command = "QUIT"
            if not command:
                continue
            upper = command.upper()
            if upper in {"QUIT", "EXIT"}:
                television.stop()
                break
            if upper == "HELP":
                print(
                    "REFRESH | TUNE <index> (current entry only) | BEGIN <index> "
                    "(past/current entry) | PAUSE | PLAY | SKIP_BACK [seconds] | "
                    "SKIP_FORWARD [seconds] | GO_LIVE | STATUS | QUIT"
                )
                continue
            try:
                result = console.execute(command)
            except (GuideError, ChannelRuntimeError, PlaybackError, ValueError) as exc:
                print(f"ERROR: {exc}")
                continue
            if result:
                print(result)
    except KeyboardInterrupt:
        print("\nStopping.")
        television.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
