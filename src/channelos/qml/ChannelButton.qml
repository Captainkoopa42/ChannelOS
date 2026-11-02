import QtQuick
import QtQuick.Controls

Button {
    id: channelButton

    property bool destructive: false

    implicitWidth: Math.max(72, buttonLabel.implicitWidth + 28)
    implicitHeight: 38
    leftPadding: 14
    rightPadding: 14
    topPadding: 8
    bottomPadding: 8
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    contentItem: Text {
        id: buttonLabel
        text: channelButton.text
        color: !channelButton.enabled
               ? "#607489"
               : channelButton.destructive
               ? "#ff6666"
               : channelButton.activeFocus
                 || channelButton.highlighted
                 || channelButton.checked
               ? "#ffffff" : "#f4f7fb"
        font.pixelSize: 12
        font.weight: channelButton.activeFocus
                     || channelButton.highlighted
                     || channelButton.checked
                     ? Font.DemiBold : Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 7
        color: !channelButton.enabled
               ? "#091522"
               : channelButton.down
               ? (channelButton.destructive ? "#54212a" : "#0a66ad")
               : channelButton.destructive
               ? (channelButton.hovered ? "#351b24" : "#21151c")
               : channelButton.highlighted
               ? (channelButton.hovered ? "#42adff" : "#1a91ff")
               : channelButton.checked
               ? (channelButton.hovered ? "#176aa6" : "#12527f")
               : channelButton.activeFocus
               ? (channelButton.hovered ? "#1a4d82" : "#12396a")
               : channelButton.hovered
               ? "#143a5c" : "#0d2035"
        border.color: !channelButton.enabled
                      ? "#14283b"
                      : channelButton.destructive
                      ? "#ff6666"
                      : channelButton.activeFocus
                        || channelButton.highlighted
                        || channelButton.checked
                      ? "#42adff" : "#1a3550"
        border.width: channelButton.activeFocus
                      || channelButton.highlighted
                      || channelButton.checked ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }
}
