import QtQuick
import QtQuick.Controls

SpinBox {
    id: channelSpin

    implicitHeight: 38
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    palette.window: "#111f2c"
    palette.windowText: "#f4f7fb"
    palette.base: "#111f2c"
    palette.text: "#f4f7fb"
    palette.button: "#162a3a"
    palette.buttonText: "#f4f7fb"
    palette.highlight: "#1a91ff"
    palette.highlightedText: "#ffffff"
    palette.mid: "#294158"

    contentItem: TextInput {
        z: 2
        text: channelSpin.textFromValue(channelSpin.value, channelSpin.locale)
        color: channelSpin.enabled ? "#f4f7fb" : "#607489"
        selectionColor: "#1a91ff"
        selectedTextColor: "#ffffff"
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
               ? "#0a66ad"
               : channelSpin.up.hovered
               ? "#1a3b52" : "#162a3a"
        border.color: channelSpin.activeFocus ? "#42adff" : "#294158"

        Text {
            anchors.centerIn: parent
            text: "+"
            color: channelSpin.enabled ? "#f4f7fb" : "#607489"
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
               ? "#0a66ad"
               : channelSpin.down.hovered
               ? "#1a3b52" : "#162a3a"
        border.color: channelSpin.activeFocus ? "#42adff" : "#294158"

        Text {
            anchors.centerIn: parent
            text: "−"
            color: channelSpin.enabled ? "#f4f7fb" : "#607489"
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }

    background: Rectangle {
        radius: 6
        color: !channelSpin.enabled
               ? "#091522"
               : channelSpin.activeFocus
               ? "#12396a"
               : channelSpin.hovered
               ? "#142634" : "#111f2c"
        border.color: !channelSpin.enabled
                      ? "#14283b"
                      : channelSpin.activeFocus
                      ? "#42adff" : "#294158"
        border.width: channelSpin.activeFocus ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }
}
