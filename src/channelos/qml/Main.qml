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

    readonly property color appBackground: "#050c15"
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
    property int selectedLibrary: 0
    property string statusMessage: ""
    property bool liveHudVisible: false
    property string channelEntry: ""
    property int volumePercent: 100
    property bool muted: false
    property bool audioHudVisible: false

    // One authoritative lower-third mode. This prevents the bounded HUD from
    // momentarily rendering Live and then On Demand (or vice versa) while the
    // controller publishes a screen/playback transition.
    readonly property string bottomHudMode: {
        if (screen === "ondemand" && onDemand && onDemand.active)
            return "ondemand"
        if (screen === "live" && playback && playback.active)
            return "live"
        return "hidden"
    }

    // Context properties are cleared during engine teardown. Guarding
    // these bindings keeps shutdown quiet without changing runtime behavior.
    property var playback: channelOS ? channelOS.playback : ({ active: false })
    property var homeTelevision: channelOS
                                ? channelOS.homeTelevision
                                : ({
                                      mode: "static",
                                      isUnassigned: true,
                                      channelNumber: 1,
                                      displayNumber: "001",
                                      channelName: "ChannelOS",
                                      title: "NO PROGRAMMING",
                                      continueLabel: "Set Up Channel 001"
                                  })
    property var onDemand: channelOS ? channelOS.onDemand : ({ active: false })
    property var librarySnapshot: channelOS ? channelOS.librarySnapshot : ({ items: [] })
    property var libraryItems: librarySnapshot.items || []
    property var snapshot: channelOS ? channelOS.snapshot : ({ rows: [] })
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
            return ({ channelNumber: 1, displayNumber: "001", channelName: "ChannelOS", isUnassigned: true, programs: [] })
        return rows[selectedRow]
    }

    function selectedProgramData() {
        var programs = programsForRow(selectedRow)
        if (selectedProgram < 0 || selectedProgram >= programs.length)
            return ({ title: "No Programming", startMs: 0, endMs: 0, isCurrent: false, isUnassigned: false })
        return programs[selectedProgram]
    }

    function selectedLibraryData() {
        if (!libraryItems
                || selectedLibrary < 0
                || selectedLibrary >= libraryItems.length) {
            return ({
                title: "No media indexed",
                fileName: "",
                path: "",
                sourceRoot: "",
                sourceName: "",
                durationSeconds: 0,
                sizeBytes: 0,
                containerFormat: ""
            })
        }

        return libraryItems[selectedLibrary]
    }

    function paintStatic(canvas) {
        var ctx = canvas.getContext("2d")
        ctx.fillStyle = "#111820"
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        for (var i = 0; i < 1800; ++i) {
            var g = 45 + Math.floor(Math.random() * 160)
            ctx.fillStyle = "rgb(" + g + "," + g + "," + g + ")"
            var size = 1 + Math.floor(Math.random() * 3)
            ctx.fillRect(
                Math.random() * canvas.width,
                Math.random() * canvas.height,
                size,
                size
            )
        }
    }

    function formatDurationSeconds(seconds) {
        var total = Math.max(0, Math.floor(Number(seconds) || 0))

        if (total <= 0)
            return "Unknown duration"

        var hours = Math.floor(total / 3600)
        var minutes = Math.floor((total % 3600) / 60)
        var secs = total % 60

        if (hours > 0) {
            return hours + ":"
                   + (minutes < 10 ? "0" : "") + minutes + ":"
                   + (secs < 10 ? "0" : "") + secs
        }

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

    Component.onCompleted: {
        if (rows.length > 0)
            selectRow(0)
    }

    onRowsChanged: {
        if (rows.length > 0)
            selectRow(Math.min(selectedRow, rows.length - 1))
    }

    onLibraryItemsChanged: {
        if (libraryItems.length === 0) {
            selectedLibrary = 0
        } else {
            selectedLibrary = Math.max(
                0,
                Math.min(
                    selectedLibrary,
                    libraryItems.length - 1
                )
            )
        }
    }

    Timer {
        interval: 15000
        repeat: true
        running: true
        onTriggered: {
            if (channelOS)
                channelOS.refresh()
        }
    }

    Timer {
        id: statusTimer
        interval: 2600
        repeat: false
        onTriggered: root.statusMessage = ""
    }

    Rectangle {
        anchors.fill: parent
        color: root.appBackground
    }

    // Native libVLC presentation surface.
    //
    // This exists as part of the QML hierarchy from application startup.
    // Qt owns its native parenting, geometry and visibility; ChannelOS
    // playback only receives the contained QWindow handle.
    WindowContainer {
        id: liveVideoContainer

        // Keep the Guide geometry on the path already validated on Windows.
        // Home uses the same root-coordinate idea, but its native surface is
        // made visible from remembered/default television state before libVLC
        // starts. Decoder activity must not be the thing that makes its target
        // HWND visible; otherwise Windows can create D3D11 output against a
        // hidden child and leave the Home picture blank on boot.
        readonly property bool fullPresentation:
            root.screen === "live" || root.screen === "ondemand"
        readonly property bool showHomePreview:
            root.screen === "home"
            && root.homeTelevision.mode !== "static"
        readonly property bool showGuidePreview:
            root.screen === "guide" && Boolean(root.playback.active)

        x: fullPresentation
           ? 0
           : (showHomePreview
              ? homeLeft.width + 24
              : guideScreen.x + guideHeader.x
                + guidePreviewPanel.x + guideVideoSlot.x)

        y: fullPresentation
           ? 0
           : (showHomePreview
              ? 24
              : guideScreen.y + guideHeader.y
                + guidePreviewPanel.y + guideVideoSlot.y)

        width: fullPresentation
               ? root.width
               : (showHomePreview
                  ? homePreview.width - 12
                  : guideVideoSlot.width)

        height: fullPresentation
                ? root.height
                : (showHomePreview
                   ? homeVideoSlot.height
                   : guideVideoSlot.height)

        visible: fullPresentation || showHomePreview || showGuidePreview
        window: channelOSVideoWindow
        z: 50
    }

    // Windows-safe television HUD architecture.
    //
    // The libVLC target is a native child window. A second full-screen
    // transparent native sibling can obscure it across maximize/restore
    // transitions, so ChannelOS keeps HUD surfaces bounded to the pixels they
    // actually draw. The translucent lower-third is a bounded transient
    // top-level Window so Windows/DWM owns its alpha composition.

    // Top-center numeric channel entry.
    WindowContainer {
        id: channelEntryContainer
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: 44
        width: Math.max(150, 72 + root.channelEntry.length * 22)
        height: 64
        visible: (root.screen === "live" || root.screen === "ondemand")
                 && root.channelEntry.length > 0
        z: 60

        window: Window {
            color: "transparent"
            flags: Qt.FramelessWindowHint
                   | Qt.WindowDoesNotAcceptFocus
                   | Qt.WindowTransparentForInput

            Rectangle {
                anchors.fill: parent
                radius: 10
                color: "#dc081625"
                border.color: root.accentBright
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    text: "CH " + root.channelEntry
                    color: root.textPrimary
                    font.pixelSize: 28
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                }
            }
        }
    }

    // Top-left volume / mute popup.
    WindowContainer {
        id: audioHudContainer
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 34
        anchors.topMargin: 28
        width: root.muted ? 128 : 118
        height: 44
        visible: root.audioHudVisible
                 && (root.screen === "live" || root.screen === "ondemand")
        z: 60

        window: Window {
            color: "transparent"
            flags: Qt.FramelessWindowHint
                   | Qt.WindowDoesNotAcceptFocus
                   | Qt.WindowTransparentForInput

            Rectangle {
                anchors.fill: parent
                radius: 8
                color: "#dc081625"

                Text {
                    anchors.centerIn: parent
                    text: root.muted ? "MUTED" : "VOL " + root.volumePercent
                    color: root.muted ? root.liveRed : root.textPrimary
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    // Transparent bounded bottom HUD.
    //
    // IMPORTANT: this is intentionally a top-level transient Window, NOT a
    // WindowContainer child. The old full-screen native HUD could obscure VLC
    // after maximize, while the bounded child HUD could not alpha-compose over
    // the VLC child reliably. This keeps the old translucent HUD look while
    // limiting the overlay to only the lower-third pixels.
    Window {
        id: bottomHudOverlay
        transientParent: root
        flags: Qt.Tool
               | Qt.FramelessWindowHint
               | Qt.WindowDoesNotAcceptFocus
               | Qt.WindowTransparentForInput
        color: "transparent"

        x: root.x
        y: root.y + root.height - height
        width: root.width
        height: root.bottomHudMode === "live" ? 255 : 220

        visible: root.visible
                 && root.visibility !== Window.Minimized
                 && root.bottomHudMode !== "hidden"
                 && (root.bottomHudMode !== "live"
                     || root.liveHudVisible)

        readonly property string hudMode: root.bottomHudMode

        readonly property real liveProgressFraction: {
            var start = Number(root.playback.programStartMs || 0)
            var end = Number(root.playback.programEndMs || 0)
            var viewer = Number(root.playback.viewerTimeMs || 0)
            if (end <= start)
                return 0
            return Math.max(0, Math.min(1, (viewer - start) / (end - start)))
        }

        readonly property real onDemandProgressFraction: {
            var duration = Number(root.onDemand.durationSeconds || 0)
            var position = Number(root.onDemand.positionSeconds || 0)
            if (duration <= 0)
                return 0
            return Math.max(0, Math.min(1, position / duration))
        }

        // Classic Live-TV lower third.
        Item {
            anchors.fill: parent
            visible: bottomHudOverlay.hudMode === "live"

            Rectangle {
                anchors.fill: parent

                // Same old ChannelOS lower-third color. Because this Rectangle
                // now lives in a top-level alpha-composited Window, its alpha
                // blends with the video instead of resolving against a native
                // child backing surface.
                color: "#e6081625"

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 2
                    color: root.accent
                    opacity: 0.75
                }

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 34
                    spacing: 10

                    Row {
                        spacing: 16

                        Text {
                            text: "CH "
                                  + (root.playback.displayNumber || "---")
                                  + "   "
                                  + (root.playback.channelName || "")
                            color: root.accentBright
                            font.pixelSize: 22
                            font.weight: Font.DemiBold
                            font.letterSpacing: 1
                        }

                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            height: 30
                            width: liveStateText.implicitWidth + 24
                            radius: 15
                            color: root.playback.paused
                                   ? "#9a6a20"
                                   : (root.playback.isLive
                                      ? "#a83232"
                                      : "#164d80")

                            Text {
                                id: liveStateText
                                anchors.centerIn: parent
                                text: root.playback.paused
                                      ? ("PAUSED"
                                         + (root.playback.lagSeconds >= 1
                                            ? " - "
                                              + Math.round(root.playback.lagSeconds)
                                              + "s BEHIND"
                                            : ""))
                                      : (root.playback.isLive
                                         ? "LIVE"
                                         : Math.round(root.playback.lagSeconds)
                                           + "s BEHIND LIVE")
                                color: root.textPrimary
                                font.pixelSize: 14
                                font.weight: Font.Bold
                            }
                        }
                    }

                    Text {
                        text: root.playback.title || "No Programming"
                        color: root.textPrimary
                        font.pixelSize: 30
                        font.weight: Font.DemiBold
                        width: parent.width
                        elide: Text.ElideRight
                    }

                    Row {
                        width: parent.width
                        spacing: 18

                        Text {
                            text: root.formatClock(root.playback.programStartMs)
                                  + " - "
                                  + root.formatClock(root.playback.programEndMs)
                            color: root.textSecondary
                            font.pixelSize: 17
                        }

                        Text {
                            text: root.playback.isLive
                                  ? "Broadcast Clock"
                                  : "Viewer Clock"
                            color: root.playback.isLive
                                   ? root.liveRed
                                   : root.accentBright
                            font.pixelSize: 17
                            font.weight: Font.DemiBold
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 5
                        radius: 3
                        color: "#31465b"

                        Rectangle {
                            width: parent.width * bottomHudOverlay.liveProgressFraction
                            height: parent.height
                            radius: 3
                            color: root.accentBright
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 20

                        Text {
                            text: "NEXT"
                            color: root.textSecondary
                            font.pixelSize: 14
                            font.weight: Font.Bold
                        }

                        Text {
                            text: root.playback.nextTitle || "No next program"
                            color: root.textPrimary
                            font.pixelSize: 16
                            width: parent.width * 0.57
                            elide: Text.ElideRight
                        }

                        Text {
                            text: root.playback.nextStartMs
                                  ? root.formatClock(root.playback.nextStartMs)
                                  : ""
                            color: root.textSecondary
                            font.pixelSize: 15
                        }
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 32
                    anchors.bottomMargin: 16
                    spacing: 25

                    Text { text: "SPACE  Pause / Play"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "LEFT  -10s"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "RIGHT  +30s"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "UP/DOWN  Channel"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "0-9  Tune"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "P  Previous"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "+/-  Volume"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "M  Mute"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "L  Live"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "G  Guide"; color: root.textSecondary; font.pixelSize: 13 }
                }
            }
        }

        // Classic On Demand lower third.
        Item {
            anchors.fill: parent
            visible: bottomHudOverlay.hudMode === "ondemand"

            Rectangle {
                anchors.fill: parent
                color: "#e6081625"

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 2
                    color: root.accent
                }

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 34
                    spacing: 10

                    Row {
                        spacing: 18

                        Text {
                            text: "CHANNEL OS  |  ON DEMAND"
                            color: root.accentBright
                            font.pixelSize: 20
                            font.weight: Font.DemiBold
                            font.letterSpacing: 1
                        }

                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            height: 28
                            width: odStateText.implicitWidth + 24
                            radius: 14
                            color: root.onDemand.paused
                                   ? "#9a6a20"
                                   : "#164d80"

                            Text {
                                id: odStateText
                                anchors.centerIn: parent
                                text: root.onDemand.paused ? "PAUSED" : "PLAYING"
                                color: root.textPrimary
                                font.pixelSize: 13
                                font.weight: Font.Bold
                            }
                        }
                    }

                    Text {
                        text: root.onDemand.title || "Owned Media"
                        color: root.textPrimary
                        font.pixelSize: 29
                        font.weight: Font.DemiBold
                        width: parent.width
                        elide: Text.ElideRight
                    }

                    Text {
                        text: root.formatDurationSeconds(root.onDemand.positionSeconds)
                              + " / "
                              + root.formatDurationSeconds(root.onDemand.durationSeconds)
                        color: root.textSecondary
                        font.pixelSize: 16
                    }

                    Rectangle {
                        width: parent.width
                        height: 5
                        radius: 3
                        color: "#31465b"

                        Rectangle {
                            width: parent.width
                                   * bottomHudOverlay.onDemandProgressFraction
                            height: parent.height
                            radius: 3
                            color: root.accentBright
                        }
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 32
                    anchors.bottomMargin: 18
                    spacing: 28

                    Text { text: "SPACE  Pause / Play"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "LEFT  -10s"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "RIGHT  +30s"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "+/-  Volume"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "M  Mute"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "0-9  Tune Channel"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "P  Previous Channel"; color: root.textSecondary; font.pixelSize: 13 }
                    Text { text: "ESC  Library"; color: root.textSecondary; font.pixelSize: 13 }
                }
            }
        }
    }

    // Bounded clock overlay. Keeping this native surface small avoids
    // recreating the full-screen transparent sibling that conflicted with the
    // embedded libVLC presentation surface on Windows.
    WindowContainer {
        id: liveClockContainer
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 26
        anchors.rightMargin: 34
        width: 154
        height: 46
        visible: root.screen === "ondemand"
                 || (root.screen === "live" && root.liveHudVisible)
        z: 60

        window: Window {
            id: liveClockWindow
            color: "transparent"
            flags: Qt.FramelessWindowHint
                   | Qt.WindowDoesNotAcceptFocus
                   | Qt.WindowTransparentForInput

            property real nowMs: Date.now()

            Timer {
                interval: 1000
                repeat: true
                running: true
                onTriggered: liveClockWindow.nowMs = Date.now()
            }

            Rectangle {
                anchors.fill: parent
                radius: 7
                color: "#b8081625"
                border.color: "#1a3550"
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    text: root.formatClock(liveClockWindow.nowMs)
                    color: root.textPrimary
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
            }
        }
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
                    model: [
                        root.homeTelevision.continueLabel || "Continue Watching",
                        "Open Guide",
                        "Library / On Demand",
                        "Channels",
                        "Settings"
                    ]
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
            readonly property bool unassigned:
                root.homeTelevision.mode === "static"

            // Geometry-only reservation for the existing native libVLC child.
            // The video does not overlap the program metadata below it.
            Item {
                id: homeVideoSlot
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 6
                height: Math.max(1, parent.height - 178)
            }

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
                visible: homePreview.unassigned
                onPaint: root.paintStatic(staticCanvas)
            }
            Timer {
                interval: 95
                repeat: true
                running: root.screen === "home" && homePreview.unassigned
                onTriggered: staticCanvas.requestPaint()
            }

            Rectangle {
                anchors.fill: parent
                visible: !homePreview.unassigned
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#153b60" }
                    GradientStop { position: 0.55; color: "#0b2034" }
                    GradientStop { position: 1.0; color: "#06101a" }
                }
            }

            Rectangle {
                anchors.fill: parent
                color: "#020913"
                opacity: 0.17
            }

            Column {
                anchors.centerIn: parent
                spacing: 12
                visible: homePreview.unassigned
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "CH 001"; color: root.textPrimary; font.pixelSize: 56; font.letterSpacing: 5 }
                Rectangle { width: 230; height: 2; color: root.accent; anchors.horizontalCenter: parent.horizontalCenter }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "UNASSIGNED"; color: root.accentBright; font.pixelSize: 28; font.letterSpacing: 8 }
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "NO PROGRAMMING"; color: "#c5ccd4"; font.pixelSize: 16; font.letterSpacing: 4 }
            }

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: 34
                anchors.rightMargin: 34
                anchors.bottomMargin: 34
                spacing: 8
                visible: !homePreview.unassigned

                Text {
                    text: root.homeTelevision.stateLabel || "TELEVISION"
                    color: root.accentBright
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    font.letterSpacing: 3
                }
                Text {
                    text: "CH " + (root.homeTelevision.displayNumber || "---")
                          + "  " + (root.homeTelevision.channelName || "")
                    color: root.textPrimary
                    font.pixelSize: 22
                    font.weight: Font.DemiBold
                }
                Text {
                    text: root.homeTelevision.title || "No Programming"
                    color: root.textPrimary
                    font.pixelSize: 34
                    font.weight: Font.DemiBold
                    width: parent.width
                    elide: Text.ElideRight
                }
                Text {
                    text: root.homeTelevision.programStartMs
                          ? root.formatClock(root.homeTelevision.programStartMs)
                            + " - "
                            + root.formatClock(root.homeTelevision.programEndMs)
                          : "No scheduled programming"
                    color: root.textSecondary
                    font.pixelSize: 17
                }
                Text {
                    visible: root.homeTelevision.mode === "current"
                    text: root.homeTelevision.isLive
                          ? "LIVE • Broadcast Clock"
                          : Math.round(root.homeTelevision.lagSeconds || 0)
                            + "s behind live • Viewer Clock"
                    color: root.homeTelevision.isLive
                           ? root.liveRed
                           : root.accentBright
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
            }

            Row {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 18
                spacing: 12
                Rectangle {
                    width: 10
                    height: 10
                    radius: 5
                    color: homePreview.unassigned ? root.accent : root.liveRed
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: "CH " + (root.homeTelevision.displayNumber || "001")
                    color: root.textPrimary
                    font.pixelSize: 19
                }
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

    // Library / On Demand: real user-owned indexed media.
    Item {
        id: libraryScreen

        anchors.fill: parent
        visible: root.screen === "library"

        readonly property var selectedItem:
            root.selectedLibraryData()

        Rectangle {
            id: libraryHeader

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top

            height: 112

            color: "#071322"
            border.color: root.line
            border.width: 1

            Row {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 34
                anchors.topMargin: 28
                spacing: 10

                Text {
                    text: "Channel"
                    color: root.textPrimary
                    font.pixelSize: 28
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "OS"
                    color: root.accentBright
                    font.pixelSize: 28
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "  |  LIBRARY / ON DEMAND"
                    color: root.accentBright
                    font.pixelSize: 21
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 34
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 17

                text: (root.librarySnapshot.count || 0)
                      + " owned media item"
                      + (
                          (root.librarySnapshot.count || 0) === 1
                          ? ""
                          : "s"
                      )
                      + "   |   "
                      + (root.librarySnapshot.sourceCount || 0)
                      + " source"
                      + (
                          (root.librarySnapshot.sourceCount || 0) === 1
                          ? ""
                          : "s"
                      )

                color: root.textSecondary
                font.pixelSize: 15
            }
        }

        Rectangle {
            id: libraryListPanel

            anchors.left: parent.left
            anchors.top: libraryHeader.bottom
            anchors.bottom: libraryFooter.top

            width: parent.width * 0.62

            color: "#06111e"
            border.color: root.line
            border.width: 1

            ListView {
                id: libraryList

                anchors.fill: parent
                anchors.margins: 18

                spacing: 6
                clip: true

                model: root.libraryItems
                currentIndex: root.selectedLibrary

                boundsBehavior: Flickable.StopAtBounds

                delegate: Rectangle {
                    width: libraryList.width
                    height: 76
                    radius: 7

                    color: index === root.selectedLibrary
                           ? "#12396a"
                           : "#0a1a2b"

                    border.color: index === root.selectedLibrary
                                  ? root.accentBright
                                  : "#17324a"

                    border.width:
                        index === root.selectedLibrary ? 2 : 1

                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter

                        anchors.leftMargin: 18
                        anchors.rightMargin: 18

                        spacing: 4

                        Text {
                            text: modelData.title

                            color: root.textPrimary
                            font.pixelSize: 18

                            font.weight:
                                index === root.selectedLibrary
                                ? Font.DemiBold
                                : Font.Normal

                            width: parent.width
                            elide: Text.ElideRight
                        }

                        Row {
                            spacing: 16

                            Text {
                                text: root.formatDurationSeconds(
                                    modelData.durationSeconds
                                )

                                color: root.textSecondary
                                font.pixelSize: 13
                            }

                            Text {
                                text: modelData.containerFormat
                                color: root.accentBright
                                font.pixelSize: 13
                            }

                            Text {
                                text: modelData.sourceName
                                color: root.textSecondary
                                font.pixelSize: 13
                            }
                        }
                    }
                }
            }

            Column {
                anchors.centerIn: parent
                spacing: 12

                visible: root.libraryItems.length === 0

                Text {
                    anchors.horizontalCenter:
                        parent.horizontalCenter

                    text: "YOUR LIBRARY IS EMPTY"

                    color: root.textPrimary
                    font.pixelSize: 25
                    font.weight: Font.DemiBold
                }

                Text {
                    anchors.horizontalCenter:
                        parent.horizontalCenter

                    text: "Press A to add a media folder."

                    color: root.textSecondary
                    font.pixelSize: 16
                }
            }
        }

        Rectangle {
            id: libraryDetails

            anchors.left: libraryListPanel.right
            anchors.right: parent.right
            anchors.top: libraryHeader.bottom
            anchors.bottom: libraryFooter.top

            color: "#091827"

            border.color: root.line
            border.width: 1

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top

                anchors.margins: 24

                height: parent.height * 0.34
                radius: 10

                gradient: Gradient {
                    GradientStop {
                        position: 0.0
                        color: "#12304a"
                    }

                    GradientStop {
                        position: 1.0
                        color: "#08131f"
                    }
                }

                border.color: root.accent
                border.width: 1

                Column {
                    anchors.centerIn: parent
                    spacing: 8

                    Text {
                        anchors.horizontalCenter:
                            parent.horizontalCenter

                        text: "OWNED MEDIA"

                        color: root.accentBright
                        font.pixelSize: 17
                        font.letterSpacing: 3
                    }

                    Text {
                        anchors.horizontalCenter:
                            parent.horizontalCenter

                        text:
                            libraryScreen.selectedItem.containerFormat
                            || "MEDIA"

                        color: root.textPrimary
                        font.pixelSize: 34
                        font.weight: Font.DemiBold
                    }
                }
            }

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top

                anchors.topMargin: parent.height * 0.39
                anchors.leftMargin: 28
                anchors.rightMargin: 28

                spacing: 12

                Text {
                    text: libraryScreen.selectedItem.title

                    color: root.textPrimary
                    font.pixelSize: 25
                    font.weight: Font.DemiBold

                    width: parent.width
                    elide: Text.ElideRight
                }

                Text {
                    text:
                        root.formatDurationSeconds(
                            libraryScreen.selectedItem.durationSeconds
                        )
                        + "   |   "
                        + root.formatBytes(
                            libraryScreen.selectedItem.sizeBytes
                        )
                        + "   |   "
                        + libraryScreen.selectedItem.containerFormat

                    color: root.textSecondary
                    font.pixelSize: 15
                    width: parent.width
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: root.line
                }

                Text {
                    text: "SOURCE"
                    color: root.accentBright
                    font.pixelSize: 12
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                }

                Text {
                    text: libraryScreen.selectedItem.sourceRoot

                    color: root.textSecondary
                    font.pixelSize: 14

                    width: parent.width
                    wrapMode: Text.WrapAnywhere
                    maximumLineCount: 2
                }

                Text {
                    text: "FILE"
                    color: root.accentBright
                    font.pixelSize: 12
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                }

                Text {
                    text: libraryScreen.selectedItem.fileName

                    color: root.textSecondary
                    font.pixelSize: 14

                    width: parent.width
                    elide: Text.ElideMiddle
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom

                anchors.margins: 28

                height: 58
                radius: 7

                color: root.libraryItems.length > 0
                       ? "#12396a"
                       : "#0a1826"

                border.color:
                    root.libraryItems.length > 0
                    ? root.accentBright
                    : root.line

                border.width: 1

                Text {
                    anchors.centerIn: parent

                    text: root.libraryItems.length > 0
                          ? "ENTER   PLAY ON DEMAND"
                          : "A   ADD MEDIA FOLDER"

                    color: root.textPrimary
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1
                }
            }
        }

        Rectangle {
            id: libraryFooter

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom

            height: 56

            color: "#06111e"
            border.color: root.line
            border.width: 1

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 26
                spacing: 34

                Text {
                    text: "UP/DOWN  Browse"
                    color: root.textSecondary
                    font.pixelSize: 14
                }

                Text {
                    text: "ENTER  Play On Demand"
                    color: root.textSecondary
                    font.pixelSize: 14
                }

                Text {
                    text: "A  Add Media Folder"
                    color: root.textSecondary
                    font.pixelSize: 14
                }

                Text {
                    text: "ESC  Home"
                    color: root.textSecondary
                    font.pixelSize: 14
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
                id: guidePreviewPanel
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 26
                width: parent.width * 0.38
                radius: 8
                color: "#0b1b2b"
                border.color: root.accent
                border.width: guideScreen.programData.isCurrent ? 1 : 0

                // Keep the bottom status strip in QML while the single native
                // video surface occupies the picture area above it.
                Item {
                    id: guideVideoSlot
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 6
                    height: Math.max(1, parent.height - 52)
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    visible: !guideScreen.rowData.isUnassigned
                             && !root.playback.active
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#12304a" }
                        GradientStop { position: 0.55; color: "#0a1a29" }
                        GradientStop { position: 1.0; color: "#07111c" }
                    }
                    radius: 7
                }

                Canvas {
                    id: guideStaticCanvas
                    anchors.fill: parent
                    anchors.margins: 1
                    visible: Boolean(guideScreen.rowData.isUnassigned)
                             && !root.playback.active
                    onPaint: root.paintStatic(guideStaticCanvas)
                }

                Timer {
                    interval: 95
                    repeat: true
                    running: root.screen === "guide"
                             && Boolean(guideScreen.rowData.isUnassigned)
                             && !root.playback.active
                    onTriggered: guideStaticCanvas.requestPaint()
                }

                Text {
                    anchors.centerIn: parent
                    visible: !guideScreen.rowData.isUnassigned
                             && !root.playback.active
                    text: guideScreen.rowData.displayNumber + "\n" + guideScreen.rowData.channelName
                    horizontalAlignment: Text.AlignHCenter
                    color: root.textPrimary
                    font.pixelSize: 28
                    lineHeight: 1.25
                }

                Column {
                    anchors.centerIn: parent
                    visible: Boolean(guideScreen.rowData.isUnassigned)
                             && !root.playback.active
                    spacing: 7
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "CH 001"
                        color: root.textPrimary
                        font.pixelSize: 30
                        font.weight: Font.DemiBold
                        font.letterSpacing: 3
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "UNASSIGNED"
                        color: root.accentBright
                        font.pixelSize: 18
                        font.weight: Font.Bold
                        font.letterSpacing: 5
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "STATIC / NO PROGRAMMING"
                        color: root.textSecondary
                        font.pixelSize: 12
                        font.letterSpacing: 2
                    }
                }
                Row {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.margins: 18
                    spacing: 8
                    Rectangle {
                        width: 9
                        height: 9
                        radius: 5
                        color: root.liveRed
                        anchors.verticalCenter: parent.verticalCenter
                        visible: root.playback.active
                                 || (guideScreen.programData.isCurrent
                                     && !guideScreen.rowData.isUnassigned)
                    }
                    Text {
                        text: root.playback.active
                              ? "WATCHING CH "
                                + (root.playback.displayNumber || "---")
                              : (guideScreen.rowData.isUnassigned
                                 ? "NO PROGRAMMING"
                                 : (guideScreen.programData.isCurrent
                                    ? "LIVE"
                                    : "PROGRAM PREVIEW"))
                        color: root.textPrimary
                        font.pixelSize: 15
                    }
                }
            }

            Text {
                // Keep the Guide clock outside the live television viewport.
                anchors.right: guidePreviewPanel.left
                anchors.top: parent.top
                anchors.rightMargin: 18
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
                        anchors.right: watchingBadge.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: channelRow.rowData.channelName
                        color: index === root.selectedRow ? root.accentBright : root.textSecondary
                        font.pixelSize: 18
                        elide: Text.ElideRight
                    }

                    Text {
                        id: watchingBadge
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        visible: root.homeTelevision.mode === "current"
                                 && Number(root.homeTelevision.channelNumber)
                                    === Number(channelRow.rowData.channelNumber)
                        text: "WATCHING"
                        color: root.liveRed
                        font.pixelSize: 11
                        font.weight: Font.Bold
                        font.letterSpacing: 1
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

                    // Exact scheduled occurrences remain in rowData.programs.
                    // displaySegments is presentation-only aggregation for
                    // short-form channels at multi-hour Guide scale.
                    Repeater {
                        model: channelRow.rowData.displaySegments || []

                        delegate: Rectangle {
                            property bool rowSelected:
                                channelRow.ListView.view
                                && channelRow.ListView.view.currentIndex === channelRow.index

                            property bool containsSelection:
                                root.selectedProgram >= modelData.firstProgramIndex
                                && root.selectedProgram <= modelData.lastProgramIndex

                            property bool selectedSegment:
                                rowSelected && containsSelection

                            property real rawX:
                                ((modelData.startMs - root.horizonStartMs)
                                 / root.horizonSpanMs) * programArea.width

                            property real rawWidth:
                                ((modelData.endMs - modelData.startMs)
                                 / root.horizonSpanMs) * programArea.width

                            x: Math.max(0, rawX) + 1
                            y: 3

                            width: Math.max(
                                1,
                                Math.min(
                                    programArea.width - x,
                                    rawWidth - 2
                                )
                            )

                            height: programArea.height - 6
                            radius: modelData.isCluster ? 6 : 4

                            color: selectedSegment
                                   ? "#146ad1"
                                   : (
                                       modelData.isUnassigned
                                       ? "#17202a"
                                       : (
                                           modelData.isCurrent
                                           ? "#123558"
                                           : (
                                               modelData.isCluster
                                               ? "#102a43"
                                               : "#0d2134"
                                           )
                                       )
                                   )

                            border.color: selectedSegment
                                          ? root.accentBright
                                          : (
                                              modelData.isCluster
                                              ? "#24577d"
                                              : "#193a55"
                                          )

                            border.width: selectedSegment ? 2 : 1

                            Column {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 12
                                anchors.rightMargin: 8
                                spacing: 3

                                visible: parent.width >= 42

                                Text {
                                    text: modelData.title
                                    color: root.textPrimary
                                    font.pixelSize: modelData.isCluster ? 14 : 17
                                    font.weight: Font.DemiBold
                                    width: parent.width
                                    elide: Text.ElideRight
                                }

                                Text {
                                    text: modelData.isCluster
                                          ? modelData.programCount + " clips"
                                          : root.formatClock(modelData.startMs)
                                            + " - "
                                            + root.formatClock(modelData.endMs)

                                    color: "#b8c7d6"
                                    font.pixelSize: 12
                                    width: parent.width
                                    elide: Text.ElideRight
                                    visible: parent.width >= 72
                                }
                            }

                            Rectangle {
                                visible: modelData.isCluster
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 5
                                anchors.rightMargin: 5
                                anchors.bottomMargin: 5
                                height: 2
                                radius: 1
                                color: root.accent
                                opacity: 0.65
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

