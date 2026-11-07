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
               ? Theme.c("#607489")
               : channelButton.destructive
               ? Theme.c("#ff6666")
               : channelButton.highlighted
               ? Theme.c("#ffffff")
               : channelButton.activeFocus || channelButton.checked
               ? Theme.c("#fffffe") : Theme.c("#f4f7fb")
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
               ? Theme.c("#091522")
               : channelButton.down
               ? (channelButton.destructive ? Theme.c("#54212a") : Theme.c("#0a66ad"))
               : channelButton.destructive
               ? (channelButton.hovered ? Theme.c("#351b24") : Theme.c("#21151c"))
               : channelButton.highlighted
               ? (channelButton.hovered ? Theme.c("#42adff") : Theme.c("#1a91ff"))
               : channelButton.checked
               ? (channelButton.hovered ? Theme.c("#176aa6") : Theme.c("#12527f"))
               : channelButton.activeFocus
               ? (channelButton.hovered ? Theme.c("#1a4d82") : Theme.c("#12396a"))
               : channelButton.hovered
               ? Theme.c("#143a5c") : Theme.c("#0d2035")
        border.color: !channelButton.enabled
                      ? Theme.c("#14283b")
                      : channelButton.destructive
                      ? Theme.c("#ff6666")
                      : channelButton.activeFocus
                        || channelButton.highlighted
                        || channelButton.checked
                      ? Theme.c("#42adff") : Theme.c("#1a3550")
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
