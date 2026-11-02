from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from channelos.interaction import (
    _program_index_at_time,
    _row_index_for_channel,
    install_interaction_support,
)


def test_program_index_at_time_uses_exact_schedule_occurrence() -> None:
    programs = [
        {"startMs": 1000, "endMs": 2000},
        {"startMs": 2000, "endMs": 3500},
    ]

    assert _program_index_at_time(programs, 1000) == 0
    assert _program_index_at_time(programs, 1999) == 0
    assert _program_index_at_time(programs, 2000) == 1
    assert _program_index_at_time(programs, 3499) == 1
    assert _program_index_at_time(programs, 3500) is None


def test_row_index_for_channel_matches_guide_row() -> None:
    rows = [
        {"channelNumber": 7},
        {"channelNumber": 21},
    ]

    assert _row_index_for_channel(rows, 21) == 1
    assert _row_index_for_channel(rows, 99) is None


def test_interaction_patch_hides_duplicate_broadcaster_home_layer() -> None:
    class FakeWindow:
        screenChanged = None

        def __init__(self) -> None:
            self.screen = "home"

        def property(self, name: str):
            assert name == "screen"
            return self.screen

    class FakeItem:
        def __init__(self) -> None:
            self.visible = True

        def setVisible(self, visible: bool) -> None:
            self.visible = visible

    class FakeBaseFilter:
        def __init__(self, controller, window) -> None:
            self._controller = controller
            self._window = window
            self._library_item = None
            self._broadcaster_item = None
            self._studio_item = None

        def bind_management_overlays(self, **kwargs) -> None:
            self._library_item = kwargs.get("library_item")
            self._broadcaster_item = kwargs.get("broadcaster_item")
            self._studio_item = kwargs.get("studio_item")

        def eventFilter(self, watched, event) -> bool:
            return False

    class FakeModule:
        BroadcasterKeyFilter = FakeBaseFilter

    install_interaction_support(FakeModule)
    patched = FakeModule.BroadcasterKeyFilter(None, FakeWindow())
    broadcaster = FakeItem()
    patched.bind_management_overlays(
        library_item=FakeItem(),
        broadcaster_item=broadcaster,
        studio_item=FakeItem(),
    )

    assert broadcaster.visible is False

    patched._window.screen = "broadcaster"
    patched._sync_management_visibility()
    assert broadcaster.visible is True


def test_screen_transition_sync_is_deferred_until_after_qml_input() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "channelos" / "interaction.py"
    text = source.read_text(encoding="utf-8")

    assert "def _defer_ui_sync(self) -> None:" in text
    assert "QTimer.singleShot(0, self._sync_management_visibility)" in text
    assert "QTimer.singleShot(0, self._sync_focus_highlight)" in text
    assert text.count("self._defer_ui_sync()") >= 3


def test_interaction_patch_is_idempotent() -> None:
    class FakeBaseFilter:
        def __init__(self, controller, window) -> None:
            self._controller = controller
            self._window = window

        def eventFilter(self, watched, event) -> bool:
            return False

    class FakeModule:
        BroadcasterKeyFilter = FakeBaseFilter

    install_interaction_support(FakeModule)
    first = FakeModule.BroadcasterKeyFilter
    install_interaction_support(FakeModule)

    assert FakeModule.BroadcasterKeyFilter is first
