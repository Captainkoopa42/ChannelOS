pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "PlannerDraft.js" as Draft

Item {
    id: planner
    anchors.fill: parent
    property var hostWindow: Window.window
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
    readonly property color bg: "#07101e"
    readonly property color panel: "#102036"
    readonly property color line: "#2b435e"
    readonly property color muted: "#9eb2cc"
    readonly property color ink: "#ecf4ff"
    readonly property color accent: "#82b9f5"
    readonly property var track: rules.tracks.filter(function(t) { return t.id === selectedTrack })[0] || ({})
    readonly property var group: rules.groups.filter(function(g) { return g.id === track.group_id })[0] || ({name:"Select a track",asset_ids:[]})
    readonly property var windows: rules.windows.filter(function(w) { return w.track_id === selectedTrack })
    readonly property bool previewCurrent: Boolean(forecast.ok) && Number(forecast.token) === serial
    readonly property bool canApply: loaded && dirty && previewCurrent && forecast.confidence !== "Blocked" && !worker.busy && !applying && String(editor.name || "").trim().length > 0

    component Caption: Label { color: planner.muted; font.pixelSize: 11; wrapMode: Text.WordWrap }
    component Heading: Label { color: planner.ink; font.pixelSize: 16; font.weight: Font.DemiBold }
    component Action: Button {
        id: action
        implicitHeight: 34
        font.pixelSize: 12
        contentItem: Text { text: action.text; color: action.enabled ? planner.ink : "#5d7088"; font: action.font; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight }
        background: Rectangle { radius: 6; color: action.highlighted ? "#285b90" : action.down ? "#2a496b" : action.hovered ? "#213b57" : "#172b42"; border.color: action.activeFocus ? "#9bcbff" : planner.line }
    }
    component Field: TextField { color: planner.ink; font.pixelSize: 12; selectByMouse: true; implicitHeight: 34; background: Rectangle { radius: 5; color: "#0a1729"; border.color: parent.activeFocus ? planner.accent : planner.line } }
    component Pick: ComboBox {
        id: pick
        font.pixelSize: 12; implicitHeight: 34
        palette.text: planner.ink
        palette.buttonText: planner.ink
        palette.base: "#10243b"
        palette.window: "#10243b"
        contentItem: Text { text: pick.displayText; color: planner.ink; font: pick.font; verticalAlignment: Text.AlignVCenter; leftPadding: 8; rightPadding: 22; elide: Text.ElideRight }
        background: Rectangle { radius: 5; color: "#0a1729"; border.color: pick.activeFocus ? planner.accent : planner.line }
    }
    component Card: Rectangle { color: planner.panel; border.color: planner.line; radius: 10 }

    function task(action, payload) {
        payload.token=serial
        channelOS.plannerTask(action,JSON.stringify(payload))
    }
    function mutate(callback) {
        var next=Draft.copy(rules)
        callback(next)
        editor=Object.assign({},editor,{planner:next})
        changed()
    }
    function changed() {
        serial++
        dirty=true
        pendingPreview=true
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
    function addTrack(bin,rerun,at) {
        if((editor.sources || []).indexOf(bin.source)<0)
            editor=Object.assign({},editor,{sources:(editor.sources || []).concat([bin.source])})
        mutate(function(r) { selectedTrack=Draft.addTrack(r,bin,rerun,at) })
    }
    function preview() {
        if(!loaded) return
        var draft=Object.assign({},editor,adSettings.editorObject())
        draft.name=String(draft.name || "Untitled planner")
        draft.mode="planner"
        pendingPreview=false
        task("preview",{editor:draft,view_start:selectedTab===2 ? viewDate.slice(0,7)+"-01" : viewDate,view_days:selectedTab===0 ? 1 : selectedTab===2 ? 31 : 7})
    }
    function loadDraft() {
        if (!channelOS || typeof channelOS.plannerTask !== "function") return
        if (!hostWindow || hostWindow.screen!=="planner") return
        var number=Number(hostWindow.plannerChannelNumber || 0)
        if(loadingDraft && editingNumber===number) return
        loadingDraft=true
        loaded=false
        feedback="Loading indexed media…"
        editingNumber=number
        task("load",{number:editingNumber})
    }
    function title(asset) { return asset && media[asset] ? media[asset].title : asset ? "Unavailable media" : "Off air" }
    function trackName(id) { var t=rules.tracks.filter(function(t) { return t.id===id })[0]; var g=t ? rules.groups.filter(function(g) { return g.id===t.group_id })[0] : null; return g ? g.name : id }
    function stamp(value) { return value ? String(value).replace("T"," ").replace(/\+00:00$/, " UTC") : "Waiting for rules" }
    function milestone(value) { return value ? String(value).slice(0,10) : "Unresolved" }
    function rows() {
        var list=forecast.segments || []
        if(selectedTab===0) list=list.filter(function(s) { return s.local_day===viewDate })
        return list
    }
    function requestExit(destination) {
        exitDestination=String(destination || "broadcaster")
        back()
    }
    function back() {
        if(adSettings.dialogOpen) { adSettings.cancelActive(); return }
        if(cycleDialog.visible) { cycleDialog.close(); return }
        if(sourcesDialog.visible) { sourcesDialog.close(); return }
        if(rulesDialog.visible) { rulesDialog.close(); return }
        if(pauseDialog.visible) { pauseDialog.close(); return }
        if(layerDialog.visible) { layerDialog.close(); return }
        if(discardDialog.visible) { discardDialog.close(); return }
        if(dirty) discardDialog.open()
        else { channelOS.cancelPlannerTask(); if(hostWindow) hostWindow.screen=exitDestination }
    }
    function handleControllerIntent(intent) {
        if(intent==="BACK") { back(); return true }
        return false
    }
    Keys.onEscapePressed: back()
    function apply() {
        if(!canApply) return
        editor=Object.assign({},editor,adSettings.editorObject(),{mode:"planner"})
        var result=channelOS.startChannelMutation(editingNumber ? "update" : "create",editingNumber,editor)
        if(result.ok) { applying=true; feedback="Preparing and validating channel…" }
        else { feedback=result.message; feedbackError=true }
    }
    Timer { id: previewTimer; interval: 400; onTriggered: planner.preview() }
    Connections {
        target: channelOS
        ignoreUnknownSignals: true
        function onPlannerResult(action, raw) {
            var result=JSON.parse(raw)
            if(action==="load") planner.loadingDraft=false
            if(!result.ok) { planner.feedback=result.message; planner.feedbackError=true; if(action==="preview") planner.forecast=result; return }
            planner.feedbackError=false
            if(action==="load") {
                planner.editor=result.editor
                planner.mediaBin=result.bin
                planner.media=result.media
                planner.mediaRows=result.mediaRows || []
                planner.profiles=result.profiles
                planner.selectedTrack=planner.rules.tracks.length ? planner.rules.tracks[0].id : ""
                planner.viewDate=String(planner.rules.start_at).slice(0,10)
                adSettings.load(result.editor)
                planner.loaded=true
                planner.dirty=false
                planner.serial++
                planner.feedback=result.message
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
                planner.feedback=action==="bind_profile" ? "Pinned profile preview applied to this draft. Review the forecast, then Apply channel." : result.imported+" user-supplied original airings imported into the draft."
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
            if(result.ok) { planner.dirty=false; planner.editingNumber=Number(planner.editor.channel); if(planner.hostWindow) planner.hostWindow.plannerChannelNumber=planner.editingNumber }
        }
    }
    onHostWindowChanged: if(hostWindow && hostWindow.screen==="planner") loadDraft()
    Connections {
        target: planner.hostWindow || null
        function onScreenChanged() {
            if(planner.hostWindow.screen==="planner") planner.loadDraft()
            else { planner.loadingDraft=false; channelOS.cancelPlannerTask() }
        }
    }

    Rectangle { anchors.fill: parent; color: planner.bg }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: 2
                Caption { text: "CHANNELOS  /  BROADCASTER"; font.letterSpacing: 2 }
                Label { text: "Broadcast Planner"; color: planner.ink; font.pixelSize: 26; font.weight: Font.Bold }
            }
            Item { Layout.fillWidth: true }
            Caption { text: planner.dirty ? "DRAFT · UNSAVED CHANGES" : "DRAFT · LIVE TV UNCHANGED"; color: planner.dirty ? "#f5c17c" : planner.muted }
            BusyIndicator { running: planner.worker.busy; visible: running; implicitWidth: 28; implicitHeight: 28 }
            Action { text: "Back"; onClicked: planner.requestExit("broadcaster") }
            Action { text: "Rules"; onClicked: { rawRules.text=JSON.stringify(planner.rules,null,2); rulesDialog.open() } }
            Action { id: applyAction; objectName:"plannerApply"; text: planner.applying ? "Applying…" : "Apply channel"; highlighted: true; enabled: planner.canApply; onClicked: planner.apply() }
        }
        GridLayout {
            Layout.fillWidth: true; columns: planner.width<1350 ? 2 : 3; columnSpacing: 14; rowSpacing: 8
            RowLayout {
                Layout.fillWidth: true
                Caption { text: "CHANNEL" }
                Field { text: String(planner.editor.channel || ""); Layout.preferredWidth: 65; enabled: !planner.editingNumber; onEditingFinished: planner.setEditor("channel",text) }
                Field { id: channelNameField; objectName:"plannerChannelName"; text: String(planner.editor.name || ""); placeholderText: "Name your channel"; Layout.fillWidth: true; Layout.preferredWidth: 180; Layout.minimumWidth: 130; onEditingFinished: planner.setEditor("name",text) }
            }
            RowLayout {
                Layout.fillWidth: true
                Caption { text: "FIRST SHOW ANCHOR" }
                Field { text: String(planner.rules.start_at || ""); Layout.preferredWidth: 215; Layout.minimumWidth: 195; placeholderText: "ISO timestamp with UTC offset"; onEditingFinished: planner.mutate(function(r) { r.start_at=text }) }
                Field { text: String(planner.rules.timezone || "UTC"); Layout.fillWidth: true; Layout.preferredWidth: 185; Layout.minimumWidth: 145; placeholderText: "America/Los_Angeles"; onEditingFinished: planner.mutate(function(r) { r.timezone=text }) }
            }
            RowLayout {
                Layout.columnSpan: planner.width<1350 ? 2 : 1; Layout.alignment: Qt.AlignRight
                Action { text: "Ad breaks"; onClicked: adSettings.openBasic() }
                Action { text: "Sources"; onClicked: sourcesDialog.open() }
                Action { text: "Channel cycle"; onClicked: cycleDialog.open() }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            Card {
                Layout.preferredWidth: Math.max(205,planner.width*.19)
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 10
                    Heading { text: "Smart Media Bin" }
                    Caption { text: "Indexed owned media · hold and drag a collection to a calendar hour, or add a track."; Layout.fillWidth: true }
                    Field { Layout.fillWidth: true; placeholderText: "Search collections…"; onTextChanged: planner.search=text }
                    ListView {
                        id: binList
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 9
                        model: planner.mediaBin.filter(function(g) { return g.name.toLowerCase().indexOf(planner.search.toLowerCase())>=0 })
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            id: binCard
                            required property var modelData
                            width: binList.width; height: binContent.implicitHeight+20; radius: 7
                            property var binGroup: modelData
                            color: "#182d46"; border.color: "#365475"
                            Drag.active: binDrag.drag.active
                            Drag.source: binCard
                            Drag.keys: ["planner-group"]
                            Drag.hotSpot.x: width/2
                            Drag.hotSpot.y: height/2
                            ColumnLayout {
                                id: binContent
                                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 5
                                Label { text: binCard.modelData.name; color: planner.ink; font.weight: Font.DemiBold; font.pixelSize: 13; elide: Text.ElideRight; Layout.fillWidth: true }
                                Caption { text: binCard.modelData.count+" items · "+(binCard.modelData.seconds/3600).toFixed(1)+" actual hours" }
                                Caption { text: binCard.modelData.missing ? binCard.modelData.missing+" unavailable / unprobed" : "Owned media · canonical asset IDs"; color: binCard.modelData.missing ? "#f5c17c" : planner.muted; Layout.fillWidth: true }
                                RowLayout {
                                    Action { text: "+ Track"; Layout.fillWidth: true; onClicked: planner.addTrack(binCard.modelData,false) }
                                    Action { text: "+ Rerun"; Layout.fillWidth: true; onClicked: planner.addTrack(binCard.modelData,true) }
                                }
                                Action { text: "+ Filler pool"; Layout.fillWidth: true; onClicked: { if((planner.editor.sources || []).indexOf(binCard.modelData.source)<0) planner.editor=Object.assign({},planner.editor,{sources:(planner.editor.sources || []).concat([binCard.modelData.source])}); planner.mutate(function(r) { r.filler_asset_ids=(r.filler_asset_ids || []).concat(binCard.modelData.asset_ids).filter(function(id,i,a) { return a.indexOf(id)===i }); r.gap_filler=true }) } }
                            }
                            MouseArea {
                                id: binDrag
                                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 50
                                drag.target: binCard; drag.axis: Drag.XAndYAxis
                                onReleased: { binCard.Drag.drop(); binCard.x=0; binCard.y=0; binList.forceLayout() }
                                onDoubleClicked: planner.addTrack(binCard.modelData,false)
                            }
                        }
                    }
                    Caption { text: planner.mediaBin.length ? "Actual duration and calendar finish are measured separately." : "No indexed media. Add and scan a source in Library first."; Layout.fillWidth: true }
                }
            }
            Card {
                id: scheduleCard
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 0
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 10
                    TabBar {
                        id: tabs
                        Layout.fillWidth: true
                        currentIndex: planner.selectedTab
                        onCurrentIndexChanged: { planner.selectedTab=currentIndex; if(planner.loaded) previewTimer.restart() }
                        TabButton { text: "Day"; font.pixelSize: 12 }
                        TabButton { text: "Week"; font.pixelSize: 12 }
                        TabButton { text: "Seasonal"; font.pixelSize: 12 }
                        TabButton { text: "Forecast"; font.pixelSize: 12 }
                        TabButton { text: "Profiles"; font.pixelSize: 12 }
                        TabButton { text: "Original airings"; font.pixelSize: 12 }
                    }
                    StackLayout {
                        currentIndex: planner.selectedTab
                        Layout.fillWidth: true; Layout.fillHeight: true
                        Item {
                            ColumnLayout {
                                anchors.fill: parent
                                RowLayout {
                                    Heading { text: "Day schedule" }
                                    Item { Layout.fillWidth: true }
                                    Action { text: "‹"; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate,-1); previewTimer.restart() } }
                                    Field { text: planner.viewDate; Layout.preferredWidth: 110; onEditingFinished: { planner.viewDate=text; previewTimer.restart() } }
                                    Action { text: "›"; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate,1); previewTimer.restart() } }
                                }
                                Caption { text: "Channel time zone: "+String(planner.rules.timezone || "UTC")+" · "+(planner.editor.calendarBlocks || []).length+" protected manual blocks"; Layout.fillWidth: true }
                                ListView {
                                    id: dayList
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 5
                                    model: 24
                                    ScrollBar.vertical: ScrollBar {}
                                    delegate: Rectangle {
                                        id: hourRow
                                        required property int index
                                        width: dayList.width; height: Math.max(42,hourShows.implicitHeight+12)
                                        radius: 5; color: drop.containsDrag ? "#254c70" : "#0c1a2d"
                                        RowLayout {
                                            anchors.fill: parent; anchors.margins: 6
                                            Caption { text: Draft.hour(hourRow.index); Layout.preferredWidth: 44 }
                                            ColumnLayout {
                                                id: hourShows
                                                Layout.fillWidth: true; spacing: 3
                                                Repeater {
                                                    model: planner.rows().filter(function(s) { return Number(String(s.display_start || "").slice(11,13))===hourRow.index })
                                                    delegate: Rectangle {
                                                        id: dayShow
                                                        required property var modelData
                                                        Layout.fillWidth: true; implicitHeight: showLabel.implicitHeight+12; radius: 5
                                                        color: modelData.kind==="offair" ? "#102033" : modelData.kind==="advertisement" ? "#58472b" : modelData.kind==="filler" ? "#26394c" : "#244b68"
                                                        Label { id: showLabel; anchors.fill: parent; anchors.margins: 6; text: String(dayShow.modelData.display_start).slice(11)+"  "+planner.title(dayShow.modelData.asset_id)+"  · "+dayShow.modelData.kind; color: planner.ink; font.pixelSize: 11; wrapMode: Text.WordWrap }
                                                    }
                                                }
                                                Caption { visible: hourShows.children.length<=2; text: "Drop a collection here to create a daily window"; opacity: .6; Layout.fillWidth: true }
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
                                Caption { text: "Windows sharing a track use one cursor. Era mode uses reference-year weekdays; Day shows the mapped actual dates."; Layout.fillWidth: true }
                                ListView {
                                    id: weekList
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8
                                    model: 7
                                    delegate: Card {
                                        id: weekdayCard
                                        required property int index
                                        width: weekList.width; height: weekContent.implicitHeight+20
                                        ColumnLayout {
                                            id: weekContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10
                                            Heading { text: ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][weekdayCard.index] }
                                            Repeater {
                                                model: planner.rules.windows.filter(function(w) { return !w.scope || !w.scope.weekdays || w.scope.weekdays.indexOf(weekdayCard.index)>=0 })
                                                delegate: Action {
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    text: modelData.start+" – "+modelData.end+"  · "+planner.trackName(modelData.track_id)+"  · "+(modelData.bracket_minutes || 60)+"m brackets"
                                                    onClicked: planner.selectedTrack=modelData.track_id
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        ScrollView {
                            clip: true
                            ColumnLayout {
                                width: parent.width; spacing: 14
                                Heading { text: "Seasonal rules & suspensions" }
                                RowLayout {
                                    Action { text: "‹ Month"; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate.slice(0,7)+"-01",-1); previewTimer.restart() } }
                                    Heading { text: planner.viewDate.slice(0,7); Layout.fillWidth: true }
                                    Action { text: "Month ›"; onClicked: { planner.viewDate=Draft.rangeDate(planner.viewDate.slice(0,7)+"-01",32).slice(0,7)+"-01"; previewTimer.restart() } }
                                }
                                GridLayout {
                                    columns: 7; Layout.fillWidth: true; rowSpacing: 4; columnSpacing: 4
                                    Repeater { model: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]; delegate: Caption { required property string modelData; text: modelData; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter } }
                                    Repeater {
                                        model: Draft.monthDays(planner.viewDate)
                                        delegate: Action {
                                            required property string modelData
                                            Layout.fillWidth: true; implicitHeight: 48; font.pixelSize: 11
                                            property var counts: (planner.forecast.calendar_days || {})[modelData] || ({})
                                            text: Number(modelData.slice(-2))+"\n"+(counts.programs ? counts.programs+" airings" : "—")
                                            opacity: modelData.slice(0,7)===planner.viewDate.slice(0,7) ? 1 : .4
                                            onClicked: { planner.viewDate=modelData; planner.selectedTab=0; previewTimer.restart() }
                                        }
                                    }
                                }
                                Caption { text: "Higher-priority layers replace only their overlapping time. A channel-wide override must be chosen explicitly."; Layout.fillWidth: true }
                                RowLayout {
                                    Action { text: "+ Seasonal layer"; onClicked: { layerName.text="Holiday schedule"; layerMonths.text="12"; layerDialog.open() } }
                                    Action { text: "+ Suspend selected track"; enabled: !!planner.selectedTrack; onClicked: pauseDialog.open() }
                                }
                                Repeater {
                                    model: planner.rules.layers || []
                                    delegate: Card {
                                        id: layerCard
                                        required property var modelData
                                        Layout.fillWidth: true; implicitHeight: layerText.implicitHeight+24
                                        ColumnLayout {
                                            id: layerText; anchors.fill: parent; anchors.margins: 12
                                            Heading { text: layerCard.modelData.name }
                                            Caption { text: "Priority "+layerCard.modelData.priority+" · "+layerCard.modelData.replace_scope+" · months "+((layerCard.modelData.scope || {}).months || []).join(", "); Layout.fillWidth: true }
                                            Action { text: "Assign selected track’s windows"; enabled: !!planner.selectedTrack; onClicked: planner.mutate(function(r) { r.windows.forEach(function(w) { if(w.track_id===planner.selectedTrack) w.layer_id=layerCard.modelData.id }) }) }
                                        }
                                    }
                                }
                                Repeater {
                                    model: planner.rules.suspensions || []
                                    delegate: Card {
                                        id: pauseCard
                                        required property var modelData
                                        Layout.fillWidth: true; implicitHeight: pauseText.implicitHeight+24
                                        ColumnLayout {
                                            id: pauseText; anchors.fill: parent; anchors.margins: 12
                                            Heading { text: pauseCard.modelData.name || "Suspension" }
                                            Caption { text: pauseCard.modelData.target+" / "+(pauseCard.modelData.target_id || "all")+" · "+JSON.stringify(pauseCard.modelData.scope)+" · resume: "+pauseCard.modelData.resume; Layout.fillWidth: true }
                                            Action { text: "Remove suspension"; onClicked: planner.mutate(function(r) { r.suspensions=r.suspensions.filter(function(p) { return p.id!==pauseCard.modelData.id }) }) }
                                        }
                                    }
                                }
                                Caption { text: "Use Rules for individual date overrides, full-channel layers, custom scopes, and exact suspension targets."; Layout.fillWidth: true }
                            }
                        }
                        ScrollView {
                            clip: true
                            ColumnLayout {
                                width: parent.width; spacing: 12
                                Heading { text: "Live forecast" }
                                Caption { text: "Detached calculation · "+(planner.forecast.confidence || "Waiting")+" · calculated through "+String(planner.forecast.calculated_through || "—"); Layout.fillWidth: true }
                                Repeater {
                                    model: planner.forecast.tracks || []
                                    delegate: Card {
                                        id: trackForecast
                                        required property var modelData
                                        Layout.fillWidth: true; implicitHeight: trackStats.implicitHeight+24
                                        ColumnLayout {
                                            id: trackStats; anchors.fill: parent; anchors.margins: 12
                                            Heading { text: trackForecast.modelData.name }
                                            Caption { text: trackForecast.modelData.count+" items · "+trackForecast.modelData.actual_hours.toFixed(1)+" actual hours · "+trackForecast.modelData.occupied_hours.toFixed(1)+" occupied hours"; Layout.fillWidth: true }
                                            Caption { text: "First: "+planner.stamp(trackForecast.modelData.first_airing); Layout.fillWidth: true }
                                            Caption { text: "First pass ends: "+planner.stamp(trackForecast.modelData.last_airing); Layout.fillWidth: true }
                                            Caption { text: trackForecast.modelData.elapsed_days!==null ? "Elapsed calendar span: "+Number(trackForecast.modelData.elapsed_days).toFixed(1)+" days" : "Calendar span unresolved"; Layout.fillWidth: true }
                                            Caption { text: "After completion: "+trackForecast.modelData.post_completion+" · "+(trackForecast.modelData.required ? "required by channel gate" : "independent / optional"); Layout.fillWidth: true }
                                        }
                                    }
                                }
                                Repeater {
                                    model: planner.forecast.issues || []
                                    delegate: Caption { required property var modelData; text: modelData.message; color: modelData.blocking ? "#ffb0b5" : "#f5ce95"; Layout.fillWidth: true }
                                }
                            }
                        }
                        ScrollView {
                            clip: true
                            ColumnLayout {
                                width: parent.width; spacing: 12
                                Heading { text: "Reusable time-block profiles" }
                                Caption { text: "Profiles save named time slots and policies. Media assignments and progression stay inside each channel."; Layout.fillWidth: true }
                                RowLayout {
                                    Field { id: profileName; placeholderText: "Morning programming"; Layout.fillWidth: true }
                                    Action { text: "Save current windows"; enabled: planner.rules.windows.length>0 && profileName.text.length>0; onClicked: planner.task("save_profile",{profile:Draft.profile(planner.rules,profileName.text)}) }
                                    Action { text: "Import"; onClicked: planner.task("import_profile",{}) }
                                }
                                Repeater {
                                    model: planner.profiles
                                    delegate: Card {
                                        id: profileCard
                                        required property var modelData
                                        Layout.fillWidth: true; implicitHeight: profileBody.implicitHeight+24
                                        ColumnLayout {
                                            id: profileBody; anchors.fill: parent; anchors.margins: 12; spacing: 7
                                            Heading { text: profileCard.modelData.name+"  · v"+profileCard.modelData.version }
                                            Repeater {
                                                model: profileCard.modelData.slots
                                                delegate: RowLayout {
                                                    id: slotRow
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    Caption { text: (slotRow.modelData.name || slotRow.modelData.id)+" · "+slotRow.modelData.start+"–"+slotRow.modelData.end; Layout.fillWidth: true }
                                                    Pick {
                                                        Layout.preferredWidth: 160
                                                        model: planner.rules.tracks.map(function(t) { return t.id })
                                                        onActivated: { var next=Object.assign({},planner.assignments); next[profileCard.modelData.id+":"+slotRow.modelData.id]=currentText; planner.assignments=next }
                                                        Component.onCompleted: if(count>0) { var next=Object.assign({},planner.assignments); next[profileCard.modelData.id+":"+slotRow.modelData.id]=currentText; planner.assignments=next }
                                                    }
                                                }
                                            }
                                            RowLayout {
                                                Action { text: "Preview / reapply to draft"; enabled: planner.rules.tracks.length>0; onClicked: { var a={}; profileCard.modelData.slots.forEach(function(s) { a[s.id]=planner.assignments[profileCard.modelData.id+":"+s.id] || planner.rules.tracks[0].id }); planner.task("bind_profile",{planner:planner.rules,profile:profileCard.modelData,assignments:a}) } }
                                                Action { text: "Duplicate"; onClicked: planner.task("duplicate_profile",{profile:profileCard.modelData}) }
                                                Action { text: "Save next version"; enabled: planner.rules.windows.length>0; onClicked: { var p=Draft.profile(planner.rules,profileCard.modelData.name); p.id=profileCard.modelData.id; planner.task("save_profile",{profile:p}) } }
                                                Action { text: "Export"; onClicked: planner.task("export_profile",{profile:profileCard.modelData}) }
                                            }
                                        }
                                    }
                                }
                                Repeater {
                                    model: planner.rules.profile_bindings || []
                                    delegate: Caption { required property var modelData; text: "PINNED: "+modelData.id+" v"+modelData.version+" · "+Object.keys(modelData.assignments).length+" channel-local assignments"; Layout.fillWidth: true }
                                }
                            }
                        }
                        Item {
                            ColumnLayout {
                                anchors.fill: parent; spacing: 10
                                Heading { text: "Original airings & era recreation" }
                                Caption { text: "Use your own airing records and owned media. Era mode maps reference-year weekdays and date scopes onto the actual broadcast days. It remains approximate; the computer’s clock is unchanged."; Layout.fillWidth: true }
                                RowLayout {
                                    Pick { id: historyMode; model: ["none","era","original","replay"]; currentIndex: Math.max(0,model.indexOf(planner.rules.historical_mode || "none")); onActivated: planner.mutate(function(r) { r.historical_mode=currentText }) }
                                    Field { placeholderText: "Reference year"; text: planner.rules.reference_year ? String(planner.rules.reference_year) : ""; Layout.preferredWidth: 110; onEditingFinished: planner.mutate(function(r) { r.reference_year=text ? Number(text) : null }) }
                                    Field { placeholderText: "Replay YYYY-MM-DD"; text: planner.rules.replay_start || ""; Layout.fillWidth: true; onEditingFinished: planner.mutate(function(r) { r.replay_start=text || null }) }
                                }
                                Action { text: "Import user-supplied CSV / JSON airings"; onClicked: planner.task("import_airings",{planner:planner.rules}) }
                                Caption { text: "Columns: id, asset_id, starts_at, ends_at, track_id, source, accuracy, substitute_id, rerun. Timestamps require UTC offsets. Missing media requires an explicit substitute."; Layout.fillWidth: true }
                                ListView {
                                    id: historicalList
                                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 8
                                    model: planner.rules.historical_airings || []
                                    delegate: Card {
                                        required property var modelData
                                        id: airing
                                        width: historicalList.width; height: airingText.implicitHeight+20
                                        ColumnLayout {
                                            id: airingText; anchors.fill: parent; anchors.margins: 10
                                            Caption { text: planner.stamp(airing.modelData.starts_at)+" · "+planner.title(airing.modelData.substitute_id || airing.modelData.asset_id); color: planner.ink; Layout.fillWidth: true }
                                            Caption { text: (airing.modelData.source || "Provenance missing")+" · "+(airing.modelData.accuracy || "exact"); Layout.fillWidth: true }
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
                Layout.preferredWidth: Math.max(280,planner.width*.235); Layout.minimumWidth: 0; Layout.fillHeight: true
                ScrollView {
                    anchors.fill: parent; anchors.margins: 12; clip: true
                    contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width; spacing: 10
                    Heading { text: "Media tracks" }
                    Pick { Layout.fillWidth: true; model: planner.rules.tracks.map(function(t) { var g=planner.rules.groups.filter(function(g) { return g.id===t.group_id })[0]; return (g ? g.name : t.id)+(t.mode==="rerun" ? " · rerun" : "") }); currentIndex: planner.rules.tracks.findIndex(function(t) { return t.id===planner.selectedTrack }); onActivated: planner.selectedTrack=planner.rules.tracks[currentIndex].id }
                    Heading { text: planner.group.name; font.pixelSize: 14; Layout.fillWidth: true; elide: Text.ElideRight }
                    Caption { text: (planner.group.asset_ids || []).length+" items · "+(planner.track.mode || "primary")+" cursor" }
                    RowLayout {
                        Caption { text: "After first pass" }
                        Pick { Layout.fillWidth: true; model: ["filler","loop","rerun","unassigned","successor"]; currentIndex: Math.max(0,model.indexOf(planner.track.post_completion || "filler")); enabled: !!planner.selectedTrack; onActivated: planner.setTrack("post_completion",currentText) }
                    }
                    Pick { visible: planner.track.post_completion==="successor"; Layout.fillWidth: true; model: planner.rules.tracks.filter(function(t) { return t.id!==planner.selectedTrack }).map(function(t) { return t.id }); onActivated: planner.setTrack("successor_id",currentText) }
                    CheckBox { text: "Required for completion"; font.pixelSize: 12; palette.windowText: planner.ink; checked: planner.track.required !== false; enabled: !!planner.selectedTrack && planner.track.mode!=="rerun"; onClicked: planner.setTrack("required",checked) }
                    RowLayout {
                        Caption { text: "Order" }
                        Pick { model: ["sequential","shuffle"]; currentIndex: planner.track.order==="shuffle" ? 1 : 0; enabled: !!planner.selectedTrack; onActivated: planner.setTrack("order",currentText) }
                        Field { placeholderText: "Start #"; text: String((planner.track.start_index || 0)+1); Layout.fillWidth: true; enabled: !!planner.selectedTrack; onEditingFinished: planner.setTrack("start_index",Number(text)-1) }
                    }
                    RowLayout {
                        Action { text: "+ Shared airing"; enabled: !!planner.selectedTrack; onClicked: planner.mutate(function(r) { Draft.addWindow(r,planner.selectedTrack) }) }
                        Action { text: "Remove track"; enabled: !!planner.selectedTrack; onClicked: planner.mutate(function(r) { Draft.removeTrack(r,planner.selectedTrack); planner.selectedTrack=r.tracks.length ? r.tracks[0].id : "" }) }
                    }
                    ListView {
                        id: windowList
                        Layout.fillWidth: true; Layout.preferredHeight: Math.max(190,Math.min(360,contentHeight)); clip: true; spacing: 10
                        model: planner.windows
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Card {
                            id: windowCard
                            required property var modelData
                            width: windowList.width; height: windowFields.implicitHeight+18; color: "#162c45"
                            ColumnLayout {
                                id: windowFields; anchors.fill: parent; anchors.margins: 9; spacing: 6
                                RowLayout {
                                    Field { text: windowCard.modelData.start; Layout.fillWidth: true; onEditingFinished: planner.setWindow(windowCard.modelData.id,"start",text) }
                                    Caption { text: "to" }
                                    Field { text: windowCard.modelData.end; Layout.fillWidth: true; onEditingFinished: planner.setWindow(windowCard.modelData.id,"end",text) }
                                }
                                RowLayout {
                                    Caption { text: "Bracket" }
                                    SpinBox { from: 1; to: 480; value: Number(windowCard.modelData.bracket_minutes || 60); editable: true; onValueModified: planner.setWindow(windowCard.modelData.id,"bracket_minutes",value); Layout.fillWidth: true }
                                    Caption { text: "min" }
                                }
                                Pick { Layout.fillWidth: true; model: ["strict","overrun","carryover","next_fit"]; currentIndex: Math.max(0,model.indexOf(windowCard.modelData.fit || "strict")); onActivated: { var fit=currentText; planner.mutate(function(r) { r.windows.forEach(function(w) { if(w.id===windowCard.modelData.id) { w.fit=fit; if(fit==="overrun" && !w.max_overrun_minutes) w.max_overrun_minutes=15 } }) }) } }
                                SpinBox { visible: windowCard.modelData.fit==="overrun"; from: 1; to: 480; value: Number(windowCard.modelData.max_overrun_minutes || 15); editable: true; Layout.fillWidth: true; onValueModified: planner.setWindow(windowCard.modelData.id,"max_overrun_minutes",value) }
                                Flow {
                                    Layout.fillWidth: true; spacing: 2
                                    Repeater {
                                        model: ["M","T","W","T","F","S","S"]
                                        delegate: Action {
                                            id: dayToggle
                                            required property int index
                                            required property string modelData
                                            text: modelData; implicitWidth: 26; implicitHeight: 28
                                            highlighted: !windowCard.modelData.scope || !windowCard.modelData.scope.weekdays || windowCard.modelData.scope.weekdays.indexOf(index)>=0
                                            onClicked: { var scope=Draft.copy(windowCard.modelData.scope || {weekdays:[0,1,2,3,4,5,6]}); var days=scope.weekdays || [0,1,2,3,4,5,6]; scope.weekdays=days.indexOf(index)>=0 ? days.filter(function(d) { return d!==dayToggle.index }) : days.concat([index]).sort(); planner.setWindow(windowCard.modelData.id,"scope",scope) }
                                        }
                                    }
                                }
                                Action { text: "Delete airing window"; Layout.fillWidth: true; onClicked: planner.mutate(function(r) { r.windows=r.windows.filter(function(w) { return w.id!==windowCard.modelData.id }) }) }
                            }
                        }
                    }
                    Caption { text: "First-pass completion stays earned while this media loops. Reruns use their own cursor."; Layout.fillWidth: true }
                    CheckBox { text: "Use selected gap filler"; font.pixelSize: 12; palette.windowText: planner.ink; checked: planner.rules.gap_filler || false; onClicked: planner.mutate(function(r) { r.gap_filler=checked }) }
                }
                }
            }
        }
        Card {
            id: milestonesCard
            Layout.fillWidth: true; implicitHeight: milestoneRow.implicitHeight+28
            RowLayout {
                id: milestoneRow
                anchors.fill: parent; anchors.margins: 14; spacing: 20
                Repeater {
                    model: [{label:"MEDIA ENDS",value:planner.forecast.media_ends},{label:"CYCLE READY",value:planner.forecast.cycle_ready},{label:planner.rules.cycle.action==="once" ? "CHANNEL CLOSES" : "ACTUAL RESTART",value:planner.forecast.actual_restart}]
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Caption { text: parent.modelData.label; font.letterSpacing: 1 }
                        Label { text: planner.milestone(parent.modelData.value); color: planner.ink; font.pixelSize: 20; font.weight: Font.Bold }
                        Caption { text: parent.modelData.value ? planner.stamp(parent.modelData.value).slice(11) : "Adjust rules or inspect forecast" }
                    }
                }
                ColumnLayout {
                    Caption { text: "FORECAST CONFIDENCE" }
                    Label { text: planner.pendingPreview || planner.worker.busy ? "Calculating…" : planner.forecast.confidence || "Waiting"; color: planner.forecast.confidence==="Blocked" ? "#ffb0b5" : "#83dac3"; font.pixelSize: 18; font.weight: Font.Bold }
                    Action { text: planner.worker.busy ? "Cancel calculation" : "Recalculate"; onClicked: { if(planner.worker.busy) channelOS.cancelPlannerTask(); else planner.preview() } }
                }
            }
        }
        Caption { Layout.fillWidth: true; text: planner.feedback; color: planner.feedbackError ? "#ffb0b5" : planner.muted; maximumLineCount: 2; elide: Text.ElideRight }
    }
    AdSettingsEditor { id: adSettings; hostItem: planner; channelNumber: Number(planner.editor.channel || 1); channelName: String(planner.editor.name || "Channel"); mediaLibrary: planner.mediaRows; sourceOptions: planner.editor.sourceOptions || []; onSettingsApplied: planner.changed() }
    Dialog {
        id: discardDialog; anchors.centerIn: parent; modal: true; title: "Leave this draft?"; standardButtons: Dialog.Discard | Dialog.Cancel
        Label { text: "Your live channel is unchanged. Unsaved planner edits will be discarded."; color: planner.ink }
        onDiscarded: { planner.dirty=false; channelOS.cancelPlannerTask(); if(planner.hostWindow) planner.hostWindow.screen=planner.exitDestination }
    }
    Dialog {
        id: rulesDialog; anchors.centerIn: parent; modal: true; width: Math.min(920,planner.width-100); height: Math.min(720,planner.height-70); title: "Complete broadcast rules"; standardButtons: Dialog.Apply | Dialog.Cancel
        ColumnLayout {
            anchors.fill: parent
            Caption { text: "Advanced editor for exact date ranges, nested ALL/ANY gates, filler pools, protected overrides, and historical substitutions. Validation and forecast run before Apply channel."; Layout.fillWidth: true }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; TextArea { id: rawRules; font.family: "monospace"; font.pixelSize: 12; selectByMouse: true; color: planner.ink; wrapMode: TextEdit.NoWrap } }
        }
        onApplied: { try { planner.editor=Object.assign({},planner.editor,{planner:JSON.parse(rawRules.text)}); planner.changed(); close() } catch(error) { planner.feedback=String(error); planner.feedbackError=true } }
    }
    Dialog {
        id: cycleDialog; anchors.centerIn: parent; modal: true; width: 660; height: Math.min(690,planner.height-70); title: "Whole-channel cycle"; standardButtons: Dialog.Close
        ScrollView {
            anchors.fill: parent; clip: true
            ColumnLayout {
                width: parent.width; spacing: 10
                Caption { text: "A cycle closes only after its required content, date gate and safe boundary. The current complete program and committed ads always finish."; Layout.fillWidth: true }
                RowLayout { Caption { text: "End action" } Pick { model: ["restart","once"]; currentIndex: planner.rules.cycle.action==="once" ? 1 : 0; onActivated: planner.setCycle("action",currentText) } }
                RowLayout { Caption { text: "Content gate" } Pick { model: ["all","any","selected_all","selected_any","custom","none"]; currentIndex: Math.max(0,model.indexOf(planner.rules.cycle.completion || "all")); onActivated: planner.setCycle("completion",currentText) } }
                Repeater {
                    model: planner.rules.tracks.filter(function(t) { return t.mode!=="rerun" })
                    delegate: CheckBox {
                        required property var modelData
                        text: modelData.id
                        visible: String(planner.rules.cycle.completion || "").indexOf("selected_")===0
                        checked: (planner.rules.cycle.required_tracks || []).indexOf(modelData.id)>=0
                        onClicked: { var id=modelData.id; planner.mutate(function(r) { var a=r.cycle.required_tracks || []; r.cycle.required_tracks=checked ? a.concat([id]) : a.filter(function(t) { return t!==id }) }) }
                    }
                }
                Caption { visible: planner.rules.cycle.completion==="custom"; text: "Edit the nested ALL/ANY completion gate in Rules. Every leaf names a primary track."; Layout.fillWidth: true }
                Field { Layout.fillWidth: true; placeholderText: "Earliest date · ISO timestamp + UTC offset (optional)"; text: planner.rules.cycle.not_before || ""; onEditingFinished: planner.setCycle("not_before",text || null) }
                RowLayout { Caption { text: "Combine content + date" } Pick { model: ["and","or"]; currentIndex: planner.rules.cycle.gate_mode==="or" ? 1 : 0; onActivated: planner.setCycle("gate_mode",currentText) } }
                CheckBox { text: "I accept that date-only / OR can restart unfinished media"; checked: planner.rules.cycle.allow_unfinished || false; onClicked: planner.setCycle("allow_unfinished",checked) }
                RowLayout { Caption { text: "Restart boundary" } Pick { model: ["safe","day","week","month","quarter","year","period","manual"]; currentIndex: Math.max(0,model.indexOf(planner.rules.cycle.boundary || "safe")); onActivated: planner.setCycle("boundary",currentText) } }
                RowLayout {
                    Caption { text: "Weekday (0=Monday)" }
                    SpinBox { from: 0; to: 6; value: Number(planner.rules.cycle.boundary_weekday || 0); onValueModified: planner.setCycle("boundary_weekday",value) }
                    Field { text: planner.rules.cycle.boundary_time || "00:00"; Layout.preferredWidth: 90; onEditingFinished: planner.setCycle("boundary_time",text) }
                }
                RowLayout { visible: planner.rules.cycle.boundary==="period"; Caption { text: "Custom period · days" } SpinBox { from: 1; to: 3660; value: Number(planner.rules.cycle.period_days || 7); onValueModified: planner.setCycle("period_days",value) } }
                RowLayout { visible: planner.rules.cycle.action==="once"; Caption { text: "After Air Once & Done" } Pick { model: ["slate","offair","filler"]; currentIndex: Math.max(0,model.indexOf(planner.rules.cycle.after_once || "slate")); onActivated: planner.setCycle("after_once",currentText) } }
                RowLayout { Caption { text: "Edits take effect" } Pick { model: ["next_cycle","safe_future"]; currentIndex: planner.rules.edit_effect==="safe_future" ? 1 : 0; onActivated: planner.mutate(function(r) { r.edit_effect=currentText }) } }
                Caption { text: "Next cycle preserves this cycle’s intent. Safe future keeps earned progress and starts after the current program and committed ads. Closed-cycle history is retained."; Layout.fillWidth: true }
                Action { text: "Release ready manual cycle"; visible: planner.rules.cycle.boundary==="manual"; enabled: planner.editingNumber>0 && !planner.dirty && !planner.applying; onClicked: { var result=channelOS.startChannelMutation("release_cycle",planner.editingNumber,{}); if(result.ok) planner.applying=true; else { planner.feedback=result.message; planner.feedbackError=true } } }
            }
        }
    }
    Dialog {
        id: sourcesDialog; anchors.centerIn: parent; modal: true; width: Math.min(640,planner.width-80); height: Math.min(520,planner.height-80); title: "Planner media sources"; standardButtons: Dialog.Close
        ScrollView {
            anchors.fill: parent; clip: true
            ColumnLayout {
                width: parent.width
                Caption { text: "Add or remove indexed sources for this draft. Adding a collection from the bin includes its source automatically."; Layout.fillWidth: true }
                Repeater {
                    model: planner.editor.sourceOptions || []
                    delegate: CheckBox {
                        required property string modelData
                        text: modelData
                        palette.windowText: planner.ink
                        checked: (planner.editor.sources || []).indexOf(modelData)>=0
                        onClicked: { var source=modelData; var values=planner.editor.sources || []; planner.setEditor("sources",checked ? values.concat([source]) : values.filter(function(s) { return s!==source })) }
                    }
                }
            }
        }
    }
    Dialog {
        id: pauseDialog; anchors.centerIn: parent; modal: true; width: 470; title: "Suspend programming"; standardButtons: Dialog.Apply | Dialog.Cancel
        ColumnLayout {
            anchors.fill: parent
            Field { id: pauseName; text: "Holiday pause"; Layout.fillWidth: true }
            Pick { id: pauseTarget; model: ["track","group","window","layer","filler","advertising","channel"]; Layout.fillWidth: true }
            Field { id: pauseId; text: planner.selectedTrack; placeholderText: "Target ID (blank for channel / filler / advertising)"; Layout.fillWidth: true }
            Field { id: pauseFrom; placeholderText: "From date · YYYY-MM-DD"; Layout.fillWidth: true }
            Field { id: pauseUntil; placeholderText: "Through date · YYYY-MM-DD"; Layout.fillWidth: true }
            Pick { id: pauseResume; model: ["continue","restart","skip"]; Layout.fillWidth: true }
            Caption { text: "Hold and continue preserves the next episode. A pause never earns a completion or satisfies a cycle gate."; Layout.fillWidth: true }
        }
        onApplied: { planner.mutate(function(r) { r.suspensions.push({id:Draft.uid("pause"),name:pauseName.text,target:pauseTarget.currentText,target_id:pauseId.text || null,scope:{from_date:pauseFrom.text || null,until_date:pauseUntil.text || null},resume:pauseResume.currentText}) }); close() }
    }
    Dialog {
        id: layerDialog; anchors.centerIn: parent; modal: true; width: 470; title: "Seasonal calendar layer"; standardButtons: Dialog.Apply | Dialog.Cancel
        ColumnLayout {
            anchors.fill: parent
            Field { id: layerName; placeholderText: "Layer name"; Layout.fillWidth: true }
            Field { id: layerMonths; placeholderText: "Months · 11,12"; Layout.fillWidth: true }
            Field { id: layerFrom; placeholderText: "Optional from date · YYYY-MM-DD"; Layout.fillWidth: true }
            Field { id: layerUntil; placeholderText: "Optional through date · YYYY-MM-DD"; Layout.fillWidth: true }
            SpinBox { id: layerPriority; from: 1; to: 1000; value: 100; editable: true }
            CheckBox { id: wholeLayer; text: "Explicitly replace the whole channel on matching dates" }
        }
        onApplied: { planner.mutate(function(r) { r.layers.push({id:Draft.uid("layer"),name:layerName.text,scope:{months:layerMonths.text ? layerMonths.text.split(",").map(Number) : [],from_date:layerFrom.text || null,until_date:layerUntil.text || null},priority:layerPriority.value,replace_scope:wholeLayer.checked ? "channel" : "overlap"}) }); close() }
    }
}
