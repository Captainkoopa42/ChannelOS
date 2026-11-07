pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

// Edit a Kids, Daycare or Lobby profile: which channels it shows, what the
// viewer can do, the volume limit and (Lobby) the channel it starts on.
// Remote: Up/Down move, Left/Right/Select change, Back closes without saving.
Popup {
    id: editor
    objectName: "profileEditor"
    parent: Overlay.overlay
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0
    width: parent ? Math.min(parent.width - 80, 720) : 720
    height: parent ? Math.min(parent.height - 80, 760) : 640
    modal: true
    padding: 0
    closePolicy: Popup.CloseOnEscape

    property string profileId: "kids"
    property var draft: ({})
    property int current: 0
    signal saved(var result)

    readonly property var toggleRows: [
        { key: "guide", title: "Guide", detail: "Browse what is on and what is next." },
        { key: "ondemand", title: "On Demand", detail: "Pick programs from the whole library." },
        { key: "change_channels", title: "Change Channels", detail: "Channel up/down and number entry. Off keeps the screen on one channel." },
        { key: "seek", title: "Skip & Rewind", detail: "Skip, rewind and fast-forward during programs." }
    ]
    readonly property var channelChoices: channelOS && channelOS.profileChannelChoices ? channelOS.profileChannelChoices : []
    readonly property var volumeLimits: channelOS && channelOS.profileVolumeLimits ? channelOS.profileVolumeLimits : [30, 40, 50, 60, 70, 80, 90, 100]
    readonly property var items: {
        var list = []
        if (profileId !== "lobby") {
            for (var i = 0; i < toggleRows.length; ++i)
                list.push({ kind: "toggle", key: toggleRows[i].key, title: toggleRows[i].title, detail: toggleRows[i].detail })
        }
        list.push({ kind: "volume", title: "Volume Limit", detail: "The loudest this profile can go." })
        if (profileId === "lobby")
            list.push({ kind: "boot", title: "Starts On", detail: "The channel the Lobby plays full screen at launch." })
        list.push({ kind: "allChannels", title: "Channels", detail: "Select checks or clears them all. Unchecked channels disappear from this profile." })
        for (var c = 0; c < channelChoices.length; ++c)
            list.push({ kind: "channel", number: channelChoices[c].number, title: channelChoices[c].number + "  " + channelChoices[c].name })
        list.push({ kind: "save", title: "Save" })
        return list
    }

    function openFor(id) {
        profileId = String(id)
        var profiles = channelOS && channelOS.profiles ? channelOS.profiles : []
        var found = null
        for (var i = 0; i < profiles.length; ++i)
            if (profiles[i].id === profileId) found = profiles[i]
        draft = found ? JSON.parse(JSON.stringify(found)) : ({ channels: [], volume_limit: 70 })
        if (!draft.channels) draft.channels = []
        current = 0
        open()
    }
    function hasChannel(number) { return (draft.channels || []).indexOf(number) >= 0 }
    function touch() { draft = JSON.parse(JSON.stringify(draft)) }
    function toggleChannel(number) {
        var list = draft.channels || []
        var at = list.indexOf(number)
        if (at >= 0) list.splice(at, 1); else list.push(number)
        draft.channels = list
        touch()
    }
    function cycle(values, value, direction) {
        var at = values.indexOf(value)
        if (at < 0) at = 0
        return values[(at + direction + values.length) % values.length]
    }
    function valueText(item) {
        switch (item.kind) {
        case "toggle": return draft[item.key] ? "On" : "Off"
        case "volume": return (draft.volume_limit || 100) + "%"
        case "boot": return draft.boot_channel ? "Channel " + draft.boot_channel : "First channel"
        case "allChannels": return (draft.channels || []).length + " of " + channelChoices.length
        case "channel": return hasChannel(item.number) ? "✓" : ""
        }
        return ""
    }
    function change(item, direction) {
        if (!item) return
        if (item.kind === "toggle") { draft[item.key] = !draft[item.key]; touch() }
        else if (item.kind === "volume") { draft.volume_limit = cycle(volumeLimits, draft.volume_limit, direction); touch() }
        else if (item.kind === "boot") {
            var numbers = [0].concat((draft.channels || []).slice().sort(function(a, b) { return a - b }))
            var next = cycle(numbers, draft.boot_channel || 0, direction)
            draft.boot_channel = next > 0 ? next : null
            touch()
        } else if (item.kind === "allChannels") {
            draft.channels = (draft.channels || []).length === channelChoices.length
                ? [] : channelChoices.map(function(c) { return c.number })
            touch()
        } else if (item.kind === "channel") toggleChannel(item.number)
        else if (item.kind === "save") save()
    }
    function save() {
        var changes = { channels: draft.channels || [], volume_limit: draft.volume_limit, boot_channel: draft.boot_channel || null }
        for (var i = 0; i < toggleRows.length; ++i)
            if (profileId !== "lobby") changes[toggleRows[i].key] = Boolean(draft[toggleRows[i].key])
        var result = channelOS.updateProfile(profileId, JSON.stringify(changes))
        saved(result)
        if (result && result.ok) close()
    }
    function handleIntent(intent) {
        switch (String(intent)) {
        case "UP": current = Math.max(0, current - 1); break
        case "DOWN": current = Math.min(items.length - 1, current + 1); break
        case "LEFT": change(items[current], -1); break
        case "RIGHT":
        case "SELECT": change(items[current], 1); break
        case "BACK":
        case "HOME": close(); break
        }
        list.positionViewAtIndex(current, ListView.Contain)
    }

    background: Rectangle {
        radius: 14
        color: Theme.c("#0b1b2b")
        border.color: Theme.c("#24577d")
    }

    contentItem: Item {
        Text {
            id: heading
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: 26
            text: "Edit " + (editor.profileId.charAt(0).toUpperCase() + editor.profileId.slice(1)) + " Profile"
            color: Theme.c("#f4f7fb")
            font.pixelSize: 26
            font.weight: Font.DemiBold
        }
        Text {
            id: hint
            anchors.left: heading.left
            anchors.right: parent.right
            anchors.rightMargin: 26
            anchors.top: heading.bottom
            anchors.topMargin: 6
            wrapMode: Text.Wrap
            text: editor.profileId === "lobby"
                  ? "Lobby plays full screen with no menus. Settings and channel management stay behind the PIN."
                  : "Settings and channel management always stay behind the PIN."
            color: Theme.c("#a3b6ca")
            font.pixelSize: 14
        }
        ListView {
            id: list
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: hint.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 20
            clip: true
            spacing: 4
            model: editor.items
            delegate: Rectangle {
                id: row
                required property var modelData
                required property int index
                readonly property bool focused: editor.current === index
                width: list.width
                height: modelData.kind === "channel" ? 40 : (modelData.detail ? 62 : 48)
                radius: 8
                color: focused ? Theme.c("#163b5d") : (modelData.kind === "save" ? Theme.c("#12304d") : "transparent")
                border.color: focused ? Theme.c("#42adff") : "transparent"
                border.width: 2
                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: row.modelData.kind === "channel" ? 34 : 14
                    anchors.right: valueLabel.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        text: row.modelData.title
                        color: Theme.c("#f4f7fb")
                        font.pixelSize: row.modelData.kind === "channel" ? 16 : 18
                        font.weight: row.modelData.kind === "save" ? Font.DemiBold : Font.Normal
                        elide: Text.ElideRight
                        width: parent.width
                    }
                    Text {
                        visible: Boolean(row.modelData.detail)
                        text: row.modelData.detail || ""
                        color: Theme.c("#8fa9c2")
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        width: parent.width
                    }
                }
                Text {
                    id: valueLabel
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: editor.valueText(row.modelData)
                    color: Theme.c("#42adff")
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { editor.current = row.index; editor.change(row.modelData, 1) }
                }
            }
        }
    }
}
