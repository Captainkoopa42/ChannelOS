from pathlib import Path

import channelos


def test_channel_studio_exposes_calendar_drag_drop_and_safe_apply() -> None:
    qml = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "ChannelStudioScreen.qml"
    ).read_text(encoding="utf-8")

    assert 'property string viewMode: "week"' in qml
    assert 'text: "Week"' in qml
    assert 'text: "Month"' in qml
    assert 'text: "Day"' in qml
    assert 'text: "FULL DAY EDITOR"' in qml
    assert '"Show Media Bin"' in qml
    assert 'text: "Midday"' in qml
    assert 'text: "Evening"' in qml
    assert "function openDay(" in qml
    assert "function addAssetAtMinute(" in qml
    assert "function moveBlockToMinute(" in qml
    assert "function placementConflict(" in qml
    assert "minuteForTrackPosition" in qml
    assert "studioRoot.openDay(monthDay.cellDate)" in qml
    assert "studioRoot.openDay(weekDay.columnDate)" in qml
    assert 'text: "Auto Fill Range"' in qml
    assert 'text: "Apply to Channel"' in qml
    assert "DropArea" in qml
    assert 'Drag.keys: ["channelos-media"]' in qml
    assert 'Drag.keys: ["channelos-block"]' in qml
    assert 'text: "15-minute snap • drag a block to reschedule • conflicts are refused without changing the draft"' in qml
    assert 'text: "−15 min"' in qml
    assert 'text: "+15 min"' in qml
    assert 'placeholderText: "HH:MM"' in qml
    assert 'text: "FILLER SOURCES  •  "' in qml
    assert "channelOS.startStudioAutoFill" in qml
    assert "channelOS.cancelStudioAutoFill" in qml
    assert "onStudioAutoFillCompleted" in qml
    assert '"Cancel Auto Fill"' in qml
    assert "ProgressBar" in qml
    assert 'text: "Groups & Show Filler"' in qml
    assert "channelOS.createStudioGroup" in qml
    assert "channelOS.deleteStudioGroup" in qml
    assert "fillerAssetIdsJson" in qml
    assert 'text: "Use After Selected Show"' in qml
    assert 'text: "Copy / Repeat Week"' in qml
    assert 'title: "Copy or Repeat This Week"' in qml
    assert 'model: ["Require Empty Target Weeks", "Replace Target Weeks"]' in qml
    assert "function copyWeekPattern(" in qml
    assert "copyBlockToWeek" in qml
    assert "calendarBlockCount" in qml
    assert "channelOS.updateChannel" in qml
    assert "channelOS.createChannel" in qml
    assert "Live television is unchanged until Apply" in qml
    assert 'function leaveStudio()' in qml
    assert 'requestExit("home")' in qml
    assert 'function openBroadcaster()' in qml
    assert 'requestExit("broadcaster")' in qml
    assert "hostWindow.screen = destination" in qml
    assert 'text: "‹ Home"' in qml
    assert 'text: "Channels"' in qml
    assert "enabled: studioSurface.visible" in qml
    assert "enabled: parent.visible" not in qml
    assert 'title: "Discard unapplied Channel Studio changes?"' in qml
    assert "function rebuildBlockIndex()" in qml
    assert "calendarBlocks.clear()" in qml


def test_broadcaster_keeps_classic_editor_and_routes_to_studio() -> None:
    qml = (
        Path(channelos.__file__).resolve().parent
        / "qml"
        / "BroadcasterScreen.qml"
    ).read_text(encoding="utf-8")

    assert 'text: "New in Studio"' in qml
    assert 'text: "Open Studio"' in qml
    assert 'text: "Classic New"' in qml
    assert ': "Classic Edit"' in qml
    assert 'String(channel.mode) === "calendar"' in qml
    assert 'broadcasterRoot.hostWindow.screen = "studio"' in qml
