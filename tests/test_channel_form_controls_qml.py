from pathlib import Path

import pytest

import channelos


QML_ROOT = Path(channelos.__file__).resolve().parent / "qml"


@pytest.mark.parametrize(
    ("filename", "required_tokens"),
    [
        (
            "ChannelTextField.qml",
            [
                "TextField {",
                'color: enabled ? "#f4f7fb" : "#607489"',
                'placeholderTextColor: "#7f93a8"',
                'selectionColor: "#1a91ff"',
                "channelField.activeFocus",
                "channelField.hovered",
            ],
        ),
        (
            "ChannelTextArea.qml",
            [
                "TextArea {",
                'placeholderTextColor: "#7f93a8"',
                "channelArea.activeFocus",
                "channelArea.hovered",
            ],
        ),
        (
            "ChannelComboBox.qml",
            [
                "ComboBox {",
                'palette.base: "#111f2c"',
                'palette.highlight: "#1a91ff"',
                "channelCombo.activeFocus",
                "delegate: ItemDelegate",
                "popup: Popup",
            ],
        ),
        (
            "ChannelSpinBox.qml",
            [
                "SpinBox {",
                "contentItem: TextInput",
                "up.indicator: Rectangle",
                "down.indicator: Rectangle",
                "channelSpin.activeFocus",
            ],
        ),
        (
            "ChannelCheckBox.qml",
            [
                "CheckBox {",
                "indicator: Rectangle",
                "channelCheck.checked",
                'text: "✓"',
            ],
        ),
        (
            "ChannelProgressBar.qml",
            [
                "ProgressBar {",
                "channelProgress.visualPosition",
                "channelProgress.indeterminate",
                "NumberAnimation on sweepPosition",
            ],
        ),
    ],
)
def test_shared_form_controls_cover_every_visual_state(
    filename: str,
    required_tokens: list[str],
) -> None:
    qml = (QML_ROOT / filename).read_text(encoding="utf-8")

    assert '"#111f2c"' in qml
    for token in required_tokens:
        assert token in qml


@pytest.mark.parametrize(
    "filename",
    [
        "ChannelTextField.qml",
        "ChannelTextArea.qml",
        "ChannelComboBox.qml",
        "ChannelSpinBox.qml",
        "ChannelCheckBox.qml",
    ],
)
def test_focusable_form_controls_use_alpha_style_filled_focus(filename: str) -> None:
    qml = (QML_ROOT / filename).read_text(encoding="utf-8")

    assert '"#12396a"' in qml
    assert '"#42adff"' in qml


@pytest.mark.parametrize(
    ("filename", "expected_counts"),
    [
        (
            "BroadcasterScreen.qml",
            {
                "ChannelTextField": 2,
                "ChannelTextArea": 1,
                "ChannelComboBox": 2,
                "ChannelSpinBox": 2,
                "ChannelCheckBox": 1,
            },
        ),
        (
            "ChannelStudioScreen.qml",
            {
                "ChannelTextField": 7,
                "ChannelComboBox": 5,
                "ChannelSpinBox": 3,
                "ChannelProgressBar": 1,
            },
        ),
        (
            "LibraryManagerScreen.qml",
            {"ChannelTextField": 1, "ChannelComboBox": 1},
        ),
        (
            "LibraryScreen.qml",
            {"ChannelTextField": 1},
        ),
    ],
)
def test_application_surfaces_use_shared_form_controls(
    filename: str,
    expected_counts: dict[str, int],
) -> None:
    qml = (QML_ROOT / filename).read_text(encoding="utf-8")

    for control, expected in expected_counts.items():
        assert qml.count(f"{control} {{") == expected

    for native_control in (
        "TextField",
        "TextArea",
        "ComboBox",
        "SpinBox",
        "CheckBox",
        "ProgressBar",
    ):
        assert f"\n        {native_control} {{" not in qml
        assert f"\n            {native_control} {{" not in qml
        assert f"\n                {native_control} {{" not in qml
        assert f"\n                    {native_control} {{" not in qml
