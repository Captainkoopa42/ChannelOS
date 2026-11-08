import QtQuick
import QtQuick.Controls

TextArea {
    id: channelArea

    leftPadding: 12
    rightPadding: 12
    topPadding: 10
    bottomPadding: 10
    color: enabled ? Theme.c("#f4f7fb") : Theme.c("#607489")
    placeholderTextColor: Theme.c("#7f93a8")
    selectionColor: Theme.c("#1a91ff")
    selectedTextColor: Theme.c("#ffffff")
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    background: Rectangle {
        radius: 6
        color: !channelArea.enabled
               ? Theme.c("#091522")
               : channelArea.activeFocus
               ? Theme.c("#12396a")
               : channelArea.hovered
               ? Theme.c("#142634") : Theme.c("#111f2c")
        border.color: !channelArea.enabled
                      ? Theme.c("#14283b")
                      : channelArea.activeFocus
                      ? Theme.c("#42adff") : Theme.c("#294158")
        border.width: channelArea.activeFocus ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }
}
