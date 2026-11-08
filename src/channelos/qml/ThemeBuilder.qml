pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Theme Builder: edit a theme's colours and wallpaper with a live preview
// across the whole app, then save it as your own theme.
Popup {
    id: builder
    objectName: "themeBuilder"
    parent: Overlay.overlay
    x: 0
    y: 0
    width: parent ? parent.width : 1280
    height: parent ? parent.height : 720
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.NoAutoClose

    property var themes: channelOS && channelOS.themes ? channelOS.themes : []
    property var roleList: channelOS && channelOS.themeRoles ? channelOS.themeRoles : []
    property var draft: ({ name: "My Theme", roles: ({}), wallpaper: "", wallpaperUrl: "",
                           wallpaperFit: "fill", wallpaperOpacity: 100, panelOpacity: 85 })
    property string selectedId: ""
    property bool dirty: false
    property string status: ""
    property bool statusError: false
    property string editingRole: ""

    readonly property var swatches: [
        "#003399", "#6699cc", "#ff6600", "#ffcc00", "#cc0000", "#ff3399", "#9933cc", "#00cc99",
        "#1a73e8", "#34a853", "#fbbc04", "#ea4335", "#202124", "#5f6368", "#dadce0", "#f1f3f4",
        "#ffffff", "#000000", "#050c15", "#081625", "#1a91ff", "#42adff", "#f4f7fb", "#ff4a4a"
    ]

    function themeById(id) {
        for (var i = 0; i < themes.length; ++i)
            if (themes[i].id === id) return themes[i]
        return null
    }
    function load(id) {
        var theme = themeById(id)
        if (!theme) return
        selectedId = id
        draft = {
            id: theme.builtin ? "" : theme.id,
            name: theme.builtin ? "My " + theme.name : theme.name,
            roles: JSON.parse(JSON.stringify(theme.roles)),
            wallpaper: theme.wallpaper || "", wallpaperUrl: theme.wallpaperUrl || "",
            wallpaperFit: theme.wallpaperFit || "fill",
            wallpaperOpacity: Number(theme.wallpaperOpacity || 100),
            panelOpacity: Number(theme.panelOpacity || 100) >= 100 ? 85 : Number(theme.panelOpacity)
        }
        dirty = false
        status = theme.builtin ? theme.name + " is built in. Saving creates your own copy." : ""
        statusError = false
        preview()
    }
    function set(key, value) {
        var next = Object.assign({}, draft)
        next[key] = value
        draft = next
        dirty = true
        previewTimer.restart()
    }
    function setRole(key, value) {
        var roles = Object.assign({}, draft.roles)
        roles[key] = String(value).toLowerCase()
        set("roles", roles)
    }
    function payload() {
        return JSON.stringify({ id: draft.id || "", name: draft.name, roles: draft.roles,
                                wallpaper: draft.wallpaper, wallpaperFit: draft.wallpaperFit,
                                wallpaperOpacity: draft.wallpaperOpacity, panelOpacity: draft.panelOpacity })
    }
    function preview() {
        if (channelOS && typeof channelOS.previewTheme === "function")
            channelOS.previewTheme(payload())
    }
    function save(use) {
        var result = channelOS.saveTheme(payload(), use)
        status = String(result.message || "")
        statusError = !result.ok
        if (result.ok) {
            dirty = false
            selectedId = String(result.id)
            draft = Object.assign({}, draft, { id: String(result.id) })
            if (!use) preview()
        }
    }
    function useSelected() {
        var result = channelOS.useTheme(selectedId)
        status = String(result.message || "")
        statusError = !result.ok
    }
    function chooseImage() {
        var result = channelOS.chooseThemeImage()
        if (result.cancelled) return
        status = String(result.message || "")
        statusError = !result.ok
        if (result.ok) {
            var next = Object.assign({}, draft, { wallpaper: result.file, wallpaperUrl: result.url })
            draft = next
            dirty = true
            preview()
        }
    }
    function openBuilder() {
        var current = channelOS && channelOS.settings ? String(channelOS.settings.theme || "channelos") : "channelos"
        open()
        load(themeById(current) ? current : "channelos")
        Qt.callLater(focusSelectedTheme)
    }
    // Remote and controller: put focus on the theme being edited.
    function focusSelectedTheme() {
        for (var i = 0; i < themes.length; ++i) {
            if (themes[i].id === selectedId) {
                themeList.positionViewAtIndex(i, ListView.Contain)
                var row = themeList.itemAtIndex(i)
                if (row) { row.forceActiveFocus(); return }
            }
        }
        saveUseButton.forceActiveFocus()
    }
    function closeBuilder() {
        picker.close()
        if (channelOS && typeof channelOS.endThemePreview === "function")
            channelOS.endThemePreview()
        close()
    }
    function handleIntent(intent) {
        if (intent === "BACK" || intent === "HOME") {
            if (picker.visible) picker.close()
            else closeBuilder()
        }
    }
    function hsl(hex) {
        var c = Qt.color(hex)
        return { h: Math.max(0, c.hslHue), s: c.hslSaturation, l: c.hslLightness }
    }
    function hexOf(h, s, l) {
        var c = Qt.hsla(h, s, l, 1)
        function part(v) { var t = Math.round(v * 255).toString(16); return t.length < 2 ? "0" + t : t }
        return "#" + part(c.r) + part(c.g) + part(c.b)
    }

    Timer { id: previewTimer; interval: 120; onTriggered: builder.preview() }

    background: ThemeBackdrop {}

    component Heading: Text { color: Theme.c("#f4f7fb"); font.pixelSize: 16; font.weight: Font.DemiBold }
    component Caption: Text { color: Theme.c("#9fb0c2"); font.pixelSize: 12; wrapMode: Text.WordWrap }
    component Card: Rectangle { radius: 10; color: Theme.c("#081625"); border.color: Theme.c("#1a3550") }
    component Percent: RowLayout {
        id: percent
        property string label
        property int value
        property int from: 10
        readonly property real sliderValue: slider.value
        signal moved(int value)
        Layout.fillWidth: true
        Caption { text: percent.label; Layout.preferredWidth: 120 }
        Slider {
            id: slider
            Layout.fillWidth: true
            from: percent.from; to: 100; stepSize: 5
            // A Binding element keeps following the draft after a drag or key
            // press (a plain `value:` binding is broken by the first move).
            Binding on value { value: percent.value; restoreMode: Binding.RestoreNone }
            onMoved: percent.moved(Math.round(value))
            background: Rectangle {
                x: slider.leftPadding; y: slider.topPadding + slider.availableHeight / 2 - 3
                width: slider.availableWidth; height: 6; radius: 3
                color: Theme.c("#1a3550")
                Rectangle { width: slider.visualPosition * parent.width; height: parent.height; radius: 3; color: Theme.c("#1a91ff") }
            }
            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: 20; height: 20; radius: 10
                color: Theme.c("#f4f7fb"); border.color: Theme.c("#42adff"); border.width: 2
            }
        }
        Text { text: percent.value + "%"; color: Theme.c("#42adff"); font.pixelSize: 13; Layout.preferredWidth: 44 }
    }

    contentItem: ColumnLayout {
        spacing: 0

        // Header
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 76
            color: Theme.c("#071322")
            border.color: Theme.c("#1a3550")
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 28
                anchors.rightMargin: 28
                spacing: 14
                ColumnLayout {
                    spacing: 2
                    Text { text: "Theme Builder"; color: Theme.c("#f4f7fb"); font.pixelSize: 26; font.weight: Font.DemiBold }
                    Caption { text: "Pick colours, add your own wallpaper, and watch every screen change as you go." }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    visible: builder.dirty
                    radius: 12; color: Theme.c("#4b3717"); border.color: Theme.c("#ffb84a")
                    implicitWidth: unsaved.implicitWidth + 20; implicitHeight: 28
                    Text { id: unsaved; anchors.centerIn: parent; text: "UNSAVED"; color: Theme.c("#ffb84a"); font.pixelSize: 11; font.weight: Font.Bold }
                }
                ChannelButton { text: "Save"; enabled: builder.dirty || !builder.draft.id; onClicked: builder.save(false) }
                ChannelButton { id: saveUseButton; objectName: "themeBuilderSaveUse"; text: "Save & Use"; highlighted: true; onClicked: builder.save(true) }
                ChannelButton { text: "Close"; onClicked: builder.closeBuilder() }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 20
            spacing: 16

            // Theme list
            Card {
                Layout.preferredWidth: Math.max(230, builder.width * 0.2)
                Layout.maximumWidth: Layout.preferredWidth
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    Heading { text: "Themes" }
                    ListView {
                        id: themeList
                        objectName: "themeBuilderList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 8
                        model: builder.themes
                        delegate: Rectangle {
                            id: themeRow
                            required property var modelData
                            required property int index
                            width: themeList.width
                            height: 62
                            radius: 8
                            activeFocusOnTab: true
                            Keys.onSpacePressed: builder.load(modelData.id)
                            Keys.onReturnPressed: builder.load(modelData.id)
                            onActiveFocusChanged: if (activeFocus) themeList.positionViewAtIndex(index, ListView.Contain)
                            color: modelData.id === builder.selectedId ? Theme.c("#12396a") : Theme.c("#0d2035")
                            border.color: activeFocus ? Theme.c("#f4f7fb") : modelData.id === builder.selectedId ? Theme.c("#42adff") : Theme.c("#1a3550")
                            border.width: activeFocus || modelData.id === builder.selectedId ? 2 : 1
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 6
                                RowLayout {
                                    Text { text: themeRow.modelData.name; color: Theme.c("#f4f7fb"); font.pixelSize: 14; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                    Text { visible: themeRow.modelData.builtin; text: "BUILT IN"; color: Theme.c("#9fb0c2"); font.pixelSize: 9; font.letterSpacing: 1 }
                                    Text { visible: channelOS && channelOS.settings && channelOS.settings.theme === themeRow.modelData.id; text: "IN USE"; color: Theme.c("#2bcf75"); font.pixelSize: 9; font.weight: Font.Bold }
                                }
                                Row {
                                    spacing: 3
                                    Repeater {
                                        model: ["background", "surface", "text", "accent", "highlight", "live"]
                                        delegate: Rectangle {
                                            required property string modelData
                                            width: 22; height: 12; radius: 3
                                            color: themeRow.modelData.roles[modelData] || "transparent"
                                            border.color: Theme.c("#1a3550")
                                        }
                                    }
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: builder.load(themeRow.modelData.id)
                            }
                        }
                    }
                    Caption {
                        Layout.fillWidth: true
                        text: "Click a theme to edit it. Built-in themes stay as they are: saving one makes your own copy."
                    }
                    ChannelButton {
                        Layout.fillWidth: true
                        text: "Switch to This Theme"
                        enabled: builder.selectedId !== "" && !builder.dirty
                                 && !(channelOS && channelOS.settings && channelOS.settings.theme === builder.selectedId)
                        onClicked: builder.useSelected()
                    }
                    ChannelButton {
                        Layout.fillWidth: true
                        text: builder.selectedId.indexOf("custom-") === 0 ? "Delete This Theme" : "Built-in (can't delete)"
                        destructive: true
                        enabled: builder.selectedId.indexOf("custom-") === 0
                        onClicked: {
                            var result = channelOS.deleteTheme(builder.selectedId)
                            builder.status = String(result.message || "")
                            builder.statusError = !result.ok
                            if (result.ok) builder.load("channelos")
                        }
                    }
                }
            }

            // Colours
            Card {
                Layout.fillWidth: true
                Layout.minimumWidth: 360
                Layout.fillHeight: true
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 14
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            Caption { text: "NAME"; Layout.preferredWidth: 60 }
                            ChannelTextField {
                                objectName: "themeBuilderName"
                                Layout.fillWidth: true
                                text: builder.draft.name
                                maximumLength: 40
                                onTextEdited: builder.set("name", text)
                            }
                        }
                        Heading { text: "Colors" }
                        Caption { text: "Click a swatch to pick a colour, or type a hex code. Every screen is built from these."; Layout.fillWidth: true }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: width > 640 ? 2 : 1
                            columnSpacing: 14
                            rowSpacing: 8
                            Repeater {
                                model: builder.roleList
                                delegate: RowLayout {
                                    id: roleRow
                                    required property var modelData
                                    readonly property string value: builder.draft.roles[modelData.key] || "#000000"
                                    Layout.fillWidth: true
                                    spacing: 10
                                    Rectangle {
                                        id: swatch
                                        objectName: "themeRoleSwatch_" + roleRow.modelData.key
                                        width: 44; height: 34; radius: 7
                                        color: roleRow.value
                                        activeFocusOnTab: true
                                        function pick() { builder.editingRole = roleRow.modelData.key; picker.openFor(roleRow.value, swatch) }
                                        Keys.onSpacePressed: pick()
                                        Keys.onReturnPressed: pick()
                                        border.color: activeFocus ? Theme.c("#f4f7fb") : Theme.c("#42adff")
                                        border.width: activeFocus ? 3 : swatchArea.containsMouse ? 2 : 1
                                        MouseArea {
                                            id: swatchArea
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: swatch.pick()
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 1
                                        Text { text: roleRow.modelData.label; color: Theme.c("#f4f7fb"); font.pixelSize: 13; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                                        Text { text: roleRow.modelData.hint || ""; color: Theme.c("#9fb0c2"); font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
                                    }
                                    ChannelTextField {
                                        Layout.preferredWidth: 96
                                        text: roleRow.value
                                        font.family: "monospace"
                                        validator: RegularExpressionValidator { regularExpression: /^#[0-9a-fA-F]{6}$/ }
                                        objectName: "themeRoleHex_" + roleRow.modelData.key
                                        onEditingFinished: {
                                            if (acceptableInput) builder.setRole(roleRow.modelData.key, text)
                                            else text = Qt.binding(function() { return roleRow.value })
                                        }
                                    }
                                }
                            }
                        }
                        Heading { text: "Reset colors" }
                        Caption { Layout.fillWidth: true; text: "Replace all twelve colors with a built-in set to start over. The name and wallpaper stay as they are." }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            Repeater {
                                model: builder.themes.filter(function(t) { return t.builtin })
                                delegate: ChannelButton {
                                    required property var modelData
                                    text: "Use " + modelData.name + " colors"
                                    onClicked: builder.set("roles", JSON.parse(JSON.stringify(modelData.roles)))
                                }
                            }
                        }
                    }
                }
            }

            // Wallpaper and preview
            ColumnLayout {
                Layout.preferredWidth: Math.max(320, builder.width * 0.27)
                Layout.maximumWidth: Layout.preferredWidth
                Layout.fillHeight: true
                spacing: 16
                Card {
                    Layout.fillWidth: true
                    implicitHeight: wallpaperColumn.implicitHeight + 28
                    ColumnLayout {
                        id: wallpaperColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 10
                        Heading { text: "Wallpaper" }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 96
                            radius: 8
                            clip: true
                            color: Theme.c("#050c15")
                            border.color: Theme.c("#1a3550")
                            Image {
                                anchors.fill: parent
                                anchors.margins: 1
                                source: builder.draft.wallpaperUrl || ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                sourceSize.width: 600
                            }
                            Caption { anchors.centerIn: parent; visible: !builder.draft.wallpaperUrl; text: "No image" }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            ChannelButton { objectName: "themeBuilderChooseImage"; text: "Choose Image…"; Layout.fillWidth: true; onClicked: builder.chooseImage() }
                            ChannelButton {
                                text: "Remove"
                                enabled: builder.draft.wallpaper !== ""
                                onClicked: { builder.draft = Object.assign({}, builder.draft, { wallpaper: "", wallpaperUrl: "" }); builder.dirty = true; builder.preview() }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Caption { text: "Fit"; Layout.preferredWidth: 120 }
                            ChannelComboBox {
                                Layout.fillWidth: true
                                model: [{ value: "fill", label: "Fill the screen" }, { value: "fit", label: "Fit whole image" },
                                        { value: "tile", label: "Tile" }, { value: "center", label: "Center" }]
                                textRole: "label"
                                valueRole: "value"
                                Binding on currentIndex { value: ["fill", "fit", "tile", "center"].indexOf(builder.draft.wallpaperFit); restoreMode: Binding.RestoreNone }
                                onActivated: builder.set("wallpaperFit", currentValue)
                            }
                        }
                        Percent { label: "Image opacity"; value: builder.draft.wallpaperOpacity; onMoved: function(v) { builder.set("wallpaperOpacity", v) } }
                        Percent { id: panelPercent; label: "Panel opacity"; from: 40; value: builder.draft.panelOpacity; onMoved: function(v) { builder.set("panelOpacity", v) } }
                        Caption { Layout.fillWidth: true; text: "Lower panel opacity lets the wallpaper show through, MySpace-style. Images are copied into your setup, so they travel with a portable drive." }
                    }
                }
                Card {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ScrollView {
                    anchors.fill: parent
                    anchors.margins: 14
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        spacing: 8
                        Heading { text: "Preview" }
                        Caption { Layout.fillWidth: true; text: "Examples of each color in use. The whole app is already showing your draft, so you can also look around behind this window." }
                        Caption { Layout.fillWidth: true; text: "A program card with its LIVE badge (Panels, Text, Live & alerts)" }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 64
                            radius: 8
                            color: Theme.c("#0d2035")
                            border.color: Theme.c("#1a3550")
                            Column {
                                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; anchors.leftMargin: 12
                                spacing: 4
                                Text { text: "Tonight on Channel 7"; color: Theme.c("#f4f7fb"); font.pixelSize: 15; font.weight: Font.DemiBold }
                                Text { text: "8:00 PM - 9:00 PM"; color: Theme.c("#9fb0c2"); font.pixelSize: 12 }
                            }
                            Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 12; text: "● LIVE"; color: Theme.c("#ff4a4a"); font.pixelSize: 13; font.weight: Font.Bold }
                        }
                        Caption { Layout.fillWidth: true; text: "The selected program in the Guide (Highlight)" }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 40
                            radius: 6
                            color: Theme.c("#146ad1")
                            border.color: Theme.c("#42adff"); border.width: 2
                            Text { anchors.centerIn: parent; text: "Selected program"; color: Theme.c("#f4f7fb"); font.pixelSize: 13 }
                        }
                        Caption { Layout.fillWidth: true; text: "Buttons: everyday, main action (Accent), and turned on (Selection)" }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            // Samples only: they show colors and do nothing.
                            ChannelButton { text: "Everyday"; focusPolicy: Qt.NoFocus }
                            ChannelButton { text: "Apply"; highlighted: true; focusPolicy: Qt.NoFocus }
                            ChannelButton { text: "Turned On"; checked: true; focusPolicy: Qt.NoFocus }
                        }
                    }
                    }
                }
            }
        }

        // Footer
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            color: builder.statusError ? Theme.c("#32151b") : Theme.c("#071322")
            border.color: builder.statusError ? Theme.c("#ff6666") : Theme.c("#1a3550")
            Text {
                objectName: "themeBuilderStatus"
                anchors.left: parent.left; anchors.leftMargin: 24; anchors.verticalCenter: parent.verticalCenter
                text: builder.status || "Save keeps this theme for later  •  Save & Use also switches the app to it  •  Close throws away unsaved changes"
                color: builder.statusError ? Theme.c("#ff6666") : Theme.c("#9fb0c2")
                font.pixelSize: 13
            }
            Text {
                anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
                text: "ESC  Close"
                color: Theme.c("#9fb0c2")
                font.pixelSize: 12
            }
        }
    }

    // Colour picker
    Popup {
        id: picker
        objectName: "themeColorPicker"
        width: 320
        padding: 14
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        property real hue: 0
        property real saturation: 0
        property real lightness: 0
        property Item returnFocus: null
        readonly property string current: builder.hexOf(hue, saturation, lightness)
        onOpened: Qt.callLater(function() {
            var first = picker.contentItem.nextItemInFocusChain(true)
            if (first) first.forceActiveFocus()
        })
        onClosed: if (returnFocus) returnFocus.forceActiveFocus()
        function openFor(hex, anchorItem) {
            returnFocus = anchorItem
            var value = builder.hsl(hex)
            hue = value.h; saturation = value.s; lightness = value.l
            var point = anchorItem.mapToItem(builder.contentItem, 0, anchorItem.height + 6)
            x = Math.min(point.x, builder.width - width - 10)
            y = Math.max(10, Math.min(point.y, builder.height - 400))
            open()
        }
        function apply(hex) {
            var value = builder.hsl(hex)
            hue = value.h; saturation = value.s; lightness = value.l
            builder.setRole(builder.editingRole, hex)
        }
        function changed() { builder.setRole(builder.editingRole, current) }
        background: Rectangle { radius: 10; color: Theme.c("#0d2035"); border.color: Theme.c("#42adff") }
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Rectangle { width: 52; height: 52; radius: 8; color: picker.current; border.color: Theme.c("#1a3550") }
                ColumnLayout {
                    Text { text: builder.editingRole ? (builder.roleList.filter(function(r) { return r.key === builder.editingRole })[0] || {label: ""}).label : ""; color: Theme.c("#f4f7fb"); font.pixelSize: 14; font.weight: Font.DemiBold }
                    Text { text: picker.current; color: Theme.c("#9fb0c2"); font.family: "monospace"; font.pixelSize: 13 }
                }
            }
            Repeater {
                model: [{ key: "hue", label: "Hue" }, { key: "saturation", label: "Color" }, { key: "lightness", label: "Light" }]
                delegate: RowLayout {
                    id: channel
                    required property var modelData
                    Layout.fillWidth: true
                    Text { text: channel.modelData.label; color: Theme.c("#9fb0c2"); font.pixelSize: 12; Layout.preferredWidth: 44 }
                    Slider {
                        id: track
                        Layout.fillWidth: true
                        from: 0; to: 1
                        stepSize: 0.01
                        Binding on value { value: picker[channel.modelData.key]; restoreMode: Binding.RestoreNone }
                        onMoved: { picker[channel.modelData.key] = value; picker.changed() }
                        background: Rectangle {
                            x: track.leftPadding; y: track.topPadding + track.availableHeight / 2 - 7
                            width: track.availableWidth; height: 14; radius: 7
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: channel.modelData.key === "hue" ? Qt.hsla(0, 1, 0.5, 1) : channel.modelData.key === "saturation" ? Qt.hsla(picker.hue, 0, picker.lightness, 1) : "#000000" }
                                GradientStop { position: 0.17; color: channel.modelData.key === "hue" ? Qt.hsla(0.17, 1, 0.5, 1) : channel.modelData.key === "saturation" ? Qt.hsla(picker.hue, 0.17, picker.lightness, 1) : Qt.hsla(picker.hue, picker.saturation, 0.17, 1) }
                                GradientStop { position: 0.33; color: channel.modelData.key === "hue" ? Qt.hsla(0.33, 1, 0.5, 1) : channel.modelData.key === "saturation" ? Qt.hsla(picker.hue, 0.33, picker.lightness, 1) : Qt.hsla(picker.hue, picker.saturation, 0.33, 1) }
                                GradientStop { position: 0.5; color: channel.modelData.key === "hue" ? Qt.hsla(0.5, 1, 0.5, 1) : channel.modelData.key === "saturation" ? Qt.hsla(picker.hue, 0.5, picker.lightness, 1) : Qt.hsla(picker.hue, picker.saturation, 0.5, 1) }
                                GradientStop { position: 0.67; color: channel.modelData.key === "hue" ? Qt.hsla(0.67, 1, 0.5, 1) : channel.modelData.key === "saturation" ? Qt.hsla(picker.hue, 0.67, picker.lightness, 1) : Qt.hsla(picker.hue, picker.saturation, 0.67, 1) }
                                GradientStop { position: 0.83; color: channel.modelData.key === "hue" ? Qt.hsla(0.83, 1, 0.5, 1) : channel.modelData.key === "saturation" ? Qt.hsla(picker.hue, 0.83, picker.lightness, 1) : Qt.hsla(picker.hue, picker.saturation, 0.83, 1) }
                                GradientStop { position: 1.0; color: channel.modelData.key === "hue" ? Qt.hsla(1, 1, 0.5, 1) : channel.modelData.key === "saturation" ? Qt.hsla(picker.hue, 1, picker.lightness, 1) : "#ffffff" }
                            }
                        }
                        handle: Rectangle {
                            x: track.leftPadding + track.visualPosition * (track.availableWidth - width)
                            y: track.topPadding + track.availableHeight / 2 - height / 2
                            width: 18; height: 18; radius: 9
                            color: picker.current; border.color: "#ffffff"; border.width: 2
                        }
                    }
                }
            }
            GridLayout {
                columns: 8
                rowSpacing: 4
                columnSpacing: 4
                Repeater {
                    model: builder.swatches
                    delegate: Rectangle {
                        required property string modelData
                        width: 30; height: 24; radius: 4
                        color: modelData
                        activeFocusOnTab: true
                        Keys.onSpacePressed: picker.apply(modelData)
                        Keys.onReturnPressed: picker.apply(modelData)
                        border.color: activeFocus ? Theme.c("#f4f7fb") : Theme.c("#1a3550")
                        border.width: activeFocus ? 3 : 1
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: picker.apply(parent.modelData) }
                    }
                }
            }
            ChannelButton { text: "Done"; Layout.alignment: Qt.AlignRight; onClicked: picker.close() }
        }
    }
}
