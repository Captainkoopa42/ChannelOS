pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "AdSources.js" as AdSources

Item {
    id: adsRoot
    width: 0; height: 0
    property Item hostItem: parent
    property int channelNumber: 1
    property string channelName: "Channel"
    property var mediaLibrary: []
    property var sourceOptions: []
    property var previewProvider: null
    property bool inlineBin: false
    property bool adEnabled: false
    property string setupMode: "after_show"
    property string playOrder: "shuffle"
    property real clockInterval: 900
    property real clockOffset: -new Date().getTimezoneOffset() * 60
    property bool customClockMode: false
    property int customUnit: 1
    property real smooshMinimum: 5
    property var excludedAssetIds: []
    property var loadedData: ({})
    property var adPlacementSnapshots: []
    property bool advancedDirty: false
    property string feedbackMessage: ""
    property bool feedbackIsError: false
    readonly property var selectedSources: split(adSourcesArea.text)
    readonly property var selectedIds: split(adAssetIdsField.text)
    readonly property bool managedBin: setupMode === "advanced" && adPlacementSnapshots.length > 0
    readonly property var binScope: mediaScope()
    readonly property bool dialogOpen: basicDialog.visible || advancedDialog.visible || binDialog.visible
    signal settingsApplied()
    signal binRequested()
    readonly property color appBackground: "#050c15"
    readonly property color panel: "#081625"
    readonly property color panelRaised: "#0d2035"
    readonly property color panelSoft: "#10283f"
    readonly property color line: "#1a3550"
    readonly property color textPrimary: "#f4f7fb"
    readonly property color textSecondary: "#9fb0c2"
    readonly property color accent: "#1a91ff"
    readonly property color accentBright: "#42adff"
    readonly property color liveGreen: "#2bcf75"
    readonly property color warning: "#ffb84a"
    readonly property color danger: "#ff6666"

    component StudioButton: Button {
        id: studioButton

        property bool destructive: false

        implicitWidth: Math.max(72, buttonLabel.implicitWidth + 28)
        implicitHeight: 38
        leftPadding: 14
        rightPadding: 14
        topPadding: 8
        bottomPadding: 8
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true

        contentItem: Text {
            id: buttonLabel
            text: studioButton.text
            color: !studioButton.enabled
                   ? "#607489"
                   : studioButton.destructive
                   ? adsRoot.danger
                   : studioButton.highlighted || studioButton.checked
                   ? "#ffffff" : adsRoot.textPrimary
            font.pixelSize: 12
            font.weight: studioButton.highlighted || studioButton.checked
                         ? Font.DemiBold : Font.Medium
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            id: buttonBackground
            radius: 7
            color: !studioButton.enabled
                   ? "#091522"
                   : studioButton.down
                   ? (studioButton.destructive ? "#54212a" : "#0a66ad")
                   : studioButton.destructive
                   ? (studioButton.hovered ? "#351b24" : "#21151c")
                   : studioButton.highlighted
                   ? (studioButton.hovered ? adsRoot.accentBright
                                           : adsRoot.accent)
                   : studioButton.checked
                   ? (studioButton.hovered ? "#176aa6" : "#12527f")
                   : studioButton.hovered
                   ? "#143a5c" : adsRoot.panelRaised
            border.color: !studioButton.enabled
                          ? "#14283b"
                          : studioButton.destructive
                          ? adsRoot.danger
                          : studioButton.activeFocus
                            || studioButton.highlighted
                            || studioButton.checked
                          ? adsRoot.accentBright : adsRoot.line
            border.width: studioButton.activeFocus
                          || studioButton.highlighted
                          || studioButton.checked ? 2 : 1

            Behavior on color {
                ColorAnimation { duration: 90 }
            }
            Behavior on border.color {
                ColorAnimation { duration: 90 }
            }
        }
    }

    component StudioDialog: Dialog {
        modal: true
        dim: true
        padding: 24
        palette.window: adsRoot.panelRaised
        palette.windowText: adsRoot.textPrimary
        palette.button: adsRoot.panelRaised
        palette.buttonText: adsRoot.textPrimary

        background: Rectangle {
            radius: 10
            color: adsRoot.panelRaised
            border.color: adsRoot.line
            border.width: 1
        }

        Overlay.modal: Rectangle {
            color: "#aa02070d"
        }
    }


    component Field: ColumnLayout {
        property string label: ""
        property alias text: field.text
        property alias placeholderText: field.placeholderText
        Layout.fillWidth: true; spacing: 4
        Label { text: parent.label; color: adsRoot.textSecondary; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
        ChannelTextField { id: field; Layout.fillWidth: true; onTextEdited: adsRoot.advancedDirty = true }
    }
    component Choice: ColumnLayout {
        property string label: ""
        property alias currentIndex: choice.currentIndex
        property alias model: choice.model
        Layout.fillWidth: true; spacing: 4
        Label { text: parent.label; color: adsRoot.textSecondary; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
        ChannelComboBox { id: choice; Layout.fillWidth: true; onActivated: adsRoot.advancedDirty = true }
    }
    component AdTab: TabButton {
        id: tab
        implicitHeight: 38
        contentItem: Text { text: tab.text; color: adsRoot.textPrimary; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { color: tab.checked ? "#12527f" : adsRoot.panel; border.color: tab.checked || tab.activeFocus ? adsRoot.accentBright : adsRoot.line; radius: 4 }
    }
    function split(value) { return String(value || "").split(";").map(function(x) { return x.trim() }).filter(function(x) { return x.length > 0 }) }
    function editorObject() {
        return {
            adBreaksEnabled: adsRoot.adEnabled,
            adSources: adSourcesArea.text.split(";").map(function(value) {
                return value.trim()
            }).filter(function(value) { return value.length > 0 }),
            adSelectionStrategy: [
                "best_fit", "largest", "smallest", "sequential",
                "least_played", "complete_rotation"
            ][adStrategyBox.currentIndex],
            adConfigVersion: "0.6", adSetupMode: setupMode, adPlayOrder: playOrder,
            adClockIntervalSeconds: clockInterval, adClockOffsetSeconds: clockOffset,
            adAssetIds: adAssetIdsField.text.split(";").map(function(value) {
                return value.trim()
            }).filter(function(value) { return value.length > 0 }),
            adCollectionId: adCollectionField.text.trim(),
            adProfileId: adProfileField.text.trim(),
            adBreakpointsSeconds: adBreakpointsField.text.split(";").map(function(value) {
                return value.trim()
            }).filter(function(value) { return value.length > 0 }),
            adIntervalSeconds: adIntervalField.text.trim(),
            adBreakDurationSeconds: Number(adDurationField.text),
            adPriority: Number(adPriorityField.text),
            adTimingPolicy: ["strict_fit", "smoosh", "expand"][adTimingBox.currentIndex],
            adSmooshMinimumSeconds: smooshMinimum,
            adSmooshMaxTrimSeconds: Number(adSmooshTrimField.text),
            adExpandMaxSeconds: Number(adExpandField.text),
            adTriggers: adTriggersField.text.split(";").map(function(value) {
                return value.trim()
            }).filter(function(value) { return value.length > 0 }),
            adTransitionBehavior: ["cut", "fade", "hold"][adTransitionBox.currentIndex],
            adTransitionSeconds: Number(adTransitionSecondsField.text),
            adSlotSeconds: adSlotSecondsField.text.trim() ? Number(adSlotSecondsField.text) : null,
            adSchedulePriority: ["program", "fixed", "advertising"][adSchedulePriorityBox.currentIndex],
            adExpandSource: ["schedule_shift", "available_slot_time", "current_program", "next_event"][adExpandSourceBox.currentIndex],
            adPlacements: adPlacementSnapshots,
            adCollectionMembership: adsRoot.loadedData.adCollectionMembership || "fixed",
            adExcludedAssetIds: excludedAssetIds
        }
    }
    function load(data) {
        loadedData = Object.assign({}, data || ({}))
        adEnabled = Boolean(data.adBreaksEnabled)
        setupMode = String(data.adSetupMode || (data.adBreaksEnabled || (data.adSources || []).length || (data.adAssetIds || []).length || (data.adPlacements || []).length ? "advanced" : "after_show"))
        if (!data.adBreaksEnabled && !(data.adSources || []).length && !(data.adAssetIds || []).length && !(data.adPlacements || []).length && !data.adCollectionId && !data.adProfileId)
            setupMode = "after_show"
        playOrder = String(data.adPlayOrder || "shuffle")
        clockInterval = Number(data.adClockIntervalSeconds || 900)
        customClockMode = [900, 1800, 3600].indexOf(clockInterval) < 0
        customUnit = clockInterval % 3600 === 0 ? 2 : clockInterval % 60 === 0 ? 1 : 0
        clockOffset = data.adClockOffsetSeconds === undefined ? -new Date().getTimezoneOffset() * 60 : Number(data.adClockOffsetSeconds)
        smooshMinimum = Number(data.adSmooshMinimumSeconds || 5)
        excludedAssetIds = data.adExcludedAssetIds || []
        adSourcesArea.text = (data.adSources || []).join("; ")
        var adStrategy = String(data.adSelectionStrategy || "best_fit")
        adStrategyBox.currentIndex = Math.max(0, [
            "best_fit", "largest", "smallest", "sequential",
            "least_played", "complete_rotation"
        ].indexOf(adStrategy))
        adAssetIdsField.text = (data.adAssetIds || []).join("; ")
        adCollectionField.text = String(data.adCollectionId || "")
        adProfileField.text = String(data.adProfileId || "")
        adBreakpointsField.text = (data.adBreakpointsSeconds || []).join("; ")
        adIntervalField.text = String(data.adIntervalSeconds || "")
        adDurationField.text = String(data.adBreakDurationSeconds || 120)
        adPriorityField.text = String(data.adPriority || 0)
        adTimingBox.currentIndex = Math.max(0, ["strict_fit", "smoosh", "expand"].indexOf(
            String(data.adTimingPolicy || "strict_fit")))
        adSmooshTrimField.text = String(data.adSmooshMaxTrimSeconds === undefined ? 15 : data.adSmooshMaxTrimSeconds)
        adExpandField.text = String(data.adExpandMaxSeconds || 0)
        adTriggersField.text = (data.adTriggers || [
            "breakpoint", "interval", "between_programs", "calendar_boundary"
        ]).join("; ")
        adTransitionBox.currentIndex = Math.max(0, ["cut", "fade", "hold"].indexOf(
            String(data.adTransitionBehavior || "cut")))

        adTransitionSecondsField.text = String(data.adTransitionSeconds === undefined ? 0.5 : data.adTransitionSeconds)
        adSlotSecondsField.text = String(data.adSlotSeconds || "")
        adSchedulePriorityBox.currentIndex = Math.max(0, ["program", "fixed", "advertising"].indexOf(String(data.adSchedulePriority || "program")))
        adExpandSourceBox.currentIndex = Math.max(0, ["schedule_shift", "available_slot_time", "current_program", "next_event"].indexOf(String(data.adExpandSource || "schedule_shift")))
        adPlacementSnapshots = data.adPlacements || []

        advancedDirty = false
    }
    function setSources(paths) { adSourcesArea.text = paths.join("; "); settingsApplied() }
    function setExcluded(ids) { excludedAssetIds = ids; settingsApplied() }
    function openBasic() { basicDialog.open() }
    function openBin() { binDialog.open() }
    function openAdvanced() { advancedTabs.currentIndex = 0; advancedDialog.open() }
    function mediaScope() {
        if (!managedBin) return {sources:selectedSources, ids:selectedIds, excluded:excludedAssetIds}
        var sources = [], ids = [], eligible = ({})
        adPlacementSnapshots.forEach(function(placement) {
            var policy = placement.policy || ({})
            if (policy.enabled === false) return
            var roots = (policy.sources || []).map(function(source) { return String(source.path) })
            roots.forEach(function(path) { if (sources.indexOf(path) < 0) sources.push(path) })
            ;(policy.asset_ids || []).forEach(function(id) { if (ids.indexOf(id) < 0) ids.push(id) })
            AdSources.selected(mediaLibrary, roots, policy.asset_ids || [], policy.excluded_asset_ids || []).forEach(function(item) { eligible[item.assetId] = true })
        })
        var excluded = AdSources.selected(mediaLibrary, sources, ids, []).filter(function(item) { return !eligible[item.assetId] }).map(function(item) { return item.assetId })
        return {sources:sources, ids:ids, excluded:excluded}
    }
    function sourceCount() { return AdSources.selected(mediaLibrary, binScope.sources, binScope.ids, binScope.excluded).length }
    function cancelActive() { if (basicDialog.visible) basicDialog.reject(); else if (advancedDialog.visible) advancedDialog.reject(); else if (binDialog.visible) binDialog.reject() }
    function description() {
        if (!adEnabled) return "Play shows without ad breaks."
        if (setupMode === "advanced") return "Custom rules are active. Review them in Advanced Ad Settings."
        var order = playOrder === "shuffle" ? "Shuffle every clip once before the list repeats." : "Follow the Ad Bin order, then repeat the list."
        if (setupMode === "after_show") return "Play one full ad after every show. " + order
        var interval = clockInterval % 3600 === 0 ? clockInterval / 3600 + " hour(s)" : clockInterval % 60 === 0 ? clockInterval / 60 + " minutes" : clockInterval + " seconds"
        return (setupMode === "aligned" ? "Start shows on a " + interval + " grid; whole ads and filler fill the gaps. " : "Play ads at clock marks every " + interval + " and after shows; nearby breaks merge. ") + order
    }
    function preview() {
        if (!previewProvider) { previewStatus.text = "Add program sources and a channel name before previewing."; return }
        var result = previewProvider(editorObject())
        var events = result && result.adPreview || []
        previewStatus.text = result && result.ok ? (events.length ? events.slice(0, 6).map(function(event) { return Qt.formatTime(new Date(event.startUtc), "h:mm:ss AP") + " · " + event.title }).join("\n") : "No ads in this preview window.") : String(result && result.message || "Preview could not be created")
    }
    StudioDialog {
        id: basicDialog
        objectName: "simpleAdBreaksDialog"
        title: "Ad Breaks"
        parent: Overlay.overlay
        width: Math.min(640, adsRoot.hostItem.width - 40)
        height: Math.min(adsRoot.hostItem.height - 40, basicColumn.implicitHeight + 120)
        x: (adsRoot.hostItem.width - width) / 2; y: (adsRoot.hostItem.height - height) / 2
        property var saved: ({})
        onOpened: { saved = adsRoot.editorObject(); previewStatus.text = "" }
        onRejected: adsRoot.load(saved)
        onAccepted: adsRoot.settingsApplied()
        footer: Item {
            implicitHeight: 60
            RowLayout {
                anchors.fill: parent; anchors.margins: 12
                StudioButton { text: "Preview"; onClicked: adsRoot.preview() }
                Item { Layout.fillWidth: true }
                StudioButton { text: "Cancel"; onClicked: basicDialog.reject() }
                StudioButton { text: "Apply to Draft"; highlighted: true; onClicked: basicDialog.accept() }
            }
        }
        contentItem: Flickable {
            clip: true; contentWidth: width; contentHeight: basicColumn.implicitHeight; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            ColumnLayout {
                id: basicColumn; width: parent.width - 14; spacing: 15
                ChannelCheckBox { objectName: "simpleAdsEnabled"; text: "Enable ads"; checked: adsRoot.adEnabled; onClicked: adsRoot.adEnabled = checked }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Ad Bin · " + adsRoot.sourceCount() + " selected clips"; color: adsRoot.textSecondary; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    StudioButton { text: "View Ad Bin"; onClicked: { basicDialog.close(); adsRoot.settingsApplied(); if (adsRoot.inlineBin) adsRoot.binRequested(); else binDialog.open() } }
                }
                ColumnLayout {
                    visible: adsRoot.setupMode === "advanced"; Layout.fillWidth: true
                    Label { text: "Custom settings active"; color: adsRoot.warning }
                    RowLayout {
                        StudioButton { text: "Review Advanced"; onClicked: { basicDialog.close(); adsRoot.openAdvanced() } }
                        StudioButton { text: "Use simple settings"; onClicked: adsRoot.setupMode = "after_show" }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 12; enabled: adsRoot.adEnabled && adsRoot.setupMode !== "advanced"
                    Label { text: "Play ads in"; color: adsRoot.textPrimary }
                    RowLayout {
                        Layout.fillWidth: true
                        StudioButton { objectName: "simpleSequential"; text: "Sequential"; Layout.fillWidth: true; checked: adsRoot.playOrder === "sequential"; onClicked: adsRoot.playOrder = "sequential" }
                        StudioButton { objectName: "simpleShuffle"; text: "Shuffle"; Layout.fillWidth: true; checked: adsRoot.playOrder === "shuffle"; onClicked: adsRoot.playOrder = "shuffle" }
                    }
                    Label { text: "Every selected clip plays once before the list repeats."; color: adsRoot.textSecondary; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Label { visible: adsRoot.setupMode === "after_show"; text: "One show → one full ad → next show"; color: adsRoot.accentBright; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    ChannelCheckBox { objectName: "simpleTimedScheduling"; text: "Timed scheduling"; checked: adsRoot.setupMode === "timed" || adsRoot.setupMode === "aligned"; onClicked: adsRoot.setupMode = checked ? "timed" : "after_show" }
                    ColumnLayout {
                        visible: adsRoot.setupMode === "timed" || adsRoot.setupMode === "aligned"; Layout.fillWidth: true; spacing: 10
                        RowLayout {
                            Layout.fillWidth: true
                            StudioButton { objectName: "simpleTimedBreaks"; text: "Timed Ad Breaks"; Layout.fillWidth: true; checked: adsRoot.setupMode === "timed"; onClicked: adsRoot.setupMode = "timed" }
                            StudioButton { objectName: "simpleAlignedStarts"; text: "Aligned Show Starts"; Layout.fillWidth: true; checked: adsRoot.setupMode === "aligned"; onClicked: adsRoot.setupMode = "aligned" }
                        }
                        Label { text: adsRoot.setupMode === "aligned" ? "Shows start on clock marks. Ads fill the time between shows; long shows finish normally." : "Ads at clock marks and after shows. Interrupted shows resume afterward."; color: adsRoot.textSecondary; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                        ChannelComboBox {
                            objectName: "simpleClockInterval"; Layout.fillWidth: true
                            model: ["Every 15 minutes", "Every 30 minutes", "Every hour", "Custom…"]
                            currentIndex: adsRoot.customClockMode ? 3 : adsRoot.clockInterval === 900 ? 0 : adsRoot.clockInterval === 1800 ? 1 : 2
                            onActivated: { adsRoot.customClockMode = currentIndex === 3; if (currentIndex < 3) adsRoot.clockInterval = [900, 1800, 3600][currentIndex] }
                        }
                        RowLayout {
                            id: customClock; visible: adsRoot.customClockMode; Layout.fillWidth: true
                            Label { text: "Every"; color: adsRoot.textSecondary }
                            ChannelSpinBox { id: customValue; objectName: "simpleCustomInterval"; from: 1; to: Math.floor(86400 / [1,60,3600][adsRoot.customUnit]); editable: true; value: Math.max(1, adsRoot.clockInterval / [1,60,3600][adsRoot.customUnit]); onValueModified: adsRoot.clockInterval = value * [1,60,3600][adsRoot.customUnit] }
                            ChannelComboBox { Layout.fillWidth: true; model: ["Seconds", "Minutes", "Hours"]; currentIndex: adsRoot.customUnit; onActivated: { var amount = customValue.value; adsRoot.customUnit = currentIndex; adsRoot.clockInterval = Math.min(86400, amount * [1,60,3600][currentIndex]) } }
                        }
                        Label { text: adsRoot.clockInterval === 900 ? "Clock marks: :00 · :15 · :30 · :45" : adsRoot.clockInterval === 1800 ? "Clock marks: :00 · :30" : adsRoot.clockInterval === 3600 ? "Clock marks: on the hour" : "Custom clock interval · " + adsRoot.clockInterval + " seconds"; color: adsRoot.accentBright; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    }
                }
                Label { objectName: "simpleAdSummary"; text: adsRoot.description(); color: adsRoot.textPrimary; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Text { id: previewStatus; Layout.fillWidth: true; color: adsRoot.textSecondary; wrapMode: Text.Wrap; font.pixelSize: 12 }
            }
        }
    }
    StudioDialog {
        id: advancedDialog; objectName: "advancedAdSettingsDialog"; title: "Advanced Ad Settings"
        parent: Overlay.overlay
        width: Math.min(770, adsRoot.hostItem.width - 40); height: Math.min(760, adsRoot.hostItem.height - 40)
        x: (adsRoot.hostItem.width - width) / 2; y: (adsRoot.hostItem.height - height) / 2
        property var saved: ({})
        onOpened: { saved = adsRoot.editorObject(); adsRoot.advancedDirty = false; adCatalogDialog.reload() }
        onRejected: adsRoot.load(saved)
        onAccepted: { if (adsRoot.advancedDirty) adsRoot.setupMode = "advanced"; adsRoot.settingsApplied() }
        footer: Item {
            implicitHeight: 60
            RowLayout {
                anchors.fill: parent; anchors.margins: 12
                StudioButton { text: "Ad Breaks"; onClicked: { if (adsRoot.advancedDirty) adsRoot.setupMode = "advanced"; advancedDialog.close(); basicDialog.open() } }
                Item { Layout.fillWidth: true }
                StudioButton { text: "Cancel"; onClicked: advancedDialog.reject() }
                StudioButton { text: "Apply to Draft"; highlighted: true; onClicked: advancedDialog.accept() }
            }
        }
        contentItem: ColumnLayout {
            TabBar {
                id: advancedTabs; Layout.fillWidth: true
                AdTab { text: "Break rules" }
                AdTab { text: "Timing & fitting" }
                AdTab { text: "Playback" }
                AdTab { text: "Profiles"; objectName: "adProfilesTab" }
            }
            StackLayout {
                currentIndex: advancedTabs.currentIndex; Layout.fillWidth: true; Layout.fillHeight: true
                ScrollView {
                    contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width - 14; spacing: 14
                        Label { text: "Where breaks can happen"; color: adsRoot.textPrimary }
                        ChannelCheckBox { text: "Enable ads"; checked: adsRoot.adEnabled; onClicked: { adsRoot.adEnabled = checked; adsRoot.advancedDirty = true } }
                        Field { id: adBreakpointsField; label: "Points within a show · seconds"; placeholderText: "900; 1800" }
                        Field { id: adIntervalField; label: "Repeat within a show · seconds (optional)" }
                        Field { id: adSlotSecondsField; label: "Fixed slot length · seconds (optional)" }
                        Field { id: adTriggersField; label: "Placement rules · semicolon separated"; text: "breakpoint; interval; between_programs; calendar_boundary" }
                        Label { text: "Rules: breakpoint, interval, between_programs, calendar_boundary, fixed_slot. Independent collection/profile placements are under Profiles."; color: adsRoot.textSecondary; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    }
                }
                ScrollView {
                    contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width - 14; spacing: 14
                        RowLayout { Layout.fillWidth: true; Field { id: adDurationField; label: "Break length · seconds"; text: "120" } Field { id: adPriorityField; label: "Priority · whole number"; text: "0" } }
                        Choice { id: adTimingBox; label: "Duration fitting"; model: ["Strict fit", "Smoosh", "Expand"] }
                        Field { label: "Smoosh minimum clip · seconds"; text: String(adsRoot.smooshMinimum); onTextChanged: { if (Number(text) > 0) adsRoot.smooshMinimum = Number(text) } }
                        RowLayout { Layout.fillWidth: true; Field { id: adSmooshTrimField; label: "Maximum trim · seconds"; text: "15" } Field { id: adExpandField; label: "Maximum extra time · seconds"; text: "0" } }
                        Choice { id: adSchedulePriorityBox; label: "Schedule priority"; model: ["Preserve program", "Keep timing fixed", "Prioritize ads"] }
                        Choice { id: adExpandSourceBox; label: "Extra time comes from"; model: ["Shift sequential programming", "Use available slot time", "Borrow current program", "Borrow next event"] }
                        Label { text: "Fixed calendar starts remain protected."; color: adsRoot.textSecondary; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    }
                }
                ScrollView {
                    contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width - 14; spacing: 14
                        Choice { id: adStrategyBox; label: "Selection strategy"; model: ["Best Fit", "Largest", "Smallest", "Sequential", "Least Played", "Complete Rotation"] }
                        Choice { id: adTransitionBox; label: "Transition"; model: ["Cut", "Fade through black", "Hold last frame"] }
                        Field { id: adTransitionSecondsField; label: "Transition length · seconds"; text: "0.5" }
                        Label { text: "Best Fit chooses complete clips that fit the available time. Remaining time uses channel filler."; color: adsRoot.textSecondary; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    }
                }
    Item {
        id: adCatalogDialog
        property var catalogData: ({})
        property var placementRules: []
        property string catalogFeedback: ""

        function splitValues(value) {
            return String(value || "").split(";").map(function(part) {
                return part.trim()
            }).filter(function(part) { return part.length > 0 })
        }

        function showResult(result) {
            catalogFeedback = result && result.message
                    ? String(result.message) : "Catalog request failed"
            if (result && result.ok) {
                catalogData = result
                adsRoot.feedbackMessage = catalogFeedback
                adsRoot.feedbackIsError = false
            } else {
                adsRoot.feedbackMessage = catalogFeedback
                adsRoot.feedbackIsError = true
            }
        }

        function loadSavedProfile(index) {
            var profile = (catalogData.profiles || [])[index]
            if (!profile) return
            var values = profile.defaults || ({})
            catalogProfileId.text = String(profile.profileId || "")
            catalogProfileName.text = String(profile.name || "")
            catalogProfileDuration.text = String(values.duration_seconds || 120)
            catalogProfileInterval.text = String(values.interval_seconds || "")
            catalogProfileDefaults.text = JSON.stringify(values)
            catalogAssignProfile.text = String(profile.profileId || "")
            adProfileField.text = String(profile.profileId || "")
            adDurationField.text = String(values.duration_seconds || 120)
            adBreakpointsField.text = (values.breakpoints_seconds || []).join("; ")
            adIntervalField.text = String(values.interval_seconds || "")
            adTriggersField.text = (values.triggers || ["between_programs"]).join("; ")
            adStrategyBox.currentIndex = Math.max(0, ["best_fit", "largest", "smallest", "sequential", "least_played", "complete_rotation"].indexOf(values.strategy || "best_fit"))
            adTimingBox.currentIndex = Math.max(0, ["strict_fit", "smoosh", "expand"].indexOf(values.timing_policy || "strict_fit"))
            adTransitionBox.currentIndex = Math.max(0, ["cut", "fade", "hold"].indexOf(values.transition_behavior || "cut"))
            adTransitionSecondsField.text = String(values.transition_seconds === undefined ? .5 : values.transition_seconds)
            adsRoot.setupMode = "advanced"
            adsRoot.advancedDirty = true
            catalogFeedback = "Profile loaded into this draft. Apply to Draft when ready."
        }

        function reload() {
            var response = channelOS && typeof channelOS.adCatalogSnapshot === "function" ? channelOS.adCatalogSnapshot() : ({ok:false, message:"Profiles are unavailable"})
            catalogData = response || ({})
            var saved = (catalogData.assignments || []).filter(function(item) {
                return Number(item.channelNumber) === adsRoot.channelNumber
            })
            placementRules = saved.length ? saved[0].placements || [] : []
            catalogFeedback = response && response.ok
                    ? "Catalog is ready. Save reusable items before assigning them."
                    : String(response && response.message || "Unable to open catalog")
        }

        Component.onCompleted: reload()
        Flickable {
            anchors.fill: parent
            id: catalogScroll
            clip: true
            contentWidth: width
            contentHeight: catalogColumn.implicitHeight + 12
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: catalogColumn
                width: catalogScroll.width - 16
                spacing: 10


                Text {
                    Layout.fillWidth: true
                    color: adsRoot.textSecondary
                    wrapMode: Text.Wrap
                    font.pixelSize: 11
                    text: "All commercials use the canonical Library index. "
                          + "Dynamic collections follow indexed folders; fixed "
                          + "collections use selected asset IDs. Applying a channel "
                          + "embeds a portable snapshot of both collection and profile."
                }

                Text {
                    Layout.fillWidth: true
                    color: adsRoot.warning
                    wrapMode: Text.Wrap
                    font.pixelSize: 11
                    text: adCatalogDialog.catalogFeedback
                }
                Label { text: "Saved profiles"; color: adsRoot.textPrimary }
                RowLayout {
                    Layout.fillWidth: true
                    ChannelComboBox { id: savedProfileChoice; objectName: "savedAdProfileChoice"; Layout.fillWidth: true; model: adCatalogDialog.catalogData.profiles || []; textRole: "name" }
                    StudioButton { text: "Load Profile"; enabled: savedProfileChoice.count > 0; onClicked: adCatalogDialog.loadSavedProfile(savedProfileChoice.currentIndex) }
                }
                Label { text: "Saved collections"; color: adsRoot.textPrimary }
                RowLayout {
                    Layout.fillWidth: true
                    ChannelComboBox { id: savedCollectionChoice; Layout.fillWidth: true; model: adCatalogDialog.catalogData.collections || []; textRole: "name" }
                    StudioButton { text: "Load Collection"; enabled: savedCollectionChoice.count > 0; onClicked: {
                        var item = adCatalogDialog.catalogData.collections[savedCollectionChoice.currentIndex]
                        catalogCollectionId.text = String(item.collectionId || "")
                        catalogCollectionName.text = String(item.name || "")
                        catalogCollectionAssets.text = (item.assetIds || []).join("; ")
                        catalogCollectionSources.text = (item.sourcePaths || []).join("; ")
                        catalogCollectionExclusions.text = (item.excludedAssetIds || []).join("; ")
                        catalogCollectionMode.currentIndex = item.membership === "dynamic" ? 1 : 0
                        catalogAssignCollection.text = String(item.collectionId || "")
                        adSourcesArea.text = (item.sourcePaths || []).join("; ")
                        adAssetIdsField.text = (item.assetIds || []).join("; ")
                        adCollectionField.text = String(item.collectionId || "")
                        adsRoot.excludedAssetIds = item.excludedAssetIds || []
                        adsRoot.advancedDirty = true
                        adCatalogDialog.catalogFeedback = "Collection loaded into this draft."
                    } }
                }
                StudioButton { id: profileSection0; Layout.fillWidth: true; text: (checked ? "▾  " : "▸  ") + "Collection details · membership & IDs"; checkable: true }
                ColumnLayout { Layout.fillWidth: true; spacing: 10; visible: profileSection0.checked
                RowLayout {
                    Layout.fillWidth: true
                    ChannelTextField {
                        id: catalogCollectionId
                        Layout.fillWidth: true
                        placeholderText: "Collection ID, e.g. network-ads"
                    }
                    ChannelTextField {
                        id: catalogCollectionName
                        Layout.fillWidth: true
                        placeholderText: "Collection display name"
                    }
                    ChannelComboBox {
                        id: catalogCollectionMode
                        Layout.preferredWidth: 115
                        model: ["Fixed", "Dynamic"]
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ChannelComboBox {
                        id: catalogMediaPicker
                        Layout.fillWidth: true
                        model: adsRoot.mediaLibrary
                        textRole: "title"
                    }
                    StudioButton {
                        text: "Add Media"
                        onClicked: {
                            var media = adsRoot.mediaLibrary[catalogMediaPicker.currentIndex]
                            if (!media) return
                            var ids = adCatalogDialog.splitValues(catalogCollectionAssets.text)
                            if (ids.indexOf(media.assetId) < 0) ids.push(media.assetId)
                            catalogCollectionAssets.text = ids.join("; ")
                        }
                    }
                }
                ChannelTextField {
                    id: catalogCollectionAssets
                    Layout.fillWidth: true
                    placeholderText: "Canonical asset IDs (semicolon separated)"
                }
                ChannelTextField {
                    id: catalogCollectionSources
                    Layout.fillWidth: true
                    placeholderText: "Dynamic source folders (semicolon separated)"
                }
                ChannelTextField {
                    id: catalogCollectionExclusions
                    Layout.fillWidth: true
                    placeholderText: "Excluded asset IDs (optional)"
                }
                StudioButton {
                    text: "Save Collection"
                    onClicked: {
                        var result = channelOS.saveAdCollection({
                            collectionId: catalogCollectionId.text.trim(),
                            name: catalogCollectionName.text.trim(),
                            membership: catalogCollectionMode.currentIndex === 1
                                        ? "dynamic" : "fixed",
                            assetIds: adCatalogDialog.splitValues(catalogCollectionAssets.text),
                            sourcePaths: adCatalogDialog.splitValues(catalogCollectionSources.text),
                            excludedAssetIds: adCatalogDialog.splitValues(catalogCollectionExclusions.text)
                        })
                        adCatalogDialog.showResult(result)
                    }
                }

                }
                StudioButton { id: profileSection1; Layout.fillWidth: true; text: (checked ? "▾  " : "▸  ") + "Profile details · defaults & ID"; checkable: true }
                ColumnLayout { Layout.fillWidth: true; spacing: 10; visible: profileSection1.checked
                RowLayout {
                    Layout.fillWidth: true
                    ChannelTextField {
                        id: catalogProfileId
                        Layout.fillWidth: true
                        placeholderText: "Profile ID, e.g. standard"
                    }
                    ChannelTextField {
                        id: catalogProfileName
                        Layout.fillWidth: true
                        placeholderText: "Profile display name"
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ChannelComboBox {
                        id: catalogProfileStrategy
                        Layout.fillWidth: true
                        model: ["Best fit", "Largest", "Smallest", "Sequential", "Least played", "Complete rotation"]
                    }
                    ChannelTextField {
                        id: catalogProfileDuration
                        Layout.fillWidth: true
                        text: "120"
                        placeholderText: "Break seconds"
                    }
                    ChannelTextField {
                        id: catalogProfileInterval
                        Layout.fillWidth: true
                        placeholderText: "Interval seconds (optional)"
                    }
                }
                ChannelCheckBox {
                    id: catalogAdvancedProfile
                    text: "Advanced profile settings"
                }
                ChannelTextField {
                    id: catalogProfileDefaults
                    visible: catalogAdvancedProfile.checked
                    Layout.fillWidth: true
                    text: '{"enabled":true,"duration_seconds":120,"strategy":"best_fit","triggers":["breakpoint","interval","between_programs"]}'
                    placeholderText: "JSON policy defaults"
                }
                StudioButton {
                    text: "Save Profile"
                    onClicked: {
                        try {
                            var defaults = catalogAdvancedProfile.checked
                                ? JSON.parse(catalogProfileDefaults.text)
                                : {enabled: true,
                                   duration_seconds: Number(catalogProfileDuration.text),
                                   interval_seconds: catalogProfileInterval.text.trim() ? Number(catalogProfileInterval.text) : null,
                                   strategy: ["best_fit", "largest", "smallest", "sequential", "least_played", "complete_rotation"][catalogProfileStrategy.currentIndex],
                                   breakpoints_seconds: adsRoot.editorObject().adBreakpointsSeconds.map(Number),
                                   timing_policy: adsRoot.editorObject().adTimingPolicy,
                                   transition_behavior: adsRoot.editorObject().adTransitionBehavior,
                                   transition_seconds: Number(adTransitionSecondsField.text)}
                            adCatalogDialog.showResult(channelOS.saveAdBreakProfile({
                                profileId: catalogProfileId.text.trim(),
                                name: catalogProfileName.text.trim(),
                                defaults: defaults
                            }))
                        } catch (error) {
                            adCatalogDialog.catalogFeedback = "Invalid profile JSON: " + error
                        }
                    }
                }

                }
                StudioButton { id: profileSection2; Layout.fillWidth: true; text: (checked ? "▾  " : "▸  ") + "Channel assignment · references & overrides"; checkable: true }
                ColumnLayout { Layout.fillWidth: true; spacing: 10; visible: profileSection2.checked
                Label { text: "Current channel media & references"; color: adsRoot.textPrimary }
                Field { id: adSourcesArea; label: "Source folders · semicolon separated"; placeholderText: "Select folders in the Ad Bin" }
                Field { id: adAssetIdsField; label: "Canonical ad asset IDs · optional with folders"; placeholderText: "sha256:…; sha256:…" }
                RowLayout {
                    Layout.fillWidth: true
                    Field { id: adCollectionField; label: "Collection ID" }
                    Field { id: adProfileField; label: "Profile ID" }
                }

                RowLayout {
                    Layout.fillWidth: true
                    ChannelTextField {
                        id: catalogAssignCollection
                        Layout.fillWidth: true
                        placeholderText: "Saved collection ID"
                    }
                    ChannelTextField {
                        id: catalogAssignProfile
                        Layout.fillWidth: true
                        placeholderText: "Saved profile ID"
                    }
                }
                Text {
                    text: "Placement rules (optional)"
                    color: adsRoot.textPrimary
                    font.bold: true
                }
                RowLayout {
                    Layout.fillWidth: true
                    ChannelComboBox {
                        id: placementTrigger
                        Layout.fillWidth: true
                        model: ["Program breakpoints", "Program interval", "Between programs", "Calendar gap", "Fixed slot"]
                    }
                    ChannelComboBox {
                        id: placementCollection
                        Layout.fillWidth: true
                        model: adCatalogDialog.catalogData.collections || []
                        textRole: "name"
                    }
                    ChannelComboBox {
                        id: placementProfile
                        Layout.fillWidth: true
                        model: adCatalogDialog.catalogData.profiles || []
                        textRole: "name"
                    }
                }
                StudioButton {
                    id: addAdPlacementButton
                    text: "Add Placement"
                    onClicked: {
                        var collections = adCatalogDialog.catalogData.collections || []
                        var profiles = adCatalogDialog.catalogData.profiles || []
                        if (!collections[placementCollection.currentIndex] || !profiles[placementProfile.currentIndex]) return
                        var trigger = ["breakpoint", "interval", "between_programs", "calendar_boundary", "fixed_slot"][placementTrigger.currentIndex]
                        var rules = adCatalogDialog.placementRules.slice()
                        var identity = trigger + "-" + String(Date.now())
                        rules.push({placement_id: identity, trigger: trigger,
                                    collection_id: collections[placementCollection.currentIndex].collectionId,
                                    profile_id: profiles[placementProfile.currentIndex].profileId,
                                    overrides: trigger === "fixed_slot" ? {slot_seconds: Number(adSlotSecondsField.text || 1800)} : {}})
                        adCatalogDialog.placementRules = rules
                    }
                }
                Repeater {
                    model: adCatalogDialog.placementRules
                    delegate: RowLayout {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: modelData.trigger + " • " + modelData.collection_id + " • " + modelData.profile_id
                            color: adsRoot.textSecondary
                        }
                        StudioButton {
                            text: "Remove"
                            onClicked: {
                                var rules = adCatalogDialog.placementRules.slice()
                                rules.splice(parent.index, 1)
                                adCatalogDialog.placementRules = rules
                            }
                        }
                    }
                }
                ChannelCheckBox {
                    id: catalogAdvancedOverrides
                    text: "Advanced channel overrides"
                }
                ChannelTextField {
                    id: catalogAssignOverrides
                    visible: catalogAdvancedOverrides.checked
                    Layout.fillWidth: true
                    text: "{}"
                    placeholderText: "Per-channel overrides (JSON)"
                }
                StudioButton {
                    id: saveAdAssignmentButton
                    text: "Save Assignment to Current Channel"
                    highlighted: true
                    onClicked: {
                        try {
                            var overrides = JSON.parse(catalogAssignOverrides.text)
                            var result = channelOS.assignAdBreakProfile({
                                channelNumber: adsRoot.channelNumber,
                                collectionId: catalogAssignCollection.text.trim(),
                                profileId: catalogAssignProfile.text.trim(),
                                overrides: overrides,
                                placements: adCatalogDialog.placementRules
                            })
                            adCatalogDialog.showResult(result)
                            if (result && result.ok) {
                                adCollectionField.text = catalogAssignCollection.text.trim()
                                adProfileField.text = catalogAssignProfile.text.trim()
                                adsRoot.adEnabled = true
                                adsRoot.setupMode = "advanced"
                                adsRoot.adPlacementSnapshots = adCatalogDialog.placementRules
                                adsRoot.advancedDirty = true
                            }
                        } catch (error) {
                            adCatalogDialog.catalogFeedback = "Invalid overrides JSON: " + error
                        }
                    }
                }

                }
                Text {
                    Layout.fillWidth: true
                    color: adsRoot.textSecondary
                    wrapMode: Text.Wrap
                    font.pixelSize: 10
                    text: "Saved collections: "
                          + ((adCatalogDialog.catalogData.collections || []).map(function(item) {
                                return item.collectionId
                             }).join(", ") || "none")
                          + "    Profiles: "
                          + ((adCatalogDialog.catalogData.profiles || []).map(function(item) {
                                return item.profileId
                             }).join(", ") || "none")
                }
                StudioButton {
                    text: "Current Channel Diagnostics"
                    onClicked: {
                        var report = channelOS.adBreakDiagnostics(
                            adsRoot.channelNumber)
                        adCatalogDialog.catalogFeedback = report && report.ok
                                ? ("Plans: " + report.plannedBreaks
                                   + " | Aired: " + report.completedAirings
                                   + " | Viewed: " + report.completedViewings)
                                : String(report && report.message || "Channel is not active")
                    }
                }

            }
        }
    }

            }
        }
    }
    StudioDialog {
        id: binDialog; title: "Ad Bin"; parent: Overlay.overlay
        width: Math.min(650, adsRoot.hostItem.width - 40); height: Math.min(700, adsRoot.hostItem.height - 40)
        x: (adsRoot.hostItem.width - width) / 2; y: (adsRoot.hostItem.height - height) / 2
        contentItem: AdMediaBin {
            mediaLibrary: adsRoot.mediaLibrary; sourceOptions: adsRoot.sourceOptions
            sources: adsRoot.binScope.sources; assetIds: adsRoot.binScope.ids; excludedIds: adsRoot.binScope.excluded
            readOnly: adsRoot.managedBin
            onSourcesEdited: function(paths) { adsRoot.setSources(paths) }
            onExclusionsEdited: function(ids) { adsRoot.setExcluded(ids) }
        }
        standardButtons: Dialog.Close
    }

}
