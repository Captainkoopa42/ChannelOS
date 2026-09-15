from __future__ import annotations

import faulthandler
import logging
import os
import platform
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Self, TextIO

from . import __version__

LOG_FILENAME = "channelos.log"
CRASH_LOG_FILENAME = "channelos-crash.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
CRASH_LOG_MAX_BYTES = 2 * 1024 * 1024
CRASH_LOG_BACKUP_COUNT = 2
LOG_DIRECTORY_ENV = "CHANNELOS_LOG_DIR"


class LoggingStream:
    """Line-buffered stdout/stderr adapter for console-free packaged builds."""

    def __init__(
        self,
        logger: logging.Logger,
        level: int,
        console: TextIO | None,
    ) -> None:
        self._logger = logger
        self._level = level
        self._console = console
        self._pending = ""

    @property
    def encoding(self) -> str:
        return "utf-8"

    def write(self, value: str) -> int:
        text = str(value)
        if self._console is not None:
            self._console.write(text)
            self._console.flush()
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, "%s", line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        if self._pending.strip():
            self._logger.log(self._level, "%s", self._pending.rstrip("\r"))
        self._pending = ""
        if self._console is not None:
            self._console.flush()

    def isatty(self) -> bool:
        return bool(self._console is not None and self._console.isatty())


def _rotate_plain_log(path: Path, *, max_bytes: int, backups: int) -> None:
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return
        oldest = path.with_name(f"{path.name}.{backups}")
        oldest.unlink(missing_ok=True)
        for index in range(backups - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            if source.exists():
                source.replace(path.with_name(f"{path.name}.{index + 1}"))
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        # Failing to rotate diagnostics must never prevent ChannelOS startup.
        return


class DiagnosticSession:
    """Own durable application, Qt, thread, and fatal-crash diagnostics."""

    def __init__(self, logs_directory: str | Path) -> None:
        self.logs_directory = Path(logs_directory)
        self.log_path = self.logs_directory / LOG_FILENAME
        self.crash_log_path = self.logs_directory / CRASH_LOG_FILENAME
        self._logger = logging.getLogger("channelos")
        self._handler: RotatingFileHandler | None = None
        self._crash_file: TextIO | None = None
        self._previous_level = self._logger.level
        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = threading.excepthook
        self._previous_qt_handler = None
        self._qt_handler_installed = False
        self._faulthandler_was_enabled = faulthandler.is_enabled()
        self._previous_log_directory = os.environ.get(LOG_DIRECTORY_ENV)

    def __enter__(self) -> Self:
        self.logs_directory.mkdir(parents=True, exist_ok=True)
        os.environ[LOG_DIRECTORY_ENV] = str(self.logs_directory.resolve(strict=False))
        handler = RotatingFileHandler(
            self.log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)sZ %(levelname)s %(threadName)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        self._handler = handler
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)

        _rotate_plain_log(
            self.crash_log_path,
            max_bytes=CRASH_LOG_MAX_BYTES,
            backups=CRASH_LOG_BACKUP_COUNT,
        )
        try:
            self._crash_file = self.crash_log_path.open(
                "a",
                encoding="utf-8",
                buffering=1,
            )
            if not self._faulthandler_was_enabled:
                faulthandler.enable(file=self._crash_file, all_threads=True)
        except (OSError, RuntimeError) as exc:
            self._logger.warning("Fatal crash capture could not be enabled: %s", exc)

        sys.excepthook = self._handle_unhandled_exception
        threading.excepthook = self._handle_thread_exception
        self._logger.info(
            "Diagnostic session started version=%s pid=%d frozen=%s python=%s platform=%s architecture=%s",
            __version__,
            os.getpid(),
            bool(getattr(sys, "frozen", False)),
            platform.python_version(),
            platform.platform(),
            platform.machine(),
        )
        return self

    def install_qt_message_handler(self) -> None:
        if self._qt_handler_installed:
            return
        try:
            from PySide6.QtCore import QtMsgType, qInstallMessageHandler
        except (ImportError, OSError) as exc:
            self._logger.warning("Qt diagnostic capture is unavailable: %s", exc)
            return

        levels = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }

        def handle_qt_message(message_type, context, message) -> None:
            location = ""
            if context is not None and getattr(context, "file", None):
                location = f" [{context.file}:{int(context.line or 0)}]"
            self._logger.log(
                levels.get(message_type, logging.INFO),
                "Qt%s: %s",
                location,
                message,
            )

        self._previous_qt_handler = qInstallMessageHandler(handle_qt_message)
        self._qt_handler_installed = True
        # Keep the Python callback alive while Qt owns its function pointer.
        self._qt_message_handler = handle_qt_message
        self._logger.info("Qt/QML diagnostic capture enabled")

    def stdout_stream(self, console: TextIO | None = None) -> LoggingStream:
        return LoggingStream(logging.getLogger("channelos.stdout"), logging.INFO, console)

    def stderr_stream(self, console: TextIO | None = None) -> LoggingStream:
        return LoggingStream(logging.getLogger("channelos.stderr"), logging.WARNING, console)

    def _handle_unhandled_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        self._logger.critical(
            "Unhandled exception on the main thread",
            exc_info=(exc_type, exc_value, traceback),
        )

    def _handle_thread_exception(self, args: object) -> None:
        self._logger.critical(
            "Unhandled exception on worker thread %s",
            args.thread.name if args.thread is not None else "unknown",  # type: ignore[attr-defined]
            exc_info=(  # type: ignore[attr-defined]
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            ),
        )

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None and exc_value is not None:
            self._logger.critical(
                "Diagnostic session ended with an unhandled exception",
                exc_info=(exc_type, exc_value, traceback),
            )
        else:
            self._logger.info("Diagnostic session ended normally")

        if self._qt_handler_installed:
            from PySide6.QtCore import qInstallMessageHandler

            qInstallMessageHandler(self._previous_qt_handler)
            self._qt_handler_installed = False
        sys.excepthook = self._previous_sys_hook
        threading.excepthook = self._previous_thread_hook

        if not self._faulthandler_was_enabled and faulthandler.is_enabled():
            faulthandler.disable()
        if self._crash_file is not None:
            self._crash_file.close()
            self._crash_file = None

        if self._handler is not None:
            self._handler.flush()
            self._logger.removeHandler(self._handler)
            self._handler.close()
            self._handler = None
        self._logger.setLevel(self._previous_level)
        if self._previous_log_directory is None:
            os.environ.pop(LOG_DIRECTORY_ENV, None)
        else:
            os.environ[LOG_DIRECTORY_ENV] = self._previous_log_directory
