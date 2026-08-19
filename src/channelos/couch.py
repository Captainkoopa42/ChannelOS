from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .guide import GuideError, GuideService
from .library import MediaLibrary
from .loader import load_channel
from .models import ChannelValidationError
from .resolve import resolve_channel
from .runtime import (
    ChannelRuntime,
    ChannelRuntimeError,
    RuntimeStore,
    TelevisionRuntime,
)

DEFAULT_DATABASE = Path(".channelos") / "library.db"
DEFAULT_RUNTIME_DATABASE = Path(".channelos") / "runtime.db"


class CouchUIError(RuntimeError):
    """Raised when the couch UI cannot be started."""


def _open_runtimes(
    paths: list[Path],
    library: MediaLibrary,
    store: RuntimeStore,
) -> tuple[ChannelRuntime, ...]:
    opened: list[ChannelRuntime] = []
    for path in paths:
        try:
            definition = load_channel(path)
        except ChannelValidationError as exc:
            raise CouchUIError(str(exc)) from exc
        resolved = resolve_channel(definition, library)
        if not resolved.media:
            raise CouchUIError(
                f"Channel {definition.display_number} — {definition.name} has no indexed online media. "
                "Scan its source folders first."
            )
        try:
            opened.append(ChannelRuntime.open(resolved, store))
        except ChannelRuntimeError as exc:
            raise CouchUIError(str(exc)) from exc
    if not opened:
        raise CouchUIError("couch UI requires at least one channel")
    return tuple(opened)


def run_couch(
    paths: list[Path],
    *,
    db: Path = DEFAULT_DATABASE,
    state_db: Path = DEFAULT_RUNTIME_DATABASE,
    windowed: bool = False,
) -> int:
    library = MediaLibrary(db)
    store = RuntimeStore(state_db)
    runtimes = _open_runtimes(paths, library, store)
    service = GuideService(runtimes)
    television = TelevisionRuntime(runtimes, store)

    try:
        from .couch_qt import run_qt
    except (ImportError, OSError) as exc:
        raise CouchUIError(
            "ChannelOS couch UI requires the optional Qt package. "
            "Install it with: python -m pip install -e \".[ui]\""
        ) from exc

    return run_qt(service, television, windowed=windowed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channelos-couch",
        description="Launch the ChannelOS fullscreen couch interface.",
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
        "--windowed",
        action="store_true",
        help="launch in a normal window instead of fullscreen",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_couch(
            args.paths,
            db=args.db,
            state_db=args.state_db,
            windowed=args.windowed,
        )
    except (CouchUIError, GuideError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
