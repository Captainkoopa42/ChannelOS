.pragma library

function copy(value) { return JSON.parse(JSON.stringify(value)) }
function uid(prefix) { return prefix + "-" + Date.now().toString(36) + "-" + Math.floor(Math.random()*1000000).toString(36) }
function hour(value) { return (value < 10 ? "0" : "") + value + ":00" }
function addTrack(rules, group, rerun, at) {
    var existing = rules.groups.filter(function(g) { return g.id === group.id })[0]
    if (!existing) rules.groups.push({id:group.id,name:group.name,kind:group.kind || "series",asset_ids:copy(group.asset_ids)})
    var shared = rules.tracks.filter(function(t) { return t.group_id===group.id && t.mode!=="rerun" })[0]
    if(shared && !rerun) { addWindow(rules,shared.id,at); return shared.id }
    var track = {id:uid(rerun ? "rerun" : "track"),group_id:group.id,mode:rerun ? "rerun" : "primary",
                 order:"sequential",post_completion:rerun ? "loop" : "filler",required:!rerun,start_index:0}
    rules.tracks.push(track)
    addWindow(rules,track.id,at)
    return track.id
}
function addWindow(rules, trackId, at) {
    var hourNumber = at === undefined ? 9 : Number(at)
    if (at === undefined) {
        var occupied = rules.windows.map(function(w) { return w.start })
        while (hourNumber < 23 && occupied.indexOf(hour(hourNumber)) >= 0) hourNumber++
    }
    var window = {id:uid("window"),track_id:trackId,start:hour(hourNumber),end:hourNumber===23 ? "24:00" : hour(hourNumber+1),
                  bracket_minutes:60,fit:"strict",max_overrun_minutes:0,scope:{weekdays:[0,1,2,3,4,5,6]}}
    rules.windows.push(window)
    return window.id
}
function removeTrack(rules, id) {
    rules.tracks = rules.tracks.filter(function(t) { return t.id !== id })
    rules.windows = rules.windows.filter(function(w) { return w.track_id !== id })
    rules.suspensions = rules.suspensions.filter(function(p) { return !(p.target === "track" && p.target_id === id) })
    rules.profile_bindings = (rules.profile_bindings || []).filter(function(p) {
        return Object.keys(p.assignments).every(function(s) { return p.assignments[s] !== id })
    })
    if (rules.cycle.required_tracks) rules.cycle.required_tracks = rules.cycle.required_tracks.filter(function(t) { return t !== id })
    if (rules.cycle.restart_tracks) rules.cycle.restart_tracks = rules.cycle.restart_tracks.filter(function(t) { return t !== id })
}
function profile(rules, name) {
    return {id:uid("profile"),version:1,name:name,slots:rules.windows.map(function(w,i) {
        var slot={id:"slot-"+(i+1),name:"Slot "+(i+1)}
        ;["start","end","bracket_minutes","fit","max_overrun_minutes","scope","priority"].forEach(function(k) {
            if(w[k] !== undefined) slot[k] = copy(w[k])
        })
        return slot
    })}
}
function rangeDate(value, shift) {
    var d=new Date(value + "T12:00:00Z")
    d.setUTCDate(d.getUTCDate()+shift)
    return d.toISOString().slice(0,10)
}
function monthDays(value) {
    var first=value.slice(0,7)+"-01"
    var week=new Date(first+"T12:00:00Z").getUTCDay()
    var leading=(week+6)%7
    var days=[]
    for(var i=0;i<42;i++) days.push(rangeDate(first,i-leading))
    return days
}
