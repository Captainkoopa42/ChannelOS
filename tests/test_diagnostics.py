from __future__ import annotations

import logging
from pathlib import Path

import pytest

from channelos import diagnostics as diagnostics_module
from channelos.diagnostics import (
    CRASH_LOG_FILENAME,
    LOG_FILENAME,
    DiagnosticSession,
)


def test_diagnostic_session_captures_application_and_stream_messages(
    tmp_path: Path,
) -> None:
    with DiagnosticSession(tmp_path) as diagnostics:
        logging.getLogger("channelos.test").info("library scan checkpoint")
        stderr = diagnostics.stderr_stream()
        stderr.write("decoder warning\n")
        stderr.flush()

    content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
    assert "Diagnostic session started" in content
    assert "library scan checkpoint" in content
    assert "decoder warning" in content
    assert "Diagnostic session ended normally" in content
    assert (tmp_path / CRASH_LOG_FILENAME).is_file()


def test_diagnostic_session_captures_qt_warnings(tmp_path: Path) -> None:
    from PySide6.QtCore import qWarning

    with DiagnosticSession(tmp_path) as diagnostics:
        diagnostics.install_qt_message_handler()
        qWarning("QML diagnostic checkpoint")

    content = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
    assert "Qt/QML diagnostic capture enabled" in content
    assert "QML diagnostic checkpoint" in content


def test_diagnostic_log_rotates_at_its_size_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(diagnostics_module, "LOG_MAX_BYTES", 512)

    with DiagnosticSession(tmp_path):
        logger = logging.getLogger("channelos.rotation-test")
        for index in range(8):
            logger.info("rotation-checkpoint-%d %s", index, "x" * 200)

    assert (tmp_path / f"{LOG_FILENAME}.1").is_file()
