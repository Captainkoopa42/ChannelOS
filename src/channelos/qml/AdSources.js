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
function prepare(media) {
    // Cross the QVariant boundary once, rather than once per source comparison.
    var rows = JSON.parse(JSON.stringify(media || []))
    return rows.map(function(item) {
        return {item:item, locations:(item.locations && item.locations.length ? item.locations : [item]).map(function(location) {
            return {value:location, key:key(location.path)}
        })}
    })
}
function groupPrepared(prepared, sources, ids) {
    var result=[], roots=Object.create(null), requested=Object.create(null), seen=Object.create(null)
    ids.forEach(function(id) { requested[String(id)]=true })
    sources.forEach(function(path, index) {
        var parts=String(path).replace(/\\/g,"/").replace(/\/+$/,"").split("/")
        result.push({path:path, name:parts[parts.length-1] || path, media:[]})
        var normalized=key(path)
        if (!(normalized in roots)) roots[normalized]=index
    })
    var fixed=null
    prepared.forEach(function(row) {
        var item=row.item, id=String(item.assetId || "")
        if (!id || seen[id]) return
        var first=sources.length, location=null
        row.locations.forEach(function(candidate) {
            var path=candidate.key
            while (path.length) {
                if (path in roots && roots[path] < first) { first=roots[path]; location=candidate.value }
                var slash=path.lastIndexOf("/")
                if (slash<0) break
                path=path.substring(0,slash)
                // POSIX root is represented by the empty normalized key.
                if (!path.length && "" in roots && roots[""]<first) { first=roots[""]; location=candidate.value }
            }
        })
        if (location) { result[first].media.push(Object.assign({},item,location)); seen[id]=true }
        else if (requested[id]) {
            if (!fixed) { fixed={path:"", name:"Selected clips",media:[]}; result.push(fixed) }
            fixed.media.push(item); seen[id]=true
        }
    })
    result.forEach(function(group) { group.media.sort(function(a,b) { return natural(a.path,b.path) }) })
    return result
}
function membership(groups) {
    var byId=Object.create(null), counts=Object.create(null), total=0
    groups.forEach(function(group) {
        counts[group.path]=group.media.length
        group.media.forEach(function(item) { byId[String(item.assetId)]=group.path; total++ })
    })
    return {byId:byId, counts:counts,total:total}
}
function selection(index, excluded) {
    var ignored=Object.create(null), counts=Object.assign(Object.create(null),index.counts), total=index.total
    excluded.forEach(function(value) {
        var id=String(value)
        if (!ignored[id] && id in index.byId) { total--; counts[index.byId[id]]-- }
        ignored[id]=true
    })
    return {ignored:ignored, counts:counts,total:total}
}
function groups(media, sources, ids, excluded) {
    var result=groupPrepared(prepare(media),sources,ids), ignored=Object.create(null)
    excluded.forEach(function(id) { ignored[String(id)]=true })
    result.forEach(function(group) { group.media=group.media.filter(function(item) { return !ignored[String(item.assetId)] }) })
    return result
}
function selected(media, sources, ids, excluded) {
    var result=[]
    groups(media,sources,ids,excluded).forEach(function(group) { result=result.concat(group.media) })
    return result
}
