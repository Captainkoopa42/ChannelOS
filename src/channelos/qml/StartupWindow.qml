import QtQuick
import QtQuick.Window

// The first window ChannelOS shows: the boot video (when set) plays while the
// setup opens behind it, then the chosen loading style takes over.
Window {
    id: startupWindow
    width: 1100; height: 650
    title: "ChannelOS"
    color: Theme.c("#050c15")
    visible: true
    readonly property var boot: startupControl ? startupControl.boot : ({})
    readonly property bool videoPlaying: startupControl ? startupControl.videoPlaying : false

    onClosing: function(close) {
        if (startupControl && !startupControl.canClose) {
            close.accepted = false
            startupControl.closeRequested()
        }
    }

    Binding {
        target: Theme
        property: "spec"
        value: startupControl && startupControl.themeSpec ? startupControl.themeSpec : ({})
    }
    Binding {
        target: Theme
        property: "name"
        value: startupControl && startupControl.themeSpec && startupControl.themeSpec.name
               ? String(startupControl.themeSpec.name) : "channelos"
    }

    BootScreen {
        anchors.fill: parent
        loadingStyle: String(startupWindow.boot.loadingStyle || "classic")
        showStatic: String(startupWindow.boot.video || "static") === "static"
                    || (startupWindow.boot.video === "custom" && !startupWindow.videoPlaying)
        reducedMotion: Boolean(startupWindow.boot.reducedMotion)
        progress: startupControl ? startupControl.progress : 0
        message: startupControl ? startupControl.message : ""
        running: !startupWindow.videoPlaying
    }

    // The custom boot video renders into this native child window.
    WindowContainer {
        anchors.fill: parent
        visible: startupWindow.videoPlaying
        window: typeof bootVideoWindow !== "undefined" ? bootVideoWindow : null
    }

    // Any key or click skips the boot video.
    Item {
        anchors.fill: parent
        focus: true
        Component.onCompleted: forceActiveFocus()
        Keys.onPressed: function(event) {
            if (startupWindow.videoPlaying && startupControl) {
                startupControl.skipBootVideo()
                event.accepted = true
            }
        }
        MouseArea {
            anchors.fill: parent
            onClicked: if (startupWindow.videoPlaying && startupControl) startupControl.skipBootVideo()
        }
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 48
        visible: startupControl && startupControl.canClose
        ChannelButton {
            text: "Close"
            onClicked: Qt.quit()
        }
    }
}
