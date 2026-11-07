import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A date button that opens a month calendar. `date` is "YYYY-MM-DD" or "".
ChannelButton {
    id: picker

    property string date: ""
    property bool optional: false
    property string placeholder: "Choose date"
    property string viewMonth: ""
    signal picked(string date)

    readonly property var weekdayNames: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    readonly property var monthNames: ["January", "February", "March", "April", "May", "June", "July",
                                       "August", "September", "October", "November", "December"]

    implicitWidth: Math.max(150, implicitContentWidth + leftPadding + rightPadding)
    text: date ? label(date) : placeholder
    onClicked: {
        viewMonth = (date || today()).slice(0, 7)
        popup.open()
    }

    function today() {
        var now = new Date()
        return iso(now.getFullYear(), now.getMonth() + 1, now.getDate())
    }
    function pad(value) { return (value < 10 ? "0" : "") + value }
    function iso(year, month, day) { return year + "-" + pad(month) + "-" + pad(day) }
    function parts(value) {
        var bits = String(value).split("-")
        return { year: Number(bits[0]), month: Number(bits[1]), day: Number(bits[2] || 1) }
    }
    function label(value) {
        var p = parts(value)
        var day = new Date(Date.UTC(p.year, p.month - 1, p.day))
        if (isNaN(day.getTime())) return String(value)
        return weekdayNames[(day.getUTCDay() + 6) % 7] + ", " + monthNames[p.month - 1].slice(0, 3)
                + " " + p.day + ", " + p.year
    }
    function shiftMonth(amount) {
        var p = parts(viewMonth + "-01")
        var moved = new Date(Date.UTC(p.year, p.month - 1 + amount, 1))
        viewMonth = iso(moved.getUTCFullYear(), moved.getUTCMonth() + 1, 1).slice(0, 7)
    }
    function cells() {
        var p = parts(viewMonth + "-01")
        var first = new Date(Date.UTC(p.year, p.month - 1, 1))
        var leading = (first.getUTCDay() + 6) % 7
        var list = []
        for (var i = 0; i < 42; ++i) {
            var day = new Date(Date.UTC(p.year, p.month - 1, 1 + i - leading))
            list.push(iso(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate()))
        }
        return list
    }
    function choose(value) {
        date = value
        picked(value)
        popup.close()
    }

    Popup {
        id: popup
        y: picker.height + 4
        width: 300
        padding: 12
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 10; color: Theme.c("#0d2035"); border.color: Theme.c("#1a3550") }

        ColumnLayout {
            anchors.fill: parent
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                ChannelButton { text: "‹"; implicitWidth: 38; onClicked: picker.shiftMonth(-1) }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: picker.viewMonth
                          ? picker.monthNames[picker.parts(picker.viewMonth + "-01").month - 1] + " "
                            + picker.parts(picker.viewMonth + "-01").year : ""
                    color: Theme.c("#f4f7fb")
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
                ChannelButton { text: "›"; implicitWidth: 38; onClicked: picker.shiftMonth(1) }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 7
                rowSpacing: 3
                columnSpacing: 3
                Repeater {
                    model: picker.weekdayNames
                    delegate: Text {
                        required property string modelData
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: modelData
                        color: Theme.c("#9fb0c2")
                        font.pixelSize: 10
                    }
                }
                Repeater {
                    model: popup.visible ? picker.cells() : []
                    delegate: Rectangle {
                        id: cell
                        required property string modelData
                        readonly property bool inMonth: modelData.slice(0, 7) === picker.viewMonth
                        readonly property bool selected: modelData === picker.date
                        readonly property bool isToday: modelData === picker.today()
                        Layout.fillWidth: true
                        implicitHeight: 32
                        radius: 6
                        color: selected ? Theme.c("#1a91ff") : cellArea.containsMouse ? Theme.c("#143a5c") : "transparent"
                        border.color: isToday && !selected ? Theme.c("#42adff") : "transparent"
                        Text {
                            anchors.centerIn: parent
                            text: Number(cell.modelData.slice(-2))
                            color: cell.selected ? Theme.c("#ffffff") : cell.inMonth ? Theme.c("#f4f7fb") : Theme.c("#55687c")
                            font.pixelSize: 12
                            font.weight: cell.selected ? Font.Bold : Font.Normal
                        }
                        MouseArea {
                            id: cellArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: picker.choose(cell.modelData)
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                ChannelButton { text: "Today"; Layout.fillWidth: true; onClicked: picker.choose(picker.today()) }
                ChannelButton {
                    visible: picker.optional
                    text: "Clear"
                    Layout.fillWidth: true
                    onClicked: picker.choose("")
                }
            }
        }
    }
}
