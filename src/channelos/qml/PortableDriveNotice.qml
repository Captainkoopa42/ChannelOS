import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

FocusScope {
    id: notice
    property var hostWindow: null
    anchors.fill: parent
    property var setup: channelOS && typeof channelOS.portableSetup !== "undefined" ? channelOS.portableSetup : ({})
    property string feedback: ""
    visible: Boolean(setup.active) && setup.available === false
    onVisibleChanged: if (visible) openButton.forceActiveFocus()
    function handleControllerIntent(intent) {
        if (intent === "LEFT" || intent === "RIGHT" || intent === "UP" || intent === "DOWN") {
            var focus = notice.Window.window.activeFocusItem
            if (focus) focus.nextItemInFocusChain(intent === "RIGHT" || intent === "DOWN").forceActiveFocus()
        } else if (intent === "SELECT") {
            var button = notice.Window.window.activeFocusItem
            if (button && typeof button.clicked === "function") button.clicked()
        }
    }
    Rectangle { anchors.fill: parent; color: "#ed050c15" }
    MouseArea { anchors.fill: parent }
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(650, parent.width - 80)
        spacing: 18
        Label { text: "Reconnect your portable drive"; color: "#f4f7fb"; font.pixelSize: 26; font.bold: true }
        Label {
            Layout.fillWidth: true
            text: notice.feedback || String(notice.setup.message || "Playback is stopped while the drive is unavailable.")
            color: "#b7c5d5"; wrapMode: Text.Wrap
        }
        RowLayout {
            ChannelButton { text: "Check Drive"; onClicked: { notice.feedback = ""; channelOS.checkPortableDrive() } }
            ChannelButton {
                id: openButton; text: "Open Another Setup…"
                onClicked: {
                    var result = channelOS.chooseExistingPortableSetup()
                    if (result && result.message) notice.feedback = result.message
                }
            }
            ChannelButton { text: "Exit"; onClicked: Qt.quit() }
        }
    }
}
