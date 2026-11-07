pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: settingsRoot
    property var hostWindow: null
    property bool startupModeApplied: false
    readonly property var preferences:
        channelOS ? channelOS.settings : ({
            volumePercent: 100,
            muted: false,
            audioOutputDeviceId: "",
            audioOutputDeviceName: "System Default",
            audioOutputDevices: [],
            skipBackSeconds: 10,
            skipForwardSeconds: 30,
            controllerEnabled: true,
            performanceProfile: "standard",
            generateVideoThumbnails: true,
            artworkCacheLimitMb: 0,
            backgroundArtworkDuringPlayback: true,
            reducedMotion: false,
            artworkCacheBytes: 0,
            artworkCacheFiles: 0
        })
    readonly property string displayMode:
        channelOS ? String(channelOS.displayMode || "fullscreen") : "fullscreen"
    // Settings are grouped into tabs. Each row has a key; "action" rows run
    // something, every other row cycles a value with Left/Right or - / +.
    readonly property var tabs: [
        { key: "general", title: "General", detail: "Display, controls, performance and artwork" },
        { key: "media", title: "Video & Audio", detail: "Picture, sound and output device" },
        { key: "extras", title: "Extras", detail: "Themes, startup and portable setups" },
        { key: "profiles", title: "Profiles", detail: "Kids, Daycare and Lobby modes with a PIN lock" }
    ]
    readonly property var allRows: [
        { tab: "general", key: "displayMode", title: "Display Mode", detail: "Switch ChannelOS between fullscreen television and a normal desktop window." },
        { tab: "general", key: "performanceProfile", title: "Performance Profile", detail: "Standard preserves full artwork behavior. Lightweight reduces optional background work." },
        { tab: "general", key: "reducedMotion", title: "Reduced Motion", detail: "Remove shelf and artwork fades for a calmer, lighter interface." },
        { tab: "general", key: "controllerEnabled", title: "Controller Input", detail: "Accept controller commands only while ChannelOS has focus. Turn this off to disable controller polling entirely." },
        { tab: "general", key: "skipBack", title: "Skip Back", detail: "How far Left/Rewind jumps during Live TV and On Demand." },
        { tab: "general", key: "skipForward", title: "Skip Forward", detail: "How far Right/Fast Forward jumps during Live TV and On Demand." },
        { tab: "general", key: "generateVideoThumbnails", title: "Generate Video Thumbnails", detail: "Use FFmpeg when no local sidecar image or cached thumbnail exists." },
        { tab: "general", key: "artworkCacheLimit", title: "Generated Artwork Cache", detail: "Limit only ChannelOS-generated thumbnails. Zero means unlimited." },
        { tab: "general", key: "backgroundArtworkDuringPlayback", title: "Artwork During Playback", detail: "Allow optional thumbnail generation while Live TV or On Demand is playing." },
        { tab: "general", key: "clearArtwork", action: "clear", title: "Clear Generated Artwork", detail: "Delete generated thumbnails only. Media and sidecar images remain untouched." },
        { tab: "general", key: "logs", action: "Open Log Folder", title: "Diagnostic Logs", detail: "Open the folder containing rotating app and fatal-crash logs you can share for debugging." },
        { tab: "general", key: "reset", action: "Restore Defaults", title: "Reset Defaults", detail: "Restore every setting on every tab to its default: audio, display, controls, picture and theme." },
        { tab: "media", key: "audioOutput", title: "Audio Output", detail: "Choose System Default, speakers, headphones, or another destination exposed by VLC." },
        { tab: "media", key: "volume", title: "Volume", detail: "The volume ChannelOS uses now and on its next launch." },
        { tab: "media", key: "muted", title: "Muted", detail: "Remember whether ChannelOS should start muted." },
        { tab: "media", key: "videoAspectRatio", title: "Aspect Ratio", detail: "Auto uses each video's own shape. Force 4:3, 16:9, widescreen film ratios and more for mislabeled recordings." },
        { tab: "media", key: "videoFit", title: "Picture Fit", detail: "Fit shows the whole picture with bars, Fill crops the edges to fill the screen, Stretch fills it by distorting." },
        { tab: "media", key: "videoOverscan", title: "Overscan Trim", detail: "Trim the noisy edges found on VHS and broadcast captures, like a real TV did." },
        { tab: "media", key: "videoDeinterlace", title: "Deinterlace", detail: "Smooth combing on interlaced recordings. Auto lets VLC decide. Applies from the next program." },
        { tab: "media", key: "videoHardwareDecoding", title: "Hardware Decoding", detail: "Use the graphics card to decode video. Turn off if a driver shows green frames or artifacts. Applies from the next program." },
        { tab: "media", key: "videoBrightness", title: "Brightness", detail: "Picture brightness for every program." },
        { tab: "media", key: "videoContrast", title: "Contrast", detail: "Picture contrast for every program." },
        { tab: "media", key: "videoSaturation", title: "Color Saturation", detail: "Picture color intensity for every program." },
        { tab: "extras", key: "theme", title: "Theme", detail: "Change the look of ChannelOS. Themes you make in the Theme Builder appear here too." },
        { tab: "extras", key: "themeBuilder", action: "Open Theme Builder", title: "Theme Builder", detail: "Make your own theme: pick every color, add a wallpaper image, and preview it live." },
        { tab: "extras", key: "bootVideo", title: "Boot Video", detail: "What plays when ChannelOS starts: TV static, your own video, or nothing. Any button skips it." },
        { tab: "extras", key: "bootVideoFile", action: "Choose Video…", title: "My Boot Video", detail: "Pick a video to play at startup, like a console boot animation. It is copied into your setup." },
        { tab: "extras", key: "bootVideoSound", title: "Boot Video Sound", detail: "Play your boot video with sound, or silently." },
        { tab: "extras", key: "loadingStyle", title: "Loading Style", detail: "Classic, a fill bar along the bottom, or the dancing ChannelOS TV. Reduced Motion uses the fill bar." },
        { tab: "extras", key: "bootPreview", action: "Preview", title: "Preview Startup", detail: "Watch the loading style without restarting." },
        { tab: "extras", key: "portable", action: "Copy / Open Setup", title: "Portable Setup & Backup", detail: "Copy channels, the media index, ad configuration and history to a drive as a backup or to take with you, or open a setup you copied earlier." },
        { tab: "profiles", key: "activeProfile", title: "Switch Profile", detail: "Left/Right to choose, Select to switch. Kids, Daycare and Lobby lock until the PIN is entered." },
        { tab: "profiles", key: "profilePin", action: "Set PIN", title: "PIN", detail: "4 to 8 digits. Needed to leave a locked profile, open Settings or close ChannelOS from one." },
        { tab: "profiles", key: "editKids", action: "Edit…", title: "Kids", detail: "The channels you choose for your kids, with a softer volume limit. Settings and channel tools stay locked." },
        { tab: "profiles", key: "editDaycare", action: "Edit…", title: "Daycare", detail: "Like Kids, with no On Demand or skipping: programs play as scheduled." },
        { tab: "profiles", key: "editLobby", action: "Edit…", title: "Lobby", detail: "Starts full screen on one channel with no menus, for waiting rooms, shops and displays." }
    ]
    property int currentTab: 0
    readonly property var settingsRows: allRows.filter(function(row) { return row.tab === tabs[currentTab].key })
    readonly property bool themeBuilderOpen: themeBuilder.visible

    function openThemeBuilder() { themeBuilder.openBuilder() }
    // Profiles tab: the profile Left/Right points at before Select switches.
    property string pendingProfile: ""
    readonly property var profileInfo: channelOS && channelOS.profile ? channelOS.profile : ({ id: "home", name: "Home", hasPin: false })
    readonly property var profileOrder: ["home", "kids", "daycare", "lobby"]
    readonly property var profileTitles: ({ home: "Home", kids: "Kids", daycare: "Daycare", lobby: "Lobby" })
    function chosenProfile() { return pendingProfile.length > 0 ? pendingProfile : String(profileInfo.id || "home") }
    function handleDigit(digit) {
        if (pinSetPopup.visible)
            pinSetPad.handleIntent("DIGIT", Number(digit))
    }
    function handleThemeBuilderIntent(intent) { themeBuilder.handleIntent(String(intent)) }
    function selectTab(index) {
        currentTab = (index + tabs.length) % tabs.length
        if (hostWindow)
            hostWindow.settingsSelection = 0
    }
    function selectedRow() {
        var index = hostWindow ? hostWindow.settingsSelection : 0
        return settingsRows[Math.max(0, Math.min(settingsRows.length - 1, index))]
    }

    anchors.fill: parent
    visible: hostWindow !== null && hostWindow.screen === "settings"

    function profileLabel() {
        var profile = String(preferences.performanceProfile || "standard")
        return profile.charAt(0).toUpperCase() + profile.slice(1)
    }

    function displayModeLabel() {
        return displayMode === "windowed" ? "Windowed" : "Fullscreen"
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

    function applyDisplayMode() {
        if (hostWindow === null)
            return
        if (displayMode === "windowed")
            hostWindow.showNormal()
        else
            hostWindow.showFullScreen()
    }

    function applyStartupDisplayMode() {
        if (hostWindow === null)
            return
        if (!startupModeApplied) {
            startupModeApplied = true
            // A launcher-level --windowed request is an explicit developer
            // override. Preserve it for this run even when the saved preference
            // still says fullscreen.
            if (hostWindow.visibility === Window.Windowed
                    && displayMode === "fullscreen")
                return
        }
        applyDisplayMode()
    }

    function changeDisplayMode(direction) {
        if (!channelOS)
            return
        showResult(channelOS.changeDisplayMode(direction))
        applyDisplayMode()
    }

    function onOff(value) { return value ? "On" : "Off" }

    function valueFor(key) {
        switch (key) {
        case "performanceProfile": return profileLabel()
        case "displayMode": return displayModeLabel()
        case "audioOutput": return String(preferences.audioOutputDeviceName || "System Default")
        case "volume": return (preferences.volumePercent || 0) + "%"
        case "muted": return onOff(preferences.muted)
        case "skipBack": return (preferences.skipBackSeconds || 10) + " seconds"
        case "skipForward": return (preferences.skipForwardSeconds || 30) + " seconds"
        case "generateVideoThumbnails": return onOff(preferences.generateVideoThumbnails)
        case "artworkCacheLimit": return cacheLimitLabel()
        case "backgroundArtworkDuringPlayback": return onOff(preferences.backgroundArtworkDuringPlayback)
        case "reducedMotion": return onOff(preferences.reducedMotion)
        case "controllerEnabled": return onOff(preferences.controllerEnabled)
        case "theme": return String(preferences.themeName || "ChannelOS")
        case "bootVideo": return String(preferences.bootVideoLabel || "TV Static")
        case "bootVideoSound": return onOff(preferences.bootVideoSound !== false)
        case "loadingStyle": return String(preferences.loadingStyleLabel || "Classic")
        case "activeProfile":
            var chosen = chosenProfile()
            return profileTitles[chosen] + (chosen === String(profileInfo.id) ? "  (on)" : "  — Select to switch")
        case "profilePin": return profileInfo.hasPin ? "Set" : "Not set"
        }
        if (String(key).indexOf("video") === 0)
            return String(preferences[key] || "Auto")
        return ""
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

    function adjust(row, direction) {
        if (!row || row.action)
            return
        if (row.key === "displayMode") {
            changeDisplayMode(direction)
            return
        }
        if (row.key === "activeProfile") {
            var at = profileOrder.indexOf(chosenProfile())
            pendingProfile = profileOrder[(at + direction + profileOrder.length) % profileOrder.length]
            return
        }
        showResult(channelOS.adjustSetting(row.key, direction))
    }

    function activateAction(row) {
        if (!row || !row.action)
            return
        if (row.key === "themeBuilder") {
            openThemeBuilder()
        } else if (row.key === "clearArtwork") {
            showResult(typeof channelOS.beginArtworkCacheClear === "function"
                       ? channelOS.beginArtworkCacheClear() : channelOS.clearArtworkCache())
        } else if (row.key === "logs") {
            showResult(channelOS.openDiagnosticLogs())
        } else if (row.key === "reset") {
            showResult(channelOS.resetSettings())
            Qt.callLater(applyDisplayMode)
        } else if (row.key === "portable") {
            portableSetupDialog.open()
        } else if (row.key === "bootVideoFile") {
            if (typeof channelOS.chooseBootVideo === "function") {
                var result = channelOS.chooseBootVideo()
                if (!result.cancelled) showResult(result)
            }
        } else if (row.key === "bootPreview") {
            bootPreview.open()
        } else if (row.key === "profilePin") {
            pinSetPad.firstPin = ""
            pinSetPad.reset()
            pinSetPopup.open()
        } else if (row.key.indexOf("edit") === 0) {
            profileEditor.openFor(row.key.slice(4).toLowerCase())
        }
    }
    function switchProfile() {
        var target = chosenProfile()
        var result = channelOS.activateProfile(target)
        pendingProfile = ""
        showResult(result)
    }

    function handleControllerIntent(intent) {
        intent = String(intent)
        if (bootPreview.visible) {
            bootPreview.close()
            return
        }
        if (themeBuilder.visible) {
            themeBuilder.handleIntent(intent)
            return
        }
        if (pinSetPopup.visible) {
            pinSetPad.handleIntent(intent, -1)
            return
        }
        if (profileEditor.visible) {
            profileEditor.handleIntent(intent)
            return
        }
        if (portableSetupDialog.visible) {
            portableSetupDialog.handleControllerIntent(intent)
            return
        }
        if (!hostWindow || hostWindow.screen !== "settings")
            return
        if (intent === "BACK" || intent === "HOME") {
            hostWindow.screen = "home"
            return
        }
        // Shoulders, triggers, Page Up/Down and media keys switch tabs.
        if (["CHANNEL_DOWN", "SKIP_BACK", "REWIND", "PREVIOUS"].indexOf(intent) >= 0) {
            selectTab(currentTab - 1)
            return
        }
        if (["CHANNEL_UP", "SKIP_FORWARD", "FAST_FORWARD", "NEXT"].indexOf(intent) >= 0) {
            selectTab(currentTab + 1)
            return
        }
        if (intent === "UP") {
            hostWindow.settingsSelection = Math.max(0, hostWindow.settingsSelection - 1)
            return
        }
        if (intent === "DOWN") {
            hostWindow.settingsSelection = Math.min(settingsRows.length - 1, hostWindow.settingsSelection + 1)
            return
        }
        var row = selectedRow()
        if (intent === "LEFT" || intent === "RIGHT") {
            adjust(row, intent === "LEFT" ? -1 : 1)
            return
        }
        if (intent === "SELECT") {
            if (row && row.key === "activeProfile")
                switchProfile()
            else if (row && row.action)
                activateAction(row)
            else
                adjust(row, 1)
        }
    }

    ThemeBackdrop {
        anchors.fill: parent
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
        color: Theme.c("#071322")
        border.color: Theme.c("#1a3550")
        border.width: 1

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 38
            spacing: 18

            Row {
                spacing: 2
                Text { text: "Channel"; color: Theme.c("#f4f7fb"); font.pixelSize: 34; font.weight: Font.DemiBold }
                Text { text: "OS"; color: Theme.c("#42adff"); font.pixelSize: 34; font.weight: Font.DemiBold }
            }

            Item { width: 1; height: 18 }

            Repeater {
                model: settingsRoot.tabs
                delegate: Rectangle {
                    id: tabButton
                    required property int index
                    required property var modelData
                    readonly property bool current: index === settingsRoot.currentTab
                    objectName: "settingsTab_" + modelData.key
                    width: parent ? parent.width : 0
                    height: 68
                    radius: 7
                    color: current ? Theme.c("#12396a") : tabMouse.containsMouse ? Theme.c("#10283f") : "transparent"
                    border.color: current ? Theme.c("#42adff") : "transparent"
                    border.width: current ? 2 : 0
                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 18
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 3
                        Text {
                            text: tabButton.modelData.title
                            color: Theme.c("#f4f7fb")
                            font.pixelSize: 19
                            font.weight: tabButton.current ? Font.DemiBold : Font.Normal
                        }
                        Text {
                            width: parent.width
                            text: tabButton.modelData.detail
                            color: Theme.c("#9fb0c2")
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                    }
                    MouseArea {
                        id: tabMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: settingsRoot.selectTab(tabButton.index)
                    }
                }
            }

            Item { width: 1; height: 6 }

            Rectangle {
                width: parent.width
                height: 52
                radius: 7
                color: backMouse.containsMouse ? Theme.c("#10283f") : "transparent"
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: "‹  Back to Home"
                    color: Theme.c("#9fb0c2")
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
                color: Theme.c("#42adff")
                font.pixelSize: 13
                font.weight: Font.Bold
                font.letterSpacing: 2
            }
            Text {
                text: settingsRoot.profileLabel()
                color: Theme.c("#f4f7fb")
                font.pixelSize: 22
                font.weight: Font.DemiBold
            }
            Text {
                width: parent.width
                text: "Preferences save to the active setup. Audio device selection stays on this PC. Lightweight reduces optional artwork work and motion."
                color: Theme.c("#9fb0c2")
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
            text: settingsRoot.tabs[settingsRoot.currentTab].title
            color: Theme.c("#f4f7fb")
            font.pixelSize: 34
            font.weight: Font.DemiBold
        }

        Text {
            id: settingsSubtitle
            anchors.left: settingsTitle.left
            anchors.right: settingsTitle.right
            anchors.top: settingsTitle.bottom
            anchors.topMargin: 4
            text: settingsRoot.currentTab === 1
                  ? "Picture and sound for Live TV, On Demand and the Home preview. Changes save automatically."
                  : settingsRoot.currentTab === 2
                  ? "Make ChannelOS look your way, and back up or carry your whole setup. Changes save automatically."
                  : "How ChannelOS looks on screen, responds to controls and handles artwork. Changes save automatically."
            color: Theme.c("#9fb0c2")
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
                color: selected ? Theme.c("#102b50") : Theme.c("#0b1b2e")
                border.color: selected ? Theme.c("#42adff") : Theme.c("#17324a")
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
                        color: Theme.c("#f4f7fb")
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: settingRow.modelData.detail
                        color: Theme.c("#9fb0c2")
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
                    visible: !settingRow.modelData.action

                    Rectangle {
                        width: 38
                        height: 38
                        radius: 6
                        color: minusMouse.containsMouse ? Theme.c("#1a4d82") : Theme.c("#10283f")
                        border.color: Theme.c("#1a91ff")
                        Text { anchors.centerIn: parent; text: "−"; color: Theme.c("#f4f7fb"); font.pixelSize: 22 }
                        MouseArea {
                            id: minusMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                settingsRoot.hostWindow.settingsSelection = settingRow.index
                                settingsRoot.adjust(settingRow.modelData, -1)
                            }
                        }
                    }

                    Text {
                        width: 196
                        anchors.verticalCenter: parent.verticalCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: settingsRoot.valueFor(settingRow.modelData.key)
                        color: Theme.c("#42adff")
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Rectangle {
                        width: 38
                        height: 38
                        radius: 6
                        color: plusMouse.containsMouse ? Theme.c("#1a4d82") : Theme.c("#10283f")
                        border.color: Theme.c("#1a91ff")
                        Text { anchors.centerIn: parent; text: "+"; color: Theme.c("#f4f7fb"); font.pixelSize: 22 }
                        MouseArea {
                            id: plusMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                settingsRoot.hostWindow.settingsSelection = settingRow.index
                                settingsRoot.adjust(settingRow.modelData, 1)
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
                    visible: Boolean(settingRow.modelData.action)
                    color: actionMouse.containsMouse ? Theme.c("#1a4d82") : Theme.c("#10283f")
                    border.color: Theme.c("#1a91ff")
                    Text {
                        anchors.centerIn: parent
                        text: settingRow.modelData.key === "clearArtwork"
                              ? "Clear • " + settingsRoot.cacheUsageLabel()
                              : String(settingRow.modelData.action || "")
                        color: Theme.c("#f4f7fb")
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
                            settingsRoot.activateAction(settingRow.modelData)
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: channelOS
        ignoreUnknownSignals: true
        function onArtworkCacheCleared(result) { settingsRoot.showResult(result) }
        function onSettingsChanged() {
            if (settingsRoot.startupModeApplied)
                Qt.callLater(settingsRoot.applyDisplayMode)
        }
    }

    Shortcut {
        sequence: "F11"
        context: Qt.ApplicationShortcut
        onActivated: settingsRoot.changeDisplayMode(1)
    }

    Component.onCompleted: Qt.callLater(applyStartupDisplayMode)

    Rectangle {
        id: settingsFooter
        anchors.left: settingsSidebar.right
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 50
        color: Theme.c("#071322")
        border.color: Theme.c("#1a3550")
        border.width: 1
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 30
            anchors.verticalCenter: parent.verticalCenter
            text: "ARROWS  Navigate / Change     ENTER  Select     PG UP / PG DN  or  LB / RB  Tabs     F11  Display Mode     ESC  Home"
            color: Theme.c("#9fb0c2")
            font.pixelSize: 13
        }
    }

    PortableSetupDialog {
        id: portableSetupDialog
        parent: Overlay.overlay
    }

    ThemeBuilder {
        id: themeBuilder
    }

    ProfileEditor {
        id: profileEditor
        onSaved: function(result) { settingsRoot.showResult(result) }
    }

    // Set or change the PIN: enter it, then once more to confirm.
    Popup {
        id: pinSetPopup
        objectName: "pinSetPopup"
        parent: Overlay.overlay
        x: 0
        y: 0
        width: parent ? parent.width : 1280
        height: parent ? parent.height : 720
        padding: 0
        modal: true
        closePolicy: Popup.CloseOnEscape
        background: Item {}
        contentItem: PinPad {
            id: pinSetPad
            property string firstPin: ""
            title: firstPin.length > 0 ? "Enter the same PIN again" : (settingsRoot.profileInfo.hasPin ? "Choose a new PIN" : "Choose a PIN")
            reason: firstPin.length > 0 ? "" : "4 to 8 digits. Keep it somewhere safe: it is the way out of Kids, Daycare and Lobby."
            onSubmitted: function(pin) {
                if (firstPin.length === 0) {
                    firstPin = pin
                    reset()
                    return
                }
                if (pin !== firstPin) {
                    firstPin = ""
                    rejected("Those PINs did not match. Start again.")
                    return
                }
                var result = channelOS.setProfilePin(pin)
                firstPin = ""
                if (result && result.ok) {
                    pinSetPopup.close()
                    settingsRoot.showResult(result)
                } else {
                    rejected(result ? result.message : "PIN not saved")
                }
            }
            onCancelled: { firstPin = ""; pinSetPopup.close() }
        }
    }

    // Startup preview: the chosen loading style running through a full boot.
    Popup {
        id: bootPreview
        objectName: "bootPreview"
        parent: Overlay.overlay
        x: 0
        y: 0
        width: parent ? parent.width : 1280
        height: parent ? parent.height : 720
        padding: 0
        modal: true
        closePolicy: Popup.CloseOnEscape
        property real fake: 0
        onOpened: { fake = 0; previewRun.restart() }
        onClosed: previewRun.stop()
        SequentialAnimation {
            id: previewRun
            NumberAnimation { target: bootPreview; property: "fake"; from: 0; to: 1; duration: 5200; easing.type: Easing.InOutQuad }
            PauseAnimation { duration: 900 }
            ScriptAction { script: bootPreview.close() }
        }
        contentItem: BootScreen {
            loadingStyle: String(settingsRoot.preferences.loadingStyle || "classic")
            showStatic: String(settingsRoot.preferences.bootVideo || "static") !== "off"
            reducedMotion: Boolean(settingsRoot.preferences.reducedMotion)
            progress: bootPreview.fake
            message: bootPreview.fake < 0.4 ? "Opening your ChannelOS setup…" : bootPreview.fake < 0.8 ? "Tuning in…" : "Loading the rest of your channels…"
            running: bootPreview.visible
            Text {
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.topMargin: 28
                visible: String(settingsRoot.preferences.bootVideo) === "custom"
                text: "Your boot video plays first, then this"
                color: Theme.v("#c8d4e2")
                font.pixelSize: 16
            }
            Text {
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                anchors.margins: 24
                text: "Preview  •  any button closes"
                color: Theme.v("#9fb0c2")
                font.pixelSize: 13
            }
            MouseArea { anchors.fill: parent; onClicked: bootPreview.close() }
        }
    }
}
