import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1600
    height: 900
    minimumWidth: 1100
    minimumHeight: 650
    visible: false
    color: "#050c15"
    title: "ChannelOS"

    readonly property color background: "#050c15"
    readonly property color panel: "#081625"
    readonly property color panelRaised: "#0d2035"
    readonly property color panelSoft: "#10283f"
    readonly property color line: "#1a3550"
    readonly property color textPrimary: "#f4f7fb"
    readonly property color textSecondary: "#9fb0c2"
    readonly property color accent: "#1a91ff"
    readonly property color accentBright: "#42adff"
    readonly property color liveRed: "#ff4a4a"

    property string screen: "home"
    property int homeSelection: 0
    property int selectedRow: 0
    property int selectedProgram: 0
    property string statusMessage: ""
    property var snapshot: channelOS.snapshot
    property var rows: snapshot.rows || []
    property real horizonStartMs: snapshot.horizonStartMs || 0
    property real horizonEndMs: snapshot.horizonEndMs || 1
    property real generatedAtMs: snapshot.generatedAtMs || 0
    property real horizonSpanMs: Math.max(1, horizonEndMs - horizonStartMs)

    function programsForRow(rowIndex) {
        if (!rows || rowIndex < 0 || rowIndex >= rows.length)
            return []
        return rows[rowIndex].programs || []
    }

    function currentProgramIndex(rowIndex) {
        var programs = programsForRow(rowIndex)
        for (var i = 0; i < programs.length; ++i) {
            if (programs[i].isCurrent)
                return i
        }
        return programs.length > 0 ? 0 : -1
    }

    function selectRow(rowIndex) {
        if (!rows || rows.length === 0)
            return
        selectedRow = Math.max(0, Math.min(rows.length - 1, rowIndex))
        selectedProgram = currentProgramIndex(selectedRow)
        guideList.positionViewAtIndex(selectedRow, ListView.Contain)
    }

    function selectedRowData() {
        if (!rows || rows.length === 0 || selectedRow < 0 || selectedRow >= rows.length)
            return ({ channelNumber: 1, displayNumber: "001", channelName: "Unassigned", programs: [] })
        return rows[selectedRow]
    }

    function selectedProgramData() {
        var programs = programsForRow(selectedRow)
        if (selectedProgram < 0 || selectedProgram >= programs.length)
            return ({ title: "No Programming", startMs: 0, endMs: 0, isCurrent: false })
        return programs[selectedProgram]
    }

    function formatClock(ms) {
        if (!ms)
            return "--:--"
        var d = new Date(ms)
        var hours = d.getHours()
        var minutes = d.getMinutes()
        var suffix = hours >= 12 ? "PM" : "AM"
        hours = hours % 12
        if (hours === 0)
            hours = 12
        return hours + ":" + (minutes < 10 ? "0" : "") + minutes + " " + suffix
    }

    function formatDate(ms) {
        if (!ms)
            return ""
        var d = new Date(ms)
        return d.toLocaleDateString(Qt.locale(), "ddd, MMM d")
    }

    function showStatus(message) {
        statusMessage = message
        statusTimer.restart()
    }

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_G) {
            screen = "guide"
            selectRow(selectedRow)
            event.accepted = true
            return
        }
        if (event.key === Qt.Key_Escape || event.key === Qt.Key_Backspace) {
            if (screen === "guide")
                screen = "home"
            else
                Qt.quit()
            event.accepted = true
            return
        }

        if (screen === "home") {
            if (event.key === Qt.Key_Up) {
                homeSelection = Math.max(0, homeSelection - 1)
                event.accepted = true
            } else if (event.key === Qt.Key_Down) {
                homeSelection = Math.min(4, homeSelection + 1)
                event.accepted = true
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                if (homeSelection === 1) {
                    screen = "guide"
                    selectRow(selectedRow)
                } else if (homeSelection === 0) {
                    showStatus("Continue Watching will connect to the Viewer Clock in the playback slice")
                } else {
                    showStatus("This section is reserved for the next couch UI slice")
                }
                event.accepted = true
            }
            return
        }

        if (screen === "guide") {
            if (event.key === Qt.Key_Up) {
                selectRow(selectedRow - 1)
                event.accepted = true
            } else if (event.key === Qt.Key_Down) {
                selectRow(selectedRow + 1)
                event.accepted = true
            } else if (event.key === Qt.Key_Left) {
                selectedProgram = Math.max(0, selectedProgram - 1)
                event.accepted = true
            } else if (event.key === Qt.Key_Right) {
                var programs = programsForRow(selectedRow)
                selectedProgram = Math.min(Math.max(0, programs.length - 1), selectedProgram + 1)
                event.accepted = true
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                showStatus("Tune selection captured — playback surface is the next plumbing slice")
                event.accepted = true
            } else if (event.key === Qt.Key_Home) {
                selectedProgram = currentProgramIndex(selectedRow)
                event.accepted = true
            }
        }
    }

    Component.onCompleted: {
        forceActiveFocus()
        if (rows.length > 0)
            selectRow(0)
    }

    onRowsChanged: {
        if (rows.length > 0)
            selectRow(Math.min(selectedRow, rows.length - 1))
    }

    Timer {
        interval: 15000
        repeat: true
        running: true
        onTriggered: channelOS.refresh()
    }

    Timer {
        id: statusTimer
        interval: 2600
        repeat: false
        onTriggered: root.statusMessage = ""
    }

    Rectangle {
        anchors.fill: parent
        color: root.background
    }

    // Startup / Home: classic split television landing page.
    Item {
        anchors.fill: parent
        visible: root.screen === "home"

        Rectangle {
            id: homeLeft
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: homeCards.top
            width: parent.width * 0.34
            color: "#071322"
            border.color: root.line
            border.width: 1

            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#0a1c32" }
                    GradientStop { position: 1.0; color: "#06101d" }
                }
                opacity: 0.72
            }

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 54
                spacing: 12

                Row {
                    spacing: 2
                    Text { text: "Channel"; color: root.textPrimary; font.pixelSize: 38; font.weight: Font.DemiBold }
                    Text { text: "OS"; color: root.accentBright; font.pixelSize: 38; font.weight: Font.DemiBold }
                }

                Item { width: 1; height: 18 }
                Text { text: root.formatClock(root.generatedAtMs); color: root.textPrimary; font.pixelSize: 31 }
                Text { text: root.formatDate(root.generatedAtMs); color: root.textSecondary; font.pixelSize: 18 }
                Rectangle { width: parent.width; height: 1; color: root.line }
                Text { text: "Welcome back."; color: root.textPrimary; font.pixelSize: 28; font.weight: Font.DemiBold }
                Text {
                    text: "Your home for live television and\nyour own media library."
                    color: root.textSecondary
                    font.pixelSize: 18
                    lineHeight: 1.25
                }
                Item { width: 1; height: 12 }

                Repeater {
                    model: ["Continue Watching", "Open Guide", "Library / On Demand", "Channels", "Settings"]
                    delegate: Rectangle {
                        width: parent.width
                        height: 54
                        radius: 6
                        color: index === root.homeSelection ? "#12396a" : "transparent"
                        border.color: index === root.homeSelection ? root.accentBright : "transparent"
                        border.width: index === root.homeSelection ? 2 : 0

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 22
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData
                            color: index === root.homeSelection ? root.textPrimary : root.textSecondary
                            font.pixelSize: 20
                            font.weight: index === root.homeSelection ? Font.DemiBold : Font.Normal
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 18
                            anchors.verticalCenter: parent.verticalCenter
                            text: "›"
                            color: index === root.homeSelection ? root.accentBright : root.textSecondary
                            font.pixelSize: 28
                        }
                    }
                }
            }
        }

        Rectangle {
            id: homePreview
            anchors.left: homeLeft.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: homeCards.top
            anchors.margins: 18
            radius: 9
            clip: true
            color: "#10151b"
            border.color: "#173653"
            border.width: 1

            Canvas {
                id: staticCanvas
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.fillStyle = "#111820"
                    ctx.fillRect(0, 0, width, height)
                    for (var i = 0; i < 1800; ++i) {
                        var g = 45 + Math.floor(Math.random() * 160)
                        ctx.fillStyle = "rgb(" + g + "," + g + "," + g + ")"
                        var size = 1 + Math.floor(Math.random() * 3)
                        ctx.fillRect(Math.random() * width, Math.random() * height, size, size)
                    }
                }
            }
            Timer {
                interval: 95
                repeat: true
                running: root.screen === "home"
                onTriggered: staticCanvas.requestPaint()
            }

            Rectangle {
                anchors.fill: parent
                color: "#020913"
                opacity: 0.17
            }
            Column {
                anchors.centerIn: parent
                spacing: 12
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "CH 001"; color: root.textPrimary; font.pixelSize: 56; font.letterSpacing: 5 }
                Rectangle { width: 230; height: 2; color: root.accent; anchors.horizontalCenter: parent.horizontalCenter }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "UNASSIGNED"; color: root.accentBright; font.pixelSize: 28; font.letterSpacing: 8 }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "NO PROGRAMMING"; color: "#c5ccd4"; font.pixelSize: 16; font.letterSpacing: 4 }
            }

            Row {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 18
                spacing: 12
                Rectangle { width: 10; height: 10; radius: 5; color: root.accent; anchors.verticalCenter: parent.verticalCenter }
                Text { text: "CH 001"; color: root.textPrimary; font.pixelSize: 19 }
            }
        }

        Rectangle {
            id: homeCards
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: parent.height * 0.29
            color: "#07111e"
            border.color: root.line
            border.width: 1

            Row {
                anchors.fill: parent
                anchors.margins: 28
                spacing: 18

                Repeater {
                    model: [
                        { title: "Guide", subtitle: "See what's on now and next." },
                        { title: "Library", subtitle: "Browse your owned media." },
                        { title: "Last Channel", subtitle: "Return to your recent channel." },
                        { title: "Channel Browser", subtitle: "Explore the active lineup." }
                    ]
                    delegate: Rectangle {
                        width: (homeCards.width - 56 - 54) / 4
                        height: parent.height
                        radius: 10
                        color: index === 0 ? "#102b50" : "#0b1b2e"
                        border.color: index === 0 ? root.accentBright : "#17324a"
                        border.width: index === 0 ? 2 : 1

                        Column {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 24
                            spacing: 10
                            Text { text: modelData.title; color: root.textPrimary; font.pixelSize: 24; font.weight: Font.DemiBold }
                            Text { text: modelData.subtitle; color: root.textSecondary; font.pixelSize: 16; wrapMode: Text.WordWrap; width: parent.width }
                        }
                    }
                }
            }
        }
    }

    // Full Guide: authoritative ChannelOS schedule projected into an Xfinity-style grid.
    Item {
        id: guideScreen
        anchors.fill: parent
        visible: root.screen === "guide"

        readonly property var rowData: root.selectedRowData()
        readonly property var programData: root.selectedProgramData()
        readonly property real channelColumnWidth: 255

        Rectangle {
            id: guideHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: parent.height * 0.35
            color: "#071322"
            border.color: root.line
            border.width: 1

            Column {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 36
                width: parent.width * 0.53
                spacing: 10

                Row {
                    spacing: 12
                    Text { text: "Channel"; color: root.textPrimary; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { text: "OS"; color: root.accentBright; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { text: "  |  GUIDE"; color: root.accentBright; font.pixelSize: 22; anchors.verticalCenter: parent.verticalCenter }
                }
                Item { width: 1; height: 8 }
                Text { text: guideScreen.rowData.displayNumber + "  " + guideScreen.rowData.channelName; color: root.accentBright; font.pixelSize: 20; font.letterSpacing: 2 }
                Text { text: guideScreen.programData.title; color: root.textPrimary; font.pixelSize: 36; font.weight: Font.DemiBold; elide: Text.ElideRight; width: parent.width }
                Text {
                    text: guideScreen.programData.startMs ? root.formatClock(guideScreen.programData.startMs) + "  –  " + root.formatClock(guideScreen.programData.endMs) : "No scheduled programming"
                    color: root.textSecondary
                    font.pixelSize: 20
                }
                Text {
                    text: guideScreen.programData.isCurrent ? "NOW PLAYING • LIVE" : (guideScreen.programData.isPast ? "EARLIER" : "UPCOMING")
                    color: guideScreen.programData.isCurrent ? root.liveRed : root.textSecondary
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
            }

            Rectangle {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 26
                width: parent.width * 0.38
                radius: 8
                color: "#0b1b2b"
                border.color: root.accent
                border.width: guideScreen.programData.isCurrent ? 1 : 0

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#12304a" }
                        GradientStop { position: 0.55; color: "#0a1a29" }
                        GradientStop { position: 1.0; color: "#07111c" }
                    }
                    radius: 7
                }
                Text {
                    anchors.centerIn: parent
                    text: guideScreen.rowData.displayNumber + "\n" + guideScreen.rowData.channelName
                    horizontalAlignment: Text.AlignHCenter
                    color: root.textPrimary
                    font.pixelSize: 28
                    lineHeight: 1.25
                }
                Row {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: 18
                    spacing: 8
                    Rectangle { width: 9; height: 9; radius: 5; color: root.liveRed; anchors.verticalCenter: parent.verticalCenter; visible: guideScreen.programData.isCurrent }
                    Text { text: guideScreen.programData.isCurrent ? "LIVE" : "PROGRAM PREVIEW"; color: root.textPrimary; font.pixelSize: 15 }
                }
            }

            Text {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: 36
                anchors.topMargin: 16
                text: root.formatClock(root.generatedAtMs)
                color: root.textPrimary
                font.pixelSize: 18
            }
        }

        Rectangle {
            id: guideTimelineHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: guideHeader.bottom
            height: 52
            color: "#081625"
            border.color: root.line
            border.width: 1

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 28
                anchors.verticalCenter: parent.verticalCenter
                text: "TODAY  " + root.formatDate(root.generatedAtMs)
                color: root.textPrimary
                font.pixelSize: 17
                font.weight: Font.DemiBold
            }

            Item {
                anchors.left: parent.left
                anchors.leftMargin: guideScreen.channelColumnWidth
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom

                Repeater {
                    model: 7
                    delegate: Text {
                        x: index * (parent.width / 6) - (index === 6 ? width : 0)
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.formatClock(root.horizonStartMs + index * 30 * 60 * 1000)
                        color: index === 0 ? root.accentBright : root.textPrimary
                        font.pixelSize: 17
                    }
                }
            }
        }

        ListView {
            id: guideList
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: guideTimelineHeader.bottom
            anchors.bottom: guideFooter.top
            model: root.rows
            clip: true
            interactive: true
            currentIndex: root.selectedRow
            boundsBehavior: Flickable.StopAtBounds

            delegate: Item {
                id: channelRow
                width: guideList.width
                height: 76
                property var rowData: modelData

                Rectangle {
                    id: channelCell
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: guideScreen.channelColumnWidth
                    color: index === root.selectedRow ? "#0d2b4b" : "#071321"
                    border.color: index === root.selectedRow ? root.accent : root.line
                    border.width: 1

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 26
                        anchors.verticalCenter: parent.verticalCenter
                        text: channelRow.rowData.displayNumber
                        color: root.textPrimary
                        font.pixelSize: 25
                        font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 92
                        anchors.right: parent.right
                        anchors.rightMargin: 18
                        anchors.verticalCenter: parent.verticalCenter
                        text: channelRow.rowData.channelName
                        color: index === root.selectedRow ? root.accentBright : root.textSecondary
                        font.pixelSize: 18
                        elide: Text.ElideRight
                    }
                }

                Item {
                    id: programArea
                    anchors.left: channelCell.right
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    clip: true

                    Rectangle { anchors.fill: parent; color: "#081522"; border.color: root.line; border.width: 1 }

                    Repeater {
                        model: channelRow.rowData.programs || []
                        delegate: Rectangle {
                            property real rawX: ((modelData.startMs - root.horizonStartMs) / root.horizonSpanMs) * programArea.width
                            property real rawWidth: ((modelData.endMs - modelData.startMs) / root.horizonSpanMs) * programArea.width
                            x: Math.max(0, rawX) + 1
                            y: 3
                            width: Math.max(5, Math.min(programArea.width - x, rawWidth - 2))
                            height: programArea.height - 6
                            radius: 4
                            color: index === root.selectedProgram && channelRow.ListView.view && channelRow.ListView.view.currentIndex === channelRow.index ? "#146ad1" : (modelData.isCurrent ? "#123558" : "#0d2134")
                            border.color: index === root.selectedProgram && channelRow.ListView.view && channelRow.ListView.view.currentIndex === channelRow.index ? root.accentBright : "#193a55"
                            border.width: index === root.selectedProgram && channelRow.ListView.view && channelRow.ListView.view.currentIndex === channelRow.index ? 2 : 1

                            Column {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 14
                                anchors.rightMargin: 8
                                spacing: 3
                                Text {
                                    text: modelData.title
                                    color: root.textPrimary
                                    font.pixelSize: 17
                                    font.weight: Font.DemiBold
                                    width: parent.width
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: root.formatClock(modelData.startMs) + " – " + root.formatClock(modelData.endMs)
                                    color: "#b8c7d6"
                                    font.pixelSize: 13
                                    width: parent.width
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            // Current Broadcast Clock line.
            x: guideScreen.channelColumnWidth + ((root.generatedAtMs - root.horizonStartMs) / root.horizonSpanMs) * (parent.width - guideScreen.channelColumnWidth)
            y: guideTimelineHeader.y + guideTimelineHeader.height - 6
            width: 2
            height: guideFooter.y - y
            color: root.accentBright
            visible: root.generatedAtMs >= root.horizonStartMs && root.generatedAtMs <= root.horizonEndMs
            z: 20
        }

        Rectangle {
            id: guideFooter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 54
            color: "#06111e"
            border.color: root.line
            border.width: 1

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 26
                spacing: 36
                Text { text: "G  Guide / Go to Now"; color: root.textSecondary; font.pixelSize: 15 }
                Text { text: "← →  Time"; color: root.textSecondary; font.pixelSize: 15 }
                Text { text: "↑ ↓  Channels"; color: root.textSecondary; font.pixelSize: 15 }
                Text { text: "ENTER  Select"; color: root.textSecondary; font.pixelSize: 15 }
                Text { text: "ESC  Back"; color: root.textSecondary; font.pixelSize: 15 }
            }
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 72
        width: Math.min(parent.width * 0.7, statusText.implicitWidth + 56)
        height: 48
        radius: 8
        color: "#d9142b46"
        border.color: root.accent
        visible: root.statusMessage.length > 0
        z: 100

        Text {
            id: statusText
            anchors.centerIn: parent
            text: root.statusMessage
            color: root.textPrimary
            font.pixelSize: 16
        }
    }
}
