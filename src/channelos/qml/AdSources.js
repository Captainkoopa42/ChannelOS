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
    var indexed = rows.map(function(item) {
        return {item:item, locations:(item.locations && item.locations.length ? item.locations : [item]).map(function(location) {
            return {value:location, key:key(location.path)}
        })}
    })
    var parents=Object.create(null)
    indexed.forEach(function(row) {
        row.locations.forEach(function(location) {
            var path=location.key
            while (path.length) {
                if (!(path in parents)) parents[path]=[]
                parents[path].push({row:row,location:location})
                var slash=path.lastIndexOf("/")
                if (slash<0) break
                path=path.substring(0,slash)
            }
        })
    })
    return {rows:indexed, parents:parents, buckets:Object.create(null), order:[]}
}
function sourceMedia(prepared, path) {
    var root=key(path)
    if (root in prepared.buckets) return prepared.buckets[root]
    var media=[], seen=Object.create(null)
    ;(prepared.parents[root] || []).forEach(function(candidate) {
        var item=candidate.row.item, id=String(item.assetId || "")
        if (!id || seen[id]) return
        media.push(Object.assign({},item,candidate.location.value)); seen[id]=true
    })
    media.sort(function(a,b) { return natural(a.path,b.path) })
    if (prepared.order.length>=32) delete prepared.buckets[prepared.order.shift()]
    prepared.order.push(root); prepared.buckets[root]=media
    return media
}
function groupPrepared(prepared, sources, ids) {
    var result=[], requested=Object.create(null), seen=Object.create(null)
    ids.forEach(function(id) { requested[String(id)]=true })
    sources.forEach(function(path) {
        var parts=String(path).replace(/\\/g,"/").replace(/\/+$/,"").split("/")
        var selected=sourceMedia(prepared,path).filter(function(item) {
            var id=String(item.assetId)
            if (seen[id]) return false
            seen[id]=true; return true
        })
        result.push({path:path,name:parts[parts.length-1] || path,media:selected})
    })
    var fixed=[]
    prepared.rows.forEach(function(row) {
        var id=String(row.item.assetId || "")
        if (requested[id] && !seen[id]) { fixed.push(row.item); seen[id]=true }
    })
    if (fixed.length) {
        fixed.sort(function(a,b) { return natural(a.path,b.path) })
        result.push({path:"",name:"Selected clips",media:fixed})
    }
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
