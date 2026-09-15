import QtQuick
import QtQuick.Controls

ComboBox {
    id: channelCombo

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 34
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    palette.window: "#111f2c"
    palette.windowText: "#f4f7fb"
    palette.base: "#111f2c"
    palette.alternateBase: "#162a3a"
    palette.text: "#f4f7fb"
    palette.button: "#111f2c"
    palette.buttonText: "#f4f7fb"
    palette.highlight: "#1a91ff"
    palette.highlightedText: "#ffffff"
    palette.placeholderText: "#7f93a8"
    palette.mid: "#294158"

    contentItem: Text {
        leftPadding: 0
        rightPadding: channelCombo.indicator.width + channelCombo.spacing
        text: channelCombo.displayText
        color: channelCombo.enabled ? "#f4f7fb" : "#607489"
        font: channelCombo.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: channelCombo.width - width - 12
        y: Math.round((channelCombo.height - height) / 2)
        text: "▾"
        color: channelCombo.enabled
               ? (channelCombo.activeFocus ? "#42adff" : "#9fb0c2")
               : "#607489"
        font.pixelSize: 16
        font.weight: Font.DemiBold
    }

    background: Rectangle {
        radius: 6
        color: !channelCombo.enabled
               ? "#091522"
               : channelCombo.down
               ? "#172e40"
               : channelCombo.activeFocus
               ? "#13283a"
               : channelCombo.hovered
               ? "#142634" : "#111f2c"
        border.color: !channelCombo.enabled
                      ? "#14283b"
                      : channelCombo.activeFocus
                      ? "#42adff" : "#294158"
        border.width: channelCombo.activeFocus ? 2 : 1

        Behavior on color {
            ColorAnimation { duration: 90 }
        }
        Behavior on border.color {
            ColorAnimation { duration: 90 }
        }
    }

    delegate: ItemDelegate {
        width: channelCombo.width
        highlighted: channelCombo.highlightedIndex === index

        contentItem: Text {
            text: channelCombo.textRole
                  ? (Array.isArray(channelCombo.model)
                     ? modelData[channelCombo.textRole]
                     : model[channelCombo.textRole])
                  : modelData
            color: highlighted ? "#ffffff" : "#f4f7fb"
            font: channelCombo.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: 4
            color: highlighted ? "#1a91ff" : "transparent"
        }
    }

    popup: Popup {
        y: channelCombo.height + 3
        width: channelCombo.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        padding: 4

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: channelCombo.popup.visible
                   ? channelCombo.delegateModel : null
            currentIndex: channelCombo.highlightedIndex
            highlightMoveDuration: 80
            ScrollIndicator.vertical: ScrollIndicator {}
        }

        background: Rectangle {
            radius: 7
            color: "#0d1b28"
            border.color: "#294158"
            border.width: 1
        }
    }
}
