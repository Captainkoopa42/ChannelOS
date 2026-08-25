from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .broadcaster import BroadcasterError, BroadcasterService
from .display_mode import install_display_mode_support
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
DEFAULT_CHANNEL_DIRECTORY = Path("channels")


class CouchUIError(RuntimeError):
    """Raised when the couch UI cannot be started."""


def _open_runtimes(
    paths: list[Path] | tuple[Path, ...],
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
        raise CouchUIError(
            "couch UI requires at least one channel. Provide a channel YAML "
            f"or create one in {DEFAULT_CHANNEL_DIRECTORY}."
        )
    return tuple(opened)


def run_couch(
    paths: list[Path],
    *,
    db: Path = DEFAULT_DATABASE,
    state_db: Path = DEFAULT_RUNTIME_DATABASE,
    channels_dir: Path = DEFAULT_CHANNEL_DIRECTORY,
    windowed: bool = False,
) -> int:
    library = MediaLibrary(db)
    store = RuntimeStore(state_db)

    try:
        broadcaster = BroadcasterService(
            paths,
            channels_dir,
            library,
        )
    except (BroadcasterError, ChannelValidationError) as exc:
        raise CouchUIError(str(exc)) from exc

    runtimes = _open_runtimes(broadcaster.paths, library, store)
    service = GuideService(runtimes)
    television = TelevisionRuntime(runtimes, store)

    try:
        from . import broadcaster_qt
    except (ImportError, OSError) as exc:
        raise CouchUIError(
            "ChannelOS couch UI requires the optional Qt package. "
            "Install it with: python -m pip install -e \".[ui]\""
        ) from exc

    install_display_mode_support(broadcaster_qt)
    return broadcaster_qt.run_qt(
        service,
        television,
        library,
        broadcaster,
        store,
        windowed=windowed,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channelos-couch",
        description="Launch the ChannelOS fullscreen couch interface.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "zero or more channel YAML files; Broadcaster-managed definitions "
            "are also discovered automatically"
        ),
    )
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
        "--channels-dir",
        type=Path,
        default=DEFAULT_CHANNEL_DIRECTORY,
        help=(
            "directory for Broadcaster-managed portable channel definitions "
            f"(default: {DEFAULT_CHANNEL_DIRECTORY})"
        ),
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
            channels_dir=args.channels_dir,
            windowed=args.windowed,
        )
    except (CouchUIError, GuideError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
