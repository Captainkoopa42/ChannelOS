import QtQuick
import QtQuick.Controls

ProgressBar {
    id: channelProgress

    property real sweepPosition: 0

    implicitHeight: 12

    background: Rectangle {
        radius: height / 2
        color: "#111f2c"
        border.color: "#294158"
        border.width: 1
    }

    contentItem: Item {
        clip: true

        Rectangle {
            width: channelProgress.visualPosition * parent.width
            height: parent.height
            visible: !channelProgress.indeterminate
            radius: height / 2
            color: "#1a91ff"
        }

        Rectangle {
            width: Math.max(28, parent.width * 0.24)
            height: parent.height
            x: (parent.width + width) * channelProgress.sweepPosition - width
            visible: channelProgress.indeterminate
            radius: height / 2
            color: "#42adff"
        }
    }

    NumberAnimation on sweepPosition {
        from: 0
        to: 1
        duration: 900
        loops: Animation.Infinite
        running: channelProgress.indeterminate
    }
}
