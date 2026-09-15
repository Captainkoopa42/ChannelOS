from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QEvent, QPointF, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem

from .control import ControlCommand, ControlIntent

logger = logging.getLogger(__name__)


def _variant_mapping(value: object) -> dict[str, object]:
    """Normalize a QVariant/QJSValue-style mapping into a regular dict."""

    to_variant = getattr(value, "toVariant", None)
    if callable(to_variant):
        value = to_variant()
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _program_index_at_time(
    programs: Sequence[object],
    timestamp_ms: float,
) -> int | None:
    """Return the exact scheduled occurrence under a Guide timeline click."""

    for index, raw_program in enumerate(programs):
        program = _variant_mapping(raw_program)
        if not program:
            continue
        start_ms = float(program.get("startMs", 0.0) or 0.0)
        end_ms = float(program.get("endMs", 0.0) or 0.0)
        if start_ms <= timestamp_ms < end_ms:
            return index
    return None


def _row_index_for_channel(
    rows: Sequence[object],
    channel_number: int,
) -> int | None:
    for index, raw_row in enumerate(rows):
        row = _variant_mapping(raw_row)
        if int(row.get("channelNumber", -1) or -1) == int(channel_number):
            return index
    return None


def _has_qt_property(obj: object | None, name: str) -> bool:
    if obj is None:
        return False
    try:
        meta = obj.metaObject()  # type: ignore[attr-defined]
        return meta.indexOfProperty(name) >= 0
    except (AttributeError, RuntimeError):
        return False


def _parent_quick_item(item: object | None) -> QQuickItem | None:
    if not isinstance(item, QQuickItem):
        return None
    try:
        return item.parentItem()
    except RuntimeError:
        return None


def _ancestor_with_property(
    item: QQuickItem | None,
    property_name: str,
) -> QQuickItem | None:
    current = item
    while current is not None:
        if _has_qt_property(current, property_name):
            return current
        current = _parent_quick_item(current)
    return None


def _deepest_quick_item(root: QQuickItem, point: QPointF) -> QQuickItem:
    """Walk QQuickItem.childAt so Guide clicks can identify their row delegate."""

    current = root
    local = QPointF(point)
    for _ in range(32):
        try:
            child = current.childAt(local.x(), local.y())
        except RuntimeError:
            break
        if child is None:
            break
        try:
            local = child.mapFromItem(current, local)
        except (RuntimeError, TypeError):
            break
        current = child
    return current


