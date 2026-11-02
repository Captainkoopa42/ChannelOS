.pragma library

function key(path) {
    var value = String(path || "").replace(/\\/g, "/").replace(/\/+$/, "")
    return /^[A-Za-z]:/.test(value) ? value.toLowerCase() : value
}
function contains(path, root) {
    var p = key(path), r = key(root)
    return r.length > 0 && (p === r || p.indexOf(r + "/") === 0)
}
function natural(a, b) {
    var x = String(a).toLowerCase().split(/(\d+)/), y = String(b).toLowerCase().split(/(\d+)/)
    for (var i = 0; i < Math.min(x.length, y.length); ++i) {
        if (x[i] === y[i]) continue
        if (i % 2 === 1) return Number(x[i]) - Number(y[i])
        return x[i] < y[i] ? -1 : 1
    }
    return x.length - y.length
}
function groups(media, sources, ids, excluded) {
    var result = [], seen = ({}), requested = ({}), ignored = ({})
    ids.forEach(function(id) { requested[id] = true })
    excluded.forEach(function(id) { ignored[id] = true })
    sources.forEach(function(path) {
        var parts = String(path).replace(/\\/g, "/").replace(/\/+$/, "").split("/")
        result.push({path:path, name:parts[parts.length-1] || path, media:[]})
    })
    media.forEach(function(item) {
        var id = String(item.assetId || "")
        if (!id || seen[id] || ignored[id]) return
        var locations = item.locations && item.locations.length ? item.locations : [item]
        for (var i = 0; i < result.length; ++i) {
            for (var j = 0; j < locations.length; ++j) {
                if (contains(locations[j].path, result[i].path)) {
                    result[i].media.push(Object.assign({}, item, locations[j])); seen[id] = true; return
                }
            }
        }
        if (requested[id]) {
            var group = result.filter(function(g) { return g.path === "" })[0]
            if (!group) { group = {path:"", name:"Selected clips", media:[]}; result.push(group) }
            group.media.push(item); seen[id] = true
        }
    })
    result.forEach(function(group) { group.media.sort(function(a,b) { return natural(a.path,b.path) }) })
    return result
}
function selected(media, sources, ids, excluded) {
    var result = []
    groups(media, sources, ids, excluded).forEach(function(group) { result = result.concat(group.media) })
    return result
}
