import QtQuick
import QtQuick.Controls

Item {
    id: settingsRoot
    property var hostWindow: null
    readonly property var preferences:
        channelOS ? channelOS.settings : ({
            volumePercent: 100,
            muted: false,
            skipBackSeconds: 10,
            skipForwardSeconds: 30
        })

    anchors.fill: parent
    visible: hostWindow !== null && hostWindow.screen === "settings"

    function valueFor(index) {
        if (index === 0)
            return (preferences.volumePercent || 0) + "%"
        if (index === 1)
            return preferences.muted ? "On" : "Off"
        if (index === 2)
            return (preferences.skipBackSeconds || 10) + " seconds"
        if (index === 3)
            return (preferences.skipForwardSeconds || 30) + " seconds"
        return "Restore"
    }

    function settingName(index) {
        return ["volume", "muted", "skipBack", "skipForward"][index]
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
        if (index < 0 || index > 3)
            return
        showResult(channelOS.adjustSetting(settingName(index), direction))
    }

    Rectangle {
        anchors.fill: parent
        color: "#050c15"
    }

    Timer {
        id: statusClearTimer
        interval: 4200
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
                Text {
                    text: "Channel"
                    color: "#f4f7fb"
                    font.pixelSize: 34
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "OS"
                    color: "#42adff"
                    font.pixelSize: 34
                    font.weight: Font.DemiBold
                }
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
                text: "SOUND & PLAYBACK"
                color: "#42adff"
                font.pixelSize: 13
                font.weight: Font.Bold
                font.letterSpacing: 2
            }
            Text {
                width: parent.width
                text: "Preferences are stored locally in .channelos/settings.json. Your media and channel databases are not modified."
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

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 44
            spacing: 8

            Text {
                text: "Settings"
                color: "#f4f7fb"
                font.pixelSize: 34
                font.weight: Font.DemiBold
            }
            Text {
                text: "Simple defaults for your couch experience. Changes save automatically."
                color: "#9fb0c2"
                font.pixelSize: 17
            }

            Item { width: 1; height: 24 }

            Repeater {
                model: [
                    { title: "Volume", detail: "The volume ChannelOS uses now and on its next launch." },
                    { title: "Muted", detail: "Remember whether ChannelOS should start muted." },
                    { title: "Skip Back", detail: "How far Left/Rewind jumps during Live TV and On Demand." },
                    { title: "Skip Forward", detail: "How far Right/Fast Forward jumps during Live TV and On Demand." },
                    { title: "Reset Defaults", detail: "Restore volume 100%, sound on, 10 seconds back, and 30 seconds forward." }
                ]

                delegate: Rectangle {
                    readonly property bool selected:
                        settingsRoot.hostWindow !== null
                        && index === settingsRoot.hostWindow.settingsSelection
                    // Repeater delegates briefly have no parent while Qt is
                    // constructing them. Use stable root geometry so startup
                    // never evaluates parent.width through a null parent.
                    width: Math.max(
                        1,
                        settingsRoot.width - settingsSidebar.width - 88
                    )
                    height: 94
                    radius: 9
                    color: selected ? "#102b50" : "#0b1b2e"
                    border.color: selected ? "#42adff" : "#17324a"
                    border.width: selected ? 2 : 1

                    MouseArea {
                        anchors.fill: parent
                        onClicked: settingsRoot.hostWindow.settingsSelection = index
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 22
                        spacing: 6
                        width: parent.width * 0.63

                        Text {
                            text: modelData.title
                            color: "#f4f7fb"
                            font.pixelSize: 20
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: modelData.detail
                            color: "#9fb0c2"
                            font.pixelSize: 14
                            width: parent.width
                            elide: Text.ElideRight
                        }
                    }

                    Row {
                        anchors.right: parent.right
                        anchors.rightMargin: 20
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 10
                        visible: index < 4

                        Rectangle {
                            width: 42
                            height: 42
                            radius: 6
                            color: minusMouse.containsMouse ? "#1a4d82" : "#10283f"
                            border.color: "#1a91ff"
                            Text {
                                anchors.centerIn: parent
                                text: "−"
                                color: "#f4f7fb"
                                font.pixelSize: 24
                            }
                            MouseArea {
                                id: minusMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    settingsRoot.hostWindow.settingsSelection = index
                                    settingsRoot.adjust(index, -1)
                                }
                            }
                        }

                        Text {
                            width: 116
                            anchors.verticalCenter: parent.verticalCenter
                            horizontalAlignment: Text.AlignHCenter
                            text: settingsRoot.valueFor(index)
                            color: "#42adff"
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }

                        Rectangle {
                            width: 42
                            height: 42
                            radius: 6
                            color: plusMouse.containsMouse ? "#1a4d82" : "#10283f"
                            border.color: "#1a91ff"
                            Text {
                                anchors.centerIn: parent
                                text: "+"
                                color: "#f4f7fb"
                                font.pixelSize: 24
                            }
                            MouseArea {
                                id: plusMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    settingsRoot.hostWindow.settingsSelection = index
                                    settingsRoot.adjust(index, 1)
                                }
                            }
                        }
                    }

                    Rectangle {
                        anchors.right: parent.right
                        anchors.rightMargin: 20
                        anchors.verticalCenter: parent.verticalCenter
                        width: 150
                        height: 44
                        radius: 6
                        visible: index === 4
                        color: resetMouse.containsMouse ? "#1a4d82" : "#10283f"
                        border.color: "#1a91ff"

                        Text {
                            anchors.centerIn: parent
                            text: "Reset"
                            color: "#f4f7fb"
                            font.pixelSize: 16
                            font.weight: Font.DemiBold
                        }

                        MouseArea {
                            id: resetMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                settingsRoot.hostWindow.settingsSelection = 4
                                settingsRoot.showResult(channelOS.resetSettings())
                            }
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
