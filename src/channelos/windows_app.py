from __future__ import annotations

import os
import subprocess
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Mapping, TextIO

from . import couch
from .first_run import FIRST_RUN_CANCELLED, first_run_required, run_first_run_setup

DATA_DIRECTORY_ENV = "CHANNELOS_DATA_DIR"
FIRST_RUN_FLAG = "--channelos-first-run-setup"


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


def _ordinary_first_run_candidate(argv: list[str]) -> bool:
    """Limit automatic setup to normal double-click launches and --windowed."""

    return all(argument == "--windowed" for argument in argv)


def _run_first_run_helper(data_directory: Path) -> int:
    """Run Qt setup in a child process so the real couch app owns QApplication."""

    environment = os.environ.copy()
    environment[DATA_DIRECTORY_ENV] = str(data_directory)
    if getattr(sys, "frozen", False):
        command = [sys.executable, FIRST_RUN_FLAG]
    else:
        command = [sys.executable, "-m", "channelos.windows_app", FIRST_RUN_FLAG]
    completed = subprocess.run(
        command,
        env=environment,
        check=False,
    )
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    """Launch packaged ChannelOS with writable per-user state and a log file."""

    supplied = list(sys.argv[1:] if argv is None else argv)
    data_directory = default_data_directory().resolve(strict=False)
    channels_directory = data_directory / "channels"
    logs_directory = data_directory / "logs"
    channels_directory.mkdir(parents=True, exist_ok=True)
    logs_directory.mkdir(parents=True, exist_ok=True)

    if FIRST_RUN_FLAG in supplied:
        return run_first_run_setup(data_directory)

    if (
        getattr(sys, "frozen", False)
        and _ordinary_first_run_candidate(supplied)
        and first_run_required(data_directory)
    ):
        setup_result = _run_first_run_helper(data_directory)
        if setup_result == FIRST_RUN_CANCELLED:
            return 0
        if setup_result:
            _show_error(
                "ChannelOS setup could not finish.\n\n"
                "Your media was not moved or deleted. You can start ChannelOS again "
                "to retry first-run setup."
            )
            return setup_result

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
            "Your diagnostic log is here:\n\n"
            f"{log_path}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
