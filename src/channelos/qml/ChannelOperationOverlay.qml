import QtQuick
import QtQuick.Layouts

Rectangle {
    id: operationOverlay
    anchors.fill: parent
    property var hostWindow: null
    property var operation: channelOS && typeof channelOS.channelMutation !== "undefined"
                            ? channelOS.channelMutation : ({active: false})
    visible: Boolean(operation.active)
    color: Theme.c("#bb02070d")
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 64, 520)
        height: 200
        radius: 12
        color: Theme.c("#0d2035")
        border.color: Theme.c("#1a91ff")
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14
            Text { text: "UPDATING CHANNEL"; color: Theme.c("#f4f7fb"); font.pixelSize: 20; font.bold: true }
            Text {
                Layout.fillWidth: true
                text: String(operationOverlay.operation.message || "Preparing channel changes…")
                color: Theme.c("#9fb0c2"); font.pixelSize: 15; wrapMode: Text.Wrap
            }
            ChannelButton {
                text: operationOverlay.operation.cancellable ? "Cancel" : "Finishing…"
                enabled: Boolean(operationOverlay.operation.cancellable)
                onClicked: channelOS.cancelChannelMutation()
            }
        }
    }
}
