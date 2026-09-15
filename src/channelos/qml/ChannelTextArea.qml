import QtQuick
import QtQuick.Controls

TextArea {
    id: channelArea

    leftPadding: 12
    rightPadding: 12
    topPadding: 10
    bottomPadding: 10
    color: enabled ? "#f4f7fb" : "#607489"
    placeholderTextColor: "#7f93a8"
    selectionColor: "#1a91ff"
    selectedTextColor: "#ffffff"
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    background: Rectangle {
        radius: 6
        color: !channelArea.enabled
               ? "#091522"
               : channelArea.activeFocus
               ? "#12396a"
               : channelArea.hovered
               ? "#142634" : "#111f2c"
        border.color: !channelArea.enabled
                      ? "#14283b"
                      : channelArea.activeFocus
                      ? "#42adff" : "#294158"
        border.width: channelArea.activeFocus ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }
}
