from __future__ import annotations

import logging
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path

from . import couch
from .diagnostics import DiagnosticSession
from .first_run import (FIRST_RUN_CANCELLED, FIRST_RUN_OPEN_PORTABLE,
                        PORTABLE_HANDOFF, first_run_required, run_first_run_setup)
from .portable import (APP_FOLDER, DATA_FOLDER, PortableSetupError, SetupLock,
                       find_setup, load_setup, remember_setup)
from .portable_copy import inspect_setup
from .storage import DatabaseVersionError

DATA_DIRECTORY_ENV = "CHANNELOS_DATA_DIR"
FIRST_RUN_FLAG = "--channelos-first-run-setup"


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
    """Launch the selected setup, retaining its drive lease until Qt exits."""

    with ExitStack() as lifetime:
        try:
            return _launch(argv, lifetime)
        except (PortableSetupError, OSError, sqlite3.Error, DatabaseVersionError) as exc:
            message = f"ChannelOS could not open this setup.\n\n{exc}"
            logging.getLogger(__name__).error(message)
            _show_error(message)
            return 6


def _launch(argv: list[str] | None, lifetime: ExitStack) -> int:

    supplied = list(sys.argv[1:] if argv is None else argv)
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument('--portable-setup', type=Path)
    options, supplied = selector.parse_known_args(supplied)
    portable = None
    if options.portable_setup is not None:
        portable = load_setup(inspect_setup(options.portable_setup)['root'])
    elif getattr(sys, 'frozen', False) and FIRST_RUN_FLAG not in supplied:
        portable = find_setup(sys.executable)
        if portable is None and Path(sys.executable).parent.name == APP_FOLDER:
            raise PortableSetupError('The portable drive or its setup marker is missing. Reconnect the drive or use Open Existing Setup from another ChannelOS copy.')
    data_directory = default_data_directory().resolve(strict=False)
    if portable is None and FIRST_RUN_FLAG not in supplied:
        portable = find_setup(data_directory)
        if portable is None and data_directory.name == DATA_FOLDER:
            raise PortableSetupError('The portable setup marker is missing. No replacement data folder was created.')
    if portable is not None:
        if any(argument.split('=', 1)[0] in {'--db', '--state-db', '--channels-dir'} for argument in supplied):
            raise PortableSetupError('Open a portable setup without separate database or channel paths, so all changes stay together on the drive.')
        # Validate before creating directories, migrating databases or taking logs.
        inspect_setup(portable.root)
        lifetime.enter_context(SetupLock(portable))
        data_directory = portable.data_directory
        try:
            remember_setup(portable)
        except OSError:
            logging.getLogger(__name__).warning('Could not remember this portable setup on the current PC')
    channels_directory = data_directory / "channels"
    logs_directory = data_directory / "logs"
    channels_directory.mkdir(parents=True, exist_ok=True)
    logs_directory.mkdir(parents=True, exist_ok=True)

    if FIRST_RUN_FLAG in supplied:
        with DiagnosticSession(logs_directory) as diagnostics:
            diagnostics.install_qt_message_handler()
            try:
                return run_first_run_setup(data_directory)
            except Exception:
                logging.getLogger(__name__).exception("First-run setup crashed")
                return 1

    if (
        getattr(sys, "frozen", False)
        and portable is None
        and _ordinary_first_run_candidate(supplied)
        and first_run_required(data_directory)
    ):
        (data_directory / PORTABLE_HANDOFF).unlink(missing_ok=True)
        setup_result = _run_first_run_helper(data_directory)
        if setup_result == FIRST_RUN_CANCELLED:
            return 0
        if setup_result == FIRST_RUN_OPEN_PORTABLE:
            handoff = data_directory / PORTABLE_HANDOFF
            try:
                root = json.loads(handoff.read_text(encoding='utf-8'))['root']
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise PortableSetupError('The selected setup could not be opened. Start ChannelOS and choose Open Existing Setup again.') from exc
            finally:
                handoff.unlink(missing_ok=True)
            return _launch(['--portable-setup', str(root), *supplied], lifetime)
        if setup_result:
            _show_error(
                "ChannelOS setup could not finish.\n\n"
                "Your media was not moved or deleted. You can start ChannelOS again "
                "to retry first-run setup."
            )
            return setup_result

    with DiagnosticSession(logs_directory) as diagnostics:
        diagnostics.install_qt_message_handler()
        stdout = diagnostics.stdout_stream(getattr(sys, "__stdout__", None))
        stderr = diagnostics.stderr_stream(getattr(sys, "__stderr__", None))
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = couch.main(couch_arguments(supplied, data_directory))
        except Exception:
            logging.getLogger(__name__).exception("ChannelOS application crashed")
            exit_code = 1
        finally:
            stdout.flush()
            stderr.flush()
        logging.getLogger(__name__).info(
            "ChannelOS exited with code %d",
            exit_code,
        )

    if exit_code:
        _show_error(
            "ChannelOS could not start.\n\n"
            "Your diagnostic logs are here:\n\n"
            f"{logs_directory}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