def install_interaction_support(broadcaster_qt_module: Any) -> None:
    """Restore Alpha-style focus feedback and complete mouse navigation gaps.

    The current Broadcaster shell overlays an extra Home card directly over the
    original Main.qml Channels card. The original card already owns the couch
    selection state and mouse activation, so the duplicate masks the Alpha
    selection highlight. This patch keeps Broadcaster visible only on its own
    screen and lets Main.qml remain authoritative on Home.

    The Guide is the other holdout: it intentionally remained couch-driven and
    has no MouseArea on schedule cells. The patched key filter maps clicks back
    into the existing selectedRow/selectedProgram state, preserving one shared
    selection model for controller, keyboard, and mouse.
    """

    base_filter = broadcaster_qt_module.BroadcasterKeyFilter
    if getattr(base_filter, "_channelos_interaction_support", False):
        return

    class InteractiveBroadcasterKeyFilter(base_filter):
        _channelos_interaction_support = True

        def __init__(self, controller: Any, window: Any) -> None:
            super().__init__(controller, window)
            self._focus_highlight_item: object | None = None
            self._focus_highlight_original = False
            screen_changed = getattr(window, "screenChanged", None)
            if screen_changed is not None:
                try:
                    screen_changed.connect(self._sync_management_visibility)
                except (AttributeError, RuntimeError):
                    pass

        def bind_management_overlays(self, **kwargs: Any) -> None:
            super().bind_management_overlays(**kwargs)
            self._sync_management_visibility()

        def _sync_management_visibility(self) -> None:
            """Do not let Broadcaster's legacy Home card cover Main.qml."""

            item = getattr(self, "_broadcaster_item", None)
            if item is None:
                return
            try:
                item.setVisible(
                    str(self._window.property("screen")) == "broadcaster"
                )
            except RuntimeError:
                return

        def _focus_button_owner(self) -> object | None:
            try:
                current: object | None = QGuiApplication.focusObject()
            except RuntimeError:
                return None

            for _ in range(12):
                if current is None:
                    return None
                if _has_qt_property(current, "highlighted"):
                    return current
                try:
                    current = current.parent()  # type: ignore[attr-defined]
                except (AttributeError, RuntimeError):
                    return None
            return None

        def _sync_focus_highlight(self) -> None:
            """Make focused Qt Quick buttons use the same strong blue cue."""

            current = self._focus_button_owner()
            previous = self._focus_highlight_item
            if current is previous:
                return

            if previous is not None:
                try:
                    previous.setProperty(  # type: ignore[attr-defined]
                        "highlighted",
                        bool(self._focus_highlight_original),
                    )
                except (AttributeError, RuntimeError):
                    pass

            self._focus_highlight_item = current
            self._focus_highlight_original = False
            if current is None:
                return

            try:
                original = bool(current.property("highlighted"))  # type: ignore[attr-defined]
                self._focus_highlight_original = original
                if bool(current.property("enabled")):  # type: ignore[attr-defined]
                    current.setProperty("highlighted", True)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                self._focus_highlight_item = None
                self._focus_highlight_original = False

        def _guide_click_selection(self, watched: object, event: Any) -> bool:
            if watched is not self._window:
                return False
            if str(self._window.property("screen")) != "guide":
                return False
            if event.button() != Qt.MouseButton.LeftButton:
                return False

            try:
                content_item = self._window.contentItem()
                position = QPointF(event.position())
            except (AttributeError, RuntimeError, TypeError):
                return False

            hit_item = _deepest_quick_item(content_item, position)
            row_item = _ancestor_with_property(hit_item, "rowData")
            if row_item is None:
                return False

            try:
                row_data = _variant_mapping(row_item.property("rowData"))
            except RuntimeError:
                return False
            if not row_data:
                return False

            rows = self._rows()
            row_index = _row_index_for_channel(
                rows,
                int(row_data.get("channelNumber", -1) or -1),
            )
            if row_index is None:
                return False

            self._window.setProperty("selectedRow", row_index)
            program_index = self._current_program_index(row_index)

            # Main.qml keeps the first 255 px for the channel cell. Everything
            # to its right projects the Guide horizon linearly across the row.
            channel_column_width = 255.0
            click_x = float(position.x())
            if click_x > channel_column_width:
                horizon_start = float(
                    self._window.property("horizonStartMs") or 0.0
                )
                horizon_end = float(
                    self._window.property("horizonEndMs") or horizon_start
                )
                span = max(1.0, horizon_end - horizon_start)
                program_width = max(
                    1.0,
                    float(self._window.width()) - channel_column_width,
                )
                ratio = max(
                    0.0,
                    min(1.0, (click_x - channel_column_width) / program_width),
                )
                row = _variant_mapping(rows[row_index])
                programs = row.get("programs", [])
                if isinstance(programs, Sequence) and not isinstance(
                    programs, (str, bytes, bytearray)
                ):
                    clicked_index = _program_index_at_time(
                        programs,
                        horizon_start + ratio * span,
                    )
                    if clicked_index is not None:
                        program_index = clicked_index

            if program_index >= 0:
                self._window.setProperty("selectedProgram", program_index)

            if event.type() == QEvent.Type.MouseButtonDblClick:
                return bool(
                    self.dispatch_command(
                        ControlCommand(ControlIntent.SELECT)
                    )
                )

            # Keep the single-click event available to the ListView so mouse
            # dragging/scrolling remains native. Selection has already updated.
            return False

        def _video_surface_click(self, watched: object, event: Any) -> bool:
            video_window = getattr(
                self._window,
                "_channelos_video_window",
                None,
            )
            if watched is not video_window:
                return False
            if event.type() != QEvent.Type.MouseButtonRelease:
                return False
            if event.button() != Qt.MouseButton.LeftButton:
                return False

            screen = str(self._window.property("screen"))
            if screen == "home":
                self.activateHomeMenu(0)
                return True
            if screen == "guide":
                return bool(
                    self.dispatch_command(
                        ControlCommand(ControlIntent.SELECT)
                    )
                )
            if screen in {"live", "ondemand"}:
                return bool(
                    self.dispatch_command(
                        ControlCommand(ControlIntent.PLAY_PAUSE)
                    )
                )
            return False

        def eventFilter(self, watched: object, event: Any) -> bool:
            event_type = event.type()

            if event_type in {
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
            }:
                if self._guide_click_selection(watched, event):
                    QTimer.singleShot(0, self._sync_focus_highlight)
                    return True

            if event_type == QEvent.Type.MouseButtonRelease:
                if self._video_surface_click(watched, event):
                    QTimer.singleShot(0, self._sync_focus_highlight)
                    return True

            handled = super().eventFilter(watched, event)

            if event_type in {
                QEvent.Type.FocusIn,
                QEvent.Type.FocusOut,
                QEvent.Type.KeyPress,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
            }:
                QTimer.singleShot(0, self._sync_focus_highlight)

            return handled

    broadcaster_qt_module.BroadcasterKeyFilter = InteractiveBroadcasterKeyFilter
    logger.info(
        "Installed unified mouse navigation and Alpha-style focus support"
    )
