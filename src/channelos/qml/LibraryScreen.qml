pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: libraryRoot
    anchors.fill: parent
    z: 85

    property var hostWindow: null
    visible: hostWindow !== null && hostWindow.screen === "library"

    readonly property color appBackground: "#050c15"
    readonly property color railBackground: "#06111e"
    readonly property color panel: "#081625"
    readonly property color panelRaised: "#0d2035"
    readonly property color line: "#1a3550"
    readonly property color textPrimary: "#f4f7fb"
    readonly property color textSecondary: "#9fb0c2"
    readonly property color accent: "#1a91ff"
    readonly property color accentBright: "#42adff"

    property var snapshot: channelOS
                           ? (channelOS.librarySnapshot || ({}))
                           : ({})
    readonly property var preferences: channelOS ? channelOS.settings : ({})
    readonly property bool reducedMotion: Boolean(preferences.reducedMotion)
    readonly property int artworkWidth: Number(preferences.thumbnailWidth || 640)
    property var allItems: snapshot.items || []
    property var sources: snapshot.sources || []
    property var shelves: []
    readonly property int shelfCount: shelves.length
    property int selectedShelf: 0
    property int selectedColumn: 0
    property string expandedShelfId: ""
    property string query: ""
    property bool managerVisible: false
    property string clockText: ""

    function formatDuration(seconds) {
        var total = Math.max(0, Math.floor(Number(seconds) || 0))
        if (total <= 0)
            return "Unknown length"
        var hours = Math.floor(total / 3600)
        var minutes = Math.floor((total % 3600) / 60)
        if (hours > 0)
            return hours + "h " + (minutes > 0 ? minutes + "m" : "")
        return Math.max(1, minutes) + "m"
    }

    function formatBytes(bytes) {
        var value = Number(bytes) || 0
        if (value >= 1073741824)
            return (value / 1073741824).toFixed(1) + " GB"
        if (value >= 1048576)
            return (value / 1048576).toFixed(0) + " MB"
        if (value >= 1024)
            return (value / 1024).toFixed(0) + " KB"
        return value + " B"
    }

    function libraryBytes() {
        var total = 0
        for (var i = 0; i < allItems.length; ++i)
            total += Number(allItems[i].sizeBytes || 0)
        return total
    }

    function normalizedTitle(item) {
        return String(item.title || item.fileName || "Untitled Media")
    }

    function friendlyFormat(item) {
        var fileName = String(item.fileName || item.path || "")
        var dot = fileName.lastIndexOf(".")
        var extension = dot >= 0 ? fileName.substring(dot + 1).toLowerCase() : ""
        var knownExtensions = [
            "mp4", "m4v", "mov", "mkv", "webm", "avi", "ts", "m2ts",
            "mts", "mpg", "mpeg", "wmv", "flv"
        ]
        if (knownExtensions.indexOf(extension) >= 0)
            return extension.toUpperCase()

        var raw = String(item.containerFormat || "").split(",")[0].trim().toLowerCase()
        var aliases = {
            "matroska": "MKV",
            "quicktime": "MOV",
            "mpegts": "TS",
            "mpeg": "MPEG"
        }
        if (aliases[raw])
            return aliases[raw]
        return raw.length ? raw.toUpperCase() : "MEDIA"
    }

    function sortedCopy(items) {
        var result = items.slice(0)
        result.sort(function(a, b) {
            var first = libraryRoot.normalizedTitle(a).toLowerCase()
            var second = libraryRoot.normalizedTitle(b).toLowerCase()
            if (first < second) return -1
            if (first > second) return 1
            return 0
        })
        return result
    }

    function matchesQuery(item, needle) {
        var haystack = (normalizedTitle(item) + " "
                        + String(item.fileName || "") + " "
                        + String(item.sourceName || "") + " "
                        + String(item.containerFormat || "")).toLowerCase()
        return haystack.indexOf(needle) >= 0
    }

    function continueItems(items) {
        var result = []
        for (var i = 0; i < items.length; ++i) {
            if (Boolean(items[i].continueWatching))
                result.push(items[i])
        }
        result.sort(function(a, b) {
            return String(b.lastWatchedAt || "").localeCompare(
                        String(a.lastWatchedAt || ""))
        })
        return result
    }

    function defaultShelfId() {
        return continueItems(allItems).length ? "continue" : "all"
    }

    function remainingLabel(item) {
        if (!Boolean(item.continueWatching))
            return ""
        var remaining = Math.max(
                    0,
                    Number(item.durationSeconds || 0)
                    - Number(item.watchPositionSeconds || 0))
        return formatDuration(remaining) + " left"
    }

    function rebuildShelves() {
        var needle = String(query || "").trim().toLowerCase()
        var next = []
        var owned = sortedCopy(allItems)

        if (needle.length) {
            var matches = []
            for (var matchIndex = 0; matchIndex < owned.length; ++matchIndex) {
                if (matchesQuery(owned[matchIndex], needle))
                    matches.push(owned[matchIndex])
            }
            next.push({
                shelfId: "search",
                title: "SEARCH RESULTS",
                subtitle: matches.length + " matching owned media item"
                          + (matches.length === 1 ? "" : "s"),
                items: matches,
                featured: true
            })
        } else if (owned.length) {
            var continuing = continueItems(owned)
            if (continuing.length) {
                next.push({
                    shelfId: "continue",
                    title: "CONTINUE WATCHING",
                    subtitle: "Resume your saved On Demand playhead",
                    items: continuing,
                    featured: true
                })
            }

            next.push({
                shelfId: "all",
                title: "ALL MEDIA",
                subtitle: "Your complete indexed collection",
                items: owned,
                featured: true
            })

            for (var sourceIndex = 0; sourceIndex < sources.length; ++sourceIndex) {
                var source = sources[sourceIndex]
                var sourceItems = []
                var sourcePath = String(source.path || "")
                for (var itemIndex = 0; itemIndex < owned.length; ++itemIndex) {
                    if (String(owned[itemIndex].sourceRoot || "") === sourcePath)
                        sourceItems.push(owned[itemIndex])
                }
                if (sourceItems.length) {
                    next.push({
                        shelfId: "source:" + sourcePath,
                        title: String(source.name || "MEDIA SOURCE").toUpperCase(),
                        subtitle: sourceItems.length + " indexed item"
                                  + (sourceItems.length === 1 ? "" : "s"),
                        items: sourceItems,
                        featured: false
                    })
                }
            }

            var featureLength = []
            var shortForm = []
            for (var durationIndex = 0; durationIndex < owned.length; ++durationIndex) {
                var duration = Number(owned[durationIndex].durationSeconds || 0)
                if (duration >= 3600)
                    featureLength.push(owned[durationIndex])
                else if (duration > 0 && duration < 3600)
                    shortForm.push(owned[durationIndex])
            }
            if (featureLength.length) {
                next.push({
                    shelfId: "feature",
                    title: "FEATURE LENGTH",
                    subtitle: "Long-form movies, recordings, and specials",
                    items: featureLength,
                    featured: false
                })
            }
            if (shortForm.length) {
                next.push({
                    shelfId: "short",
                    title: "SHORT FORM",
                    subtitle: "Episodes, clips, and shorter programs",
                    items: shortForm,
                    featured: false
                })
            }
        }

        shelves = next
        var expandedStillExists = false
        for (var shelfIndex = 0; shelfIndex < shelves.length; ++shelfIndex) {
            if (String(shelves[shelfIndex].shelfId || "") === expandedShelfId) {
                expandedStillExists = true
                break
            }
        }
        if (!expandedStillExists)
            expandedShelfId = defaultShelfId()
        selectedShelf = Math.max(0, Math.min(selectedShelf, shelves.length - 1))
        var selectedItems = shelves.length ? (shelves[selectedShelf].items || []) : []
        selectedColumn = Math.max(0, Math.min(selectedColumn, selectedItems.length - 1))
        publishInfoSelection()
        Qt.callLater(ensureSelectionVisible)
    }

    function selectedItem() {
        if (!shelves.length || selectedShelf < 0 || selectedShelf >= shelves.length)
            return ({})
        var items = shelves[selectedShelf].items || []
        if (!items.length || selectedColumn < 0 || selectedColumn >= items.length)
            return ({})
        return items[selectedColumn]
    }

    function publishInfoSelection() {
        if (hostWindow)
            hostWindow.libraryInfoItem = selectedItem()
    }

    function selectCard(shelfIndex, columnIndex) {
        selectedShelf = Math.max(0, Math.min(shelves.length - 1, shelfIndex))
        var items = shelves.length ? (shelves[selectedShelf].items || []) : []
        selectedColumn = Math.max(0, Math.min(items.length - 1, columnIndex))
        publishInfoSelection()
        ensureSelectionVisible()
    }

    function shelfExpanded(shelfIndex) {
        if (shelfIndex < 0 || shelfIndex >= shelves.length)
            return false
        if (String(query || "").trim().length)
            return true
        return String(shelves[shelfIndex].shelfId || "") === expandedShelfId
    }

    function toggleShelf(shelfIndex) {
        if (shelfIndex < 0 || shelfIndex >= shelves.length)
            return
        selectCard(shelfIndex, selectedColumn)
        var shelfId = String(shelves[shelfIndex].shelfId || "")
        if (String(query || "").trim().length)
            expandedShelfId = shelfId
        else
            expandedShelfId = expandedShelfId === shelfId ? "" : shelfId
        Qt.callLater(ensureSelectionVisible)
    }

    function moveShelf(delta) {
        if (!shelves.length)
            return
        selectCard(selectedShelf + delta, selectedColumn)
    }

    function moveColumn(delta) {
        if (!shelves.length)
            return
        if (!shelfExpanded(selectedShelf)) {
            if (delta > 0)
                toggleShelf(selectedShelf)
            return
        }
        var items = shelves[selectedShelf].items || []
        if (!items.length)
            return
        if (delta < 0 && selectedColumn === 0) {
            toggleShelf(selectedShelf)
            return
        }
        selectedColumn = Math.max(0, Math.min(items.length - 1, selectedColumn + delta))
        publishInfoSelection()
        ensureSelectionVisible()
    }

    function ensureSelectionVisible() {
        if (!shelves.length)
            return
        shelvesList.positionViewAtIndex(selectedShelf, ListView.Contain)
        Qt.callLater(function() {
            var shelfItem = shelvesList.itemAtIndex(selectedShelf)
            if (shelfItem && shelfItem.expanded && shelfItem.cardListView)
                shelfItem.cardListView.positionViewAtIndex(selectedColumn, ListView.Contain)
        })
    }

    function activateSelection() {
        if (!shelfExpanded(selectedShelf)) {
            toggleShelf(selectedShelf)
            return
        }
        playSelected()
    }

    function handleBack() {
        if (managerVisible) {
            returnFromManager()
        } else if (searchField.activeFocus) {
            searchField.focus = false
            forceActiveFocus()
        } else if (query.length) {
            query = ""
        } else if (hostWindow) {
            hostWindow.screen = "home"
        }
    }

    function handleControllerIntent(intent: string): void {
        if (!hostWindow || hostWindow.screen !== "library")
            return
        if (intent === "BACK") {
            handleBack()
            return
        }
        if (managerVisible || searchField.activeFocus)
            return
        if (intent === "LEFT")
            moveColumn(-1)
        else if (intent === "RIGHT")
            moveColumn(1)
        else if (intent === "UP")
            moveShelf(-1)
        else if (intent === "DOWN")
            moveShelf(1)
        else if (intent === "SELECT")
            activateSelection()
        else if (intent === "ADD_MEDIA_SOURCE")
            openManager()
    }

    function playSelected() {
        var item = selectedItem()
        if (!item.assetId)
            return
        hostWindow.screen = "ondemand"
        Qt.callLater(function() {
            var result = channelOS.playLibraryAsset(String(item.assetId))
            if (!result || !result.ok)
                hostWindow.screen = "library"
        })
    }

    function openManager() {
        managerVisible = true
        sourceManager.forceActiveFocus()
    }

    function returnFromManager() {
        managerVisible = false
        channelOS.refreshLibrary()
        forceActiveFocus()
    }

    function updateClock() {
        clockText = Qt.formatTime(new Date(), "h:mm AP")
    }

    function cardColor(item, shift) {
        var palette = [
            ["#163b5d", "#07131f"],
            ["#27445e", "#0a1522"],
            ["#244238", "#081712"],
            ["#4a314d", "#160b19"],
            ["#4b3d25", "#171108"],
            ["#293a63", "#0a1022"]
        ]
        var key = String(item.assetId || item.title || "media")
        var total = shift || 0
        for (var i = 0; i < key.length; ++i)
            total += key.charCodeAt(i)
        return palette[Math.abs(total) % palette.length]
    }

    onQueryChanged: {
        selectedShelf = 0
        selectedColumn = 0
        expandedShelfId = String(query || "").trim().length
                          ? "search" : defaultShelfId()
        rebuildShelves()
    }
    onAllItemsChanged: rebuildShelves()
    onSourcesChanged: rebuildShelves()
    onHostWindowChanged: publishInfoSelection()
    onSelectedShelfChanged: publishInfoSelection()
    onSelectedColumnChanged: publishInfoSelection()

    onVisibleChanged: {
        if (visible) {
            channelOS.refreshLibrary()
            updateClock()
            rebuildShelves()
            forceActiveFocus()
        }
    }

    Component.onCompleted: {
        updateClock()
        rebuildShelves()
        publishInfoSelection()
    }

    Connections {
        target: channelOS
        function onLibraryChanged() {
            libraryRoot.snapshot = channelOS.librarySnapshot || ({})
            libraryRoot.rebuildShelves()
        }
    }

    Timer {
        interval: 1000
        repeat: true
        running: libraryRoot.visible
        onTriggered: libraryRoot.updateClock()
    }

    Shortcut {
        sequence: "Left"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.moveColumn(-1)
    }
    Shortcut {
        sequence: "Right"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.moveColumn(1)
    }
    Shortcut {
        sequence: "Up"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.moveShelf(-1)
    }
    Shortcut {
        sequence: "Down"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.moveShelf(1)
    }
    Shortcut {
        sequence: "Return"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.activateSelection()
    }
    Shortcut {
        sequence: "Space"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.activateSelection()
    }
    Shortcut {
        sequence: "Ctrl+F"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible
        onActivated: searchField.forceActiveFocus()
    }
    Shortcut {
        sequence: "M"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.openManager()
    }
    Shortcut {
        sequence: "A"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible && !searchField.activeFocus
        onActivated: libraryRoot.openManager()
    }
    Shortcut {
        sequence: "Escape"
        enabled: libraryRoot.visible && !libraryRoot.managerVisible
        onActivated: libraryRoot.handleBack()
    }

    Rectangle {
        anchors.fill: parent
        color: appBackground
    }

    Rectangle {
        id: navigationRail
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: Math.max(292, Math.min(360, parent.width * 0.22))
        color: railBackground
        border.color: line
        border.width: 1

        Row {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 30
            anchors.topMargin: 28
            spacing: 2
            Text {
                text: "Channel"
                color: textPrimary
                font.pixelSize: 31
                font.weight: Font.DemiBold
            }
            Text {
                text: "OS"
                color: accentBright
                font.pixelSize: 31
                font.weight: Font.DemiBold
            }
        }

        Text {
            id: railClock
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 30
            anchors.topMargin: 94
            text: clockText
            color: textPrimary
            font.pixelSize: 22
        }

        Column {
            id: navigationItems
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: railClock.bottom
            anchors.leftMargin: 20
            anchors.rightMargin: 20
            anchors.topMargin: 26
            spacing: 7

            Repeater {
                model: [
                    { label: "Home", action: "home" },
                    { label: "Guide", action: "guide" },
                    { label: "Library / On Demand", action: "library" },
                    { label: "Search", action: "search" },
                    { label: "Channels", action: "channels" },
                    { label: "Manage Sources", action: "sources" }
                ]

                delegate: Rectangle {
                    id: navDelegate
                    required property var modelData
                    width: navigationItems.width
                    height: 48
                    radius: 6
                    color: modelData.action === "library" ? "#103568"
                           : navMouse.containsMouse ? "#0d2744" : "transparent"
                    border.color: modelData.action === "library"
                                  ? libraryRoot.accentBright : "transparent"
                    border.width: modelData.action === "library" ? 1 : 0

                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 17
                        text: navDelegate.modelData.label
                        color: navDelegate.modelData.action === "library"
                               ? libraryRoot.textPrimary : libraryRoot.textSecondary
                        font.pixelSize: 16
                        font.weight: navDelegate.modelData.action === "library"
                                     ? Font.DemiBold : Font.Normal
                    }

                    MouseArea {
                        id: navMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            if (navDelegate.modelData.action === "home")
                                libraryRoot.hostWindow.screen = "home"
                            else if (navDelegate.modelData.action === "guide") {
                                channelOS.refresh()
                                libraryRoot.hostWindow.screen = "guide"
                            } else if (navDelegate.modelData.action === "search")
                                searchField.forceActiveFocus()
                            else if (navDelegate.modelData.action === "channels") {
                                channelOS.refreshBroadcaster()
                                libraryRoot.hostWindow.screen = "broadcaster"
                            } else if (navDelegate.modelData.action === "sources")
                                libraryRoot.openManager()
                        }
                    }
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 22
            height: 112
            radius: 8
            color: "#091827"
            border.color: line

            Column {
                anchors.fill: parent
                anchors.margins: 15
                spacing: 7
                Text {
                    text: "OWNED LIBRARY"
                    color: textPrimary
                    font.pixelSize: 13
                    font.weight: Font.Bold
                    font.letterSpacing: 1.5
                }
                Text {
                    text: allItems.length + " media item" + (allItems.length === 1 ? "" : "s")
                          + "  •  " + sources.length + " source" + (sources.length === 1 ? "" : "s")
                    color: textSecondary
                    font.pixelSize: 12
                }
                Text {
                    text: libraryRoot.formatBytes(libraryRoot.libraryBytes()) + " indexed"
                    color: accentBright
                    font.pixelSize: 13
                }
                Rectangle {
                    width: parent.width
                    height: 5
                    radius: 3
                    color: "#142b40"
                    Rectangle {
                        width: parent.width
                        height: parent.height
                        radius: 3
                        color: accent
                        opacity: allItems.length ? 0.75 : 0.18
                    }
                }
            }
        }
    }

    Item {
        id: browseArea
        anchors.left: navigationRail.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        visible: !libraryRoot.managerVisible

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#071728" }
                GradientStop { position: 0.55; color: "#050d18" }
                GradientStop { position: 1.0; color: "#050c15" }
            }
        }

        Item {
            id: browseHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 118

            Column {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 34
                anchors.topMargin: 25
                spacing: 5
                Text {
                    text: "Library / On Demand"
                    color: textPrimary
                    font.pixelSize: 29
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Browse and play the media you own."
                    color: textSecondary
                    font.pixelSize: 14
                }
            }

            TextField {
                id: searchField
                anchors.right: manageButton.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(310, parent.width * 0.28)
                height: 44
                placeholderText: "Search your library…"
                placeholderTextColor: "#71869c"
                color: textPrimary
                text: libraryRoot.query
                onTextChanged: libraryRoot.query = text
                background: Rectangle {
                    radius: 7
                    color: panelRaised
                    border.color: searchField.activeFocus ? accentBright : line
                    border.width: searchField.activeFocus ? 2 : 1
                }
            }

            Button {
                id: manageButton
                anchors.right: parent.right
                anchors.rightMargin: 28
                anchors.verticalCenter: parent.verticalCenter
                width: 154
                height: 44
                text: "Manage Sources"
                onClicked: libraryRoot.openManager()
            }
        }

        Rectangle {
            id: selectedBanner
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: browseHeader.bottom
            anchors.leftMargin: 34
            anchors.rightMargin: 28
            height: 92
            radius: 9
            color: "#0a1b2d"
            border.color: line
            visible: Boolean(libraryRoot.selectedItem().assetId)

            readonly property var item: libraryRoot.selectedItem()

            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 7
                radius: 4
                color: accentBright
            }

            Column {
                anchors.left: parent.left
                anchors.right: playButton.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 24
                anchors.rightMargin: 20
                spacing: 5
                Text {
                    text: libraryRoot.normalizedTitle(selectedBanner.item)
                    color: textPrimary
                    font.pixelSize: 21
                    font.weight: Font.DemiBold
                    width: parent.width
                    elide: Text.ElideRight
                }
                Text {
                    text: libraryRoot.formatDuration(selectedBanner.item.durationSeconds)
                          + "  •  " + libraryRoot.friendlyFormat(selectedBanner.item)
                          + "  •  " + String(selectedBanner.item.sourceName || "Owned Media")
                          + (Boolean(selectedBanner.item.continueWatching)
                             ? "  •  " + libraryRoot.remainingLabel(selectedBanner.item)
                             : "")
                    color: textSecondary
                    font.pixelSize: 13
                    width: parent.width
                    elide: Text.ElideRight
                }
            }

            Button {
                id: playButton
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 18
                width: 172
                height: 44
                text: Boolean(selectedBanner.item.continueWatching)
                      ? "Resume On Demand" : "Play On Demand"
                onClicked: libraryRoot.playSelected()
            }
        }

        ListView {
            id: shelvesList
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: selectedBanner.visible ? selectedBanner.bottom : browseHeader.bottom
            anchors.bottom: browseFooter.top
            anchors.leftMargin: 34
            anchors.rightMargin: 0
            anchors.topMargin: 14
            anchors.bottomMargin: 8
            clip: true
            spacing: 13
            model: libraryRoot.shelves
            currentIndex: libraryRoot.selectedShelf
            boundsBehavior: Flickable.StopAtBounds

            delegate: Item {
                id: shelfDelegate
                required property int index
                required property var modelData
                property int shelfIndex: index
                property var shelfData: modelData
                property bool expanded: libraryRoot.shelfExpanded(shelfIndex)
                width: shelvesList.width
                height: expanded ? (shelfData.featured ? 222 : 179) : 42
                property alias cardListView: cardList

                Behavior on height {
                    NumberAnimation {
                        duration: libraryRoot.reducedMotion ? 0 : 150
                        easing.type: Easing.OutCubic
                    }
                }

                Rectangle {
                    id: shelfHeading
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: 24
                    height: 38
                    radius: 5
                    color: shelfDelegate.shelfIndex === libraryRoot.selectedShelf
                           ? "#0d2035" : "transparent"

                    Text {
                        id: shelfChevron
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        text: shelfDelegate.expanded ? "▾" : "▸"
                        color: shelfDelegate.shelfIndex === libraryRoot.selectedShelf
                               ? accentBright : textSecondary
                        font.pixelSize: 16
                    }

                    Text {
                        id: shelfTitle
                        anchors.left: shelfChevron.right
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(implicitWidth, shelfHeading.width * 0.52)
                        text: shelfDelegate.shelfData.title
                        color: textPrimary
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Text {
                        id: shelfSubtitle
                        anchors.left: shelfTitle.right
                        anchors.right: shelfCount.left
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: shelfDelegate.shelfData.subtitle
                        color: textSecondary
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Text {
                        id: shelfCount
                        anchors.right: parent.right
                        anchors.rightMargin: 11
                        anchors.verticalCenter: parent.verticalCenter
                        text: String((shelfDelegate.shelfData.items || []).length) + " items"
                        color: accentBright
                        font.pixelSize: 12
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            libraryRoot.toggleShelf(shelfDelegate.shelfIndex)
                            libraryRoot.forceActiveFocus()
                        }
                    }
                }

                ListView {
                    id: cardList
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: shelfHeading.bottom
                    anchors.bottom: parent.bottom
                    orientation: ListView.Horizontal
                    visible: shelfDelegate.expanded
                    opacity: shelfDelegate.expanded ? 1 : 0
                    spacing: 11
                    clip: true
                    model: shelfDelegate.shelfData.items || []
                    currentIndex: shelfDelegate.shelfIndex === libraryRoot.selectedShelf
                                  ? libraryRoot.selectedColumn : -1
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: Rectangle {
                        id: mediaCard
                        required property int index
                        required property var modelData
                        width: shelfDelegate.shelfData.featured ? 304 : 232
                        height: cardList.height - 3
                        radius: 8
                        property bool selected: shelfDelegate.shelfIndex === libraryRoot.selectedShelf
                                                && index === libraryRoot.selectedColumn
                        property var colors: libraryRoot.cardColor(modelData, index)
                        property string artworkUrl: String(modelData.artworkUrl || "")
                        property bool artworkReady: artworkImage.status === Image.Ready
                        property bool shelfOpen: shelfDelegate.expanded
                        color: colors[0]
                        border.color: selected ? accentBright : "#243d55"
                        border.width: selected ? 3 : 1

                        gradient: Gradient {
                            GradientStop { position: 0.0; color: mediaCard.colors[0] }
                            GradientStop { position: 0.68; color: mediaCard.colors[1] }
                            GradientStop { position: 1.0; color: "#050a11" }
                        }

                        function requestArtwork() {
                            if (!shelfDelegate.expanded || artworkUrl.length)
                                return
                            if (channelOS && typeof channelOS.requestLibraryArtwork === "function") {
                                var resolved = channelOS.requestLibraryArtwork(
                                            String(mediaCard.modelData.assetId || ""))
                                if (resolved)
                                    artworkUrl = String(resolved)
                            }
                        }

                        Component.onCompleted: requestArtwork()
                        onShelfOpenChanged: requestArtwork()

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: parent.height * 0.56
                            color: "transparent"

                            Image {
                                id: artworkImage
                                anchors.fill: parent
                                source: mediaCard.artworkUrl
                                sourceSize.width: libraryRoot.artworkWidth
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                autoTransform: true
                                opacity: status === Image.Ready ? 1.0 : 0.0

                                Behavior on opacity {
                                    NumberAnimation {
                                        duration: libraryRoot.reducedMotion ? 0 : 180
                                    }
                                }
                            }

                            Rectangle {
                                anchors.fill: parent
                                visible: mediaCard.artworkReady
                                gradient: Gradient {
                                    GradientStop { position: 0.0; color: "#05000000" }
                                    GradientStop { position: 0.72; color: "#18000000" }
                                    GradientStop { position: 1.0; color: "#9a050a11" }
                                }
                            }

                            Text {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.margins: 13
                                width: parent.width - 26
                                elide: Text.ElideRight
                                text: libraryRoot.friendlyFormat(mediaCard.modelData)
                                visible: !mediaCard.artworkReady
                                color: "#d9ecff"
                                opacity: 0.78
                                font.pixelSize: mediaCard.width > 260 ? 22 : 17
                                font.weight: Font.Bold
                                font.letterSpacing: 2.5
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 12
                                text: "▶"
                                color: accentBright
                                opacity: mediaCard.selected ? 1.0 : 0.58
                                font.pixelSize: 22
                            }
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: parent.height * 0.48
                            color: "#c9060c14"

                            Column {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 11
                                spacing: 4
                                Text {
                                    text: libraryRoot.normalizedTitle(mediaCard.modelData)
                                    color: textPrimary
                                    font.pixelSize: mediaCard.width > 260 ? 15 : 13
                                    font.weight: Font.DemiBold
                                    width: parent.width
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: Boolean(mediaCard.modelData.continueWatching)
                                          ? libraryRoot.remainingLabel(mediaCard.modelData)
                                            + "  •  "
                                            + String(mediaCard.modelData.sourceName || "Owned Media")
                                          : libraryRoot.formatDuration(mediaCard.modelData.durationSeconds)
                                            + "  •  "
                                            + String(mediaCard.modelData.sourceName || "Owned Media")
                                    color: textSecondary
                                    font.pixelSize: 11
                                    width: parent.width
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.leftMargin: 11
                            anchors.rightMargin: 11
                            anchors.bottomMargin: 5
                            height: 4
                            radius: 2
                            visible: Boolean(mediaCard.modelData.continueWatching)
                            color: "#31465b"

                            Rectangle {
                                width: parent.width * Math.max(
                                           0,
                                           Math.min(
                                               1,
                                               Number(mediaCard.modelData.watchProgress || 0)))
                                height: parent.height
                                radius: 2
                                color: accentBright
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                libraryRoot.selectCard(shelfDelegate.shelfIndex, mediaCard.index)
                                libraryRoot.forceActiveFocus()
                            }
                            onDoubleClicked: {
                                libraryRoot.selectCard(shelfDelegate.shelfIndex, mediaCard.index)
                                libraryRoot.playSelected()
                            }
                        }
                    }
                }
            }
        }

        Column {
            anchors.centerIn: shelvesList
            spacing: 12
            visible: shelves.length === 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: allItems.length === 0 ? "YOUR LIBRARY IS READY" : "NO MATCHES"
                color: textPrimary
                font.pixelSize: 24
                font.weight: Font.DemiBold
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: allItems.length === 0
                      ? "Add a media source and ChannelOS will build these shelves from your files."
                      : "Try a different title, filename, source, or format."
                color: textSecondary
                font.pixelSize: 14
            }
            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: allItems.length === 0
                text: "Manage Media Sources"
                onClicked: libraryRoot.openManager()
            }
        }

        Rectangle {
            id: browseFooter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 50
            color: "#06111e"
            border.color: line

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 30
                spacing: 24
                Text { text: "ARROWS  Browse"; color: textSecondary; font.pixelSize: 12 }
                Text { text: "ENTER  Open / Play"; color: textSecondary; font.pixelSize: 12 }
                Text { text: "I  Info"; color: textSecondary; font.pixelSize: 12 }
                Text { text: "CTRL+F  Search"; color: textSecondary; font.pixelSize: 12 }
                Text { text: "M  Manage Sources"; color: textSecondary; font.pixelSize: 12 }
                Text { text: "ESC  Home"; color: textSecondary; font.pixelSize: 12 }
            }
        }
    }

    LibraryManagerScreen {
        id: sourceManager
        anchors.fill: parent
        hostWindow: libraryRoot.hostWindow
        browseHost: libraryRoot
        active: libraryRoot.managerVisible
        z: 100
    }
}
