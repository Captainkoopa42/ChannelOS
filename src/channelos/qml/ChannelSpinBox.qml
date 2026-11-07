import QtQuick
import QtQuick.Controls

SpinBox {
    id: channelSpin

    implicitHeight: 38
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    palette.window: Theme.c("#111f2c")
    palette.windowText: Theme.c("#f4f7fb")
    palette.base: Theme.c("#111f2c")
    palette.text: Theme.c("#f4f7fb")
    palette.button: Theme.c("#162a3a")
    palette.buttonText: Theme.c("#f4f7fb")
    palette.highlight: Theme.c("#1a91ff")
    palette.highlightedText: Theme.c("#ffffff")
    palette.mid: Theme.c("#294158")

    contentItem: TextInput {
        z: 2
        text: channelSpin.textFromValue(channelSpin.value, channelSpin.locale)
        color: channelSpin.enabled ? Theme.c("#f4f7fb") : Theme.c("#607489")
        selectionColor: Theme.c("#1a91ff")
        selectedTextColor: Theme.c("#ffffff")
        font: channelSpin.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        leftPadding: 12
        rightPadding: 38
        readOnly: !channelSpin.editable
        validator: channelSpin.validator
        inputMethodHints: Qt.ImhFormattedNumbersOnly
    }

    up.indicator: Rectangle {
        x: channelSpin.width - width
        y: 0
        implicitWidth: 30
        implicitHeight: channelSpin.height / 2
        color: channelSpin.up.pressed
               ? Theme.c("#0a66ad")
               : channelSpin.up.hovered
               ? Theme.c("#1a3b52") : Theme.c("#162a3a")
        border.color: channelSpin.activeFocus ? Theme.c("#42adff") : Theme.c("#294158")

        Text {
            anchors.centerIn: parent
            text: "+"
            color: channelSpin.enabled ? Theme.c("#f4f7fb") : Theme.c("#607489")
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }

    down.indicator: Rectangle {
        x: channelSpin.width - width
        y: channelSpin.height - height
        implicitWidth: 30
        implicitHeight: channelSpin.height / 2
        color: channelSpin.down.pressed
               ? Theme.c("#0a66ad")
               : channelSpin.down.hovered
               ? Theme.c("#1a3b52") : Theme.c("#162a3a")
        border.color: channelSpin.activeFocus ? Theme.c("#42adff") : Theme.c("#294158")

        Text {
            anchors.centerIn: parent
            text: "−"
            color: channelSpin.enabled ? Theme.c("#f4f7fb") : Theme.c("#607489")
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }

    background: Rectangle {
        radius: 6
        color: !channelSpin.enabled
               ? Theme.c("#091522")
               : channelSpin.activeFocus
               ? Theme.c("#12396a")
               : channelSpin.hovered
               ? Theme.c("#142634") : Theme.c("#111f2c")
        border.color: !channelSpin.enabled
                      ? Theme.c("#14283b")
                      : channelSpin.activeFocus
                      ? Theme.c("#42adff") : Theme.c("#294158")
        border.width: channelSpin.activeFocus ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }
}
