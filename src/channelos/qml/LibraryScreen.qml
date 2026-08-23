import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: libraryRoot
    anchors.fill: parent
    z: 85

    property var hostWindow: null
    visible: hostWindow !== null && hostWindow.screen === "library"

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

    property var snapshot: channelOS
                           ? (channelOS.librarySnapshot || ({}))
                           : ({})
    property var scan: channelOS
                       ? (channelOS.libraryScan || ({ active: false }))
                       : ({ active: false })
    property var allItems: snapshot.items || []
    property var sources: snapshot.sources || []
    property var filteredItems: []
    property int selectedMedia: 0
    property int selectedSource: 0
    property string query: ""
    property int sortMode: 0

    property bool scanConfirmVisible: false
    property string pendingScanPath: ""
    property string pendingScanName: ""
    property int pendingScanCount: 0
    property bool pendingScanExisting: false

    property bool removeConfirmVisible: false
    property string pendingRemovePath: ""
    property string pendingRemoveName: ""

    property string feedbackMessage: ""
    property bool feedbackIsError: false

    function rebuildMedia() {
        var needle = String(query || "").trim().toLowerCase()
        var next = []
        for (var i = 0; i < allItems.length; ++i) {
            var item = allItems[i]
            var haystack = (String(item.title || "") + " "
                            + String(item.fileName || "") + " "
                            + String(item.sourceName || "") + " "
                            + String(item.containerFormat || "")).toLowerCase()
            if (!needle.length || haystack.indexOf(needle) >= 0)
                next.push(item)
        }

        next.sort(function(a, b) {
            if (sortMode === 1) {
                var sourceA = String(a.sourceName || "").toLowerCase()
                var sourceB = String(b.sourceName || "").toLowerCase()
                if (sourceA < sourceB) return -1
                if (sourceA > sourceB) return 1
            } else if (sortMode === 2) {
                return Number(b.durationSeconds || 0) - Number(a.durationSeconds || 0)
            }

            var titleA = String(a.title || "").toLowerCase()
            var titleB = String(b.title || "").toLowerCase()
            if (titleA < titleB) return -1
            if (titleA > titleB) return 1
            return 0
        })

        filteredItems = next
        if (filteredItems.length === 0)
            selectedMedia = 0
        else
            selectedMedia = Math.max(0, Math.min(selectedMedia, filteredItems.length - 1))
    }

    function selectedItem() {
        if (!filteredItems || filteredItems.length === 0
                || selectedMedia < 0 || selectedMedia >= filteredItems.length) {
            return ({
                assetId: "",
                title: "No media selected",
                fileName: "",
                path: "",
                sourceRoot: "",
                sourceName: "",
                durationSeconds: 0,
                sizeBytes: 0,
                containerFormat: ""
            })
        }
        return filteredItems[selectedMedia]
    }

    function formatDuration(seconds) {
        var total = Math.max(0, Math.floor(Number(seconds) || 0))
        if (total <= 0)
            return "Unknown duration"
        var hours = Math.floor(total / 3600)
        var minutes = Math.floor((total % 3600) / 60)
        var secs = total % 60
        if (hours > 0)
            return hours + ":" + (minutes < 10 ? "0" : "") + minutes
                   + ":" + (secs < 10 ? "0" : "") + secs
        return minutes + ":" + (secs < 10 ? "0" : "") + secs
    }

    function formatBytes(bytes) {
        var value = Number(bytes) || 0
        if (value >= 1073741824)
            return (value / 1073741824).toFixed(2) + " GB"
        if (value >= 1048576)
            return (value / 1048576).toFixed(1) + " MB"
        if (value >= 1024)
            return (value / 1024).toFixed(1) + " KB"
        return value + " B"
    }

    function setFeedback(result) {
        feedbackMessage = result && result.message ? String(result.message) : ""
        feedbackIsError = !(result && result.ok)
        feedbackTimer.restart()
    }

    function beginPreflight(result) {
        if (!result || result.cancelled)
            return
        if (!result.ok) {
            setFeedback(result)
            return
        }
        pendingScanPath = String(result.path || "")
        pendingScanName = String(result.name || result.path || "Media source")
        pendingScanCount = Number(result.supportedCount || 0)
        pendingScanExisting = Boolean(result.alreadyIndexed)
        scanConfirmVisible = true
    }

    function chooseSource() {
        beginPreflight(channelOS.chooseMediaFolder())
    }

    function preflightSource(path) {
        beginPreflight(channelOS.preflightMediaSource(String(path || "")))
    }

    function startPendingScan() {
        var result = channelOS.startMediaScan(pendingScanPath)
        if (!result.ok) {
            setFeedback(result)
            return
        }
        scanConfirmVisible = false
        setFeedback(result)
    }

    function playSelected() {
        var item = selectedItem()
        if (!item.assetId)
            return

        hostWindow.screen = "ondemand"
        Qt.callLater(function() {
            var result = channelOS.playLibraryAsset(String(item.assetId))
            if (!result.ok) {
                hostWindow.screen = "library"
                setFeedback(result)
            }
        })
    }

    function requestRemove(source) {
        if (!source)
            return
        if (source.usedByChannels && source.usedByChannels.length > 0) {
            var names = []
            for (var i = 0; i < source.usedByChannels.length; ++i)
                names.push(source.usedByChannels[i].displayNumber + " " + source.usedByChannels[i].name)
            setFeedback({
                ok: false,
                message: "This source is used by " + names.join(", ") + ". Edit those channels before removing it."
            })
            return
        }
        pendingRemovePath = String(source.path || "")
        pendingRemoveName = String(source.name || source.path || "Media source")
        removeConfirmVisible = true
    }

    function removePendingSource() {
        var result = channelOS.removeLibrarySource(pendingRemovePath)
        removeConfirmVisible = false
        setFeedback(result)
    }

    onQueryChanged: rebuildMedia()
    onSortModeChanged: rebuildMedia()
    onAllItemsChanged: rebuildMedia()

    onVisibleChanged: {
        if (visible) {
            channelOS.refreshLibrary()
            rebuildMedia()
            forceActiveFocus()
        }
    }

    Component.onCompleted: rebuildMedia()

    Connections {
        target: channelOS
        function onLibraryChanged() {
            libraryRoot.snapshot = channelOS.librarySnapshot || ({})
            libraryRoot.rebuildMedia()
        }
        function onLibraryScanChanged() {
            libraryRoot.scan = channelOS.libraryScan || ({ active: false })
        }
    }

    Shortcut {
        sequence: "Ctrl+F"
        enabled: libraryRoot.visible && !libraryRoot.scanConfirmVisible && !libraryRoot.removeConfirmVisible
        onActivated: searchField.forceActiveFocus()
    }

    Shortcut {
        sequence: "A"
        enabled: libraryRoot.visible && !searchField.activeFocus
                 && !libraryRoot.scanConfirmVisible && !libraryRoot.removeConfirmVisible
                 && !libraryRoot.scan.active
        onActivated: libraryRoot.chooseSource()
    }

    Shortcut {
        sequence: "Up"
        enabled: libraryRoot.visible && !searchField.activeFocus
                 && !libraryRoot.scanConfirmVisible && !libraryRoot.removeConfirmVisible
        onActivated: {
            libraryRoot.selectedMedia = Math.max(0, libraryRoot.selectedMedia - 1)
            mediaList.positionViewAtIndex(libraryRoot.selectedMedia, ListView.Contain)
        }
    }

    Shortcut {
        sequence: "Down"
        enabled: libraryRoot.visible && !searchField.activeFocus
                 && !libraryRoot.scanConfirmVisible && !libraryRoot.removeConfirmVisible
        onActivated: {
            libraryRoot.selectedMedia = Math.min(
                        Math.max(0, libraryRoot.filteredItems.length - 1),
                        libraryRoot.selectedMedia + 1)
            mediaList.positionViewAtIndex(libraryRoot.selectedMedia, ListView.Contain)
        }
    }

    Shortcut {
        sequence: "Return"
        enabled: libraryRoot.visible && !searchField.activeFocus
                 && !libraryRoot.scanConfirmVisible && !libraryRoot.removeConfirmVisible
                 && !libraryRoot.scan.active
        onActivated: libraryRoot.playSelected()
    }

    Shortcut {
        sequence: "Escape"
        enabled: libraryRoot.visible
        onActivated: {
            if (libraryRoot.scanConfirmVisible) {
                libraryRoot.scanConfirmVisible = false
            } else if (libraryRoot.removeConfirmVisible) {
                libraryRoot.removeConfirmVisible = false
            } else if (searchField.activeFocus) {
                searchField.focus = false
                libraryRoot.forceActiveFocus()
            } else if (hostWindow) {
                hostWindow.screen = "home"
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: appBackground
    }

    Rectangle {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 104
        color: "#071322"
        border.color: line
        border.width: 1

        Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 34
            spacing: 7

            Text {
                text: "Channel"
                color: textPrimary
                font.pixelSize: 30
                font.weight: Font.DemiBold
            }
            Text {
                text: "OS"
                color: accentBright
                font.pixelSize: 30
                font.weight: Font.DemiBold
            }
            Text {
                text: "  |  LIBRARY"
                color: accentBright
                font.pixelSize: 20
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        TextField {
            id: searchField
            anchors.right: sortBox.left
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 330
            height: 46
            placeholderText: "Search owned media…  Ctrl+F"
            placeholderTextColor: "#70869c"
            color: textPrimary
            selectionColor: accent
            selectedTextColor: "white"
            text: libraryRoot.query
            onTextChanged: libraryRoot.query = text
            background: Rectangle {
                radius: 7
                color: "#0d2035"
                border.color: searchField.activeFocus ? accentBright : line
                border.width: searchField.activeFocus ? 2 : 1
            }
        }

        ComboBox {
            id: sortBox
            anchors.right: addButton.left
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 150
            height: 46
            model: ["Title", "Source", "Duration"]
            currentIndex: libraryRoot.sortMode
            onCurrentIndexChanged: libraryRoot.sortMode = currentIndex
        }

        Button {
            id: addButton
            anchors.right: parent.right
            anchors.rightMargin: 28
            anchors.verticalCenter: parent.verticalCenter
            width: 170
            height: 46
            enabled: !libraryRoot.scan.active
            text: "+  Add Source"
            onClicked: libraryRoot.chooseSource()
        }
    }

    Rectangle {
        id: sourceRail
        anchors.left: parent.left
        anchors.top: header.bottom
        anchors.bottom: footer.top
        width: Math.max(280, parent.width * 0.22)
        color: "#06111e"
        border.color: line
        border.width: 1

        Text {
            id: sourceTitle
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 22
            anchors.topMargin: 20
            text: "MEDIA SOURCES"
            color: accentBright
            font.pixelSize: 13
            font.weight: Font.Bold
            font.letterSpacing: 2
        }

        Text {
            anchors.right: parent.right
            anchors.verticalCenter: sourceTitle.verticalCenter
            anchors.rightMargin: 22
            text: String(sources.length)
            color: textSecondary
            font.pixelSize: 13
        }

        ListView {
            id: sourceList
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: sourceTitle.bottom
            anchors.bottom: sourceSafety.top
            anchors.topMargin: 16
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            anchors.bottomMargin: 12
            spacing: 8
            clip: true
            model: libraryRoot.sources

            delegate: Rectangle {
                width: sourceList.width
                height: 116
                radius: 8
                color: index === libraryRoot.selectedSource ? "#102b50" : "#0a1a2b"
                border.color: index === libraryRoot.selectedSource ? accentBright : "#17324a"
                border.width: index === libraryRoot.selectedSource ? 2 : 1

                MouseArea {
                    anchors.fill: parent
                    onClicked: libraryRoot.selectedSource = index
                }

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    spacing: 5

                    Row {
                        width: parent.width
                        spacing: 8
                        Rectangle {
                            width: 9
                            height: 9
                            radius: 5
                            anchors.verticalCenter: parent.verticalCenter
                            color: modelData.available ? liveGreen : danger
                        }
                        Text {
                            width: parent.width - 70
                            text: modelData.name
                            color: textPrimary
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            text: modelData.available ? "ONLINE" : "OFFLINE"
                            color: modelData.available ? liveGreen : danger
                            font.pixelSize: 10
                            font.weight: Font.Bold
                        }
                    }

                    Text {
                        text: modelData.onlineLocationCount + " indexed item"
                              + (modelData.onlineLocationCount === 1 ? "" : "s")
                              + "  •  " + String(modelData.status).toUpperCase()
                        color: textSecondary
                        font.pixelSize: 12
                        width: parent.width
                        elide: Text.ElideRight
                    }

                    Text {
                        visible: modelData.usedByChannels && modelData.usedByChannels.length > 0
                        text: "USED BY " + modelData.usedByChannels.length + " CHANNEL"
                              + (modelData.usedByChannels.length === 1 ? "" : "S")
                        color: warning
                        font.pixelSize: 10
                        font.weight: Font.Bold
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 10
                    anchors.bottomMargin: 9
                    spacing: 8

                    Button {
                        width: 76
                        height: 28
                        text: "Rescan"
                        enabled: !libraryRoot.scan.active && modelData.available
                        onClicked: {
                            libraryRoot.selectedSource = index
                            libraryRoot.preflightSource(modelData.path)
                        }
                    }
                    Button {
                        width: 76
                        height: 28
                        text: "Remove"
                        enabled: !libraryRoot.scan.active
                        onClicked: {
                            libraryRoot.selectedSource = index
                            libraryRoot.requestRemove(modelData)
                        }
                    }
                }
            }
        }

        Rectangle {
            id: sourceSafety
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 14
            height: 74
            radius: 7
            color: "#091827"
            border.color: line
            border.width: 1

            Text {
                anchors.fill: parent
                anchors.margins: 11
                text: "ChannelOS references your files in place.\nRemoving a source never deletes the originals."
                color: textSecondary
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }
        }
    }

    Rectangle {
        id: mediaPanel
        anchors.left: sourceRail.right
        anchors.right: detailsPanel.left
        anchors.top: header.bottom
        anchors.bottom: footer.top
        color: "#071421"
        border.color: line
        border.width: 1

        Row {
            id: mediaHeading
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 20
            anchors.rightMargin: 20
            anchors.topMargin: 18
            height: 30

            Text {
                text: query.length ? "SEARCH RESULTS" : "OWNED MEDIA"
                color: accentBright
                font.pixelSize: 13
                font.weight: Font.Bold
                font.letterSpacing: 2
            }
            Item { width: 18; height: 1 }
            Text {
                text: filteredItems.length + " / " + allItems.length
                color: textSecondary
                font.pixelSize: 13
            }
        }

        ListView {
            id: mediaList
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: mediaHeading.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 14
            spacing: 6
            clip: true
            model: libraryRoot.filteredItems
            currentIndex: libraryRoot.selectedMedia
            boundsBehavior: Flickable.StopAtBounds

            delegate: Rectangle {
                width: mediaList.width
                height: 76
                radius: 7
                color: index === libraryRoot.selectedMedia ? "#12396a" : "#0a1a2b"
                border.color: index === libraryRoot.selectedMedia ? accentBright : "#17324a"
                border.width: index === libraryRoot.selectedMedia ? 2 : 1

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        libraryRoot.selectedMedia = index
                        libraryRoot.forceActiveFocus()
                    }
                    onDoubleClicked: {
                        libraryRoot.selectedMedia = index
                        libraryRoot.playSelected()
                    }
                }

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 5

                    Text {
                        text: modelData.title
                        color: textPrimary
                        font.pixelSize: 17
                        font.weight: index === libraryRoot.selectedMedia ? Font.DemiBold : Font.Normal
                        width: parent.width
                        elide: Text.ElideRight
                    }
                    Row {
                        spacing: 14
                        Text { text: libraryRoot.formatDuration(modelData.durationSeconds); color: textSecondary; font.pixelSize: 12 }
                        Text { text: modelData.containerFormat; color: accentBright; font.pixelSize: 12 }
                        Text { text: modelData.sourceName; color: textSecondary; font.pixelSize: 12 }
                    }
                }
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 10
            visible: libraryRoot.filteredItems.length === 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: allItems.length === 0 ? "YOUR LIBRARY IS EMPTY" : "NO MATCHES"
                color: textPrimary
                font.pixelSize: 22
                font.weight: Font.DemiBold
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: allItems.length === 0 ? "Add a media source to begin." : "Try a different search."
                color: textSecondary
                font.pixelSize: 14
            }
        }
    }

    Rectangle {
        id: detailsPanel
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: footer.top
        width: Math.max(360, parent.width * 0.28)
        color: "#091827"
        border.color: line
        border.width: 1

        readonly property var item: libraryRoot.selectedItem()

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 24
            height: 190
            radius: 10
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#12304a" }
                GradientStop { position: 1.0; color: "#08131f" }
            }
            border.color: accent
            border.width: 1

            Column {
                anchors.centerIn: parent
                spacing: 10
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "OWNED MEDIA"
                    color: accentBright
                    font.pixelSize: 14
                    font.letterSpacing: 3
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: detailsPanel.item.containerFormat || "MEDIA"
                    color: textPrimary
                    font.pixelSize: 34
                    font.weight: Font.DemiBold
                }
            }
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: 238
            anchors.leftMargin: 26
            anchors.rightMargin: 26
            spacing: 10

            Text {
                text: detailsPanel.item.title
                color: textPrimary
                font.pixelSize: 24
                font.weight: Font.DemiBold
                width: parent.width
                elide: Text.ElideRight
            }
            Text {
                text: libraryRoot.formatDuration(detailsPanel.item.durationSeconds)
                      + "  •  " + libraryRoot.formatBytes(detailsPanel.item.sizeBytes)
                      + "  •  " + detailsPanel.item.containerFormat
                color: textSecondary
                font.pixelSize: 13
                width: parent.width
            }
            Rectangle { width: parent.width; height: 1; color: line }
            Text { text: "SOURCE"; color: accentBright; font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 2 }
            Text {
                text: detailsPanel.item.sourceRoot
                color: textSecondary
                font.pixelSize: 13
                width: parent.width
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 3
            }
            Text { text: "FILE"; color: accentBright; font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 2 }
            Text {
                text: detailsPanel.item.fileName
                color: textSecondary
                font.pixelSize: 13
                width: parent.width
                elide: Text.ElideMiddle
            }
        }

        Button {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 26
            height: 52
            enabled: Boolean(detailsPanel.item.assetId) && !libraryRoot.scan.active
            text: "Play On Demand"
            onClicked: libraryRoot.playSelected()
        }
    }

    Rectangle {
        id: footer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 58
        color: "#06111e"
        border.color: line
        border.width: 1

        Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 24
            spacing: 28
            Text { text: "UP/DOWN  Browse"; color: textSecondary; font.pixelSize: 13 }
            Text { text: "ENTER  Play"; color: textSecondary; font.pixelSize: 13 }
            Text { text: "A  Add Source"; color: textSecondary; font.pixelSize: 13 }
            Text { text: "CTRL+F  Search"; color: textSecondary; font.pixelSize: 13 }
            Text { text: "ESC  Home"; color: textSecondary; font.pixelSize: 13 }
        }

        Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: 24
            text: feedbackMessage
            color: feedbackIsError ? danger : accentBright
            font.pixelSize: 12
            width: Math.min(520, parent.width * 0.38)
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: Boolean(scan.active)
        color: "#b0050c15"
        z: 200

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(680, parent.width * 0.62)
            height: 300
            radius: 12
            color: panelRaised
            border.color: accentBright
            border.width: 2

            Column {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 16

                Text {
                    text: scan.phase === "cancelling" ? "CANCELLING LIBRARY SCAN" : "INDEXING MEDIA"
                    color: accentBright
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                }
                Text {
                    text: scan.sourcePath || ""
                    color: textPrimary
                    font.pixelSize: 17
                    width: parent.width
                    elide: Text.ElideMiddle
                }
                Text {
                    text: scan.message || "Working…"
                    color: textSecondary
                    font.pixelSize: 14
                }
                Text {
                    text: scan.fileName || ""
                    color: textSecondary
                    font.pixelSize: 13
                    width: parent.width
                    elide: Text.ElideMiddle
                }
                Rectangle {
                    width: parent.width
                    height: 10
                    radius: 5
                    color: "#1c3348"
                    Rectangle {
                        width: parent.width * (Number(scan.total || 0) > 0
                                              ? Math.max(0, Math.min(1, Number(scan.current || 0) / Number(scan.total)))
                                              : 0)
                        height: parent.height
                        radius: 5
                        color: accentBright
                    }
                }
                Text {
                    text: Number(scan.total || 0) > 0
                          ? scan.current + " / " + scan.total
                          : "Discovering…"
                    color: textPrimary
                    font.pixelSize: 13
                }
                Button {
                    anchors.right: parent.right
                    width: 150
                    height: 42
                    enabled: scan.phase !== "cancelling"
                    text: scan.phase === "cancelling" ? "Cancelling…" : "Cancel Scan"
                    onClicked: libraryRoot.setFeedback(channelOS.cancelMediaScan())
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: libraryRoot.scanConfirmVisible
        color: "#b8050c15"
        z: 210

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(700, parent.width * 0.64)
            height: 330
            radius: 12
            color: panelRaised
            border.color: accentBright
            border.width: 2

            Column {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 14
                Text {
                    text: pendingScanExisting ? "RESCAN MEDIA SOURCE" : "ADD MEDIA SOURCE"
                    color: accentBright
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                }
                Text {
                    text: pendingScanName
                    color: textPrimary
                    font.pixelSize: 23
                    font.weight: Font.DemiBold
                    width: parent.width
                    elide: Text.ElideRight
                }
                Text {
                    text: pendingScanPath
                    color: textSecondary
                    font.pixelSize: 13
                    width: parent.width
                    elide: Text.ElideMiddle
                }
                Rectangle { width: parent.width; height: 1; color: line }
                Text {
                    text: "Found " + pendingScanCount + " supported media file"
                          + (pendingScanCount === 1 ? "" : "s") + "."
                    color: textPrimary
                    font.pixelSize: 17
                }
                Text {
                    text: "ChannelOS will hash and inspect these files in the background. The originals stay exactly where they are and are never modified."
                    color: textSecondary
                    font.pixelSize: 14
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                Row {
                    anchors.right: parent.right
                    spacing: 12
                    Button {
                        width: 120
                        height: 42
                        text: "Cancel"
                        onClicked: libraryRoot.scanConfirmVisible = false
                    }
                    Button {
                        width: 170
                        height: 42
                        text: pendingScanExisting ? "Start Rescan" : "Index Source"
                        onClicked: libraryRoot.startPendingScan()
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: libraryRoot.removeConfirmVisible
        color: "#b8050c15"
        z: 220

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(680, parent.width * 0.62)
            height: 320
            radius: 12
            color: panelRaised
            border.color: warning
            border.width: 2

            Column {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 14
                Text {
                    text: "REMOVE SOURCE FROM CHANNEL OS?"
                    color: warning
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                }
                Text {
                    text: pendingRemoveName
                    color: textPrimary
                    font.pixelSize: 23
                    font.weight: Font.DemiBold
                    width: parent.width
                    elide: Text.ElideRight
                }
                Text {
                    text: pendingRemovePath
                    color: textSecondary
                    font.pixelSize: 13
                    width: parent.width
                    elide: Text.ElideMiddle
                }
                Rectangle { width: parent.width; height: 1; color: line }
                Text {
                    text: "This removes ChannelOS index entries only. Your original files and folders will not be deleted, moved, renamed, or modified."
                    color: textPrimary
                    font.pixelSize: 15
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                Row {
                    anchors.right: parent.right
                    spacing: 12
                    Button {
                        width: 120
                        height: 42
                        text: "Keep Source"
                        onClicked: libraryRoot.removeConfirmVisible = false
                    }
                    Button {
                        width: 190
                        height: 42
                        text: "Remove From Library"
                        onClicked: libraryRoot.removePendingSource()
                    }
                }
            }
        }
    }

    Timer {
        id: feedbackTimer
        interval: 5500
        repeat: false
        onTriggered: libraryRoot.feedbackMessage = ""
    }
}
