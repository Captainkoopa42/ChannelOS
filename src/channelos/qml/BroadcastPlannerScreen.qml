pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "PlannerDraft.js" as Draft

// Broadcast Planner. Normally embedded in Channel Studio as its Planner tab
// (embedded: true): Studio then owns the channel identity, Apply, ad breaks
// and the media bin. The standalone layout remains for direct hosting.
Item {
    id: planner
    anchors.fill: parent
    property var hostWindow: Window.window
    property bool embedded: false
    // Embedded hosting: Studio drives activation and the channel number.
    property bool active: false
    property int channelNumber: 0
    property var externalAds: null
    // When true, the first rule that turns a calendar channel into a planner
    // channel waits for conversionRequested() to be confirmed.
    property bool confirmConversion: false
    property var pendingConversion: null
    property bool conversionAccepted: false
    signal conversionRequested()

    property var editor: ({})
    property var rules: editor.planner || ({groups:[],tracks:[],windows:[],cycle:{},suspensions:[],layers:[],profile_bindings:[]})
    property var mediaBin: []
    property var media: ({})
    property var mediaRows: []
    property var profiles: []
    property var forecast: ({})
    property var worker: channelOS && typeof channelOS.plannerStateJson !== "undefined" ? JSON.parse(channelOS.plannerStateJson) : ({busy:false})
    property int editingNumber: 0
    property int serial: 0
    property int selectedTab: 0
    property string selectedTrack: ""
    property string search: ""
    property string viewDate: new Date().toISOString().slice(0,10)
    property string feedback: ""
    property bool feedbackError: false
    property bool dirty: false
    property bool loaded: false
    property bool loadingDraft: false
    property bool applying: false
    property bool pendingPreview: false
    property string exitDestination: "broadcaster"
    property int selectedProfile: -1
    property var assignments: ({})

    // Studio palette (ChannelStudioScreen.qml).
    readonly property color bg: Theme.c("#050c15")
    readonly property color panel: Theme.c("#081625")
    readonly property color panelRaised: Theme.c("#0d2035")
    readonly property color panelSoft: Theme.c("#10283f")
    readonly property color line: Theme.c("#1a3550")
    readonly property color muted: Theme.c("#9fb0c2")
    readonly property color ink: Theme.c("#f4f7fb")
    readonly property color accent: Theme.c("#1a91ff")
    readonly property color accentBright: Theme.c("#42adff")
    readonly property color good: Theme.c("#2bcf75")
    readonly property color warning: Theme.c("#ffb84a")
    readonly property color danger: Theme.c("#ff6666")

    readonly property var track: rules.tracks.filter(function(t) { return t.id === selectedTrack })[0] || ({})
    readonly property var group: rules.groups.filter(function(g) { return g.id === track.group_id })[0] || ({name:"Select a track",asset_ids:[]})
    readonly property var windows: rules.windows.filter(function(w) { return w.track_id === selectedTrack })
    readonly property bool previewCurrent: Boolean(forecast.ok) && Number(forecast.token) === serial
    readonly property bool calculating: loaded && (pendingPreview || Number(forecast.token) !== serial)
    readonly property bool hasRules: rules.tracks.length > 0 || rules.windows.length > 0
    readonly property bool canApply: loaded && dirty && previewCurrent && forecast.confidence !== "Blocked" && !worker.busy && !applying && String(editor.name || "").trim().length > 0
    readonly property var anchorLocal: localParts(rules.start_at, rules.timezone)

    // Readable choices for internal rule values.
    readonly property var afterPassChoices: [
        {value:"filler",label:"Play filler"},{value:"loop",label:"Loop this track"},
        {value:"rerun",label:"Switch to reruns"},{value:"unassigned",label:"Leave the time unassigned"},
        {value:"successor",label:"Hand off to another track"}]
    readonly property var orderChoices: [{value:"sequential",label:"In order"},{value:"shuffle",label:"Shuffle"}]
    readonly property var fitChoices: [
        {value:"strict",label:"Fit inside the window"},{value:"overrun",label:"May run over"},
        {value:"carryover",label:"Carry over to the next airing"},{value:"next_fit",label:"Next item that fits"}]
    readonly property var historyChoices: [
        {value:"none",label:"Off"},{value:"era",label:"Era recreation"},
        {value:"original",label:"Original airings"},{value:"replay",label:"Replay from a date"}]
    readonly property var cycleActionChoices: [{value:"restart",label:"Restart the channel"},{value:"once",label:"Air once and done"}]
    readonly property var completionChoices: [
        {value:"all",label:"Every track finished"},{value:"any",label:"Any track finished"},
        {value:"selected_all",label:"All selected tracks"},{value:"selected_any",label:"Any selected track"},
        {value:"custom",label:"Custom gate (edit in Rules)"},{value:"none",label:"No content gate"}]
    readonly property var gateChoices: [{value:"and",label:"Content and date"},{value:"or",label:"Content or date"}]
    readonly property var boundaryChoices: [
        {value:"safe",label:"Next safe moment"},{value:"day",label:"Start of a day"},{value:"week",label:"Start of a week"},
        {value:"month",label:"Start of a month"},{value:"quarter",label:"Start of a quarter"},{value:"year",label:"Start of a year"},
        {value:"period",label:"Custom period"},{value:"manual",label:"When I release it"}]
    readonly property var afterOnceChoices: [{value:"slate",label:"Show an end slate"},{value:"offair",label:"Go off air"},{value:"filler",label:"Play filler"}]
    readonly property var editEffectChoices: [{value:"next_cycle",label:"From the next cycle"},{value:"safe_future",label:"At the next safe moment"}]
    readonly property var pauseTargetChoices: [
        {value:"track",label:"Selected track"},{value:"group",label:"Collection"},{value:"window",label:"Airing window"},
        {value:"layer",label:"Seasonal layer"},{value:"filler",label:"Filler"},{value:"advertising",label:"Ad breaks"},
        {value:"channel",label:"Whole channel"}]
    readonly property var resumeChoices: [
        {value:"continue",label:"Continue where it left off"},{value:"restart",label:"Restart the track"},
        {value:"skip",label:"Skip what was missed"}]
    readonly property var weekdayChoices: [
        {value:0,label:"Monday"},{value:1,label:"Tuesday"},{value:2,label:"Wednesday"},{value:3,label:"Thursday"},
        {value:4,label:"Friday"},{value:5,label:"Saturday"},{value:6,label:"Sunday"}]
    readonly property var kindLabels: ({program:"", rerun:"Rerun", filler:"Filler", advertisement:"Ad break", offair:"Off air", slate:"End slate"})

    component Caption: Label { color: planner.muted; font.pixelSize: 11; wrapMode: Text.WordWrap }
    component Heading: Label { color: planner.ink; font.pixelSize: 15; font.weight: Font.DemiBold }
    component Action: ChannelButton {}
    component Field: ChannelTextField { font.pixelSize: 12 }
    component TimeField: ChannelTextField {
        font.pixelSize: 12
        implicitWidth: 76
        placeholderText: "HH:MM"
        inputMethodHints: Qt.ImhPreferNumbers
        validator: RegularExpressionValidator { regularExpression: /^(([01][0-9]|2[0-3]):[0-5][0-9]|24:00)$/ }
    }
    // A combo box over {value,label} choices: shows labels, reports values.
    component Choice: ChannelComboBox {
        id: choice
        property var choices: []
        property var value
        signal chosen(var value)
        font.pixelSize: 12
        model: choices
        textRole: "label"
        valueRole: "value"
        // Re-sync explicitly: a user pick replaces any currentIndex binding.
        function sync() { currentIndex = Math.max(0, choices.findIndex(function(c) { return c.value === choice.value })) }
        onValueChanged: sync()
        onChoicesChanged: sync()
        Component.onCompleted: sync()
        onActivated: function(index) { chosen(choices[index].value) }
    }
    component Card: Rectangle { color: planner.panel; border.color: planner.line; radius: 10 }
    component PlannerDialog: Dialog {
        id: plannerDialog
        modal: true
        dim: true
        padding: 22
        anchors.centerIn: parent
        palette.window: planner.panelRaised
        palette.windowText: planner.ink
        palette.button: planner.panelRaised
        palette.buttonText: planner.ink
        background: Rectangle { radius: 10; color: planner.panelRaised; border.color: planner.line }
        header: Label {
            text: plannerDialog.title
            color: planner.ink
            font.pixelSize: 17
            font.weight: Font.DemiBold
            padding: 22
            bottomPadding: 0
        }
        Overlay.modal: Rectangle { color: Theme.c("#aa02070d") }
    }
    component DialogButtons: RowLayout {
        id: buttons
        property string acceptText: "Apply"
        property string rejectText: "Cancel"
        property bool showAccept: true
        signal accepted()
        signal rejected()
        Layout.fillWidth: true
        Layout.topMargin: 6
        Item { Layout.fillWidth: true }
        Action { text: buttons.rejectText; onClicked: buttons.rejected() }
        Action { visible: buttons.showAccept; text: buttons.acceptText; highlighted: true; onClicked: buttons.accepted() }
    }

    // Standalone only: embedded, Studio's ad editor is used and this one is
    // never created.
    readonly property var ownAds: ownAdsLoader.item
    function ads() { return externalAds || ownAds }
    function choiceLabel(choices, value) {
        var hit = choices.filter(function(c) { return c.value === value })[0]
        return hit ? hit.label : String(value)
    }
    function count(value, noun) { return value + " " + noun + (value === 1 ? "" : "s") }
    function hours(seconds) {
        var value = Number(seconds || 0) / 3600
        return value < 1 ? Math.round(value * 60) + " min" : value.toFixed(1) + " hours"
    }
    function localParts(iso, zone) {
        if (!iso) return ({date:"", time:"", zoneLabel:String(zone || "UTC")})
        if (channelOS && typeof channelOS.plannerIsoToLocal === "function")
            return channelOS.plannerIsoToLocal(String(iso), String(zone || "UTC"))
        return ({date:String(iso).slice(0,10), time:String(iso).slice(11,16), zoneLabel:String(zone || "UTC")})
    }
    function setAnchor(date, time, zone) {
        if (!date || !time) return
        if (!channelOS || typeof channelOS.plannerLocalToIso !== "function") {
            mutate(function(r) { r.start_at = date + "T" + time + ":00+00:00" })
            return
        }
        var result = channelOS.plannerLocalToIso(date, time, zone)
        if (!result.ok) { feedback = result.message; feedbackError = true; return }
        var iso = result.iso
        mutate(function(r) { r.start_at = iso; r.timezone = zone })
    }
    function task(action, payload) {
        payload.token=serial
        channelOS.plannerTask(action,JSON.stringify(payload))
    }
    function mutate(callback, editorPatch) {
        var next=Draft.copy(rules)
        callback(next)
        var hadRules = rules.tracks.length > 0 || rules.windows.length > 0
        var addsRules = next.tracks.length > 0 || next.windows.length > 0
        if (confirmConversion && !conversionAccepted && !hadRules && addsRules) {
            pendingConversion = {planner: next, patch: editorPatch || ({})}
            conversionRequested()
            return
        }
        editor=Object.assign({},editor,editorPatch || ({}),{planner:next})
        changed()
    }
    function acceptConversion() {
        if (!pendingConversion) return
        var pending = pendingConversion
        pendingConversion = null
        conversionAccepted = true
        editor = Object.assign({}, editor, pending.patch, {planner: pending.planner})
        changed()
    }
    function rejectConversion() {
        pendingConversion = null
        if (selectedTrack && !rules.tracks.some(function(t) { return t.id === selectedTrack }))
            selectedTrack = ""
    }
    function changed() {
        serial++
        dirty=true
        pendingPreview=true
        if (!feedbackError) feedback = "Updating forecast…"
        previewTimer.restart()
    }
    function setEditor(key,value) {
        var next=Object.assign({},editor)
        next[key]=value
        editor=next
        changed()
    }
    function setTrack(key,value) {
        mutate(function(r) { r.tracks.forEach(function(t) { if(t.id===selectedTrack) t[key]=value }) })
    }
    function setWindow(id,key,value) {
        mutate(function(r) { r.windows.forEach(function(w) { if(w.id===id) w[key]=value }) })
    }
    function setCycle(key,value) { mutate(function(r) { r.cycle[key]=value }) }
    function withSource(source) {
        var sources = editor.sources || []
        return sources.indexOf(source) >= 0 ? ({}) : ({sources: sources.concat([source])})
    }
    function addTrack(bin,rerun,at) {
        var created = ""
        mutate(function(r) { created=Draft.addTrack(r,bin,rerun,at) }, withSource(bin.source))
        if (created) selectedTrack = created
    }
    function addFiller(bin) {
        mutate(function(r) {
            r.filler_asset_ids=(r.filler_asset_ids || []).concat(bin.asset_ids).filter(function(id,i,a) { return a.indexOf(id)===i })
            r.gap_filler=true
        }, withSource(bin.source))
    }
    function preview() {
        if(!loaded) return
        var draft=Object.assign({},editor,ads().editorObject())
        draft.name=String(draft.name || "Untitled planner")
        draft.mode="planner"
        pendingPreview=false
        task("preview",{editor:draft,view_start:selectedTab===2 ? viewDate.slice(0,7)+"-01" : viewDate,view_days:selectedTab===0 ? 1 : selectedTab===2 ? 31 : 7})
    }
    function targetNumber() {
        return embedded ? Number(channelNumber || 0) : Number(hostWindow ? hostWindow.plannerChannelNumber || 0 : 0)
    }
    // Embedded: keep taking results while Studio is open, even on another tab.
    function listening() {
        return embedded ? Boolean(hostWindow && hostWindow.screen === "studio") : shouldLoad()
    }
    function shouldLoad() {
        if (embedded) return active
        return Boolean(hostWindow && hostWindow.screen === "planner")
    }
    function loadDraft() {
        if (!channelOS || typeof channelOS.plannerTask !== "function") return
        if (!shouldLoad()) return
        var number=targetNumber()
        if(loadingDraft && editingNumber===number) return
        loadingDraft=true
        loaded=false
        feedbackError=false
        feedback="Loading indexed media…"
        editingNumber=number
        task("load",{number:editingNumber})
    }
    // Embedded: forget the loaded draft (Studio reopened or applied).
    function invalidate() {
        loaded=false
        loadingDraft=false
        dirty=false
        pendingConversion=null
        conversionAccepted=false
        forecast=({})
        if (channelOS && typeof channelOS.cancelPlannerTask === "function") channelOS.cancelPlannerTask()
        if (shouldLoad()) loadDraft()
    }
    function title(asset) { return asset && media[asset] ? media[asset].title : asset ? "Unavailable media" : "Off air" }
    function trackName(id) { var t=rules.tracks.filter(function(t) { return t.id===id })[0]; var g=t ? rules.groups.filter(function(g) { return g.id===t.group_id })[0] : null; return g ? g.name + (t.mode==="rerun" ? " (reruns)" : "") : "Removed track" }
    function trackChoices(exclude) {
        return rules.tracks.filter(function(t) { return t.id!==exclude }).map(function(t) { return {value:t.id,label:trackName(t.id)} })
    }
    function clock(value) {
        if (!value) return ""
        var parts = localParts(value, rules.timezone)
        return parts.time
    }
    function stamp(value) {
        if (!value) return "Waiting for rules"
        var parts = localParts(value, rules.timezone)
        return parts.date + " " + parts.time
    }
    function milestone(value) { return value ? localParts(value, rules.timezone).date : "Not reached" }
    function scopeText(scope) {
        scope = scope || {}
        var bits = []
        if (scope.months && scope.months.length) bits.push("months " + scope.months.join(", "))
        if (scope.from_date || scope.until_date) bits.push((scope.from_date || "start") + " to " + (scope.until_date || "open"))
        return bits.length ? bits.join(" · ") : "every date"
    }
    // Forecast segments for the Day view, with adjacent off-air time merged so
    // one gap reads as one row ("07:47 – 09:00 Off air").
    function rows() {
        var list=forecast.segments || []
        if(selectedTab===0) list=list.filter(function(s) { return s.local_day===viewDate })
        var merged=[]
        for (var i=0;i<list.length;++i) {
            var segment=list[i]
            var previous=merged.length ? merged[merged.length-1] : null
            if (previous && segment.kind==="offair" && previous.kind==="offair" && previous.ends_at===segment.starts_at) {
                merged[merged.length-1]=Object.assign({},previous,{ends_at:segment.ends_at})
                continue
            }
            merged.push(segment)
        }
        return merged
    }
    function segmentText(segment) {
        var kind = kindLabels[segment.kind] === undefined ? segment.kind : kindLabels[segment.kind]
        var range = String(segment.display_start || "").slice(11) + " – " + clock(segment.ends_at)
        if (segment.kind === "offair") return range + "   Off air"
        return range + "   " + title(segment.asset_id) + (kind ? "   ·  " + kind : "")
    }
    function requestExit(destination) {
        exitDestination=String(destination || "broadcaster")
        back()
    }
    function back() {
        if(ownAds && ownAds.dialogOpen) { ownAds.cancelActive(); return }
        if(cycleDialog.visible) { cycleDialog.close(); return }
        if(sourcesDialog.visible) { sourcesDialog.close(); return }
        if(rulesDialog.visible) { rulesDialog.close(); return }
        if(pauseDialog.visible) { pauseDialog.close(); return }
        if(layerDialog.visible) { layerDialog.close(); return }
        if(discardDialog.visible) { discardDialog.close(); return }
        if(embedded) return
        if(dirty) discardDialog.open()
        else { channelOS.cancelPlannerTask(); if(hostWindow) hostWindow.screen=exitDestination }
    }
    function dialogOpen() {
        return (ownAds ? ownAds.dialogOpen : false) || cycleDialog.visible || sourcesDialog.visible || rulesDialog.visible
               || pauseDialog.visible || layerDialog.visible || discardDialog.visible
    }
    function handleControllerIntent(intent) {
        if(intent==="BACK") { back(); return true }
        return false
    }
    Keys.onEscapePressed: function(event) {
        if (embedded && !dialogOpen()) { event.accepted = false; return }
        back()
    }
    // Compose the channel the planner would apply; Studio passes its own
    // identity, calendar blocks and ad settings as `base`.
    function composeEditor(base) {
        var draft = Object.assign({}, editor, base || ({}), {mode:"planner", planner:Draft.copy(rules)})
        var sources = (base && base.sources ? base.sources : []).slice()
        ;(editor.sources || []).forEach(function(source) { if (sources.indexOf(source) < 0) sources.push(source) })
        draft.sources = sources
        return draft
    }
    function apply() {
        if(!canApply) return
        editor=Object.assign({},editor,ads().editorObject(),{mode:"planner"})
        var result=channelOS.startChannelMutation(editingNumber ? "update" : "create",editingNumber,editor)
        if(result.ok) { applying=true; feedback="Preparing and validating channel…" }
        else { feedback=result.message; feedbackError=true }
    }
    Timer { id: previewTimer; interval: 400; onTriggered: planner.preview() }
    Connections {
        target: channelOS
        ignoreUnknownSignals: true
        function onPlannerResult(action, raw) {
            if (!planner.listening()) return
            var result=JSON.parse(raw)
            if(action==="load") planner.loadingDraft=false
            if(!result.ok) { planner.feedback=result.message; planner.feedbackError=true; if(action==="preview") { planner.forecast=Object.assign({},result,{token:planner.serial}); planner.pendingPreview=false } return }
            planner.feedbackError=false
            if(action==="load") {
                if (planner.embedded && planner.confirmConversion && result.editor.planner) {
                    // A calendar channel starts the Planner tab empty: the
                    // service's suggested conversion track would otherwise
                    // convert the channel without the viewer choosing to.
                    result.editor.planner.tracks=[]
                    result.editor.planner.groups=[]
                    result.editor.planner.windows=[]
                }
                planner.editor=result.editor
                planner.mediaBin=result.bin
                planner.media=result.media
                planner.mediaRows=result.mediaRows || []
                planner.profiles=result.profiles
                planner.selectedTrack=planner.rules.tracks.length ? planner.rules.tracks[0].id : ""
                planner.viewDate=planner.localParts(planner.rules.start_at, planner.rules.timezone).date || planner.viewDate
                if (!planner.externalAds && planner.ownAds) planner.ownAds.load(result.editor)
                planner.loaded=true
                planner.dirty=false
                planner.serial++
                planner.feedback="Calculating forecast…"
                previewTimer.restart()
            } else if(action==="preview") {
                if(Number(result.token)!==planner.serial) return
                planner.forecast=result
                planner.feedback=result.issues.length ? result.issues[0].message : "Forecast ready. Live clocks and history are unchanged."
                planner.feedbackError=result.confidence==="Blocked"
            } else if(action==="bind_profile" || action==="import_airings") {
                if(Number(result.token)!==planner.serial) return
                planner.editor=Object.assign({},planner.editor,{planner:result.planner})
                planner.changed()
                planner.feedback=action==="bind_profile" ? "Profile applied to this draft. Review the forecast, then apply the channel." : result.imported+" original airings imported into the draft."
            } else {
                if(result.profiles) planner.profiles=result.profiles
                planner.feedback=result.message || "Profile saved. Channels keep their pinned versions until explicitly reapplied."
            }
        }
        function onChannelMutationCompleted(result) {
            if(!planner.applying) return
            planner.applying=false
            planner.feedback=result.message || (result.ok ? "Channel applied" : "Channel could not be applied")
            planner.feedbackError=!result.ok
            if(result.ok) { planner.dirty=false; planner.editingNumber=Number(planner.editor.channel); if(planner.hostWindow && !planner.embedded) planner.hostWindow.plannerChannelNumber=planner.editingNumber }
        }
    }
    onActiveChanged: {
        if (!embedded) return
        if (active && (!loaded || editingNumber !== Number(channelNumber || 0))) loadDraft()
    }
    onChannelNumberChanged: if (embedded && (loaded || loadingDraft) && editingNumber !== Number(channelNumber || 0)) invalidate()
    onHostWindowChanged: if(!embedded && hostWindow && hostWindow.screen==="planner") loadDraft()
    Connections {
        target: planner.hostWindow || null
        function onScreenChanged() {
            if (planner.embedded) {
                if (planner.hostWindow.screen !== "studio") { planner.loadingDraft=false; planner.loaded=false; if (typeof channelOS.cancelPlannerTask === "function") channelOS.cancelPlannerTask() }
                return
            }
            if(planner.hostWindow.screen==="planner") planner.loadDraft()
            else { planner.loadingDraft=false; channelOS.cancelPlannerTask() }
        }
    }

    ThemeBackdrop { anchors.fill: parent; visible: !planner.embedded }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: planner.embedded ? 0 : 20
        spacing: 10
        // Standalone header: title, draft state, Back / Rules / Apply.
        RowLayout {
            Layout.fillWidth: true
            visible: !planner.embedded
            ColumnLayout {
                spacing: 2
                Caption { text: "CHANNELOS  /  BROADCASTER"; font.letterSpacing: 2 }
                Label { text: "Broadcast Planner"; color: planner.ink; font.pixelSize: 24; font.weight: Font.DemiBold }
            }
            Item { Layout.fillWidth: true }
            Action { text: "Back"; onClicked: planner.requestExit("broadcaster") }
            Action { id: applyAction; objectName:"plannerApply"; text: planner.applying ? "Applying…" : "Apply channel"; highlighted: true; enabled: planner.canApply; onClicked: planner.apply() }
        }
        Flow {
            id: plannerToolbar
            objectName: "plannerToolbar"
            Layout.fillWidth: true
            spacing: 8
            Row {
                visible: !planner.embedded
                spacing: 8
                height: 38
                Caption { text: "CHANNEL"; height: 38; verticalAlignment: Text.AlignVCenter }
                Field { width: 64; text: String(planner.editor.channel || ""); enabled: !planner.editingNumber; onEditingFinished: planner.setEditor("channel",text) }
                Field { id: channelNameField; objectName:"plannerChannelName"; width: 200; text: String(planner.editor.name || ""); placeholderText: "Name your channel"; onEditingFinished: planner.setEditor("name",text) }
            }
            Row {
                spacing: 8
                height: 38
                Caption { text: "FIRST SHOW"; height: 38; verticalAlignment: Text.AlignVCenter }
                PlannerDatePicker {
                    objectName: "plannerAnchorDate"
                    date: planner.anchorLocal.date
                    onPicked: function(value) { planner.setAnchor(value, planner.anchorLocal.time || "00:00", planner.rules.timezone || "UTC") }
                }
                TimeField {
                    objectName: "plannerAnchorTime"
                    text: planner.anchorLocal.time
                    onEditingFinished: if (acceptableInput && text !== planner.anchorLocal.time) planner.setAnchor(planner.anchorLocal.date, text, planner.rules.timezone || "UTC")
                }
            }
            Row {
                spacing: 8
                height: 38
                Caption { text: "TIME ZONE"; height: 38; verticalAlignment: Text.AlignVCenter }
                Choice {
                    id: zonePick
                    objectName: "plannerTimezone"
                    width: 230
                    choices: (channelOS && channelOS.plannerTimezones ? channelOS.plannerTimezones : ["UTC"]).map(function(zone) { return {value: zone, label: zone.replace(/_/g, " ")} })
                    value: String(planner.rules.timezone || "UTC")
                    onChosen: function(value) { planner.setAnchor(planner.anchorLocal.date, planner.anchorLocal.time || "00:00", value) }
                }
            }
            Rectangle {
                visible: !planner.embedded
                height: 38
                width: draftState.implicitWidth + 24
                radius: 19
                color: planner.dirty ? Theme.c("#4b3717") : planner.panelRaised
                border.color: planner.dirty ? planner.warning : planner.line
                Text {
                    id: draftState
                    anchors.centerIn: parent
                    text: planner.dirty ? "UNAPPLIED PLANNER CHANGES" : "LIVE TV UNCHANGED"
                    color: planner.dirty ? planner.warning : planner.muted
                    font.pixelSize: 11
                    font.weight: Font.Bold
                }
            }
            Action { visible: !planner.embedded; text: "Ad Breaks"; onClicked: if (planner.ownAds) planner.ownAds.openBasic() }
            Action { text: "Sources"; onClicked: sourcesDialog.open() }
            Action { text: "Channel Cycle"; onClicked: cycleDialog.open() }
            Action { text: "Rules"; onClicked: { rawRules.text=JSON.stringify(planner.rules,null,2); rulesDialog.open() } }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            Card {
                visible: !planner.embedded
                Layout.preferredWidth: Math.max(205,planner.width*.19)
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 14; spacing: 10
                    Heading { text: "Collections" }
                    PlannerMediaBin { planner: planner; Layout.fillWidth: true; Layout.fillHeight: true }
                }
            }
            Card {
                id: scheduleCard
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 0
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 14; spacing: 10
                    Flow {
                        id: tabs
                        objectName: "plannerTabs"
                        Layout.fillWidth: true
                        spacing: 6
                        Repeater {
                            model: ["Day Plan", "Week Plan", "Seasons", "Forecast", "Profiles", "Original Airings"]
                            delegate: Action {
                                required property int index
                                required property string modelData
                                text: modelData
                                checkable: true
                                checked: planner.selectedTab === index
                                onClicked: { planner.selectedTab=index; if(planner.loaded) previewTimer.restart() }
                            }
                        }
                    }
                    StackLayout {
                        currentIndex: planner.selectedTab
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Item {
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true
                                    Heading { text: "Day schedule" }
                                    Item { Layout.fillWidth: true }
                                    Action { text: "‹"; implicitWidth: 38; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate,-1); previewTimer.restart() } }
                                    PlannerDatePicker { objectName: "plannerViewDate"; date: planner.viewDate; onPicked: function(value) { planner.viewDate=value; previewTimer.restart() } }
                                    Action { text: "›"; implicitWidth: 38; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate,1); previewTimer.restart() } }
                                }
                                Caption {
                                    Layout.fillWidth: true
                                    text: "Times in " + planner.anchorLocal.zoneLabel + " · "
                                          + (planner.editor.calendarBlocks || []).length
                                          + ((planner.editor.calendarBlocks || []).length === 1 ? " Studio block stays fixed" : " Studio blocks stay fixed")
                                }
                                ListView {
                                    id: dayList
                                    objectName: "plannerDayList"
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 5
                                    model: 24
                                    ScrollBar.vertical: ScrollBar {}
                                    delegate: Rectangle {
                                        id: hourRow
                                        required property int index
                                        readonly property var shows: planner.rows().filter(function(s) { return Number(String(s.display_start || "").slice(11,13))===hourRow.index })
                                        width: dayList.width; height: Math.max(44,hourShows.implicitHeight+12)
                                        radius: 6
                                        color: drop.containsDrag ? Theme.c("#12396a") : planner.panelRaised
                                        border.color: drop.containsDrag ? planner.accentBright : planner.line
                                        RowLayout {
                                            anchors.fill: parent; anchors.margins: 6
                                            Caption { text: Draft.hour(hourRow.index); Layout.preferredWidth: 46; color: planner.muted; font.pixelSize: 12 }
                                            ColumnLayout {
                                                id: hourShows
                                                Layout.fillWidth: true; spacing: 3
                                                Repeater {
                                                    model: hourRow.shows
                                                    delegate: Rectangle {
                                                        id: dayShow
                                                        objectName: "plannerDaySegment"
                                                        required property var modelData
                                                        Layout.fillWidth: true; implicitHeight: showLabel.implicitHeight+12; radius: 5
                                                        color: modelData.kind==="offair" ? Theme.c("#0b1622") : modelData.kind==="advertisement" ? Theme.c("#3a2e17") : modelData.kind==="filler" ? Theme.c("#14283b") : modelData.kind==="rerun" ? Theme.c("#173452") : Theme.c("#123558")
                                                        border.color: modelData.kind==="offair" ? planner.line : modelData.kind==="advertisement" ? Theme.c("#6b5326") : Theme.c("#24577d")
                                                        Label {
                                                            id: showLabel
                                                            anchors.fill: parent; anchors.margins: 6
                                                            text: planner.segmentText(dayShow.modelData)
                                                            color: dayShow.modelData.kind==="offair" ? planner.muted : planner.ink
                                                            font.pixelSize: 12
                                                            wrapMode: Text.WordWrap
                                                        }
                                                    }
                                                }
                                                Caption { visible: hourRow.shows.length===0; text: "Drop a collection here to air it daily at this hour"; opacity: .6; Layout.fillWidth: true }
                                            }
                                        }
                                        DropArea { id: drop; anchors.fill: parent; keys: ["planner-group"]; onDropped: function(event) { if(event.source && event.source.binGroup) { planner.addTrack(event.source.binGroup,false,hourRow.index); event.acceptProposedAction() } } }
                                    }
                                }
                            }
                        }
                        Item {
                            ColumnLayout {
                                anchors.fill: parent
                                Heading { text: "Weekly programming" }
                                Caption { text: "Windows that share a track continue one episode order. In era recreation, weekdays follow the reference year; Day shows the real dates."; Layout.fillWidth: true }
                                ListView {
                                    id: weekList
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8
                                    model: 7
                                    delegate: Rectangle {
                                        id: weekdayCard
                                        required property int index
                                        width: weekList.width; height: weekContent.implicitHeight+20
                                        radius: 8; color: planner.panelRaised; border.color: planner.line
                                        ColumnLayout {
                                            id: weekContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10
                                            Heading { text: planner.weekdayChoices[weekdayCard.index].label }
                                            Repeater {
                                                model: planner.rules.windows.filter(function(w) { return !w.scope || !w.scope.weekdays || w.scope.weekdays.indexOf(weekdayCard.index)>=0 })
                                                delegate: Action {
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    checked: modelData.track_id === planner.selectedTrack
                                                    text: modelData.start+" – "+modelData.end+"   "+planner.trackName(modelData.track_id)+"   ·  "+(modelData.bracket_minutes || 60)+"-minute slots"
                                                    onClicked: planner.selectedTrack=modelData.track_id
                                                }
                                            }
                                            Caption { visible: planner.rules.windows.filter(function(w) { return !w.scope || !w.scope.weekdays || w.scope.weekdays.indexOf(weekdayCard.index)>=0 }).length === 0; text: "Nothing scheduled" }
                                        }
                                    }
                                }
                            }
                        }
                        ScrollView {
                            clip: true
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 14
                                Heading { text: "Seasonal rules & pauses" }
                                RowLayout {
                                    Action { text: "‹ Month"; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate.slice(0,7)+"-01",-1); previewTimer.restart() } }
                                    Heading { text: Qt.formatDate(new Date(planner.viewDate.slice(0,7)+"-15T12:00:00Z"), "MMMM yyyy"); Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
                                    Action { text: "Month ›"; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate.slice(0,7)+"-01",32).slice(0,7)+"-01"; previewTimer.restart() } }
                                }
                                GridLayout {
                                    columns: 7; Layout.fillWidth: true; rowSpacing: 4; columnSpacing: 4
                                    Repeater { model: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]; delegate: Caption { required property string modelData; text: modelData; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter } }
                                    Repeater {
                                        model: Draft.monthDays(planner.viewDate)
                                        delegate: Action {
                                            required property string modelData
                                            Layout.fillWidth: true; implicitHeight: 50; font.pixelSize: 11
                                            property var counts: (planner.forecast.calendar_days || {})[modelData] || ({})
                                            checked: modelData===planner.viewDate
                                            text: Number(modelData.slice(-2))+"\n"+(counts.programs ? counts.programs+(counts.programs===1 ? " airing" : " airings") : "—")
                                            opacity: modelData.slice(0,7)===planner.viewDate.slice(0,7) ? 1 : .4
                                            onClicked: { planner.viewDate=modelData; planner.selectedTab=0; previewTimer.restart() }
                                        }
                                    }
                                }
                                Caption { text: "A higher-priority layer replaces only the time it overlaps, unless it is set to replace the whole channel."; Layout.fillWidth: true }
                                RowLayout {
                                    Action { text: "+ Seasonal Layer"; onClicked: { layerName.text="Holiday schedule"; layerMonths.text="12"; layerDialog.open() } }
                                    Action { text: "+ Pause Selected Track"; enabled: !!planner.selectedTrack; onClicked: pauseDialog.open() }
                                }
                                Repeater {
                                    model: planner.rules.layers || []
                                    delegate: Card {
                                        id: layerCard
                                        required property var modelData
                                        color: planner.panelRaised
                                        Layout.fillWidth: true; implicitHeight: layerText.implicitHeight+24
                                        ColumnLayout {
                                            id: layerText; anchors.fill: parent; anchors.margins: 12
                                            Heading { text: layerCard.modelData.name }
                                            Caption { text: "Priority "+layerCard.modelData.priority+" · "+(layerCard.modelData.replace_scope==="channel" ? "replaces the whole channel" : "replaces overlapping time")+" · "+planner.scopeText(layerCard.modelData.scope); Layout.fillWidth: true }
                                            Action { text: "Use for the selected track’s windows"; enabled: !!planner.selectedTrack; onClicked: planner.mutate(function(r) { r.windows.forEach(function(w) { if(w.track_id===planner.selectedTrack) w.layer_id=layerCard.modelData.id }) }) }
                                        }
                                    }
                                }
                                Repeater {
                                    model: planner.rules.suspensions || []
                                    delegate: Card {
                                        id: pauseCard
                                        required property var modelData
                                        color: planner.panelRaised
                                        Layout.fillWidth: true; implicitHeight: pauseText.implicitHeight+24
                                        ColumnLayout {
                                            id: pauseText; anchors.fill: parent; anchors.margins: 12
                                            Heading { text: pauseCard.modelData.name || "Pause" }
                                            Caption { text: planner.choiceLabel(planner.pauseTargetChoices, pauseCard.modelData.target)+(pauseCard.modelData.target==="track" && pauseCard.modelData.target_id ? " ("+planner.trackName(pauseCard.modelData.target_id)+")" : "")+" · "+planner.scopeText(pauseCard.modelData.scope)+" · then "+planner.choiceLabel(planner.resumeChoices, pauseCard.modelData.resume).toLowerCase(); Layout.fillWidth: true }
                                            Action { text: "Remove Pause"; destructive: true; onClicked: planner.mutate(function(r) { r.suspensions=r.suspensions.filter(function(p) { return p.id!==pauseCard.modelData.id }) }) }
                                        }
                                    }
                                }
                                Caption { text: "Rules holds single-date overrides, whole-channel layers, custom scopes and exact pause targets."; Layout.fillWidth: true }
                            }
                        }
                        ScrollView {
                            clip: true
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 12
                                Heading { text: "Forecast" }
                                Caption { text: (planner.calculating ? "Calculating…" : (planner.forecast.confidence || "Waiting"))+" · calculated through "+String(planner.forecast.calculated_through || "—")+" · live TV is unchanged until you apply"; Layout.fillWidth: true }
                                Repeater {
                                    model: planner.forecast.tracks || []
                                    delegate: Card {
                                        id: trackForecast
                                        required property var modelData
                                        color: planner.panelRaised
                                        Layout.fillWidth: true; implicitHeight: trackStats.implicitHeight+24
                                        ColumnLayout {
                                            id: trackStats; anchors.fill: parent; anchors.margins: 12
                                            Heading { text: trackForecast.modelData.name }
                                            Caption { text: planner.count(trackForecast.modelData.count, "video")+" · "+trackForecast.modelData.actual_hours.toFixed(1)+" hours of media · "+trackForecast.modelData.occupied_hours.toFixed(1)+" hours of airtime"; Layout.fillWidth: true }
                                            Caption { text: "First airing: "+planner.stamp(trackForecast.modelData.first_airing); Layout.fillWidth: true }
                                            Caption { text: "First pass ends: "+planner.stamp(trackForecast.modelData.last_airing); Layout.fillWidth: true }
                                            Caption { text: trackForecast.modelData.elapsed_days!==null ? "Takes "+Number(trackForecast.modelData.elapsed_days).toFixed(1)+" calendar days" : "Calendar span not reached"; Layout.fillWidth: true }
                                            Caption { text: "Afterwards: "+planner.choiceLabel(planner.afterPassChoices, trackForecast.modelData.post_completion).toLowerCase()+" · "+(trackForecast.modelData.required ? "required to finish the cycle" : "optional"); Layout.fillWidth: true }
                                        }
                                    }
                                }
                                Repeater {
                                    model: planner.forecast.issues || []
                                    delegate: Caption { required property var modelData; text: modelData.message; color: modelData.blocking ? planner.danger : planner.warning; Layout.fillWidth: true }
                                }
                            }
                        }
                        ScrollView {
                            clip: true
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width; spacing: 12
                                Heading { text: "Reusable time-block profiles" }
                                Caption { text: "Profiles save named time slots and their rules. Which media fills each slot stays with each channel."; Layout.fillWidth: true }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Field { id: profileName; placeholderText: "Morning programming"; Layout.fillWidth: true }
                                    Action { text: "Save Current Windows"; enabled: planner.rules.windows.length>0 && profileName.text.length>0; onClicked: planner.task("save_profile",{profile:Draft.profile(planner.rules,profileName.text)}) }
                                    Action { text: "Import"; onClicked: planner.task("import_profile",{}) }
                                }
                                Repeater {
                                    model: planner.profiles
                                    delegate: Card {
                                        id: profileCard
                                        required property var modelData
                                        color: planner.panelRaised
                                        Layout.fillWidth: true; implicitHeight: profileBody.implicitHeight+24
                                        ColumnLayout {
                                            id: profileBody; anchors.fill: parent; anchors.margins: 12; spacing: 7
                                            Heading { text: profileCard.modelData.name+"  ·  version "+profileCard.modelData.version }
                                            Repeater {
                                                model: profileCard.modelData.slots
                                                delegate: RowLayout {
                                                    id: slotRow
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    Caption { text: (slotRow.modelData.name || slotRow.modelData.id)+" · "+slotRow.modelData.start+" – "+slotRow.modelData.end; Layout.fillWidth: true }
                                                    Choice {
                                                        Layout.preferredWidth: 200
                                                        choices: planner.trackChoices("")
                                                        value: planner.assignments[profileCard.modelData.id+":"+slotRow.modelData.id] || (choices.length ? choices[0].value : "")
                                                        onChosen: function(value) { var next=Object.assign({},planner.assignments); next[profileCard.modelData.id+":"+slotRow.modelData.id]=value; planner.assignments=next }
                                                    }
                                                }
                                            }
                                            Flow {
                                                Layout.fillWidth: true; spacing: 6
                                                Action { text: "Preview in Draft"; enabled: planner.rules.tracks.length>0; onClicked: { var a={}; profileCard.modelData.slots.forEach(function(s) { a[s.id]=planner.assignments[profileCard.modelData.id+":"+s.id] || planner.rules.tracks[0].id }); planner.task("bind_profile",{planner:planner.rules,profile:profileCard.modelData,assignments:a}) } }
                                                Action { text: "Duplicate"; onClicked: planner.task("duplicate_profile",{profile:profileCard.modelData}) }
                                                Action { text: "Save Next Version"; enabled: planner.rules.windows.length>0; onClicked: { var p=Draft.profile(planner.rules,profileCard.modelData.name); p.id=profileCard.modelData.id; planner.task("save_profile",{profile:p}) } }
                                                Action { text: "Export"; onClicked: planner.task("export_profile",{profile:profileCard.modelData}) }
                                            }
                                        }
                                    }
                                }
                                Repeater {
                                    model: planner.rules.profile_bindings || []
                                    delegate: Caption { required property var modelData; text: "Pinned profile "+modelData.id+" (version "+modelData.version+") · "+Object.keys(modelData.assignments).length+" slots assigned"; Layout.fillWidth: true }
                                }
                            }
                        }
                        Item {
                            ColumnLayout {
                                anchors.fill: parent; spacing: 10
                                Heading { text: "Original airings & era recreation" }
                                Caption { text: "Use your own airing records and owned media. Era recreation maps a reference year's weekdays and dates onto real broadcast days. It is approximate, and the computer's clock is never changed."; Layout.fillWidth: true }
                                Flow {
                                    Layout.fillWidth: true; spacing: 8
                                    Choice { width: 200; choices: planner.historyChoices; value: planner.rules.historical_mode || "none"; onChosen: function(value) { planner.mutate(function(r) { r.historical_mode=value }) } }
                                    Field { width: 130; placeholderText: "Reference year"; inputMethodHints: Qt.ImhDigitsOnly; validator: IntValidator { bottom: 1900; top: 2200 }
                                           text: planner.rules.reference_year ? String(planner.rules.reference_year) : ""; onEditingFinished: planner.mutate(function(r) { r.reference_year=text ? Number(text) : null }) }
                                    PlannerDatePicker { optional: true; placeholder: "Replay start date"; date: planner.rules.replay_start || ""; onPicked: function(value) { planner.mutate(function(r) { r.replay_start=value || null }) } }
                                }
                                Action { text: "Import Your CSV / JSON Airings"; onClicked: planner.task("import_airings",{planner:planner.rules}) }
                                Caption { text: "Columns: id, asset_id, starts_at, ends_at, track_id, source, accuracy, substitute_id, rerun. Times need a UTC offset. Missing media needs an explicit substitute."; Layout.fillWidth: true }
                                ListView {
                                    id: historicalList
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8
                                    model: planner.rules.historical_airings || []
                                    delegate: Rectangle {
                                        required property var modelData
                                        id: airing
                                        radius: 8; color: planner.panelRaised; border.color: planner.line
                                        width: historicalList.width; height: airingText.implicitHeight+20
                                        ColumnLayout {
                                            id: airingText; anchors.fill: parent; anchors.margins: 10
                                            Caption { text: planner.stamp(airing.modelData.starts_at)+" · "+planner.title(airing.modelData.substitute_id || airing.modelData.asset_id); color: planner.ink; Layout.fillWidth: true }
                                            Caption { text: (airing.modelData.source || "No source recorded")+" · "+(airing.modelData.accuracy || "exact"); Layout.fillWidth: true }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Card {
                id: tracksCard
                Layout.preferredWidth: Math.max(280,planner.width*.25); Layout.minimumWidth: 0; Layout.fillHeight: true
                ScrollView {
                    anchors.fill: parent; anchors.margins: 14; clip: true
                    contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width; spacing: 10
                    Heading { text: "Tracks" }
                    Choice {
                        objectName: "plannerTrackPick"
                        Layout.fillWidth: true
                        enabled: planner.rules.tracks.length > 0
                        choices: planner.trackChoices("")
                        value: planner.selectedTrack
                        displayText: planner.rules.tracks.length ? currentText : "Add a collection as a track"
                        onChosen: function(value) { planner.selectedTrack=value }
                    }
                    Caption { text: planner.count((planner.group.asset_ids || []).length, "video")+" · "+(planner.track.mode==="rerun" ? "rerun order" : "first-run order"); visible: !!planner.selectedTrack }
                    Caption { text: "After the first pass" }
                    Choice { Layout.fillWidth: true; choices: planner.afterPassChoices; value: planner.track.post_completion || "filler"; enabled: !!planner.selectedTrack; onChosen: function(value) { planner.setTrack("post_completion",value) } }
                    Choice { visible: planner.track.post_completion==="successor"; Layout.fillWidth: true; choices: planner.trackChoices(planner.selectedTrack); value: planner.track.successor_id || ""; onChosen: function(value) { planner.setTrack("successor_id",value) } }
                    ChannelCheckBox { text: "Required to finish the cycle"; font.pixelSize: 12; checked: planner.track.required !== false; enabled: !!planner.selectedTrack && planner.track.mode!=="rerun"; onClicked: planner.setTrack("required",checked) }
                    RowLayout {
                        Layout.fillWidth: true
                        Caption { text: "Order"; Layout.preferredWidth: 64 }
                        Choice { Layout.fillWidth: true; choices: planner.orderChoices; value: planner.track.order || "sequential"; enabled: !!planner.selectedTrack; onChosen: function(value) { planner.setTrack("order",value) } }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Caption { text: "Start at #"; Layout.preferredWidth: 64 }
                        ChannelSpinBox { from: 1; to: Math.max(1,(planner.group.asset_ids || []).length); value: (planner.track.start_index || 0)+1; editable: true; enabled: !!planner.selectedTrack; Layout.fillWidth: true; onValueModified: planner.setTrack("start_index",value-1) }
                    }
                    RowLayout {
                        Action { text: "+ Airing Window"; enabled: !!planner.selectedTrack; onClicked: planner.mutate(function(r) { Draft.addWindow(r,planner.selectedTrack) }) }
                        Action { text: "Remove Track"; destructive: true; enabled: !!planner.selectedTrack; onClicked: planner.mutate(function(r) { Draft.removeTrack(r,planner.selectedTrack); planner.selectedTrack=r.tracks.length ? r.tracks[0].id : "" }) }
                    }
                    ListView {
                        id: windowList
                        Layout.fillWidth: true; Layout.preferredHeight: Math.max(190,Math.min(380,contentHeight)); clip: true; spacing: 10
                        model: planner.windows
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            id: windowCard
                            required property var modelData
                            radius: 8
                            width: windowList.width; height: windowFields.implicitHeight+18; color: planner.panelRaised; border.color: planner.line
                            ColumnLayout {
                                id: windowFields; anchors.fill: parent; anchors.margins: 9; spacing: 6
                                RowLayout {
                                    TimeField { text: windowCard.modelData.start; Layout.fillWidth: true; onEditingFinished: if (acceptableInput) planner.setWindow(windowCard.modelData.id,"start",text) }
                                    Caption { text: "to" }
                                    TimeField { text: windowCard.modelData.end; Layout.fillWidth: true; onEditingFinished: if (acceptableInput) planner.setWindow(windowCard.modelData.id,"end",text) }
                                }
                                RowLayout {
                                    Caption { text: "Slot length" }
                                    ChannelSpinBox { from: 1; to: 480; value: Number(windowCard.modelData.bracket_minutes || 60); editable: true; onValueModified: planner.setWindow(windowCard.modelData.id,"bracket_minutes",value); Layout.fillWidth: true }
                                    Caption { text: "min" }
                                }
                                Choice { Layout.fillWidth: true; choices: planner.fitChoices; value: windowCard.modelData.fit || "strict"; onChosen: function(value) { planner.mutate(function(r) { r.windows.forEach(function(w) { if(w.id===windowCard.modelData.id) { w.fit=value; if(value==="overrun" && !w.max_overrun_minutes) w.max_overrun_minutes=15 } }) }) } }
                                RowLayout {
                                    visible: windowCard.modelData.fit==="overrun"
                                    Caption { text: "Run over by up to" }
                                    ChannelSpinBox { from: 1; to: 480; value: Number(windowCard.modelData.max_overrun_minutes || 15); editable: true; Layout.fillWidth: true; onValueModified: planner.setWindow(windowCard.modelData.id,"max_overrun_minutes",value) }
                                    Caption { text: "min" }
                                }
                                Flow {
                                    Layout.fillWidth: true; spacing: 3
                                    Repeater {
                                        model: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
                                        delegate: Action {
                                            id: dayToggle
                                            required property int index
                                            required property string modelData
                                            text: modelData; implicitWidth: 44; implicitHeight: 30; font.pixelSize: 11
                                            leftPadding: 4; rightPadding: 4
                                            checkable: true
                                            checked: !windowCard.modelData.scope || !windowCard.modelData.scope.weekdays || windowCard.modelData.scope.weekdays.indexOf(index)>=0
                                            onClicked: { var scope=Draft.copy(windowCard.modelData.scope || {weekdays:[0,1,2,3,4,5,6]}); var days=scope.weekdays || [0,1,2,3,4,5,6]; scope.weekdays=days.indexOf(index)>=0 ? days.filter(function(d) { return d!==dayToggle.index }) : days.concat([index]).sort(); planner.setWindow(windowCard.modelData.id,"scope",scope) }
                                        }
                                    }
                                }
                                Action { text: "Delete Airing Window"; destructive: true; Layout.fillWidth: true; onClicked: planner.mutate(function(r) { r.windows=r.windows.filter(function(w) { return w.id!==windowCard.modelData.id }) }) }
                            }
                        }
                    }
                    Caption { text: "Finishing a first pass stays earned while the track loops. Reruns keep their own place."; Layout.fillWidth: true }
                    ChannelCheckBox { text: "Fill gaps with the filler pool"; font.pixelSize: 12; checked: planner.rules.gap_filler || false; onClicked: planner.mutate(function(r) { r.gap_filler=checked }) }
                }
                }
            }
        }
        Card {
            id: milestonesCard
            Layout.fillWidth: true; implicitHeight: milestoneRow.implicitHeight+(planner.embedded ? 18 : 28)
            RowLayout {
                id: milestoneRow
                anchors.fill: parent; anchors.margins: planner.embedded ? 9 : 14; spacing: 20
                Repeater {
                    model: [{label:"MEDIA ENDS",value:planner.forecast.media_ends},{label:"CYCLE READY",value:planner.forecast.cycle_ready},{label:planner.rules.cycle.action==="once" ? "CHANNEL CLOSES" : "CHANNEL RESTARTS",value:planner.forecast.actual_restart}]
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Caption { text: parent.modelData.label; font.letterSpacing: 1 }
                        Label { text: planner.calculating ? "…" : planner.milestone(parent.modelData.value); color: planner.ink; font.pixelSize: planner.embedded ? 16 : 19; font.weight: Font.Bold }
                        Caption { text: planner.calculating ? "Calculating" : parent.modelData.value ? planner.clock(parent.modelData.value)+" · "+planner.anchorLocal.zoneLabel : "Adjust the rules or check the forecast" }
                    }
                }
                ColumnLayout {
                    Caption { text: "FORECAST" }
                    Label {
                        objectName: "plannerForecastState"
                        text: !planner.loaded ? "Loading…" : planner.calculating ? "Calculating…" : planner.forecast.confidence || "Waiting"
                        color: planner.calculating || !planner.loaded ? planner.muted : planner.forecast.confidence==="Blocked" ? planner.danger : planner.good
                        font.pixelSize: planner.embedded ? 16 : 18; font.weight: Font.Bold
                    }
                    Action { implicitHeight: planner.embedded ? 32 : 38; text: planner.worker.busy ? "Cancel" : "Recalculate"; onClicked: { if(planner.worker.busy) channelOS.cancelPlannerTask(); else planner.preview() } }
                }
            }
        }
        Caption {
            objectName: "plannerFeedback"
            // Embedded, Studio's footer shows planner feedback.
            visible: !planner.embedded
            Layout.fillWidth: true
            text: planner.feedback
            color: planner.feedbackError ? planner.danger : planner.muted
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }
    Loader {
        id: ownAdsLoader
        active: !planner.embedded
        sourceComponent: AdSettingsEditor {
            hostItem: planner
            channelNumber: Number(planner.editor.channel || 1)
            channelName: String(planner.editor.name || "Channel")
            mediaLibrary: planner.mediaRows
            sourceOptions: planner.editor.sourceOptions || []
            onSettingsApplied: planner.changed()
        }
    }
    PlannerDialog {
        id: discardDialog; title: "Leave this draft?"; width: 460
        ColumnLayout {
            anchors.fill: parent
            Label { text: "Your live channel is unchanged. Unapplied planner edits will be discarded."; color: planner.ink; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            DialogButtons {
                acceptText: "Discard"; rejectText: "Keep Editing"
                onRejected: discardDialog.close()
                onAccepted: { discardDialog.close(); planner.dirty=false; channelOS.cancelPlannerTask(); if(planner.hostWindow) planner.hostWindow.screen=planner.exitDestination }
            }
        }
    }
    PlannerDialog {
        id: rulesDialog; width: Math.min(920,planner.width-100); height: Math.min(720,planner.height-70); title: "All broadcast rules"
        ColumnLayout {
            anchors.fill: parent
            Caption { text: "Advanced editor for exact date ranges, nested ALL / ANY gates, filler pools, protected overrides and historical substitutions. The forecast validates every change before you apply the channel."; Layout.fillWidth: true }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; ChannelTextArea { id: rawRules; font.family: "monospace"; font.pixelSize: 12; selectByMouse: true; wrapMode: TextEdit.NoWrap } }
            DialogButtons {
                onRejected: rulesDialog.close()
                onAccepted: { try { planner.editor=Object.assign({},planner.editor,{planner:JSON.parse(rawRules.text)}); planner.changed(); rulesDialog.close() } catch(error) { planner.feedback=String(error); planner.feedbackError=true } }
            }
        }
    }
    PlannerDialog {
        id: cycleDialog; width: 640; height: Math.min(700,planner.height-70); title: "Channel cycle"
        ColumnLayout {
            anchors.fill: parent
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                contentWidth: availableWidth
                GridLayout {
                    width: parent.width; columns: 2; columnSpacing: 12; rowSpacing: 10
                    Caption { Layout.columnSpan: 2; text: "A cycle ends only after its required content, its date gate and a safe moment. The program on air and committed ads always finish."; Layout.fillWidth: true }
                    Caption { text: "When the cycle ends" }
                    Choice { Layout.fillWidth: true; choices: planner.cycleActionChoices; value: planner.rules.cycle.action || "restart"; onChosen: function(value) { planner.setCycle("action",value) } }
                    Caption { text: "Content needed" }
                    Choice { Layout.fillWidth: true; choices: planner.completionChoices; value: planner.rules.cycle.completion || "all"; onChosen: function(value) { planner.setCycle("completion",value) } }
                    Item { width: 1; visible: String(planner.rules.cycle.completion || "").indexOf("selected_")===0 }
                    ColumnLayout {
                        visible: String(planner.rules.cycle.completion || "").indexOf("selected_")===0
                        Repeater {
                            model: planner.rules.tracks.filter(function(t) { return t.mode!=="rerun" })
                            delegate: ChannelCheckBox {
                                required property var modelData
                                text: planner.trackName(modelData.id)
                                checked: (planner.rules.cycle.required_tracks || []).indexOf(modelData.id)>=0
                                onClicked: { var id=modelData.id; var on=checked; planner.mutate(function(r) { var a=r.cycle.required_tracks || []; r.cycle.required_tracks=on ? a.concat([id]) : a.filter(function(t) { return t!==id }) }) }
                            }
                        }
                    }
                    Caption { Layout.columnSpan: 2; visible: planner.rules.cycle.completion==="custom"; text: "Edit the nested ALL / ANY gate in Rules. Every leaf names a first-run track."; Layout.fillWidth: true }
                    Caption { text: "Not before" }
                    PlannerDatePicker { optional: true; placeholder: "Any date"; date: String(planner.rules.cycle.not_before || "").slice(0,10); onPicked: function(value) { if (!value) { planner.setCycle("not_before",null); return } var iso = channelOS && channelOS.plannerLocalToIso ? channelOS.plannerLocalToIso(value,"00:00",planner.rules.timezone || "UTC") : ({ok:true,iso:value+"T00:00:00+00:00"}); if (iso.ok) planner.setCycle("not_before",iso.iso) } }
                    Caption { text: "Combine with the date" }
                    Choice { Layout.fillWidth: true; choices: planner.gateChoices; value: planner.rules.cycle.gate_mode || "and"; onChosen: function(value) { planner.setCycle("gate_mode",value) } }
                    ChannelCheckBox { Layout.columnSpan: 2; text: "Allow a date-only or OR gate to restart unfinished media"; checked: planner.rules.cycle.allow_unfinished || false; onClicked: planner.setCycle("allow_unfinished",checked) }
                    Caption { text: "Restart at" }
                    Choice { Layout.fillWidth: true; choices: planner.boundaryChoices; value: planner.rules.cycle.boundary || "safe"; onChosen: function(value) { planner.setCycle("boundary",value) } }
                    Caption { text: "Week starts on"; visible: planner.rules.cycle.boundary==="week" }
                    Choice { visible: planner.rules.cycle.boundary==="week"; Layout.fillWidth: true; choices: planner.weekdayChoices; value: Number(planner.rules.cycle.boundary_weekday || 0); onChosen: function(value) { planner.setCycle("boundary_weekday",value) } }
                    Caption { text: "At" }
                    TimeField { text: planner.rules.cycle.boundary_time || "00:00"; onEditingFinished: if (acceptableInput) planner.setCycle("boundary_time",text) }
                    Caption { visible: planner.rules.cycle.boundary==="period"; text: "Period length (days)" }
                    ChannelSpinBox { visible: planner.rules.cycle.boundary==="period"; from: 1; to: 3660; editable: true; value: Number(planner.rules.cycle.period_days || 7); onValueModified: planner.setCycle("period_days",value) }
                    Caption { visible: planner.rules.cycle.action==="once"; text: "After airing once" }
                    Choice { visible: planner.rules.cycle.action==="once"; Layout.fillWidth: true; choices: planner.afterOnceChoices; value: planner.rules.cycle.after_once || "slate"; onChosen: function(value) { planner.setCycle("after_once",value) } }
                    Caption { text: "Edits take effect" }
                    Choice { Layout.fillWidth: true; choices: planner.editEffectChoices; value: planner.rules.edit_effect || "next_cycle"; onChosen: function(value) { planner.mutate(function(r) { r.edit_effect=value }) } }
                    Caption { Layout.columnSpan: 2; text: "From the next cycle keeps this cycle as planned. At the next safe moment keeps earned progress and starts after the program on air and committed ads. History of closed cycles is kept."; Layout.fillWidth: true }
                    Action { Layout.columnSpan: 2; text: "Release Ready Cycle Now"; visible: planner.rules.cycle.boundary==="manual"; enabled: planner.editingNumber>0 && !planner.dirty && !planner.applying; onClicked: { var result=channelOS.startChannelMutation("release_cycle",planner.editingNumber,{}); if(result.ok) planner.applying=true; else { planner.feedback=result.message; planner.feedbackError=true } } }
                }
            }
            DialogButtons { showAccept: false; rejectText: "Close"; onRejected: cycleDialog.close() }
        }
    }
    PlannerDialog {
        id: sourcesDialog; width: Math.min(640,planner.width-80); height: Math.min(520,planner.height-80); title: "Planner media sources"
        ColumnLayout {
            anchors.fill: parent
            Caption { text: "Choose the indexed sources this channel may use. Adding a collection includes its source automatically."; Layout.fillWidth: true }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                ColumnLayout {
                    Repeater {
                        model: planner.editor.sourceOptions || []
                        delegate: ChannelCheckBox {
                            required property string modelData
                            text: modelData
                            checked: (planner.editor.sources || []).indexOf(modelData)>=0
                            onClicked: { var source=modelData; var values=planner.editor.sources || []; planner.setEditor("sources",checked ? values.concat([source]) : values.filter(function(s) { return s!==source })) }
                        }
                    }
                }
            }
            DialogButtons { showAccept: false; rejectText: "Close"; onRejected: sourcesDialog.close() }
        }
    }
    PlannerDialog {
        id: pauseDialog; width: 480; title: "Pause programming"
        ColumnLayout {
            anchors.fill: parent
            spacing: 8
            Field { id: pauseName; text: "Holiday pause"; Layout.fillWidth: true }
            Choice { id: pauseTarget; Layout.fillWidth: true; choices: planner.pauseTargetChoices; value: "track" }
            Caption { text: "From and through (leave open for no limit)" }
            RowLayout {
                PlannerDatePicker { id: pauseFrom; optional: true; placeholder: "From any date"; Layout.fillWidth: true }
                PlannerDatePicker { id: pauseUntil; optional: true; placeholder: "Through any date"; Layout.fillWidth: true }
            }
            Caption { text: "Afterwards" }
            Choice { id: pauseResume; Layout.fillWidth: true; choices: planner.resumeChoices; value: "continue" }
            Caption { text: "Continue keeps the next episode waiting. A pause never counts toward finishing a track or a cycle."; Layout.fillWidth: true }
            DialogButtons {
                onRejected: pauseDialog.close()
                onAccepted: {
                    var target=pauseTarget.currentValue
                    var targetId=target==="track" ? planner.selectedTrack : null
                    planner.mutate(function(r) { r.suspensions.push({id:Draft.uid("pause"),name:pauseName.text,target:target,target_id:targetId,scope:{from_date:pauseFrom.date || null,until_date:pauseUntil.date || null},resume:pauseResume.currentValue}) })
                    pauseDialog.close()
                }
            }
        }
    }
    PlannerDialog {
        id: layerDialog; width: 480; title: "Seasonal layer"
        ColumnLayout {
            anchors.fill: parent
            spacing: 8
            Field { id: layerName; placeholderText: "Layer name"; Layout.fillWidth: true }
            Caption { text: "Months" }
            Flow {
                id: layerMonthFlow
                Layout.fillWidth: true; spacing: 3
                Repeater {
                    model: ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                    delegate: Action {
                        required property int index
                        required property string modelData
                        text: modelData; implicitWidth: 52; implicitHeight: 30; font.pixelSize: 11; checkable: true
                        leftPadding: 4; rightPadding: 4
                        checked: layerMonths.text.split(",").map(Number).indexOf(index+1)>=0
                        onClicked: { var months=layerMonths.text ? layerMonths.text.split(",").map(Number) : []; months = months.indexOf(index+1)>=0 ? months.filter(function(m) { return m!==index+1 }) : months.concat([index+1]).sort(function(a,b) { return a-b }); layerMonths.text=months.join(",") }
                    }
                }
            }
            Field { id: layerMonths; visible: false }
            Caption { text: "Optional date range" }
            RowLayout {
                PlannerDatePicker { id: layerFrom; optional: true; placeholder: "From any date"; Layout.fillWidth: true }
                PlannerDatePicker { id: layerUntil; optional: true; placeholder: "Through any date"; Layout.fillWidth: true }
            }
            RowLayout {
                Caption { text: "Priority" }
                ChannelSpinBox { id: layerPriority; from: 1; to: 1000; value: 100; editable: true }
            }
            ChannelCheckBox { id: wholeLayer; text: "Replace the whole channel on matching dates" }
            DialogButtons {
                onRejected: layerDialog.close()
                onAccepted: { planner.mutate(function(r) { r.layers.push({id:Draft.uid("layer"),name:layerName.text,scope:{months:layerMonths.text ? layerMonths.text.split(",").map(Number) : [],from_date:layerFrom.date || null,until_date:layerUntil.date || null},priority:layerPriority.value,replace_scope:wholeLayer.checked ? "channel" : "overlap"}) }); layerDialog.close() }
            }
        }
    }
}
