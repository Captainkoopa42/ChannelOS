pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

// Button mapper, Steam-style: the controller drawn on the left, every button
// on the right with what it does. Up/Down choose a button, Select picks its
// action. "Find a button" jumps to whatever you press on the controller.
// While the mapper is open the controller navigates with the default layout,
// so a half-finished remap can never strand you here.
Popup {
    id: mapper
    objectName: "controllerMapper"
    parent: Overlay.overlay
    x: 0
    y: 0
    width: parent ? parent.width : 1280
    height: parent ? parent.height : 720
    modal: true
    padding: 0
    closePolicy: Popup.CloseOnEscape

    property string connectedFamily: ""
    property string connectedName: ""
    property int current: 0
    property bool listening: false
    property string flashed: ""
    property double swallowUntil: 0
    property bool pickerOpen: false
    property int pickerIndex: 0
    signal result(var result)

    readonly property var settingsMap: channelOS && channelOS.settings ? channelOS.settings : ({})
    readonly property var families: channelOS && channelOS.controllerFamilies ? channelOS.controllerFamilies : []
    readonly property var actions: channelOS && channelOS.controllerActions ? channelOS.controllerActions : []
    readonly property var bindings: channelOS && channelOS.controllerBindings ? channelOS.controllerBindings : ({})
    readonly property string layoutSetting: String(settingsMap.controllerLayout || "auto")
    readonly property string familyId: layoutSetting !== "auto" ? layoutSetting : (connectedFamily || "xbox")
    readonly property var family: {
        for (var i = 0; i < families.length; ++i)
            if (families[i].id === familyId) return families[i]
        return families.length ? families[families.length - 1] : ({ body: "gamepad", controls: [] })
    }
    readonly property var rows: {
        var list = [{ kind: "layout" }, { kind: "find" }]
        var controls = family.controls || []
        for (var i = 0; i < controls.length; ++i)
            list.push({ kind: "control", id: controls[i].id, label: controls[i].label })
        list.push({ kind: "stick" })
        list.push({ kind: "reset" })
        return list
    }
    readonly property var currentRow: rows[Math.max(0, Math.min(rows.length - 1, current))]

    function actionLabel(id) {
        for (var i = 0; i < actions.length; ++i)
            if (actions[i].id === id) return actions[i].label
        return id
    }
    function rowIndexFor(control) {
        for (var i = 0; i < rows.length; ++i)
            if (rows[i].kind === "control" && rows[i].id === control) return i
        return -1
    }
    function openMapper() {
        current = 0
        listening = false
        pickerOpen = false
        open()
    }
    function report(value) { if (value) result(value) }
    function activate(row) {
        if (!row) return
        if (row.kind === "layout") report(channelOS.adjustSetting("controllerLayout", 1))
        else if (row.kind === "find") listening = !listening
        else if (row.kind === "reset") report(channelOS.resetControllerBindings())
        else if (row.kind === "control") {
            var currentAction = bindings[row.id] || "NONE"
            pickerIndex = 0
            for (var i = 0; i < actions.length; ++i)
                if (actions[i].id === currentAction) pickerIndex = i
            pickerOpen = true
        }
    }
    function choose(index) {
        var row = currentRow
        pickerOpen = false
        if (row && row.kind === "control")
            report(channelOS.setControllerBinding(row.id, actions[index].id))
    }
    function handleIntent(intent) {
        if (Date.now() < swallowUntil) return
        intent = String(intent)
        if (pickerOpen) {
            if (intent === "UP") pickerIndex = Math.max(0, pickerIndex - 1)
            else if (intent === "DOWN") pickerIndex = Math.min(actions.length - 1, pickerIndex + 1)
            else if (intent === "SELECT") choose(pickerIndex)
            else if (intent === "BACK" || intent === "HOME") pickerOpen = false
            actionList.positionViewAtIndex(pickerIndex, ListView.Contain)
            return
        }
        if (listening && (intent === "BACK" || intent === "HOME")) { listening = false; return }
        switch (intent) {
        case "UP": current = Math.max(0, current - 1); break
        case "DOWN": current = Math.min(rows.length - 1, current + 1); break
        case "LEFT": if (currentRow.kind === "layout") report(channelOS.adjustSetting("controllerLayout", -1)); break
        case "RIGHT": if (currentRow.kind === "layout") report(channelOS.adjustSetting("controllerLayout", 1)); break
        case "SELECT": activate(currentRow); break
        case "BACK":
        case "HOME": close(); break
        }
        rowList.positionViewAtIndex(current, ListView.Contain)
    }
    function buttonPressed(control) {
        flashed = control
        flashTimer.restart()
        if (!listening) return
        var index = rowIndexFor(control)
        if (index < 0) return
        listening = false
        current = index
        rowList.positionViewAtIndex(current, ListView.Contain)
        // The same press also arrives as a command a moment later: ignore it.
        swallowUntil = Date.now() + 350
    }

    onOpened: if (channelOS && typeof channelOS.setControllerCapture === "function") channelOS.setControllerCapture(true)
    onClosed: {
        listening = false
        pickerOpen = false
        if (channelOS && typeof channelOS.setControllerCapture === "function") channelOS.setControllerCapture(false)
    }
    onRowsChanged: current = Math.min(current, rows.length - 1)

    Timer { id: flashTimer; interval: 260; onTriggered: mapper.flashed = "" }
    Connections {
        target: channelOS
        ignoreUnknownSignals: true
        function onControllerButtonPressed(control) { mapper.buttonPressed(control) }
    }

    background: Rectangle { color: Theme.c("#050c15") }

    contentItem: Item {
        // Header
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
                Text { text: "Button Mapper"; color: Theme.c("#f4f7fb"); font.pixelSize: 28; font.weight: Font.DemiBold }
                Text {
                    text: mapper.connectedName ? "Connected: " + mapper.connectedName
                                               : "No controller connected. You can still set up buttons for when one is."
                    color: Theme.c("#9fb0c2"); font.pixelSize: 14
                }
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 32
                anchors.verticalCenter: parent.verticalCenter
                text: "↑↓  Choose     SELECT  Change     BACK  Done"
                color: Theme.c("#9fb0c2"); font.pixelSize: 13
            }
        }

        ControllerDiagram {
            id: drawing
            anchors.left: parent.left
            anchors.top: header.bottom
            anchors.bottom: parent.bottom
            anchors.right: panel.left
            anchors.margins: 36
            family: mapper.family
            selected: mapper.currentRow && mapper.currentRow.kind === "control" ? mapper.currentRow.id : ""
            flashed: mapper.flashed
            onControlClicked: function(control) {
                var index = mapper.rowIndexFor(control)
                if (index >= 0) { mapper.current = index; mapper.activate(mapper.rows[index]) }
            }
        }
        Text {
            anchors.horizontalCenter: drawing.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 18
            width: drawing.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: mapper.family.name + "  ·  " + (mapper.family.detail || "")
                  + (mapper.layoutSetting === "auto" ? "  ·  matched to your controller" : "")
            color: Theme.c("#9fb0c2"); font.pixelSize: 14
        }

        Rectangle {
            id: panel
            anchors.right: parent.right
            anchors.top: header.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 20
            width: Math.min(460, parent.width * 0.38)
            radius: 12
            color: Theme.c("#081625")
            border.color: Theme.c("#1a3550")

            ListView {
                id: rowList
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                spacing: 4
                model: mapper.rows
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    required property int index
                    readonly property bool focused: mapper.current === index
                    width: rowList.width
                    height: modelData.kind === "control" ? 44 : 56
                    radius: 8
                    color: focused ? Theme.c("#12396a") : "transparent"
                    border.color: focused ? Theme.c("#42adff") : "transparent"
                    border.width: 2
                    Rectangle {
                        id: chip
                        visible: row.modelData.kind === "control"
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.max(34, chipText.implicitWidth + 14)
                        height: 28
                        radius: 14
                        color: Theme.c("#0b1b2b")
                        border.color: Theme.c("#70869c")
                        Text { id: chipText; anchors.centerIn: parent; text: row.modelData.label || ""; color: Theme.c("#f4f7fb"); font.pixelSize: 13; font.weight: Font.DemiBold }
                    }
                    Column {
                        anchors.left: row.modelData.kind === "control" ? chip.right : parent.left
                        anchors.leftMargin: 14
                        anchors.right: value.left
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            color: Theme.c("#f4f7fb")
                            font.pixelSize: 16
                            text: row.modelData.kind === "layout" ? "Layout"
                                : row.modelData.kind === "find" ? (mapper.listening ? "Press any button…" : "Find a Button")
                                : row.modelData.kind === "stick" ? "Left Stick"
                                : row.modelData.kind === "reset" ? "Reset All Buttons"
                                : mapper.actionLabel(mapper.bindings[row.modelData.id] || "NONE")
                        }
                        Text {
                            width: parent.width
                            visible: text.length > 0
                            elide: Text.ElideRight
                            color: Theme.c("#9fb0c2")
                            font.pixelSize: 12
                            text: row.modelData.kind === "layout" ? "Which controller is drawn. Automatic matches the one plugged in."
                                : row.modelData.kind === "find" ? (mapper.listening ? "Back cancels" : "Press Select, then the button you want to change")
                                : row.modelData.kind === "stick" ? "Always moves around menus, so you can't get stuck"
                                : row.modelData.kind === "reset" ? "Put every button back the way it came"
                                : ""
                        }
                    }
                    Text {
                        id: value
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.kind === "layout" ? "◀ " + (mapper.layoutSetting === "auto" ? "Automatic" : mapper.family.name) + " ▶"
                            : row.modelData.kind === "control" ? "›" : ""
                        color: Theme.c("#42adff")
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { mapper.current = row.index; mapper.activate(row.modelData) }
                    }
                }
            }
        }

        // Action picker for the chosen button.
        Rectangle {
            visible: mapper.pickerOpen
            objectName: "controllerActionPicker"
            anchors.fill: panel
            radius: 12
            color: Theme.c("#0b1b2b")
            border.color: Theme.c("#42adff")
            Text {
                id: pickerTitle
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 16
                text: mapper.currentRow && mapper.currentRow.kind === "control" ? mapper.currentRow.label + " does…" : ""
                color: Theme.c("#f4f7fb"); font.pixelSize: 18; font.weight: Font.DemiBold
            }
            ListView {
                id: actionList
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: pickerTitle.bottom
                anchors.bottom: parent.bottom
                anchors.margins: 12
                clip: true
                model: mapper.actions
                delegate: Rectangle {
                    id: actionRow
                    required property var modelData
                    required property int index
                    width: actionList.width
                    height: 36
                    radius: 6
                    color: mapper.pickerIndex === index ? Theme.c("#146ad1") : "transparent"
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: actionRow.modelData.label
                        color: Theme.c("#f4f7fb"); font.pixelSize: 15
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        visible: mapper.currentRow && mapper.bindings[mapper.currentRow.id] === actionRow.modelData.id
                        text: "current"
                        color: Theme.c("#9fb0c2"); font.pixelSize: 12
                    }
                    MouseArea { anchors.fill: parent; onClicked: mapper.choose(actionRow.index) }
                }
            }
        }
    }
}
