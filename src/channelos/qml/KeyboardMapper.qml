pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

// Keyboard mapper: every action with the keys that trigger it. Select an
// action, then press a key to add it. Backspace clears that action's keys and
// Esc cancels. Esc is always Back and the number keys always tune channels,
// so nobody can lock themselves out.
Popup {
    id: keys
    objectName: "keyboardMapper"
    parent: Overlay.overlay
    x: 0
    y: 0
    width: parent ? parent.width : 1280
    height: parent ? parent.height : 720
    modal: true
    padding: 0
    closePolicy: Popup.NoAutoClose

    property var hostWindow: null
    property int current: 0
    property bool listening: false
    signal result(var result)

    readonly property var actionRows: channelOS && channelOS.keyBindings ? channelOS.keyBindings : []
    readonly property var rows: actionRows.concat([{ action: "__reset", label: "Reset All Keys", keys: [] }])

    function setListening(value) {
        listening = value
        if (hostWindow) hostWindow.keyCaptureActive = value
        if (value) catcher.forceActiveFocus()
    }
    function openMapper() { current = 0; open() }
    function activate(index) {
        current = index
        var row = rows[index]
        if (!row) return
        if (row.action === "__reset") result(channelOS.resetKeyBindings())
        else setListening(true)
    }
    function handleIntent(intent) {
        intent = String(intent)
        if (listening) {
            if (intent === "BACK" || intent === "HOME") setListening(false)
            return
        }
        switch (intent) {
        case "UP": current = Math.max(0, current - 1); break
        case "DOWN": current = Math.min(rows.length - 1, current + 1); break
        case "SELECT": activate(current); break
        case "BACK":
        case "HOME": close(); break
        }
        list.positionViewAtIndex(current, ListView.Contain)
    }
    function captured(keyCode) {
        var row = rows[current]
        if (keyCode === Qt.Key_Escape) { setListening(false); return }
        if (keyCode === Qt.Key_Backspace || keyCode === Qt.Key_Delete) {
            result(channelOS.clearKeysForAction(row.action))
            setListening(false)
            return
        }
        var name = channelOS.keyName(keyCode)
        if (!name || name.indexOf("Key_Shift") === 0 || name === "Key_Control" || name === "Key_Alt" || name === "Key_Meta")
            return   // wait for a real key
        result(channelOS.setKeyBinding(name, row.action))
        setListening(false)
    }

    onClosed: setListening(false)

    background: Rectangle { color: Theme.c("#050c15") }

    contentItem: Item {
        Item {
            id: catcher
            objectName: "keyCatcher"
            focus: keys.listening
            Keys.onPressed: function(event) {
                if (!keys.listening) return
                event.accepted = true
                keys.captured(event.key)
            }
        }
        Rectangle {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            height: 84
            color: Theme.c("#071322")
            border.color: Theme.c("#1a3550")
            Column {
                anchors.left: parent.left
                anchors.leftMargin: 32
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4
                Text { text: "Keyboard Mapper"; color: Theme.c("#f4f7fb"); font.pixelSize: 28; font.weight: Font.DemiBold }
                Text {
                    text: "Select an action, then press a key to add it. Esc is always Back; 0–9 always tune channels."
                    color: Theme.c("#9fb0c2"); font.pixelSize: 14
                }
            }
        }
        ListView {
            id: list
            anchors.top: header.bottom
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.margins: 20
            width: Math.min(parent.width - 40, 900)
            clip: true
            spacing: 4
            model: keys.rows
            delegate: Rectangle {
                id: row
                required property var modelData
                required property int index
                readonly property bool focused: keys.current === index
                width: list.width
                height: 50
                radius: 8
                color: focused ? (keys.listening ? Theme.c("#4b3717") : Theme.c("#12396a")) : Theme.c("#081625")
                border.color: focused ? (keys.listening ? Theme.c("#ffb84a") : Theme.c("#42adff")) : Theme.c("#1a3550")
                border.width: focused ? 2 : 1
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    width: 220
                    elide: Text.ElideRight
                    text: row.modelData.label
                    color: Theme.c("#f4f7fb"); font.pixelSize: 16
                }
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 250
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    clip: true
                    Text {
                        visible: row.focused && keys.listening
                        text: "Press a key…  (Backspace clears, Esc cancels)"
                        color: Theme.c("#ffb84a"); font.pixelSize: 14
                    }
                    Repeater {
                        model: row.focused && keys.listening ? [] : row.modelData.keys
                        delegate: Rectangle {
                            id: keyChip
                            required property var modelData
                            height: 28
                            width: Math.max(34, keyText.implicitWidth + 16)
                            radius: 6
                            color: Theme.c("#0b1b2b")
                            border.color: keyChip.modelData.fixed ? Theme.c("#70869c") : Theme.c("#42adff")
                            Text { id: keyText; anchors.centerIn: parent; text: keyChip.modelData.label; color: Theme.c("#f4f7fb"); font.pixelSize: 13; font.weight: Font.DemiBold }
                        }
                    }
                    Text {
                        visible: !(row.focused && keys.listening) && row.modelData.action !== "__reset" && row.modelData.keys.length === 0
                        text: "No key"
                        color: Theme.c("#70869c"); font.pixelSize: 13
                    }
                }
                MouseArea { anchors.fill: parent; onClicked: keys.activate(row.index) }
            }
        }
    }
}
