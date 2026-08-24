from __future__ import annotations

import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Mapping, TextIO

from . import couch

DATA_DIRECTORY_ENV = "CHANNELOS_DATA_DIR"


class _Tee:
    """Write diagnostics to a durable log and an optional attached console."""

    def __init__(self, log: TextIO, console: TextIO | None) -> None:
        self._log = log
        self._console = console

    def write(self, value: str) -> int:
        self._log.write(value)
        self._log.flush()
        if self._console is not None:
            self._console.write(value)
            self._console.flush()
        return len(value)

    def flush(self) -> None:
        self._log.flush()
        if self._console is not None:
            self._console.flush()


def default_data_directory(environment: Mapping[str, str] | None = None) -> Path:
    """Return the ordinary-user data location for the packaged Windows app."""

    values = os.environ if environment is None else environment
    override = values.get(DATA_DIRECTORY_ENV)
    if override:
        return Path(override).expanduser()

    local_app_data = values.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ChannelOS"

    return Path.home() / "AppData" / "Local" / "ChannelOS"


def couch_arguments(argv: list[str], data_directory: Path) -> list[str]:
    """Add packaged defaults without overriding explicit command-line paths."""

    result = list(argv)
    defaults = (
        ("--db", data_directory / "library.db"),
        ("--state-db", data_directory / "runtime.db"),
        ("--channels-dir", data_directory / "channels"),
    )
    additions: list[str] = []
    for option, value in defaults:
        if option not in result:
            additions.extend((option, str(value)))
    return additions + result


def _show_error(message: str) -> None:
    """Show packaged startup failures even though ChannelOS has no console."""

    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None,
            message,
            "ChannelOS could not start",
            0x10,
        )
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    """Launch packaged ChannelOS with writable per-user state and a log file."""

    supplied = list(sys.argv[1:] if argv is None else argv)
    data_directory = default_data_directory().resolve(strict=False)
    channels_directory = data_directory / "channels"
    logs_directory = data_directory / "logs"
    channels_directory.mkdir(parents=True, exist_ok=True)
    logs_directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = logs_directory / f"channelos-{timestamp}.log"

    with log_path.open("w", encoding="utf-8", buffering=1) as log:
        stdout = _Tee(log, getattr(sys, "__stdout__", None))
        stderr = _Tee(log, getattr(sys, "__stderr__", None))
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = couch.main(couch_arguments(supplied, data_directory))
        except Exception:
            traceback.print_exc(file=log)
            exit_code = 1

    if exit_code:
        _show_error(
            "ChannelOS could not start.\n\n"
            "This preview still needs at least one indexed channel. "
            "Your diagnostic log is here:\n\n"
            f"{log_path}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
