import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: broadcasterRoot
    anchors.fill: parent
    z: 90

    readonly property color appBackground: "#050c15"
    readonly property color panel: "#081625"
    readonly property color panelRaised: "#0d2035"
    readonly property color panelSoft: "#10283f"
    readonly property color line: "#1a3550"
    readonly property color textPrimary: "#f4f7fb"
    readonly property color textSecondary: "#9fb0c2"
    readonly property color accent: "#1a91ff"
    readonly property color accentBright: "#42adff"
    readonly property color liveGreen: "#2bcf75"
    readonly property color warning: "#ffb84a"
    readonly property color danger: "#ff6666"

    property var hostWindow: null
    property var snapshot: channelOS.broadcasterSnapshot
    property var channels: snapshot.channels || []
    property var sourceOptions: snapshot.sourceOptions || []
    property int selectedChannelIndex: 0
    property string editorMode: "list"
    property int editingChannelNumber: 0
    property string feedbackMessage: ""
    property bool feedbackIsError: false
    property var previewData: ({ ok: false, items: [] })

    function selectedChannel() {
        if (!channels
                || selectedChannelIndex < 0
                || selectedChannelIndex >= channels.length) {
            return ({
                channelNumber: 0,
                displayNumber: "---",
                name: "No channels",
                description: "",
                mode: "",
                preserveEpisodeOrder: false,
                avoidRepeatDays: 0,
                numberWidth: 3,
                sources: [],
                sourceCount: 0,
                path: "",
                managed: false,
                nowTitle: "",
                nextTitle: ""
            })
        }
        return channels[selectedChannelIndex]
    }

    function resetFeedback() {
        feedbackMessage = ""
        feedbackIsError = false
    }

    function setResult(result) {
        feedbackMessage = result && result.message
                          ? String(result.message)
                          : ""
        feedbackIsError = !(result && result.ok)
    }

    function clearDraftSources() {
        draftSources.clear()
    }

    function addDraftSource(path) {
        var value = String(path || "")
        if (!value.length)
            return

        for (var i = 0; i < draftSources.count; ++i) {
            if (draftSources.get(i).path === value)
                return
        }
        draftSources.append({ path: value })
    }

    function beginCreate() {
        editorMode = "create"
        editingChannelNumber = 0
        resetFeedback()
        previewData = ({ ok: false, items: [] })

        channelNumberField.text = String(snapshot.suggestedChannel || 1)
        channelNameField.text = ""
        descriptionField.text = ""
        modeBox.currentIndex = 0
        preserveOrder.checked = false
        repeatDays.value = 0
        numberWidth.value = 3
        clearDraftSources()

        if (sourceOptions.length === 1)
            addDraftSource(sourceOptions[0])

        channelNameField.forceActiveFocus()
    }

    function beginEdit() {
        if (!channels.length)
            return

        var channel = selectedChannel()
        editorMode = "edit"
        editingChannelNumber = Number(channel.channelNumber)
        resetFeedback()
        previewData = ({ ok: false, items: [] })

        channelNumberField.text = String(channel.channelNumber)
        channelNameField.text = String(channel.name || "")
        descriptionField.text = String(channel.description || "")
        modeBox.currentIndex = channel.mode === "shuffle" ? 1 : 0
        preserveOrder.checked = Boolean(channel.preserveEpisodeOrder)
        repeatDays.value = Number(channel.avoidRepeatDays || 0)
        numberWidth.value = Number(channel.numberWidth || 3)
        clearDraftSources()

        var channelSources = channel.sources || []
        for (var i = 0; i < channelSources.length; ++i)
            addDraftSource(channelSources[i])

        channelNameField.forceActiveFocus()
    }

    function cancelEditor() {
        editorMode = "list"
        editingChannelNumber = 0
        previewData = ({ ok: false, items: [] })
        resetFeedback()
        broadcasterFocus.forceActiveFocus()
    }

    function draftObject() {
        var sources = []
        for (var i = 0; i < draftSources.count; ++i)
            sources.push(draftSources.get(i).path)

        return {
            channel: channelNumberField.text,
            name: channelNameField.text,
            description: descriptionField.text,
            mode: modeBox.currentText.toLowerCase(),
            preserveEpisodeOrder: preserveOrder.checked,
            avoidRepeatDays: repeatDays.value,
            numberWidth: numberWidth.value,
            sources: sources
        }
    }

    function previewDraft() {
        var result = channelOS.previewChannel(draftObject())
        previewData = result
        setResult(result)

        if (result && result.ok) {
            feedbackMessage = "Preview resolved "
                    + result.resolvedCount
                    + " indexed item"
                    + (result.resolvedCount === 1 ? "" : "s")
                    + ". Nothing has been saved yet."
            feedbackIsError = false
        }
    }

    function saveDraft() {
        var result

        if (editorMode === "edit") {
            result = channelOS.updateChannel(
                        editingChannelNumber,
                        draftObject())
        } else {
            result = channelOS.createChannel(draftObject())
        }

        setResult(result)

        if (result && result.ok) {
            channelOS.refreshBroadcaster()
            snapshot = channelOS.broadcasterSnapshot
            editorMode = "list"
            editingChannelNumber = 0
            previewData = ({ ok: false, items: [] })

            var target = Number(result.channelNumber || 0)
            for (var i = 0; i < channels.length; ++i) {
                if (Number(channels[i].channelNumber) === target) {
                    selectedChannelIndex = i
                    break
                }
            }
            broadcasterFocus.forceActiveFocus()
        }
    }

    function leaveBroadcaster() {
        editorMode = "list"
        resetFeedback()
        previewData = ({ ok: false, items: [] })
        if (broadcasterRoot.hostWindow)
            broadcasterRoot.hostWindow.screen = "home"
    }

    onChannelsChanged: {
        if (!channels.length) {
            selectedChannelIndex = 0
        } else {
            selectedChannelIndex = Math.max(
                        0,
                        Math.min(
                            selectedChannelIndex,
                            channels.length - 1))
        }
    }

    Rectangle {
        id: broadcasterHomeCard
        visible: broadcasterRoot.hostWindow
                 && broadcasterRoot.hostWindow.screen === "home"
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 28
        anchors.bottomMargin: 28
        width: (parent.width - 110) / 4
        height: parent.height * 0.29 - 56
        radius: 10
        color: homeCardMouse.containsMouse ? "#12396a" : "#0b1b2e"
        border.color: homeCardMouse.containsMouse
                      ? broadcasterRoot.accentBright
                      : "#17324a"
        border.width: homeCardMouse.containsMouse ? 2 : 1

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 24
            spacing: 10

            Text {
                text: "Broadcaster"
                color: broadcasterRoot.textPrimary
                font.pixelSize: 24
                font.weight: Font.DemiBold
            }

            Text {
                text: "Build and program your channels."
                color: broadcasterRoot.textSecondary
                font.pixelSize: 16
                wrapMode: Text.WordWrap
                width: parent.width
            }

            Text {
                text: "MOUSE / B / HOME > CHANNELS"
                color: broadcasterRoot.accentBright
                font.pixelSize: 12
                font.letterSpacing: 1
            }
        }

        MouseArea {
            id: homeCardMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor

            onClicked: {
                channelOS.refreshBroadcaster()
                broadcasterRoot.snapshot = channelOS.broadcasterSnapshot
                if (broadcasterRoot.hostWindow)
                    broadcasterRoot.hostWindow.screen = "broadcaster"
                broadcasterFocus.forceActiveFocus()
            }
        }
    }

    FocusScope {
        id: broadcasterFocus
        anchors.fill: parent
        visible: broadcasterRoot.hostWindow
                 && broadcasterRoot.hostWindow.screen === "broadcaster"
        focus: visible

        Keys.onPressed: function(event) {
            if (editorMode !== "list")
                return

            if (event.key === Qt.Key_Up) {
                selectedChannelIndex = Math.max(0, selectedChannelIndex - 1)
                event.accepted = true
            } else if (event.key === Qt.Key_Down) {
                selectedChannelIndex = Math.min(
                            Math.max(0, channels.length - 1),
                            selectedChannelIndex + 1)
                event.accepted = true
            } else if (event.key === Qt.Key_N) {
                beginCreate()
                event.accepted = true
            } else if (event.key === Qt.Key_E
                       || event.key === Qt.Key_Return
                       || event.key === Qt.Key_Enter) {
                beginEdit()
                event.accepted = true
            }
        }

        Shortcut {
            sequence: "Esc"
            enabled: broadcasterFocus.visible
            onActivated: {
                if (broadcasterRoot.editorMode === "list")
                    broadcasterRoot.leaveBroadcaster()
                else
                    broadcasterRoot.cancelEditor()
            }
        }

        Shortcut {
            sequence: "Ctrl+S"
            enabled: broadcasterFocus.visible
                     && broadcasterRoot.editorMode !== "list"
            onActivated: broadcasterRoot.saveDraft()
        }

        Rectangle {
            anchors.fill: parent
            color: broadcasterRoot.appBackground
        }

        Rectangle {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 104
            color: "#071322"
            border.color: broadcasterRoot.line
            border.width: 1

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 34
                spacing: 10

                Text {
                    text: "Channel"
                    color: broadcasterRoot.textPrimary
                    font.pixelSize: 30
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "OS"
                    color: broadcasterRoot.accentBright
                    font.pixelSize: 30
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "  |  BROADCASTER"
                    color: broadcasterRoot.accentBright
                    font.pixelSize: 22
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Column {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 32
                spacing: 5

                Text {
                    anchors.right: parent.right
                    text: "YOU OWN IT. YOU PROGRAM IT. YOU BROADCAST IT."
                    color: broadcasterRoot.textPrimary
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1
                }

                Text {
                    anchors.right: parent.right
                    text: "Mouse + keyboard enabled   |   ESC Back"
                    color: broadcasterRoot.textSecondary
                    font.pixelSize: 13
                }
            }
        }

        Item {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: header.bottom
            anchors.bottom: footer.top

            Rectangle {
                id: channelListPanel
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * 0.42
                color: "#06111e"
                border.color: broadcasterRoot.line
                border.width: 1

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 24
                    spacing: 8

                    Text {
                        text: "YOUR CHANNELS"
                        color: broadcasterRoot.accentBright
                        font.pixelSize: 14
                        font.weight: Font.Bold
                        font.letterSpacing: 2
                    }

                    Text {
                        text: snapshot.channelCount
                              + " active channel"
                              + (snapshot.channelCount === 1 ? "" : "s")
                        color: broadcasterRoot.textSecondary
                        font.pixelSize: 14
                    }
                }

                ListView {
                    id: channelList
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: listActions.top
                    anchors.topMargin: 82
                    anchors.leftMargin: 18
                    anchors.rightMargin: 18
                    anchors.bottomMargin: 16
                    spacing: 6
                    clip: true
                    model: broadcasterRoot.channels
                    currentIndex: broadcasterRoot.selectedChannelIndex
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        width: channelList.width
                        height: 86
                        radius: 7
                        color: index === broadcasterRoot.selectedChannelIndex
                               ? "#12396a"
                               : channelMouse.containsMouse
                                 ? "#0e2842"
                                 : "#0a1a2b"
                        border.color: index === broadcasterRoot.selectedChannelIndex
                                      ? broadcasterRoot.accentBright
                                      : "#17324a"
                        border.width: index === broadcasterRoot.selectedChannelIndex ? 2 : 1

                        Row {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 16
                            anchors.rightMargin: 16
                            spacing: 14

                            Text {
                                width: 74
                                text: modelData.displayNumber
                                color: broadcasterRoot.textPrimary
                                font.pixelSize: 24
                                font.weight: Font.Bold
                            }

                            Column {
                                width: parent.width - 180
                                spacing: 4

                                Text {
                                    width: parent.width
                                    text: modelData.name
                                    color: broadcasterRoot.textPrimary
                                    font.pixelSize: 18
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }

                                Text {
                                    width: parent.width
                                    text: modelData.mode.toUpperCase()
                                          + "   |   NOW: "
                                          + (modelData.nowTitle || "Ready")
                                    color: broadcasterRoot.textSecondary
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }

                                Text {
                                    width: parent.width
                                    text: "NEXT: "
                                          + (modelData.nextTitle || "Calculated at runtime")
                                    color: broadcasterRoot.textSecondary
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                            }

                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 54
                                height: 25
                                radius: 12
                                color: "#174e36"

                                Text {
                                    anchors.centerIn: parent
                                    text: "LIVE"
                                    color: broadcasterRoot.liveGreen
                                    font.pixelSize: 11
                                    font.weight: Font.Bold
                                }
                            }
                        }

                        MouseArea {
                            id: channelMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            acceptedButtons: Qt.LeftButton

                            onClicked: {
                                broadcasterRoot.selectedChannelIndex = index
                                broadcasterFocus.forceActiveFocus()
                            }

                            onDoubleClicked: {
                                broadcasterRoot.selectedChannelIndex = index
                                broadcasterRoot.beginEdit()
                            }
                        }
                    }
                }

                Row {
                    id: listActions
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 18
                    spacing: 12

                    Button {
                        text: "Create Channel"
                        width: (parent.width - 12) / 2
                        onClicked: broadcasterRoot.beginCreate()
                    }

                    Button {
                        text: "Edit Existing"
                        width: (parent.width - 12) / 2
                        enabled: broadcasterRoot.channels.length > 0
                        onClicked: broadcasterRoot.beginEdit()
                    }
                }
            }

            Rectangle {
                id: rightPanel
                anchors.left: channelListPanel.right
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                color: "#091827"
                border.color: broadcasterRoot.line
                border.width: 1

                Item {
                    anchors.fill: parent
                    visible: broadcasterRoot.editorMode === "list"

                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 34
                        spacing: 16

                        Text {
                            text: broadcasterRoot.channels.length
                                  ? "CHANNEL " + broadcasterRoot.selectedChannel().displayNumber
                                    + "  |  " + broadcasterRoot.selectedChannel().name
                                  : "CREATE YOUR FIRST CHANNEL"
                            color: broadcasterRoot.textPrimary
                            font.pixelSize: 28
                            font.weight: Font.DemiBold
                            width: parent.width
                            elide: Text.ElideRight
                        }

                        Text {
                            text: broadcasterRoot.channels.length
                                  ? (broadcasterRoot.selectedChannel().description || "No description yet.")
                                  : "Turn indexed media into persistent television."
                            color: broadcasterRoot.textSecondary
                            font.pixelSize: 16
                            width: parent.width
                            wrapMode: Text.WordWrap
                        }

                        Rectangle {
                            width: parent.width
                            height: 1
                            color: broadcasterRoot.line
                        }

                        GridLayout {
                            width: parent.width
                            columns: 2
                            columnSpacing: 18
                            rowSpacing: 14

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 112
                                radius: 8
                                color: broadcasterRoot.panelRaised
                                border.color: broadcasterRoot.line

                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8

                                    Text {
                                        text: "NOW"
                                        color: broadcasterRoot.accentBright
                                        font.pixelSize: 12
                                        font.weight: Font.Bold
                                        font.letterSpacing: 2
                                    }

                                    Text {
                                        width: parent.width
                                        text: broadcasterRoot.selectedChannel().nowTitle
                                              || "Runtime calculates the current program"
                                        color: broadcasterRoot.textPrimary
                                        font.pixelSize: 19
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 112
                                radius: 8
                                color: broadcasterRoot.panelRaised
                                border.color: broadcasterRoot.line

                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8

                                    Text {
                                        text: "NEXT"
                                        color: broadcasterRoot.accentBright
                                        font.pixelSize: 12
                                        font.weight: Font.Bold
                                        font.letterSpacing: 2
                                    }

                                    Text {
                                        width: parent.width
                                        text: broadcasterRoot.selectedChannel().nextTitle
                                              || "Calculated from the channel timeline"
                                        color: broadcasterRoot.textPrimary
                                        font.pixelSize: 19
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 112
                                radius: 8
                                color: broadcasterRoot.panelRaised
                                border.color: broadcasterRoot.line

                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8

                                    Text {
                                        text: "PROGRAMMING"
                                        color: broadcasterRoot.accentBright
                                        font.pixelSize: 12
                                        font.weight: Font.Bold
                                        font.letterSpacing: 2
                                    }

                                    Text {
                                        text: broadcasterRoot.selectedChannel().mode
                                              ? broadcasterRoot.selectedChannel().mode.toUpperCase()
                                              : "NOT SET"
                                        color: broadcasterRoot.textPrimary
                                        font.pixelSize: 19
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        text: broadcasterRoot.selectedChannel().sourceCount
                                              + " source"
                                              + (broadcasterRoot.selectedChannel().sourceCount === 1 ? "" : "s")
                                        color: broadcasterRoot.textSecondary
                                        font.pixelSize: 13
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 112
                                radius: 8
                                color: broadcasterRoot.panelRaised
                                border.color: broadcasterRoot.line

                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8

                                    Text {
                                        text: "PORTABLE DEFINITION"
                                        color: broadcasterRoot.accentBright
                                        font.pixelSize: 12
                                        font.weight: Font.Bold
                                        font.letterSpacing: 2
                                    }

                                    Text {
                                        width: parent.width
                                        text: broadcasterRoot.selectedChannel().path
                                              || snapshot.managedDirectory
                                        color: broadcasterRoot.textPrimary
                                        font.pixelSize: 13
                                        wrapMode: Text.WrapAnywhere
                                        maximumLineCount: 3
                                    }
                                }
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 130
                            radius: 8
                            color: "#0b2136"
                            border.color: broadcasterRoot.accent

                            Column {
                                anchors.fill: parent
                                anchors.margins: 20
                                spacing: 8

                                Text {
                                    text: "SAFETY RULE"
                                    color: broadcasterRoot.warning
                                    font.pixelSize: 13
                                    font.weight: Font.Bold
                                    font.letterSpacing: 2
                                }

                                Text {
                                    width: parent.width
                                    text: "Creating a channel can never silently replace an existing channel number. Editing is an explicit separate action, writes atomically, and preserves a .bak copy of the prior definition."
                                    color: broadcasterRoot.textPrimary
                                    font.pixelSize: 14
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 24
                    visible: broadcasterRoot.editorMode !== "list"
                    clip: true

                    Column {
                        width: rightPanel.width - 70
                        spacing: 16

                        Row {
                            width: parent.width
                            spacing: 14

                            Text {
                                text: broadcasterRoot.editorMode === "create"
                                      ? "CREATE CHANNEL"
                                      : "EDIT CHANNEL " + String(broadcasterRoot.editingChannelNumber)
                                color: broadcasterRoot.textPrimary
                                font.pixelSize: 27
                                font.weight: Font.DemiBold
                            }

                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: safetyLabel.implicitWidth + 22
                                height: 28
                                radius: 14
                                color: "#463719"

                                Text {
                                    id: safetyLabel
                                    anchors.centerIn: parent
                                    text: broadcasterRoot.editorMode === "create"
                                          ? "NO OVERWRITE"
                                          : "EXPLICIT EDIT + BACKUP"
                                    color: broadcasterRoot.warning
                                    font.pixelSize: 11
                                    font.weight: Font.Bold
                                }
                            }
                        }

                        Text {
                            width: parent.width
                            text: broadcasterRoot.editorMode === "create"
                                  ? "Define a new station. ChannelOS validates the real runtime before writing anything."
                                  : "Edit the selected station. Channel identity is locked during an in-place edit."
                            color: broadcasterRoot.textSecondary
                            font.pixelSize: 15
                            wrapMode: Text.WordWrap
                        }

                        GridLayout {
                            width: parent.width
                            columns: 2
                            columnSpacing: 18
                            rowSpacing: 14

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Label {
                                    text: "Channel Number"
                                    color: broadcasterRoot.textSecondary
                                }

                                TextField {
                                    id: channelNumberField
                                    Layout.fillWidth: true
                                    placeholderText: "025"
                                    readOnly: broadcasterRoot.editorMode === "edit"
                                    activeFocusOnTab: true
                                    color: broadcasterRoot.textPrimary
                                    selectedTextColor: broadcasterRoot.textPrimary
                                    selectionColor: broadcasterRoot.accent
                                    validator: IntValidator { bottom: 1; top: 9999 }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Label {
                                    text: "Channel Name"
                                    color: broadcasterRoot.textSecondary
                                }

                                TextField {
                                    id: channelNameField
                                    Layout.fillWidth: true
                                    placeholderText: "Sci-Fi Classics"
                                    activeFocusOnTab: true
                                    color: broadcasterRoot.textPrimary
                                    selectedTextColor: broadcasterRoot.textPrimary
                                    selectionColor: broadcasterRoot.accent
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Label {
                                    text: "Programming Mode"
                                    color: broadcasterRoot.textSecondary
                                }

                                ComboBox {
                                    id: modeBox
                                    Layout.fillWidth: true
                                    model: ["Sequential", "Shuffle"]
                                    activeFocusOnTab: true
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Label {
                                    text: "Display Width"
                                    color: broadcasterRoot.textSecondary
                                }

                                SpinBox {
                                    id: numberWidth
                                    Layout.fillWidth: true
                                    from: 1
                                    to: 4
                                    value: 3
                                    editable: true
                                    activeFocusOnTab: true
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Label {
                                    text: "Avoid Repeat (days)"
                                    color: broadcasterRoot.textSecondary
                                }

                                SpinBox {
                                    id: repeatDays
                                    Layout.fillWidth: true
                                    from: 0
                                    to: 365
                                    value: 0
                                    editable: true
                                    activeFocusOnTab: true
                                }
                            }

                            CheckBox {
                                id: preserveOrder
                                text: "Preserve episode/source order"
                                Layout.alignment: Qt.AlignBottom
                                activeFocusOnTab: true
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 6

                            Label {
                                text: "Description"
                                color: broadcasterRoot.textSecondary
                            }

                            TextArea {
                                id: descriptionField
                                width: parent.width
                                height: 82
                                placeholderText: "What kind of station is this?"
                                wrapMode: TextEdit.Wrap
                                activeFocusOnTab: true
                                color: broadcasterRoot.textPrimary
                                selectedTextColor: broadcasterRoot.textPrimary
                                selectionColor: broadcasterRoot.accent
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: Math.max(190, sourceColumn.implicitHeight + 34)
                            radius: 8
                            color: broadcasterRoot.panel
                            border.color: broadcasterRoot.line

                            Column {
                                id: sourceColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 16
                                spacing: 10

                                Text {
                                    text: "SOURCES"
                                    color: broadcasterRoot.accentBright
                                    font.pixelSize: 13
                                    font.weight: Font.Bold
                                    font.letterSpacing: 2
                                }

                                Row {
                                    width: parent.width
                                    spacing: 10

                                    ComboBox {
                                        id: sourcePicker
                                        width: parent.width - addSourceButton.width - 10
                                        model: broadcasterRoot.sourceOptions
                                        enabled: broadcasterRoot.sourceOptions.length > 0
                                        activeFocusOnTab: true
                                    }

                                    Button {
                                        id: addSourceButton
                                        text: "Add Source"
                                        enabled: broadcasterRoot.sourceOptions.length > 0
                                        onClicked: broadcasterRoot.addDraftSource(sourcePicker.currentText)
                                    }
                                }

                                Text {
                                    visible: broadcasterRoot.sourceOptions.length === 0
                                    width: parent.width
                                    text: "No indexed source roots are available. Add a media folder in Library first."
                                    color: broadcasterRoot.warning
                                    font.pixelSize: 13
                                    wrapMode: Text.WordWrap
                                }

                                ListView {
                                    width: parent.width
                                    height: Math.min(132, Math.max(50, contentHeight))
                                    model: draftSources
                                    clip: true
                                    spacing: 5

                                    delegate: Rectangle {
                                        width: ListView.view.width
                                        height: 42
                                        radius: 6
                                        color: "#0d2035"
                                        border.color: broadcasterRoot.line

                                        Text {
                                            anchors.left: parent.left
                                            anchors.right: removeSource.left
                                            anchors.verticalCenter: parent.verticalCenter
                                            anchors.leftMargin: 12
                                            anchors.rightMargin: 8
                                            text: model.path
                                            color: broadcasterRoot.textPrimary
                                            font.pixelSize: 13
                                            elide: Text.ElideMiddle
                                        }

                                        Button {
                                            id: removeSource
                                            anchors.right: parent.right
                                            anchors.verticalCenter: parent.verticalCenter
                                            anchors.rightMargin: 6
                                            width: 76
                                            height: 30
                                            text: "Remove"
                                            onClicked: draftSources.remove(index)
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: previewColumn.implicitHeight + 34
                            radius: 8
                            color: "#071827"
                            border.color: broadcasterRoot.line

                            Column {
                                id: previewColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 16
                                spacing: 8

                                Row {
                                    width: parent.width

                                    Text {
                                        id: previewTitle
                                        text: "PROGRAM ORDER PREVIEW"
                                        color: broadcasterRoot.accentBright
                                        font.pixelSize: 13
                                        font.weight: Font.Bold
                                        font.letterSpacing: 2
                                    }

                                    Item {
                                        width: Math.max(0, parent.width - previewTitle.implicitWidth - previewButton.width)
                                        height: 1
                                    }

                                    Button {
                                        id: previewButton
                                        text: "Preview"
                                        onClicked: broadcasterRoot.previewDraft()
                                    }
                                }

                                Text {
                                    visible: !(broadcasterRoot.previewData && broadcasterRoot.previewData.ok)
                                    text: "Preview validates the real resolver/runtime without saving or changing the live lineup."
                                    color: broadcasterRoot.textSecondary
                                    font.pixelSize: 13
                                    width: parent.width
                                    wrapMode: Text.WordWrap
                                }

                                Repeater {
                                    model: broadcasterRoot.previewData && broadcasterRoot.previewData.ok
                                           ? (broadcasterRoot.previewData.items || []) : []

                                    delegate: Row {
                                        width: previewColumn.width
                                        spacing: 12

                                        Text {
                                            width: 30
                                            text: (index + 1) + "."
                                            color: broadcasterRoot.textSecondary
                                            font.pixelSize: 13
                                        }

                                        Text {
                                            width: parent.width - 150
                                            text: modelData.title
                                            color: broadcasterRoot.textPrimary
                                            font.pixelSize: 14
                                            elide: Text.ElideRight
                                        }

                                        Text {
                                            width: 90
                                            horizontalAlignment: Text.AlignRight
                                            text: Math.round(modelData.durationSeconds) + "s"
                                            color: broadcasterRoot.textSecondary
                                            font.pixelSize: 13
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            visible: broadcasterRoot.feedbackMessage.length > 0
                            width: parent.width
                            height: feedbackText.implicitHeight + 28
                            radius: 7
                            color: broadcasterRoot.feedbackIsError ? "#401c25" : "#123628"
                            border.color: broadcasterRoot.feedbackIsError
                                          ? broadcasterRoot.danger : broadcasterRoot.liveGreen

                            Text {
                                id: feedbackText
                                anchors.fill: parent
                                anchors.margins: 14
                                text: broadcasterRoot.feedbackMessage
                                color: broadcasterRoot.textPrimary
                                font.pixelSize: 14
                                wrapMode: Text.WordWrap
                            }
                        }

                        Row {
                            width: parent.width
                            spacing: 12

                            Button {
                                text: "Cancel"
                                width: 130
                                onClicked: broadcasterRoot.cancelEditor()
                            }

                            Item {
                                width: Math.max(0, parent.width - 130 - 160 - 160 - 36)
                                height: 1
                            }

                            Button {
                                text: "Preview"
                                width: 160
                                onClicked: broadcasterRoot.previewDraft()
                            }

                            Button {
                                text: broadcasterRoot.editorMode === "create"
                                      ? "Save Channel" : "Save Changes"
                                width: 160
                                highlighted: true
                                onClicked: broadcasterRoot.saveDraft()
                            }
                        }

                        Item { width: 1; height: 24 }
                    }
                }
            }
        }

        Rectangle {
            id: footer
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 56
            color: "#06111e"
            border.color: broadcasterRoot.line
            border.width: 1

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 26
                spacing: 30

                Text { text: "UP/DOWN  Select Channel"; color: broadcasterRoot.textSecondary; font.pixelSize: 13 }
                Text { text: "N  New Channel"; color: broadcasterRoot.textSecondary; font.pixelSize: 13 }
                Text { text: "E / ENTER  Edit"; color: broadcasterRoot.textSecondary; font.pixelSize: 13 }
                Text { text: "TAB  Fields"; color: broadcasterRoot.textSecondary; font.pixelSize: 13 }
                Text { text: "CTRL+S  Save"; color: broadcasterRoot.textSecondary; font.pixelSize: 13 }
                Text { text: "ESC  Back / Cancel"; color: broadcasterRoot.textSecondary; font.pixelSize: 13 }
            }

            Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 24
                text: "Definitions: " + snapshot.managedDirectory
                color: broadcasterRoot.textSecondary
                font.pixelSize: 12
                elide: Text.ElideMiddle
                width: parent.width * 0.30
                horizontalAlignment: Text.AlignRight
            }
        }
    }

    Connections {
        target: channelOS
        function onBroadcasterChanged() {
            broadcasterRoot.snapshot = channelOS.broadcasterSnapshot
        }
    }

    ListModel {
        id: draftSources
    }
}
