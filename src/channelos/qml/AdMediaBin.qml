pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "AdSources.js" as AdSources

Item {
    id: bin
    property var mediaLibrary: []
    property var sourceOptions: []
    property var sources: []
    property var assetIds: []
    property var excludedIds: []
    property bool readOnly: false
    property var expanded: ({})
    readonly property var groups: AdSources.groups(mediaLibrary, sources, assetIds, [])
    readonly property int clipCount: AdSources.selected(mediaLibrary, sources, assetIds, excludedIds).length
    signal sourcesEdited(var paths)
    signal exclusionsEdited(var ids)

    function rows() {
        var result = [], needle = String(search.text || "").trim().toLowerCase()
        groups.forEach(function(group) {
            var matching = group.media.filter(function(item) {
                return !needle || String(item.title || "").toLowerCase().indexOf(needle) >= 0
                        || String(group.name).toLowerCase().indexOf(needle) >= 0
            })
            if (needle && !matching.length) return
            var open = Boolean(expanded[group.path]) || needle.length > 0
            result.push({source:true, path:group.path, name:group.name, count:group.media.length,
                         selected:group.media.filter(function(item) { return excludedIds.indexOf(item.assetId) < 0 }).length, open:open})
            if (open) matching.forEach(function(item) { result.push({source:false, media:item}) })
        })
        return result
    }
    function removeSource(path) {
        if (path.length) sourcesEdited(sources.filter(function(value) { return AdSources.key(value) !== AdSources.key(path) }))
        else {
            var next = excludedIds.slice()
            groups.filter(function(group) { return !group.path.length }).forEach(function(group) {
                group.media.forEach(function(item) { if (next.indexOf(item.assetId) < 0) next.push(item.assetId) })
            })
            exclusionsEdited(next)
        }
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        Label { objectName: "adBinCount"; text: bin.clipCount + " selected ads in " + bin.groups.length + " sources"; color: "#9fb0c2"; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Label { visible: bin.readOnly; text: "Managed by advanced placements. Edit their sources in Profiles."; color: "#ffb84a"; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
        ChannelTextField { id: search; objectName: "adBinSearch"; Layout.fillWidth: true; placeholderText: "Search selected ads…" }
        Label { text: "ADD INDEXED SOURCE"; color: "#9fb0c2"; font.pixelSize: 10 }
        RowLayout {
            Layout.fillWidth: true; spacing: 5; enabled: !bin.readOnly
            ChannelComboBox { id: sourcePicker; objectName: "adBinSourcePicker"; Layout.fillWidth: true; model: bin.sourceOptions; ToolTip.visible: hovered; ToolTip.text: currentText }
            ChannelButton { text: "Add"; enabled: sourcePicker.count > 0; onClicked: { var path = sourcePicker.currentText; if (!bin.sources.some(function(value) { return AdSources.key(value) === AdSources.key(path) })) { var next = bin.sources.slice(); next.push(path); bin.sourcesEdited(next) } } }
            ChannelButton { text: "Clear"; enabled: bin.sources.length > 0 || bin.assetIds.length > 0; onClicked: { bin.sourcesEdited([]); bin.exclusionsEdited(bin.assetIds.slice()) } }
        }
        Label { text: "Expand a source to choose clips. Sequential follows this source and clip order."; color: "#9fb0c2"; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
        ListView {
            id: list; objectName: "adBinList"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 7; model: bin.rows()
            ScrollBar.vertical: ScrollBar { }
            Label { anchors.centerIn: parent; width: parent.width - 16; visible: bin.groups.length === 0; text: "No ad sources selected.\nAdd an indexed source above."; color: "#9fb0c2"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
            delegate: Rectangle {
                id: card; required property var modelData
                width: list.width; height: modelData.source ? 68 : Math.max(62, clipChoice.implicitHeight + 16)
                color: "#0d2035"; border.color: "#1a3550"; radius: 7
                RowLayout {
                    anchors.fill: parent; anchors.margins: 6; visible: card.modelData.source; spacing: 5
                    ChannelButton {
                        Layout.fillWidth: true; Layout.fillHeight: true; checked: Boolean(card.modelData.open)
                        onClicked: { var next = Object.assign({}, bin.expanded); next[card.modelData.path] = !next[card.modelData.path]; bin.expanded = next }
                        contentItem: Column {
                            spacing: 4
                            Text { width: parent.width; text: (card.modelData.open ? "▾  " : "▸  ") + card.modelData.name + " · " + card.modelData.selected + "/" + card.modelData.count; color: "#f4f7fb"; font.pixelSize: 12; elide: Text.ElideRight }
                            Text { width: parent.width; text: card.modelData.path || "Fixed selection"; color: "#9fb0c2"; font.pixelSize: 10; elide: Text.ElideMiddle }
                        }
                        ToolTip.visible: hovered; ToolTip.text: String(card.modelData.path || card.modelData.name)
                    }
                    ChannelButton { text: "×"; implicitWidth: 32; destructive: true; enabled: !bin.readOnly; Accessible.name: "Remove ad source"; onClicked: bin.removeSource(card.modelData.path) }
                }
                ChannelCheckBox {
                    id: clipChoice; anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.margins: 10
                    visible: !card.modelData.source
                    enabled: !bin.readOnly
                    text: String((card.modelData.media || {}).title || "") + " · " + Number((card.modelData.media || {}).durationSeconds || 0).toFixed(0) + "s"
                    checked: bin.excludedIds.indexOf(String((card.modelData.media || {}).assetId || "")) < 0
                    onClicked: {
                        var id = String(card.modelData.media.assetId), next = bin.excludedIds.filter(function(value) { return value !== id })
                        if (!checked) next.push(id)
                        bin.exclusionsEdited(next)
                    }
                    ToolTip.visible: hovered; ToolTip.text: String((card.modelData.media || {}).path || "")
                }
            }
        }
    }
}
