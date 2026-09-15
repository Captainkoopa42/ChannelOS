from pathlib import Path

import pytest

import channelos


QML_ROOT = Path(channelos.__file__).resolve().parent / "qml"


def test_shared_channel_button_covers_interaction_and_semantic_states() -> None:
    qml = (QML_ROOT / "ChannelButton.qml").read_text(encoding="utf-8")

    assert "property bool destructive: false" in qml
    assert "focusPolicy: Qt.StrongFocus" in qml
    assert "hoverEnabled: true" in qml
    assert "channelButton.down" in qml
    assert "channelButton.hovered" in qml
    assert "channelButton.activeFocus" in qml
    assert "channelButton.highlighted" in qml
    assert "channelButton.checked" in qml
    assert '"#12396a"' in qml
    assert '"#42adff"' in qml
    assert '"#ff6666"' in qml
    assert "Behavior on color" in qml
    assert "Behavior on border.color" in qml


@pytest.mark.parametrize(
    ("filename", "expected_count"),
    [
        ("BroadcasterScreen.qml", 14),
        ("LibraryManagerScreen.qml", 9),
        ("LibraryScreen.qml", 4),
    ],
)
def test_application_surfaces_use_shared_channel_buttons(
    filename: str,
    expected_count: int,
) -> None:
    qml = (QML_ROOT / filename).read_text(encoding="utf-8")

    assert qml.count("ChannelButton {") == expected_count
    assert "\n                    Button {" not in qml
    assert "\n            Button {" not in qml
    assert "\n        Button {" not in qml


def test_destructive_actions_use_the_warning_button_state() -> None:
    broadcaster = (QML_ROOT / "BroadcasterScreen.qml").read_text(encoding="utf-8")
    manager = (QML_ROOT / "LibraryManagerScreen.qml").read_text(encoding="utf-8")

    assert broadcaster.count("destructive: true") == 4
    assert manager.count("destructive: true") == 2
    assert "palette.buttonText: broadcasterRoot.danger" not in broadcaster
