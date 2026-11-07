import QtQuick

// On-screen number pad for the profile PIN. Works with a remote or controller
// (arrows + Select, digit keys type directly, Back cancels) and with a mouse.
// Main uses it to leave a locked profile; Settings uses it to set the PIN.
Item {
    id: pad
    objectName: "pinPad"

    property string title: "Enter PIN"
    property string reason: ""
    property string error: ""
    property string entered: ""
    property int focusIndex: 0
    property int maxLength: 8
    property int minLength: 4
    // Cells: 1..9, Clear, 0, OK
    readonly property var keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "ok"]

    signal submitted(string pin)
    signal cancelled()

    function reset() {
        entered = ""
        error = ""
        focusIndex = 0
    }
    function rejected(message) {
        error = String(message || "Wrong PIN")
        entered = ""
    }
    function press(key) {
        error = ""
        if (key === "clear") {
            entered = entered.length > 0 ? entered.slice(0, -1) : ""
        } else if (key === "ok") {
            if (entered.length < minLength) {
                error = "A PIN is " + minLength + " to " + maxLength + " digits"
                return
            }
            submitted(entered)
        } else if (entered.length < maxLength) {
            entered += key
        }
    }
    // intent: ControlIntent value; digit: 0..9 for DIGIT, else -1.
    function handleIntent(intent, digit) {
        switch (String(intent)) {
        case "DIGIT":
            if (digit >= 0 && digit <= 9) press(String(digit))
            return true
        case "UP": focusIndex = (focusIndex + 9) % 12; return true
        case "DOWN": focusIndex = (focusIndex + 3) % 12; return true
        case "LEFT": focusIndex = focusIndex % 3 === 0 ? focusIndex + 2 : focusIndex - 1; return true
        case "RIGHT": focusIndex = focusIndex % 3 === 2 ? focusIndex - 2 : focusIndex + 1; return true
        case "SELECT":
        case "PLAY_PAUSE":
            press(keys[focusIndex]); return true
        case "BACK":
            cancelled(); return true
        default:
            return true   // the pad owns input while it is open
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.v("#000000")
        opacity: 0.72
        MouseArea { anchors.fill: parent; onClicked: {} }
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: 380
        height: column.implicitHeight + 48
        radius: 14
        color: Theme.c("#0b1b2b")
        border.color: Theme.c("#24577d")
        border.width: 1

        Column {
            id: column
            anchors.top: parent.top
            anchors.topMargin: 24
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 48
            spacing: 14

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: pad.title
                color: Theme.c("#f4f7fb")
                font.pixelSize: 22
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                visible: pad.reason.length > 0
                text: pad.reason
                color: Theme.c("#a3b6ca")
                font.pixelSize: 15
                wrapMode: Text.Wrap
            }
            Row {
                objectName: "pinDots"
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 12
                height: 22
                Repeater {
                    model: Math.max(pad.minLength, pad.entered.length)
                    delegate: Rectangle {
                        required property int index
                        width: 16; height: 16; radius: 8
                        anchors.verticalCenter: parent.verticalCenter
                        color: index < pad.entered.length ? Theme.c("#42adff") : "transparent"
                        border.color: Theme.c("#42adff")
                        border.width: 2
                    }
                }
            }
            Text {
                objectName: "pinError"
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: pad.error
                visible: pad.error.length > 0
                color: Theme.c("#ff8585")
                font.pixelSize: 15
                wrapMode: Text.Wrap
            }
            Grid {
                anchors.horizontalCenter: parent.horizontalCenter
                columns: 3
                spacing: 10
                Repeater {
                    model: pad.keys
                    delegate: Rectangle {
                        required property string modelData
                        required property int index
                        readonly property bool focused: pad.focusIndex === index
                        width: 92; height: 58; radius: 10
                        color: focused ? Theme.c("#1a91ff") : (keyMouse.containsMouse ? Theme.c("#173452") : Theme.c("#10283f"))
                        border.color: focused ? Theme.c("#91b9e1") : Theme.c("#27445e")
                        border.width: focused ? 2 : 1
                        Text {
                            anchors.centerIn: parent
                            text: modelData === "clear" ? "⌫" : modelData === "ok" ? "OK" : modelData
                            color: Theme.c("#f4f7fb")
                            font.pixelSize: modelData.length === 1 ? 26 : 20
                            font.weight: Font.DemiBold
                        }
                        MouseArea {
                            id: keyMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: { pad.focusIndex = index; pad.press(modelData) }
                        }
                    }
                }
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "Back to cancel"
                color: Theme.c("#70869c")
                font.pixelSize: 13
                MouseArea { anchors.fill: parent; onClicked: pad.cancelled() }
            }
        }
    }
}
