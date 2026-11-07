import QtQuick
import QtQuick.Window

Window {
    width: 1100; height: 650
    title: "ChannelOS"
    color: Theme.c("#050c15")
    visible: true
    onClosing: function(close) {
        if (startupControl && !startupControl.canClose) {
            close.accepted = false
            startupControl.closeRequested()
        }
    }
    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 620)
        spacing: 22
        Text { text: "CHANNEL OS"; color: Theme.c("#f4f7fb"); font.pixelSize: 36; font.bold: true }
        Text { width: parent.width; text: startupControl ? startupControl.message : ""; color: Theme.c("#9fb0c2"); font.pixelSize: 18; wrapMode: Text.Wrap }
        ChannelButton { text: startupControl && startupControl.canClose ? "Close" : "Cancel"; onClicked: { if (!startupControl) return; if (startupControl.canClose) Qt.quit(); else startupControl.closeRequested() } }
    }
}
