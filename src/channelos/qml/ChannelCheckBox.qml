import QtQuick
import QtQuick.Controls

CheckBox {
    id: channelCheck

    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    palette.windowText: enabled ? "#f4f7fb" : "#607489"
    palette.highlight: "#1a91ff"

    indicator: Rectangle {
        implicitWidth: 21
        implicitHeight: 21
        x: channelCheck.leftPadding
        y: Math.round((channelCheck.height - height) / 2)
        radius: 4
        color: !channelCheck.enabled
               ? "#091522"
               : channelCheck.checked
               ? "#12527f"
               : channelCheck.hovered
               ? "#142634" : "#111f2c"
        border.color: !channelCheck.enabled
                      ? "#14283b"
                      : channelCheck.activeFocus || channelCheck.checked
                      ? "#42adff" : "#294158"
        border.width: channelCheck.activeFocus || channelCheck.checked ? 2 : 1

        Text {
            anchors.centerIn: parent
            visible: channelCheck.checked
            text: "✓"
            color: "#ffffff"
            font.pixelSize: 14
            font.weight: Font.Bold
        }
    }
}
