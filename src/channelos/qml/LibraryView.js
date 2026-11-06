.pragma library

function prepare(snapshot) {
    var data = JSON.parse(JSON.stringify(snapshot || {}))
    var items = data.items || [], byId = {}, bySource = {}, search = {}
    items.forEach(function(item) {
        var id = String(item.assetId || "")
        byId[id] = item
        search[id] = [item.title, item.fileName, item.sourceName, item.containerFormat].join(" ").toLowerCase()
    })
    items.sort(function(a,b) {
        var first=String(a.title || a.fileName || "").toLowerCase()
        var second=String(b.title || b.fileName || "").toLowerCase()
        return first < second ? -1 : first > second ? 1 : 0
    })
    // Source shelves follow the same stable title order without sorting again.
    bySource = {}
    items.forEach(function(item) {
        var source=String(item.sourceRoot || "")
        if (!bySource[source]) bySource[source]=[]
        bySource[source].push(item)
    })
    return {snapshot:data, items:items, byId:byId, bySource:bySource, search:search, shelves:null}
}

function shelves(view) {
    var result=[], items=view.items
    var continuing=items.filter(function(item){return Boolean(item.continueWatching)})
    continuing.sort(function(a,b){return String(b.lastWatchedAt || "").localeCompare(String(a.lastWatchedAt || ""))})
    if (continuing.length) result.push({shelfId:"continue", title:"CONTINUE WATCHING", subtitle:"Resume your saved On Demand playhead", items:continuing, featured:true})
    if (!items.length) return result
    result.push({shelfId:"all", title:"ALL MEDIA", subtitle:"Your complete indexed collection", items:items, featured:true})
    ;(view.snapshot.sources || []).forEach(function(source) {
        var selected=view.bySource[String(source.path || "")] || []
        if (selected.length) result.push({shelfId:"source:"+source.path, title:String(source.name || "MEDIA SOURCE").toUpperCase(), subtitle:selected.length+" indexed item"+(selected.length===1?"":"s"),items:selected,featured:false})
    })
    var features=[], short=[]
    items.forEach(function(item){var duration=Number(item.durationSeconds || 0);if(duration>=3600)features.push(item);else if(duration>0)short.push(item)})
    if(features.length)result.push({shelfId:"feature",title:"FEATURE LENGTH",subtitle:"Long-form movies, recordings, and specials",items:features,featured:false})
    if(short.length)result.push({shelfId:"short",title:"SHORT FORM",subtitle:"Episodes, clips, and shorter programs",items:short,featured:false})
    return result
}
