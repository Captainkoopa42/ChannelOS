import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: portableDialog
    title: "Portable Setup"
    modal: true
    padding: 20
    width: Math.min(850, parent ? parent.width - 48 : 850)
    height: Math.min(760, parent ? parent.height - 48 : 760)
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    property var setup: channelOS && typeof channelOS.portableSetup !== "undefined" ? channelOS.portableSetup : ({})
    property var copyState: channelOS && typeof channelOS.portableCopy !== "undefined" ? channelOS.portableCopy : ({active: false})
    property var review: ({})
    property string feedback: ""
    property bool showOperation: false
    onOpened: openExisting.forceActiveFocus()
    header: Label {
        text: "Portable Setup"; color: "#f4f7fb"; font.pixelSize: 22; font.bold: true
        leftPadding: 20; topPadding: 16; bottomPadding: 8
        background: Rectangle { color: "#0d2035"; radius: 10 }
    }
    Connections {
        target: channelOS
        ignoreUnknownSignals: true
        function onPortableSetupChanged() {
            if (portableDialog.setup.active && portableDialog.setup.available === false)
                portableDialog.close()
        }
    }

    function showResult(result) {
        if (result && result.message) feedback = String(result.message)
        showOperation = false
    }
    function reviewCopy() {
        review = channelOS.previewPortableCopy(destination.text, copyMedia.checked, copyApp.checked, copyArtwork.checked)
        showResult(review)
    }
    function handleControllerIntent(intent) {
        if (intent === "BACK" || intent === "HOME") close()
        else if (intent === "UP" || intent === "DOWN") {
            var focus = portableDialog.parent.Window.window.activeFocusItem
            if (focus) focus.nextItemInFocusChain(intent === "DOWN").forceActiveFocus()
        } else if (intent === "SELECT") {
            var control = portableDialog.parent.Window.window.activeFocusItem
            if (control && typeof control.clicked === "function") {
                if (control.checkable) control.checked = !control.checked
                control.clicked()
            }
        }
    }
    background: Rectangle { color: "#0d2035"; border.color: "#294158"; radius: 10 }
    contentItem: Flickable {
        clip: true
        contentWidth: width
        contentHeight: body.implicitHeight + 12
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            id: body
            width: parent.width - 12
            spacing: 12
            Label { text: "CURRENT SETUP  •  " + String(portableDialog.setup.name || "This PC"); color: "#42adff"; font.bold: true }
            Label {
                Layout.fillWidth: true
                text: String(portableDialog.setup.dataDirectory || "")
                wrapMode: Text.WrapAnywhere; color: "#b7c5d5"
            }
            Label {
                Layout.fillWidth: true
                text: portableDialog.setup.active
                      ? "Channels, index, ad settings and history save directly to this drive."
                      : "Copy your setup to a drive, or open an existing setup and save changes there."
                wrapMode: Text.Wrap; color: "#b7c5d5"
            }
            ChannelButton {
                id: openExisting
                text: "Open Existing Setup…"
                enabled: !portableDialog.copyState.active
                onClicked: portableDialog.showResult(channelOS.chooseExistingPortableSetup())
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#294158" }
            Label { text: "COPY TO DRIVE / FOLDER"; color: "#f4f7fb"; font.bold: true }
            Label {
                Layout.fillWidth: true
                text: "Choose a folder containing your media, or choose the drive itself. Existing media there is reused."
                wrapMode: Text.Wrap; color: "#b7c5d5"
            }
            RowLayout {
                Layout.fillWidth: true
                ChannelTextField {
                    id: destination
                    objectName: "portableDestination"
                    Layout.fillWidth: true
                    placeholderText: "Destination drive or folder"
                    enabled: !portableDialog.copyState.active
                    onTextChanged: portableDialog.review = ({})
                }
                ChannelButton {
                    text: "Browse…"
                    enabled: !portableDialog.copyState.active
                    onClicked: {
                        var result = channelOS.choosePortableDestination()
                        if (result && result.ok) destination.text = result.path
                    }
                }
            }
            ChannelCheckBox {
                id: copyMedia
                text: "Copy media outside the destination"
                enabled: !portableDialog.copyState.active
                onCheckedChanged: portableDialog.review = ({})
            }
            ChannelCheckBox {
                id: copyApp
                text: "Include the ChannelOS application"
                checked: Boolean(portableDialog.setup.applicationCopyAvailable)
                enabled: !portableDialog.copyState.active && Boolean(portableDialog.setup.applicationCopyAvailable)
                onCheckedChanged: portableDialog.review = ({})
            }
            ChannelCheckBox {
                id: copyArtwork
                text: "Include generated thumbnails (optional)"
                enabled: !portableDialog.copyState.active
                onCheckedChanged: portableDialog.review = ({})
            }
            RowLayout {
                ChannelButton {
                    text: "Review Copy"
                    objectName: "portableReview"
                    enabled: destination.text.trim().length > 0 && !portableDialog.copyState.active
                    onClicked: portableDialog.reviewCopy()
                }
                ChannelButton {
                    text: "Copy Setup"
                    objectName: "portableStartCopy"
                    enabled: Boolean(portableDialog.review.ok) && !portableDialog.copyState.active
                    onClicked: {
                        var result = channelOS.startPortableCopy(destination.text, copyMedia.checked, copyApp.checked, copyArtwork.checked)
                        portableDialog.showResult(result)
                        portableDialog.showOperation = Boolean(result && result.ok)
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                visible: Boolean(portableDialog.review.ok)
                text: String(portableDialog.review.channelCount || 0) + " channels • "
                      + String(portableDialog.review.indexedFiles || 0) + " indexed videos\n"
                      + String(portableDialog.review.mediaFilesToCopy || 0) + " media files to copy ("
                      + (Number(portableDialog.review.mediaBytesToCopy || 0) / 1073741824).toFixed(2) + " GB)\n"
                      + String(portableDialog.review.offlineFiles || 0) + " unavailable files retained in the index"
                      + "\nApplication: " + (portableDialog.review.applicationIncluded ? "included" : "use a compatible ChannelOS installation")
                color: "#b7c5d5"; wrapMode: Text.Wrap
            }
            Repeater {
                model: portableDialog.review.ok ? portableDialog.review.sources : []
                delegate: Label {
                    required property var modelData
                    Layout.fillWidth: true
                    text: String(modelData.name) + " → " + String(modelData.relativePath || "drive root")
                    color: "#8fa9c2"; wrapMode: Text.WrapAnywhere
                }
            }
            ProgressBar {
                Layout.fillWidth: true
                visible: Boolean(portableDialog.copyState.active)
                from: 0; to: 100; value: Number(portableDialog.copyState.percent || 0)
            }
            Label {
                Layout.fillWidth: true
                text: String(portableDialog.showOperation ? portableDialog.copyState.message : portableDialog.feedback)
                color: portableDialog.copyState.phase === "error" ? "#ff8585" : "#b7c5d5"
                wrapMode: Text.WrapAnywhere
            }
            RowLayout {
                ChannelButton {
                    text: "Cancel Copy"
                    visible: Boolean(portableDialog.copyState.active)
                    onClicked: portableDialog.showResult(channelOS.cancelPortableCopy())
                }
                ChannelButton {
                    text: "Open Copied Setup"
                    visible: portableDialog.copyState.phase === "ready"
                    onClicked: portableDialog.showResult(channelOS.openPortableSetup(portableDialog.copyState.destination, portableDialog.copyState.setupId))
                }
            }
            Label { text: "RECENT SETUPS"; color: "#42adff"; font.bold: true }
            Repeater {
                model: portableDialog.setup.recent || []
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: String(modelData.name || "Setup") + (modelData.available ? "" : " • drive unavailable") + "\n" + modelData.root
                        color: "#b7c5d5"; wrapMode: Text.WrapAnywhere
                    }
                    ChannelButton {
                        text: "Open"
                        enabled: Boolean(modelData.available) && !portableDialog.copyState.active
                        onClicked: portableDialog.showResult(channelOS.openPortableSetup(modelData.root, modelData.setupId))
                    }
                }
            }
            ChannelButton {
                text: portableDialog.copyState.active ? "Keep Copying in Background" : "Close"
                onClicked: portableDialog.close()
            }
        }
    }
}
