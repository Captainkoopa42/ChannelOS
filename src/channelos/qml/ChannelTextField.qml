import QtQuick
import QtQuick.Controls

TextField {
    id: channelField

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 12
    color: enabled ? "#f4f7fb" : "#607489"
    placeholderTextColor: "#7f93a8"
    selectionColor: "#1a91ff"
    selectedTextColor: "#ffffff"
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    background: Rectangle {
        radius: 6
        color: !channelField.enabled
               ? "#091522"
               : channelField.activeFocus
               ? "#12396a"
               : channelField.hovered
               ? "#142634" : "#111f2c"
        border.color: !channelField.enabled
                      ? "#14283b"
                      : channelField.activeFocus
                      ? "#42adff" : "#294158"
        border.width: channelField.activeFocus ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }
}
