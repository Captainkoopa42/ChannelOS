pragma ComponentBehavior: Bound
import QtQuick

// A controller drawn from a family layout (controller_layouts.py): the body
// shape plus every control at its position on a 100 x 60 canvas.
Item {
    id: diagram
    objectName: "controllerDiagram"

    property var family: ({ body: "gamepad", controls: [] })
    property string selected: ""
    property string flashed: ""
    signal controlClicked(string control)

    readonly property real unit: Math.min(width / 100, height / 60)
    readonly property real originX: (width - unit * 100) / 2
    readonly property real originY: (height - unit * 60) / 2
    readonly property color bodyColor: Theme.c("#10283f")
    readonly property color bodyEdge: Theme.c("#24577d")

    function shapeRect(x, y, w, h) { return { x: originX + x * unit, y: originY + y * unit, w: w * unit, h: h * unit } }

    component Part: Rectangle {
        property real px; property real py; property real pw; property real ph
        x: diagram.originX + px * diagram.unit
        y: diagram.originY + py * diagram.unit
        width: pw * diagram.unit
        height: ph * diagram.unit
        color: diagram.bodyColor
        border.color: diagram.bodyEdge
        border.width: 2
        antialiasing: true
    }

    // Bodies: simple shapes that read as each controller family.
    Item {
        anchors.fill: parent
        visible: ["gamepad", "gamecube"].indexOf(diagram.family.body) >= 0
        Part { px: 4; py: 26; pw: 26; ph: 32; radius: 13 * diagram.unit; rotation: 18 }
        Part { px: 70; py: 26; pw: 26; ph: 32; radius: 13 * diagram.unit; rotation: -18 }
        Part { px: 8; py: 8; pw: 84; ph: 36; radius: 16 * diagram.unit }
    }
    Item {
        anchors.fill: parent
        visible: diagram.family.body === "deck"
        Part { px: 1; py: 8; pw: 98; ph: 46; radius: 12 * diagram.unit }
        Rectangle {
            x: diagram.originX + 38 * diagram.unit; y: diagram.originY + 30 * diagram.unit
            width: 24 * diagram.unit; height: 18 * diagram.unit; radius: 2 * diagram.unit
            color: Theme.c("#050c15"); border.color: diagram.bodyEdge
        }
    }
    Item {
        anchors.fill: parent
        visible: diagram.family.body === "n64"
        Part { px: 4; py: 4; pw: 92; ph: 26; radius: 12 * diagram.unit }
        Part { px: 8; py: 18; pw: 22; ph: 40; radius: 10 * diagram.unit }
        Part { px: 40; py: 22; pw: 20; ph: 36; radius: 10 * diagram.unit }
        Part { px: 70; py: 18; pw: 22; ph: 40; radius: 10 * diagram.unit }
        Part { px: 6; py: 6; pw: 88; ph: 22; radius: 11 * diagram.unit; border.width: 0 }
    }
    Part { visible: diagram.family.body === "dogbone"; px: 6; py: 12; pw: 88; ph: 40; radius: 20 * diagram.unit }
    Part { visible: diagram.family.body === "brick"; px: 6; py: 18; pw: 88; ph: 34; radius: 2 * diagram.unit }
    Part { visible: diagram.family.body === "genesis"; px: 6; py: 6; pw: 88; ph: 46; radius: 22 * diagram.unit }
    Part { visible: diagram.family.body === "stick"; px: 10; py: 6; pw: 80; ph: 50; radius: 4 * diagram.unit }
    Rectangle {
        // The Atari stick's shaft, behind its four directions.
        visible: diagram.family.body === "stick"
        x: diagram.originX + 50 * diagram.unit; y: diagram.originY + 29 * diagram.unit
        width: 10 * diagram.unit; height: 10 * diagram.unit; radius: width / 2
        color: Theme.c("#050c15"); border.color: diagram.bodyEdge; border.width: 2
    }

    // Controls
    Repeater {
        model: diagram.family.controls || []
        delegate: Rectangle {
            id: control
            required property var modelData
            readonly property bool isSelected: diagram.selected === modelData.id
            readonly property bool isFlashed: diagram.flashed === modelData.id
            readonly property string shape: modelData.shape
            objectName: "control_" + modelData.id
            x: diagram.originX + (modelData.x - modelData.w / 2) * diagram.unit
            y: diagram.originY + (modelData.y - modelData.h / 2) * diagram.unit
            width: modelData.w * diagram.unit
            height: modelData.h * diagram.unit
            radius: shape === "dpad" ? 1.2 * diagram.unit
                  : shape === "pad" ? 2 * diagram.unit
                  : shape === "bumper" || shape === "trigger" || shape === "pill" ? Math.min(width, height) / 2
                  : Math.min(width, height) / 2
            antialiasing: true
            z: isSelected ? 2 : 1
            color: isFlashed ? Theme.c("#42adff")
                 : isSelected ? Theme.c("#146ad1")
                 : shape === "stick" ? Theme.c("#081625")
                 : Theme.c("#0b1b2b")
            border.color: isSelected ? Theme.c("#f4f7fb") : (modelData.tint ? modelData.tint : Theme.c("#70869c"))
            border.width: isSelected ? Math.max(2, 0.6 * diagram.unit) : Math.max(1, 0.35 * diagram.unit)
            scale: isFlashed ? 1.12 : 1
            Behavior on scale { NumberAnimation { duration: 90 } }
            Rectangle {
                // Sticks get an inner cap.
                visible: control.shape === "stick"
                anchors.centerIn: parent
                width: parent.width * 0.62; height: width; radius: width / 2
                color: "transparent"
                border.color: Theme.c("#31465b"); border.width: Math.max(1, 0.3 * diagram.unit)
            }
            Text {
                anchors.centerIn: parent
                text: control.modelData.label
                color: control.isSelected || control.isFlashed ? Theme.c("#ffffff")
                       : (control.modelData.tint ? control.modelData.tint : Theme.c("#f4f7fb"))
                font.pixelSize: Math.max(8, Math.min(control.height * (control.shape === "pad" ? 0.32 : 0.5),
                                                     control.width * (text.length > 3 ? 0.24 : text.length > 1 ? 0.36 : 0.55)))
                font.weight: Font.DemiBold
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: diagram.controlClicked(control.modelData.id)
            }
        }
    }
}
