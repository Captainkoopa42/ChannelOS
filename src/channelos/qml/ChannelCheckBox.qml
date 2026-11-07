import QtQuick
import QtQuick.Controls

CheckBox {
    id: channelCheck

    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    palette.windowText: enabled ? Theme.c("#f4f7fb") : Theme.c("#607489")
    palette.highlight: Theme.c("#1a91ff")

    indicator: Rectangle {
        implicitWidth: 21
        implicitHeight: 21
        x: channelCheck.leftPadding
        y: Math.round((channelCheck.height - height) / 2)
        radius: 4
        color: !channelCheck.enabled
               ? Theme.c("#091522")
               : channelCheck.activeFocus
               ? Theme.c("#12396a")
               : channelCheck.checked
               ? Theme.c("#12527f")
               : channelCheck.hovered
               ? Theme.c("#142634") : Theme.c("#111f2c")
        border.color: !channelCheck.enabled
                      ? Theme.c("#14283b")
                      : channelCheck.activeFocus || channelCheck.checked
                      ? Theme.c("#42adff") : Theme.c("#294158")
        border.width: channelCheck.activeFocus || channelCheck.checked ? 2 : 1

        Text {
            anchors.centerIn: parent
            visible: channelCheck.checked
            text: "✓"
            color: Theme.c("#fffffe")
            font.pixelSize: 14
            font.weight: Font.Bold
        }
    }
}
