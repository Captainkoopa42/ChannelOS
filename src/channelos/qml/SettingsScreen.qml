pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: settingsRoot
    property var hostWindow: null
    readonly property var preferences:
        channelOS ? channelOS.settings : ({
            volumePercent: 100,
            muted: false,
            skipBackSeconds: 10,
            skipForwardSeconds: 30,
            performanceProfile: "standard",
            generateVideoThumbnails: true,
            artworkCacheLimitMb: 0,
            backgroundArtworkDuringPlayback: true,
            reducedMotion: false,
            artworkCacheBytes: 0,
            artworkCacheFiles: 0
        })
    readonly property var settingsRows: [
        { title: "Performance Profile", detail: "Standard preserves full artwork behavior. Lightweight reduces optional background work." },
        { title: "Volume", detail: "The volume ChannelOS uses now and on its next launch." },
        { title: "Muted", detail: "Remember whether ChannelOS should start muted." },
        { title: "Skip Back", detail: "How far Left/Rewind jumps during Live TV and On Demand." },
        { title: "Skip Forward", detail: "How far Right/Fast Forward jumps during Live TV and On Demand." },
        { title: "Generate Video Thumbnails", detail: "Use FFmpeg when no local sidecar image or cached thumbnail exists." },
        { title: "Generated Artwork Cache", detail: "Limit only ChannelOS-generated thumbnails. Zero means unlimited." },
        { title: "Artwork During Playback", detail: "Allow optional thumbnail generation while Live TV or On Demand is playing." },
        { title: "Reduced Motion", detail: "Remove shelf and artwork fades for a calmer, lighter interface." },
        { title: "Clear Generated Artwork", detail: "Delete generated thumbnails only. Media and sidecar images remain untouched." },
        { title: "Reset Defaults", detail: "Restore Standard mode, volume 100%, sound on, 10 seconds back, and 30 seconds forward." }
    ]

    anchors.fill: parent
    visible: hostWindow !== null && hostWindow.screen === "settings"

    function profileLabel() {
        var profile = String(preferences.performanceProfile || "standard")
        return profile.charAt(0).toUpperCase() + profile.slice(1)
    }

    function cacheLimitLabel() {
        var limit = Number(preferences.artworkCacheLimitMb || 0)
        return limit > 0 ? limit + " MB" : "Unlimited"
    }

    function cacheUsageLabel() {
        var bytes = Number(preferences.artworkCacheBytes || 0)
        var files = Number(preferences.artworkCacheFiles || 0)
        var size = bytes >= 1048576
                 ? (bytes / 1048576).toFixed(1) + " MB"
                 : (bytes / 1024).toFixed(1) + " KB"
        return files + (files === 1 ? " thumbnail • " : " thumbnails • ") + size
    }

    function valueFor(index) {
        if (index === 0)
            return profileLabel()
        if (index === 1)
            return (preferences.volumePercent || 0) + "%"
        if (index === 2)
            return preferences.muted ? "On" : "Off"
        if (index === 3)
            return (preferences.skipBackSeconds || 10) + " seconds"
        if (index === 4)
            return (preferences.skipForwardSeconds || 30) + " seconds"
        if (index === 5)
            return preferences.generateVideoThumbnails ? "On" : "Off"
        if (index === 6)
            return cacheLimitLabel()
        if (index === 7)
            return preferences.backgroundArtworkDuringPlayback ? "On" : "Off"
        if (index === 8)
            return preferences.reducedMotion ? "On" : "Off"
        if (index === 9)
            return cacheUsageLabel()
        return "Standard"
    }

    function settingName(index) {
        return [
            "performanceProfile",
            "volume",
            "muted",
            "skipBack",
            "skipForward",
            "generateVideoThumbnails",
            "artworkCacheLimit",
            "backgroundArtworkDuringPlayback",
            "reducedMotion"
        ][index]
    }

    function showResult(result) {
        if (hostWindow === null || !result)
            return
        if (result.message)
            hostWindow.statusMessage = result.message
        if (typeof result.volume !== "undefined")
            hostWindow.volumePercent = result.volume
        if (typeof result.muted !== "undefined")
            hostWindow.muted = result.muted
        statusClearTimer.restart()
    }

    function adjust(index, direction) {
        if (index < 0 || index > 8)
            return
        showResult(channelOS.adjustSetting(settingName(index), direction))
    }

    function activateAction(index) {
        if (index === 9)
            showResult(channelOS.clearArtworkCache())
        else if (index === 10)
            showResult(channelOS.resetSettings())
    }

    Rectangle {
        anchors.fill: parent
        color: "#050c15"
    }

    Timer {
        id: statusClearTimer
        interval: 5200
        repeat: false
        onTriggered: {
            if (settingsRoot.hostWindow !== null)
                settingsRoot.hostWindow.statusMessage = ""
        }
    }

    Rectangle {
        id: settingsSidebar
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: Math.max(300, parent.width * 0.22)
        color: "#071322"
        border.color: "#1a3550"
        border.width: 1

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 38
            spacing: 18

            Row {
                spacing: 2
                Text { text: "Channel"; color: "#f4f7fb"; font.pixelSize: 34; font.weight: Font.DemiBold }
                Text { text: "OS"; color: "#42adff"; font.pixelSize: 34; font.weight: Font.DemiBold }
            }

            Item { width: 1; height: 18 }

            Rectangle {
                width: parent.width
                height: 56
                radius: 7
                color: "#12396a"
                border.color: "#42adff"
                border.width: 2
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Settings"
                    color: "#f4f7fb"
                    font.pixelSize: 20
                    font.weight: Font.DemiBold
                }
            }

            Rectangle {
                width: parent.width
                height: 52
                radius: 7
                color: backMouse.containsMouse ? "#10283f" : "transparent"
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: "‹  Back to Home"
                    color: "#9fb0c2"
                    font.pixelSize: 18
                }
                MouseArea {
                    id: backMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: settingsRoot.hostWindow.screen = "home"
                }
            }
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 38
            spacing: 8
            Text {
                text: "CURRENT PROFILE"
                color: "#42adff"
                font.pixelSize: 13
                font.weight: Font.Bold
                font.letterSpacing: 2
            }
            Text {
                text: settingsRoot.profileLabel()
                color: "#f4f7fb"
                font.pixelSize: 22
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "Settings are local. Lightweight changes optional artwork work and motion—not playback quality, schedules, media, or channels."
                color: "#9fb0c2"
                font.pixelSize: 14
                wrapMode: Text.WordWrap
                lineHeight: 1.2
            }
        }
    }

    Item {
        anchors.left: settingsSidebar.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: settingsFooter.top

        Text {
            id: settingsTitle
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 44
            anchors.rightMargin: 44
            anchors.topMargin: 32
            text: "Settings"
            color: "#f4f7fb"
            font.pixelSize: 34
            font.weight: Font.DemiBold
        }

        Text {
            id: settingsSubtitle
            anchors.left: settingsTitle.left
            anchors.right: settingsTitle.right
            anchors.top: settingsTitle.bottom
            anchors.topMargin: 4
            text: "Choose a ready-made profile or tune individual controls. Changes save automatically."
            color: "#9fb0c2"
            font.pixelSize: 16
            elide: Text.ElideRight
        }

        ListView {
            id: settingsList
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: settingsSubtitle.bottom
            anchors.bottom: parent.bottom
            anchors.leftMargin: 44
            anchors.rightMargin: 34
            anchors.topMargin: 22
            anchors.bottomMargin: 16
            spacing: 8
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: settingsRoot.settingsRows
            currentIndex: settingsRoot.hostWindow !== null
                          ? settingsRoot.hostWindow.settingsSelection : 0
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

            delegate: Rectangle {
                id: settingRow
                required property int index
                required property var modelData
                readonly property bool selected:
                    settingsRoot.hostWindow !== null
                    && index === settingsRoot.hostWindow.settingsSelection
                width: Math.max(1, settingsList.width - 8)
                height: 82
                radius: 9
                color: selected ? "#102b50" : "#0b1b2e"
                border.color: selected ? "#42adff" : "#17324a"
                border.width: selected ? 2 : 1

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        settingsRoot.hostWindow.settingsSelection = settingRow.index
                        settingsRoot.forceActiveFocus()
                    }
                }

                Column {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 20
                    spacing: 4
                    width: Math.max(1, parent.width - 300)
                    Text {
                        text: settingRow.modelData.title
                        color: "#f4f7fb"
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: settingRow.modelData.detail
                        color: "#9fb0c2"
                        font.pixelSize: 13
                        width: parent.width
                        elide: Text.ElideRight
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    visible: settingRow.index < 9

                    Rectangle {
                        width: 38
                        height: 38
                        radius: 6
                        color: minusMouse.containsMouse ? "#1a4d82" : "#10283f"
                        border.color: "#1a91ff"
                        Text { anchors.centerIn: parent; text: "−"; color: "#f4f7fb"; font.pixelSize: 22 }
                        MouseArea {
                            id: minusMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                settingsRoot.hostWindow.settingsSelection = settingRow.index
                                settingsRoot.adjust(settingRow.index, -1)
                            }
                        }
                    }

                    Text {
                        width: 156
                        anchors.verticalCenter: parent.verticalCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: settingsRoot.valueFor(settingRow.index)
                        color: "#42adff"
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Rectangle {
                        width: 38
                        height: 38
                        radius: 6
                        color: plusMouse.containsMouse ? "#1a4d82" : "#10283f"
                        border.color: "#1a91ff"
                        Text { anchors.centerIn: parent; text: "+"; color: "#f4f7fb"; font.pixelSize: 22 }
                        MouseArea {
                            id: plusMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                settingsRoot.hostWindow.settingsSelection = settingRow.index
                                settingsRoot.adjust(settingRow.index, 1)
                            }
                        }
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    width: 236
                    height: 42
                    radius: 6
                    visible: settingRow.index >= 9
                    color: actionMouse.containsMouse ? "#1a4d82" : "#10283f"
                    border.color: "#1a91ff"
                    Text {
                        anchors.centerIn: parent
                        text: settingRow.index === 9
                              ? "Clear • " + settingsRoot.cacheUsageLabel()
                              : "Restore Standard Defaults"
                        color: "#f4f7fb"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        width: parent.width - 16
                        horizontalAlignment: Text.AlignHCenter
                    }
                    MouseArea {
                        id: actionMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            settingsRoot.hostWindow.settingsSelection = settingRow.index
                            settingsRoot.activateAction(settingRow.index)
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: settingsFooter
        anchors.left: settingsSidebar.right
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 50
        color: "#071322"
        border.color: "#1a3550"
        border.width: 1
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 30
            anchors.verticalCenter: parent.verticalCenter
            text: "ARROWS  Navigate / Change     ENTER  Select     ESC / H  Home"
            color: "#9fb0c2"
            font.pixelSize: 13
        }
    }
}
