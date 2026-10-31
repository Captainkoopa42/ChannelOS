from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Callable

from .broadcaster import BroadcasterError, BroadcasterService
from .library import MediaLibrary
from .scanner import MediaScanner, ScanProgress, ScanSummary
from .vlc_probe import LibVLCMediaProbe


FIRST_RUN_CANCELLED = 10
FIRST_RUN_OPEN_PORTABLE = 12
PORTABLE_HANDOFF = 'open-portable.json'

logger = logging.getLogger(__name__)


class FirstRunError(RuntimeError):
    """Raised when the packaged first-run setup cannot produce usable television."""


def first_run_required(data_directory: str | Path) -> bool:
    """Return whether an ordinary packaged launch still needs initial setup."""

    root = Path(data_directory)
    database = root / "library.db"
    channels = root / "channels"

    if not database.is_file():
        return True
    if not channels.is_dir() or not any(
        path.is_file()
        for pattern in ("*.yaml", "*.yml")
        for path in channels.glob(pattern)
    ):
        return True

    try:
        library = MediaLibrary(database)
        return not bool(library.list_online_media())
    except (OSError, ValueError):
        return True


def first_channel_editor(source: str | Path, *, channel: int = 1) -> dict[str, object]:
    source_path = Path(source).expanduser().resolve(strict=False)
    label = source_path.name.strip() or "My Channel"
    return {
        "channel": int(channel),
        "name": label,
        "description": "Created by ChannelOS first-run setup",
        "sources": [str(source_path)],
        "mode": "sequential",
        "preserveEpisodeOrder": True,
        "avoidRepeatDays": 0,
        "numberWidth": 3,
    }


def bootstrap_first_channel(
    media_folder: str | Path,
    data_directory: str | Path,
    *,
    on_progress: Callable[[ScanProgress], None] | None = None,
) -> tuple[ScanSummary, int | None]:
    """Index one owned-media folder and create a first channel when needed."""

    root = Path(data_directory).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    channels = root / "channels"
    channels.mkdir(parents=True, exist_ok=True)

    source = Path(media_folder).expanduser().resolve(strict=False)
    library = MediaLibrary(root / "library.db")
    scanner = MediaScanner(
        library,
        probe=LibVLCMediaProbe(),
        fail_on_probe_error=True,
    )
    summary = scanner.scan(source, on_progress=on_progress)
    if summary.discovered <= 0:
        raise FirstRunError(
            "That folder does not contain any media files ChannelOS currently supports."
        )

    broadcaster = BroadcasterService([], channels, library)
    if broadcaster.records:
        return summary, None

    channel_number = broadcaster.suggested_channel_number()
    try:
        broadcaster.create(
            first_channel_editor(source, channel=channel_number)
        )
    except BroadcasterError as exc:
        raise FirstRunError(str(exc)) from exc
    return summary, channel_number


def run_first_run_setup(data_directory: str | Path) -> int:
    """Run the small packaged Windows setup UI in a helper process."""

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QMessageBox,
        QProgressDialog,
    )

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ChannelOS")
    app.setOrganizationName("ChannelOS")

    icon_path = Path(__file__).resolve().parent / "assets" / "ChannelOS.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    welcome = QMessageBox()
    welcome.setWindowTitle('Welcome to ChannelOS')
    welcome.setText('Create your first channel, or open a setup already saved on a drive.\n\n'
                    'An existing setup keeps its channels, index and history on that drive.')
    create_button = welcome.addButton('New Library', QMessageBox.ButtonRole.AcceptRole)
    open_button = welcome.addButton('Open Existing Setup…', QMessageBox.ButtonRole.ActionRole)
    welcome.addButton(QMessageBox.StandardButton.Cancel)
    welcome.exec()
    if welcome.clickedButton() == open_button:
        folder = QFileDialog.getExistingDirectory(None, 'Open Existing ChannelOS Setup')
        if not folder:
            return FIRST_RUN_CANCELLED
        try:
            from .portable_copy import inspect_setup
            summary = inspect_setup(folder)
            path = Path(data_directory) / PORTABLE_HANDOFF
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'root': summary['root']}), encoding='utf-8')
            temporary.replace(path)
        except Exception as exc:
            QMessageBox.critical(None, 'Setup could not open', str(exc))
            return 6
        return FIRST_RUN_OPEN_PORTABLE
    if welcome.clickedButton() != create_button:
        return FIRST_RUN_CANCELLED

    folder = QFileDialog.getExistingDirectory(
        None,
        "ChannelOS — Choose Your Media Folder",
        str(Path.home()),
        QFileDialog.Option.ShowDirsOnly,
    )
    if not folder:
        return FIRST_RUN_CANCELLED

    progress = QProgressDialog(
        "Discovering supported media files…",
        None,
        0,
        0,
    )
    progress.setWindowTitle("ChannelOS — Building Your First Channel")
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.show()

    def publish(state: ScanProgress) -> None:
        if state.total <= 0:
            progress.setRange(0, 0)
            progress.setLabelText("Discovering supported media files…")
        else:
            progress.setRange(0, state.total)
            progress.setValue(min(state.current, state.total))
            if state.path is None:
                progress.setLabelText(
                    f"Found {state.total} media file(s). Preparing index…"
                )
            else:
                progress.setLabelText(
                    f"Indexing {state.current} of {state.total}\n{state.path.name}"
                )
        QApplication.processEvents()

    try:
        logger.info("First-run media scan started")
        summary, channel_number = bootstrap_first_channel(
            folder,
            data_directory,
            on_progress=publish,
        )
    except Exception as exc:
        logger.exception("First-run setup failed")
        progress.close()
        QMessageBox.critical(
            None,
            "ChannelOS setup could not finish",
            f"ChannelOS could not build the first channel.\n\n{exc}",
        )
        return 6

    logger.info(
        "First-run setup completed discovered=%d channel_created=%s",
        summary.discovered,
        channel_number is not None,
    )
    progress.close()
    if channel_number is None:
        detail = (
            f"Indexed {summary.discovered} media file(s). Existing channel definitions "
            "will be checked when ChannelOS starts."
        )
    else:
        detail = (
            f"Indexed {summary.discovered} media file(s) and created Channel "
            f"{channel_number:03d}."
        )
    QMessageBox.information(
        None,
        "ChannelOS is ready",
        detail + "\n\nChannelOS will open your television now.",
    )
    return 0
