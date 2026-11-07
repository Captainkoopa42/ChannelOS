pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Planner collections: indexed owned media grouped for tracks. Shared by the
// Planner tab in Studio (inside Studio's bin panel) and the standalone view.
ColumnLayout {
    id: bin
    property var planner: null
    spacing: 10

    Text {
        Layout.fillWidth: true
        text: bin.planner && bin.planner.mediaBin.length
              ? bin.planner.count(bin.planner.mediaBin.length, "collection") + " · drag one onto an hour in Day, or add it as a track"
              : "Indexed collections appear here"
        color: Theme.c("#9fb0c2")
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
    ChannelTextField {
        objectName: "plannerCollectionSearch"
        Layout.fillWidth: true
        placeholderText: "Search collections…"
        onTextChanged: if (bin.planner) bin.planner.search = text
    }
    ListView {
        id: binList
        objectName: "plannerCollectionList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 9
        model: bin.planner ? bin.planner.mediaBin.filter(function(g) {
            return g.name.toLowerCase().indexOf(bin.planner.search.toLowerCase()) >= 0
        }) : []
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            id: binCard
            required property var modelData
            width: binList.width
            height: binContent.implicitHeight + 20
            radius: 8
            property var binGroup: modelData
            color: binDrag.containsMouse ? Theme.c("#12304d") : Theme.c("#0d2035")
            border.color: binDrag.drag.active ? Theme.c("#42adff") : Theme.c("#1a3550")
            Drag.active: binDrag.drag.active
            Drag.source: binCard
            Drag.keys: ["planner-group"]
            Drag.hotSpot.x: width / 2
            Drag.hotSpot.y: height / 2
            ColumnLayout {
                id: binContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 5
                Text {
                    text: binCard.modelData.name
                    color: Theme.c("#f4f7fb")
                    font.weight: Font.DemiBold
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Text {
                    text: bin.planner.count(binCard.modelData.count, "video") + " · " + bin.planner.hours(binCard.modelData.seconds)
                    color: Theme.c("#9fb0c2")
                    font.pixelSize: 11
                }
                Text {
                    visible: binCard.modelData.missing > 0
                    text: binCard.modelData.missing + " unavailable or not yet measured"
                    color: Theme.c("#ffb84a")
                    font.pixelSize: 11
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    ChannelButton { text: "+ Track"; Layout.fillWidth: true; onClicked: bin.planner.addTrack(binCard.modelData, false) }
                    ChannelButton { text: "+ Rerun"; Layout.fillWidth: true; onClicked: bin.planner.addTrack(binCard.modelData, true) }
                }
                ChannelButton {
                    text: "+ Filler pool"
                    Layout.fillWidth: true
                    onClicked: bin.planner.addFiller(binCard.modelData)
                }
            }
            MouseArea {
                id: binDrag
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 50
                hoverEnabled: true
                drag.target: binCard
                drag.axis: Drag.XAndYAxis
                onReleased: { binCard.Drag.drop(); binCard.x = 0; binCard.y = 0; binList.forceLayout() }
                onDoubleClicked: bin.planner.addTrack(binCard.modelData, false)
            }
        }
    }
    Text {
        Layout.fillWidth: true
        visible: bin.planner && !bin.planner.mediaBin.length
        text: bin.planner && bin.planner.loaded ? "No indexed media. Add and scan a source in Library first." : "Loading collections…"
        color: Theme.c("#9fb0c2")
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
}
