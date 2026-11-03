from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .broadcaster import BroadcasterError, BroadcasterService
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

logger = logging.getLogger(__name__)


class CouchUIError(RuntimeError):
    """Raised when the couch UI cannot be started."""


def _open_runtimes(
    paths: list[Path] | tuple[Path, ...],
    library: MediaLibrary,
    store: RuntimeStore,
    *,
    definitions=None,
) -> tuple[ChannelRuntime, ...]:
    from .resolve import MediaResolutionIndex
    index = MediaResolutionIndex(library) if len(paths) > 1 else None
    availability = {}
    opened: list[ChannelRuntime] = []
    for path in paths:
        try:
            definition = definitions[path] if definitions is not None else load_channel(path)
        except ChannelValidationError as exc:
            raise CouchUIError(str(exc)) from exc
        try:
            from .media_resilience import _resolved_runtime
            runtime = _resolved_runtime(definition, library, store,
                persistent_when_complete=True, verify_files=True, index=index, availability=availability)
            if runtime is not None:
                opened.append(runtime)
            else:
                logger.warning("Channel %s has no available media; retained in Broadcaster", definition.display_number)
        except ChannelRuntimeError as exc:
            for runtime in opened:
                if runtime.break_store is not None:
                    runtime.break_store.close()
            raise CouchUIError(str(exc)) from exc
    return tuple(opened)


def run_couch(
    paths: list[Path],
    *,
    db: Path = DEFAULT_DATABASE,
    state_db: Path = DEFAULT_RUNTIME_DATABASE,
    channels_dir: Path = DEFAULT_CHANNEL_DIRECTORY,
    windowed: bool = False,
) -> int:
    logger.info("Opening ChannelOS couch runtime")
    try:
        from . import broadcaster_qt
        from .display_mode import install_display_mode_support
        from .interaction import install_interaction_support
        from .media_resilience import install_media_resilience_support
        from .vlc_probe import install_packaged_media_scan_support
        from .portable_qt import install_portable_support
        from .channel_jobs import install_channel_operations_support
        from .guide_projection import install_incremental_guide_support
        from .startup_qt import install_startup_support, launch
    except (ImportError, OSError) as exc:
        raise CouchUIError(
            "ChannelOS couch UI requires the optional Qt package. "
            "Install it with: python -m pip install -e \".[ui]\""
        ) from exc

    install_display_mode_support(broadcaster_qt)
    install_packaged_media_scan_support(broadcaster_qt)
    install_media_resilience_support(broadcaster_qt)
    install_portable_support(broadcaster_qt)
    install_channel_operations_support(broadcaster_qt)
    install_incremental_guide_support(broadcaster_qt)
    install_startup_support(broadcaster_qt)
    install_interaction_support(broadcaster_qt)
    return launch(broadcaster_qt, paths, db, state_db, channels_dir, windowed=windowed)


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
        '--portable-setup', type=Path,
        help='open an existing portable setup and save directly on its drive',
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="launch in a normal window instead of fullscreen",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.portable_setup is not None:
        from .windows_app import main as launch_setup
        return launch_setup(list(sys.argv[1:] if argv is None else argv))
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
