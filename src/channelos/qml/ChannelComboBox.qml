import QtQuick
import QtQuick.Controls

ComboBox {
    id: channelCombo

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 34
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true

    palette.window: Theme.c("#111f2c")
    palette.windowText: Theme.c("#f4f7fb")
    palette.base: Theme.c("#111f2c")
    palette.alternateBase: Theme.c("#162a3a")
    palette.text: Theme.c("#f4f7fb")
    palette.button: Theme.c("#111f2c")
    palette.buttonText: Theme.c("#f4f7fb")
    palette.highlight: Theme.c("#1a91ff")
    palette.highlightedText: Theme.c("#ffffff")
    palette.placeholderText: Theme.c("#7f93a8")
    palette.mid: Theme.c("#294158")

    contentItem: Text {
        leftPadding: 0
        rightPadding: channelCombo.indicator.width + channelCombo.spacing
        text: channelCombo.displayText
        color: channelCombo.enabled ? Theme.c("#f4f7fb") : Theme.c("#607489")
        font: channelCombo.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: channelCombo.width - width - 12
        y: Math.round((channelCombo.height - height) / 2)
        text: "▾"
        color: channelCombo.enabled
               ? (channelCombo.activeFocus ? Theme.c("#42adff") : Theme.c("#9fb0c2"))
               : Theme.c("#607489")
        font.pixelSize: 16
        font.weight: Font.DemiBold
    }

    background: Rectangle {
        radius: 6
        color: !channelCombo.enabled
               ? Theme.c("#091522")
               : channelCombo.down
               ? Theme.c("#172e40")
               : channelCombo.activeFocus
               ? Theme.c("#12396a")
               : channelCombo.hovered
               ? Theme.c("#142634") : Theme.c("#111f2c")
        border.color: !channelCombo.enabled
                      ? Theme.c("#14283b")
                      : channelCombo.activeFocus
                      ? Theme.c("#42adff") : Theme.c("#294158")
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
            text: {
                var value = typeof modelData === "undefined" ? undefined : modelData
                if (channelCombo.textRole) {
                    value = value && value[channelCombo.textRole] !== undefined
                            ? value[channelCombo.textRole]
                            : (typeof model !== "undefined" ? model[channelCombo.textRole] : undefined)
                }
                return value === undefined || value === null ? "" : String(value)
            }
            color: highlighted ? Theme.c("#ffffff") : Theme.c("#f4f7fb")
            font: channelCombo.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: 4
            color: highlighted ? Theme.c("#1a91ff") : "transparent"
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
            color: Theme.c("#0d1b28")
            border.color: Theme.c("#294158")
            border.width: 1
        }
    }
}
