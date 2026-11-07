pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

// Couch keyboard (Dedicated Controller Mode): a console-style on-screen
// keyboard that types into whichever text box was selected. It never takes
// focus, so a real keyboard keeps working too.
//
// Controller: D-pad/stick move, A/Select types, X (Play/Pause) deletes,
// Y (Info) adds a space, LB/RB move the cursor, Back or Done closes.
Popup {
    id: osk
    objectName: "onScreenKeyboard"
    parent: Overlay.overlay
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? parent.height - height - 24 : 0
    width: parent ? Math.min(parent.width - 40, 980) : 980
    height: column.implicitHeight + 32
    modal: false
    focus: false
    padding: 16
    closePolicy: Popup.NoAutoClose

    property var target: null
    property string mode: "letters"     // letters | symbols
    property bool shifted: false
    property bool capsLock: false
    property int row: 1
    property int col: 0
    property string preview: target ? String(target.text) : ""
    property string label: ""
    signal finished()

    readonly property var letterRows: [
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
        ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
        ["a", "s", "d", "f", "g", "h", "j", "k", "l", "'"],
        ["shift", "z", "x", "c", "v", "b", "n", "m", ",", "."],
        ["mode", "space", "back", "left", "right", "done"]
    ]
    readonly property var symbolRows: [
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
        ["!", "@", "#", "$", "%", "&", "*", "(", ")", "-"],
        ["_", "+", "=", "/", "\\", ":", ";", "\"", "?", "#"],
        ["shift", "<", ">", "[", "]", "{", "}", "~", "|", "^"],
        ["mode", "space", "back", "left", "right", "done"]
    ]
    readonly property var rows: mode === "letters" ? letterRows : symbolRows
    readonly property bool upper: shifted || capsLock

    function keyWidth(key) {
        return key === "space" ? 3.2 : key === "done" ? 1.6 : key === "mode" || key === "shift" || key === "back" ? 1.4 : 1
    }
    function keyText(key) {
        switch (key) {
        case "shift": return capsLock ? "⇪" : "⇧"
        case "space": return "Space"
        case "back": return "⌫"
        case "left": return "◀"
        case "right": return "▶"
        case "done": return "Done"
        case "mode": return mode === "letters" ? "?123" : "ABC"
        }
        return upper && key.length === 1 ? key.toUpperCase() : key
    }

    function openFor(item, name) {
        target = item
        label = name || ""
        mode = "letters"
        shifted = false
        row = 1
        col = 0
        preview = item ? String(item.text) : ""
        open()
    }
    function refresh() { preview = target ? String(target.text) : "" }
    function insertText(value) {
        if (!target) return
        if (target.selectedText && target.selectedText.length > 0)
            target.remove(target.selectionStart, target.selectionEnd)
        var position = target.cursorPosition
        target.insert(position, value)
        if (target.cursorPosition === position) target.cursorPosition = position + value.length
        refresh()
    }
    function backspace() {
        if (!target) return
        if (target.selectedText && target.selectedText.length > 0) {
            target.remove(target.selectionStart, target.selectionEnd)
        } else if (target.cursorPosition > 0) {
            var position = target.cursorPosition
            target.remove(position - 1, position)
        }
        refresh()
    }
    function moveCursor(step) {
        if (!target) return
        target.cursorPosition = Math.max(0, Math.min(String(target.text).length, target.cursorPosition + step))
    }
    function done() {
        if (target && typeof target.editingFinished === "function") target.editingFinished()
        close()
        finished()
    }
    function press(key) {
        switch (key) {
        case "shift":
            if (shifted) { shifted = false; capsLock = !capsLock } else if (capsLock) capsLock = false
            else shifted = true
            return
        case "mode": mode = mode === "letters" ? "symbols" : "letters"; return
        case "space": insertText(" "); return
        case "back": backspace(); return
        case "left": moveCursor(-1); return
        case "right": moveCursor(1); return
        case "done": done(); return
        }
        insertText(keyText(key))
        shifted = false
    }
    // Column under the same x position when moving between rows of different widths.
    function nearestColumn(fromRow, fromCol, toRow) {
        var widths = function(r) { return rows[r].map(keyWidth) }
        var source = widths(fromRow), target = widths(toRow)
        var center = 0
        for (var i = 0; i < fromCol; ++i) center += source[i]
        center += source[fromCol] / 2
        var scale = target.reduce(function(a, b) { return a + b }, 0) / source.reduce(function(a, b) { return a + b }, 0)
        center *= scale
        var edge = 0
        for (var j = 0; j < target.length; ++j) {
            edge += target[j]
            if (center <= edge) return j
        }
        return target.length - 1
    }
    function handleIntent(intent) {
        switch (String(intent)) {
        case "UP": if (row > 0) { col = nearestColumn(row, col, row - 1); row -= 1 } break
        case "DOWN": if (row < rows.length - 1) { col = nearestColumn(row, col, row + 1); row += 1 } break
        case "LEFT": col = (col + rows[row].length - 1) % rows[row].length; break
        case "RIGHT": col = (col + 1) % rows[row].length; break
        case "SELECT": press(rows[row][col]); break
        case "PLAY_PAUSE": backspace(); break
        case "INFO": insertText(" "); break
        case "CHANNEL_DOWN": case "SKIP_BACK": moveCursor(-1); break
        case "CHANNEL_UP": case "SKIP_FORWARD": moveCursor(1); break
        case "MENU": case "HOME": case "BACK": done(); break
        case "DIGIT": break
        }
        return true
    }

    onClosed: target = null
    Connections {
        target: osk.target
        ignoreUnknownSignals: true
        function onTextChanged() { osk.refresh() }
    }

    background: Rectangle {
        radius: 16
        color: Theme.c("#071322")
        border.color: Theme.c("#24577d")
        border.width: 2
    }

    contentItem: Column {
        id: column
        spacing: 10
        Row {
            width: parent.width
            spacing: 12
            Text {
                text: osk.label.length > 0 ? osk.label : "Typing"
                color: Theme.c("#9fb0c2"); font.pixelSize: 14
                anchors.verticalCenter: parent.verticalCenter
            }
            Rectangle {
                width: parent.width - 220
                height: 40
                radius: 8
                color: Theme.c("#050c15")
                border.color: Theme.c("#1a3550")
                clip: true
                Text {
                    objectName: "oskPreview"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: osk.preview.length > 0 ? osk.preview : " "
                    color: Theme.c("#f4f7fb"); font.pixelSize: 18
                    elide: Text.ElideLeft
                }
            }
            Text {
                text: "X ⌫   Y space   LB/RB cursor"
                color: Theme.c("#70869c"); font.pixelSize: 12
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Repeater {
            model: osk.rows
            delegate: Row {
                id: keyRow
                required property var modelData
                required property int index
                readonly property real unit: (column.width - spacing * (modelData.length - 1))
                                             / modelData.reduce(function(a, b) { return a + osk.keyWidth(b) }, 0)
                spacing: 6
                Repeater {
                    model: keyRow.modelData
                    delegate: Rectangle {
                        id: key
                        required property string modelData
                        required property int index
                        readonly property bool focused: osk.row === keyRow.index && osk.col === index
                        readonly property bool special: modelData.length > 1
                        width: keyRow.unit * osk.keyWidth(modelData)
                        height: 52
                        radius: 9
                        color: focused ? Theme.c("#1a91ff")
                             : modelData === "done" ? Theme.c("#12527f")
                             : (modelData === "shift" && osk.upper) ? Theme.c("#176aa6")
                             : special ? Theme.c("#0b2034") : Theme.c("#10283f")
                        border.color: focused ? Theme.c("#f4f7fb") : Theme.c("#24577d")
                        border.width: focused ? 2 : 1
                        scale: focused ? 1.05 : 1
                        Behavior on scale { NumberAnimation { duration: 70 } }
                        Text {
                            anchors.centerIn: parent
                            text: osk.keyText(key.modelData)
                            color: Theme.c("#f4f7fb")
                            font.pixelSize: key.special ? 16 : 22
                            font.weight: Font.DemiBold
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: { osk.row = keyRow.index; osk.col = key.index; osk.press(key.modelData) }
                        }
                    }
                }
            }
        }
    }
}
