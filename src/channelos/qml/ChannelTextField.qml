import QtQuick
import QtQuick.Controls

TextField {
    id: channelField

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 12
    color: enabled ? Theme.c("#f4f7fb") : Theme.c("#607489")
    placeholderTextColor: Theme.c("#7f93a8")
    selectionColor: Theme.c("#1a91ff")
    selectedTextColor: Theme.c("#ffffff")
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    background: Rectangle {
        radius: 6
        color: !channelField.enabled
               ? Theme.c("#091522")
               : channelField.activeFocus
               ? Theme.c("#12396a")
               : channelField.hovered
               ? Theme.c("#142634") : Theme.c("#111f2c")
        border.color: !channelField.enabled
                      ? Theme.c("#14283b")
                      : channelField.activeFocus
                      ? Theme.c("#42adff") : Theme.c("#294158")
        border.width: channelField.activeFocus ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }
}
