pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: studioRoot
    anchors.fill: parent
    z: 92

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

    property var hostWindow: null
    property var draftData: ({ media: [], sources: [], calendarBlocks: [] })
    property var mediaLibrary: draftData.media || []
    property var groupsLibrary: draftData.groups || []
    property var blocksByDay: ({})
    property string viewMode: "week"
    property date anchorDate: new Date()
    property string selectedDayKey: dayKey(new Date())
    property int editingChannelNumber: 0
    property int selectedBlockIndex: -1
    property bool dirty: false
    property bool loading: false
    property string pendingExitDestination: ""
    property string feedbackMessage: ""
    property bool feedbackIsError: false
    property bool autoFillApplying: false
    property var pendingAutoFillBlocks: []
    property int pendingAutoFillIndex: 0
    property string pendingAutoFillMessage: ""
    readonly property var autoFillState: channelOS
            ? channelOS.studioAutoFill
            : ({ active: false, phase: "idle", current: 0, total: 0,
                 percent: 0, message: "" })
    readonly property bool autoFillBusy: Boolean(autoFillState.active)
                                         || autoFillApplying
    readonly property int autoFillApplyPercent: pendingAutoFillBlocks.length > 0
            ? Math.min(100, Math.floor(pendingAutoFillIndex * 100
                                      / pendingAutoFillBlocks.length))
            : 0

    onSelectedBlockIndexChanged:
        exactTimeField.text = selectedBlockTimeText()
    onBlocksByDayChanged:
        exactTimeField.text = selectedBlockTimeText()

    function pad(value) {
        return Number(value) < 10 ? "0" + Number(value) : String(value)
    }

    function dayKey(value) {
        var day = new Date(value)
        return day.getFullYear() + "-" + pad(day.getMonth() + 1)
                + "-" + pad(day.getDate())
    }

    function dateAtLocalMidnight(value) {
        var day = new Date(value)
        day.setHours(0, 0, 0, 0)
        return day
    }

    function startOfWeek(value) {
        var day = dateAtLocalMidnight(value)
        var weekday = day.getDay()
        var mondayOffset = weekday === 0 ? -6 : 1 - weekday
        day.setDate(day.getDate() + mondayOffset)
        return day
    }

    function addDays(value, count) {
        var result = new Date(value)
        result.setDate(result.getDate() + Number(count))
        return result
    }

    function visibleStart() {
        if (viewMode === "month")
            return new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1)
        return startOfWeek(anchorDate)
    }

    function visibleEnd() {
        if (viewMode === "month")
            return new Date(anchorDate.getFullYear(), anchorDate.getMonth() + 1, 1)
        return addDays(startOfWeek(anchorDate), 7)
    }

    function monthGridStart() {
        return startOfWeek(new Date(anchorDate.getFullYear(),
                                    anchorDate.getMonth(), 1))
    }

    function rangeLabel() {
        if (viewMode === "month")
            return Qt.formatDate(anchorDate, "MMMM yyyy")
        var start = startOfWeek(anchorDate)
        var end = addDays(start, 6)
        return Qt.formatDate(start, "MMM d") + " — "
                + Qt.formatDate(end, "MMM d, yyyy")
    }

    function durationLabel(seconds) {
        var total = Math.max(0, Math.round(Number(seconds || 0)))
        var hours = Math.floor(total / 3600)
        var minutes = Math.floor((total % 3600) / 60)
        var secs = total % 60
        if (hours > 0)
            return hours + "h " + pad(minutes) + "m"
        if (minutes > 0)
            return minutes + "m " + pad(secs) + "s"
        return secs + "s"
    }

    function formatTime(isoText) {
        return Qt.formatTime(new Date(String(isoText)), "h:mm AP")
    }

    function editorObject() {
        var sources = []
        for (var sourceIndex = 0;
             sourceIndex < draftSources.count;
             ++sourceIndex) {
            sources.push(draftSources.get(sourceIndex).path)
        }

        var blocks = []
        for (var blockIndex = 0;
             blockIndex < calendarBlocks.count;
             ++blockIndex) {
            var block = calendarBlocks.get(blockIndex)
            var item = {
                assetId: String(block.assetId),
                startUtc: String(block.startUtc)
            }
            var fillerIds = parseAssetIds(block.fillerAssetIdsJson)
            if (fillerIds.length) {
                item.fillerMode = String(block.fillerMode || "sequential")
                item.fillerAssetIds = fillerIds
            }
            blocks.push(item)
        }

        return {
            channel: channelNumberField.text,
            name: channelNameField.text,
            description: descriptionField.text,
            mode: "calendar",
            fillerMode: fillerModeBox.currentText.toLowerCase(),
            preserveEpisodeOrder: false,
            avoidRepeatDays: repeatDays.value,
            numberWidth: 3,
            sources: sources,
            calendarBlocks: blocks
        }
    }

    function mediaForAsset(assetId) {
        var target = String(assetId || "")
        for (var index = 0; index < mediaLibrary.length; ++index) {
            if (String(mediaLibrary[index].assetId) === target)
                return mediaLibrary[index]
        }
        return ({
            assetId: target,
            title: "Unavailable media",
            path: "",
            sourceRoot: "",
            durationSeconds: 0,
            containerFormat: "MEDIA"
        })
    }

    function appendSource(sourceRoot) {
        var value = String(sourceRoot || "")
        if (!value.length)
            return
        for (var index = 0; index < draftSources.count; ++index) {
            if (String(draftSources.get(index).path) === value)
                return
        }
        draftSources.append({ path: value })
    }

    function appendBlock(block) {
        var media = mediaForAsset(block.assetId)
        var duration = Number(block.durationSeconds
                              || media.durationSeconds
                              || 0)
        var start = new Date(String(block.startUtc))
        var end = block.endUtc
                ? new Date(String(block.endUtc))
                : new Date(start.getTime() + duration * 1000)
        calendarBlocks.append({
            assetId: String(block.assetId),
            title: String(block.title || media.title || "Untitled"),
            path: String(block.path || media.path || ""),
            sourceRoot: String(block.sourceRoot || media.sourceRoot || ""),
            durationSeconds: duration,
            startUtc: start.toISOString(),
            endUtc: end.toISOString(),
            fillerMode: String(block.fillerMode || ""),
            fillerAssetIdsJson: JSON.stringify(block.fillerAssetIds || []),
            fillerGroupName: String(block.fillerGroupName || "")
        })
    }

    function blockObject(block) {
        var media = mediaForAsset(block.assetId)
        var duration = Number(block.durationSeconds
                              || media.durationSeconds
                              || 0)
        var start = new Date(String(block.startUtc))
        var end = block.endUtc
                ? new Date(String(block.endUtc))
                : new Date(start.getTime() + duration * 1000)
        return {
            assetId: String(block.assetId),
            title: String(block.title || media.title || "Untitled"),
            path: String(block.path || media.path || ""),
            sourceRoot: String(block.sourceRoot || media.sourceRoot || ""),
            durationSeconds: duration,
            startUtc: start.toISOString(),
            endUtc: end.toISOString(),
            fillerMode: String(block.fillerMode || ""),
            fillerAssetIdsJson: String(block.fillerAssetIdsJson
                                       || JSON.stringify(block.fillerAssetIds || [])),
            fillerGroupName: String(block.fillerGroupName || "")
        }
    }

    function sortBlocks() {
        var blocks = []
        for (var currentIndex = 0;
             currentIndex < calendarBlocks.count;
             ++currentIndex) {
            var current = calendarBlocks.get(currentIndex)
            blocks.push({
                assetId: current.assetId,
                title: current.title,
                path: current.path,
                sourceRoot: current.sourceRoot,
                durationSeconds: current.durationSeconds,
                startUtc: current.startUtc,
                endUtc: current.endUtc,
                fillerMode: current.fillerMode,
                fillerAssetIdsJson: current.fillerAssetIdsJson,
                fillerGroupName: current.fillerGroupName
            })
        }
        blocks.sort(function(left, right) {
            return new Date(left.startUtc).getTime()
                    - new Date(right.startUtc).getTime()
        })
        calendarBlocks.clear()
        for (var index = 0; index < blocks.length; ++index)
            calendarBlocks.append(blocks[index])
        rebuildBlockIndex()
    }

    function rebuildBlockIndex() {
        var indexByDay = ({})
        for (var index = 0; index < calendarBlocks.count; ++index) {
            var block = calendarBlocks.get(index)
            var key = dayKey(new Date(block.startUtc))
            if (!indexByDay[key])
                indexByDay[key] = []
            indexByDay[key].push({
                modelIndex: index,
                assetId: block.assetId,
                title: block.title,
                startUtc: block.startUtc,
                durationSeconds: block.durationSeconds
            })
        }
        // Replacing the object gives every calendar cell one predictable
        // binding update instead of making 42 cells rescan the complete model.
        blocksByDay = indexByDay
    }

    function loadDraft() {
        if (!channelOS || loading || autoFillBusy)
            return
        loading = true
        feedbackMessage = "Loading detached Studio draft…"
        feedbackIsError = false
        var target = hostWindow
                ? Number(hostWindow.studioChannelNumber || 0)
                : 0
        var result = channelOS.loadChannelStudio(target)
        loading = false
        if (!result || !result.ok) {
            feedbackMessage = result && result.message
                    ? String(result.message)
                    : "Channel Studio could not load this channel."
            feedbackIsError = true
            return
        }

        draftData = result.draft || ({})
        mediaLibrary = draftData.media || []
        groupsLibrary = draftData.groups || []
        editingChannelNumber = Number(draftData.editingChannelNumber || 0)
        channelNumberField.text = String(draftData.channel || 1)
        channelNameField.text = String(draftData.name || "")
        descriptionField.text = String(draftData.description || "")
        fillerModeBox.currentIndex = String(draftData.fillerMode) === "shuffle"
                ? 1 : 0
        repeatDays.value = Number(draftData.avoidRepeatDays || 0)

        draftSources.clear()
        var sources = draftData.sources || []
        for (var sourceIndex = 0; sourceIndex < sources.length; ++sourceIndex)
            appendSource(sources[sourceIndex])

        calendarBlocks.clear()
        var blocks = draftData.calendarBlocks || []
        for (var blockIndex = 0; blockIndex < blocks.length; ++blockIndex)
            appendBlock(blocks[blockIndex])
        sortBlocks()

        selectedBlockIndex = calendarBlocks.count ? 0 : -1
        anchorDate = calendarBlocks.count
                ? new Date(calendarBlocks.get(0).startUtc)
                : new Date()
        selectedDayKey = dayKey(anchorDate)
        dirty = false
        feedbackMessage = editingChannelNumber > 0
                ? (calendarBlocks.count > 0
                   ? "Calendar draft loaded. Live television is unchanged until Apply."
                   : "Classic channel loaded. Auto Fill or add media to convert it to an editable calendar.")
                : "New detached channel draft. Auto Fill a range, then reshape it."
        feedbackIsError = false
    }

    function filteredMedia() {
        var result = []
        var needle = String(mediaSearch.text || "").toLowerCase().trim()
        for (var index = 0; index < mediaLibrary.length; ++index) {
            var item = mediaLibrary[index]
            var haystack = (String(item.title || "") + " "
                            + String(item.path || "") + " "
                            + String(item.containerFormat || "")).toLowerCase()
            if (!needle.length || haystack.indexOf(needle) >= 0)
                result.push(item)
        }
        return result
    }

    function sourceChoices() {
        var result = []
        for (var index = 0; index < mediaLibrary.length; ++index) {
            var source = String(mediaLibrary[index].sourceRoot || "")
            if (source.length && result.indexOf(source) < 0)
                result.push(source)
        }
        result.sort()
        return result
    }

    function parseAssetIds(value) {
        try {
            var parsed = JSON.parse(String(value || "[]"))
            return Array.isArray(parsed) ? parsed : []
        } catch (error) {
            return []
        }
    }

    function selectedDayAssetIds() {
        var ids = []
        var seen = ({})
        var blocks = blocksByDay[selectedDayKey] || []
        for (var index = 0; index < blocks.length; ++index) {
            var assetId = String(blocks[index].assetId || "")
            if (assetId.length && !seen[assetId]) {
                seen[assetId] = true
                ids.push(assetId)
            }
        }
        return ids
    }

    function createGroupFromSelectedDay() {
        var ids = selectedDayAssetIds()
        if (!ids.length) {
            feedbackMessage = "The selected day has no fixed programs to save as a group."
            feedbackIsError = true
            return
        }
        var result = channelOS.createStudioGroup(
                    groupNameField.text,
                    ids,
                    groupModeBox.currentText.toLowerCase())
        if (!result || !result.ok) {
            feedbackMessage = result && result.message
                    ? String(result.message) : "Program group could not be saved."
            feedbackIsError = true
            return
        }
        groupsLibrary = result.groups || []
        groupNameField.text = ""
        feedbackMessage = String(result.message)
        feedbackIsError = false
    }

    function assignSelectedGroupAsFiller() {
        if (selectedBlockIndex < 0 || selectedBlockIndex >= calendarBlocks.count) {
            feedbackMessage = "Select a show on the timeline first."
            feedbackIsError = true
            return
        }
        if (groupChoiceBox.currentIndex < 0
                || groupChoiceBox.currentIndex >= groupsLibrary.length) {
            feedbackMessage = "Create or select a reusable group first."
            feedbackIsError = true
            return
        }
        var group = groupsLibrary[groupChoiceBox.currentIndex]
        if (Number(group.availableCount || 0) !== Number(group.memberCount || 0)) {
            feedbackMessage = "Every item in this group must be locally available before assignment."
            feedbackIsError = true
            return
        }
        var groupMedia = group.media || []
        for (var mediaIndex = 0; mediaIndex < groupMedia.length; ++mediaIndex)
            appendSource(groupMedia[mediaIndex].sourceRoot)
        calendarBlocks.setProperty(selectedBlockIndex, "fillerMode",
                                   String(group.mode || "sequential"))
        calendarBlocks.setProperty(selectedBlockIndex, "fillerAssetIdsJson",
                                   JSON.stringify(group.assetIds || []))
        calendarBlocks.setProperty(selectedBlockIndex, "fillerGroupName",
                                   String(group.name || "Program group"))
        dirty = true
        feedbackMessage = "“" + group.name + "” will fill the gap after the selected show."
        feedbackIsError = false
    }

    function clearSelectedShowFiller() {
        if (selectedBlockIndex < 0 || selectedBlockIndex >= calendarBlocks.count)
            return
        calendarBlocks.setProperty(selectedBlockIndex, "fillerMode", "")
        calendarBlocks.setProperty(selectedBlockIndex, "fillerAssetIdsJson", "[]")
        calendarBlocks.setProperty(selectedBlockIndex, "fillerGroupName", "")
        dirty = true
        feedbackMessage = "The selected show now returns to normal channel filler."
        feedbackIsError = false
    }

    function deleteSelectedGroup() {
        if (groupChoiceBox.currentIndex < 0
                || groupChoiceBox.currentIndex >= groupsLibrary.length)
            return
        var group = groupsLibrary[groupChoiceBox.currentIndex]
        var result = channelOS.deleteStudioGroup(String(group.groupId))
        if (!result || !result.ok) {
            feedbackMessage = result && result.message
                    ? String(result.message) : "Program group could not be deleted."
            feedbackIsError = true
            return
        }
        groupsLibrary = result.groups || []
        feedbackMessage = String(result.message)
        feedbackIsError = false
    }

    function blocksForDay(day) {
        return blocksByDay[dayKey(day)] || []
    }

    function visibleBlocks() {
        var startMs = visibleStart().getTime()
        var endMs = visibleEnd().getTime()
        var result = []
        for (var index = 0; index < calendarBlocks.count; ++index) {
            var block = calendarBlocks.get(index)
            var blockMs = new Date(block.startUtc).getTime()
            if (blockMs >= startMs && blockMs < endMs) {
                result.push({
                    modelIndex: index,
                    assetId: block.assetId,
                    title: block.title,
                    path: block.path,
                    sourceRoot: block.sourceRoot,
                    durationSeconds: block.durationSeconds,
                    startUtc: block.startUtc,
                    endUtc: block.endUtc
                })
            }
        }
        return result
    }

    function nextStartForDay(day) {
        var midnight = dateAtLocalMidnight(day)
        var latest = midnight.getTime()
        var target = dayKey(midnight)
        for (var index = 0; index < calendarBlocks.count; ++index) {
            var block = calendarBlocks.get(index)
            if (dayKey(new Date(block.startUtc)) !== target)
                continue
            latest = Math.max(latest, new Date(block.endUtc).getTime())
        }
        return new Date(latest)
    }

    function addAssetToDay(asset, day) {
        if (!asset || Number(asset.durationSeconds || 0) <= 0) {
            feedbackMessage = "This media needs a positive indexed duration before it can be scheduled."
            feedbackIsError = true
            return
        }
        appendSource(asset.sourceRoot)
        var start = nextStartForDay(day)
        appendBlock({
            assetId: asset.assetId,
            title: asset.title,
            path: asset.path,
            sourceRoot: asset.sourceRoot,
            durationSeconds: asset.durationSeconds,
            startUtc: start.toISOString()
        })
        sortBlocks()
        dirty = true
        selectedDayKey = dayKey(day)
        feedbackMessage = "Added “" + asset.title + "” at "
                + Qt.formatTime(start, "h:mm AP") + "."
        feedbackIsError = false
    }

    function moveBlockToDay(blockIndex, day) {
        if (blockIndex < 0 || blockIndex >= calendarBlocks.count)
            return
        var start = nextStartForDay(day)
        var duration = Number(calendarBlocks.get(blockIndex).durationSeconds || 0)
        calendarBlocks.setProperty(blockIndex, "startUtc", start.toISOString())
        calendarBlocks.setProperty(blockIndex, "endUtc",
                                   new Date(start.getTime() + duration * 1000).toISOString())
        sortBlocks()
        dirty = true
        selectedDayKey = dayKey(day)
        feedbackMessage = "Program moved to " + Qt.formatDate(day, "dddd, MMM d") + "."
        feedbackIsError = false
    }

    function swapPrograms(firstIndex, secondIndex) {
        if (firstIndex === secondIndex
                || firstIndex < 0 || secondIndex < 0
                || firstIndex >= calendarBlocks.count
                || secondIndex >= calendarBlocks.count)
            return
        var first = calendarBlocks.get(firstIndex)
        var second = calendarBlocks.get(secondIndex)
        var fields = ["assetId", "title", "path", "sourceRoot", "durationSeconds",
                      "fillerMode", "fillerAssetIdsJson", "fillerGroupName"]
        for (var fieldIndex = 0; fieldIndex < fields.length; ++fieldIndex) {
            var field = fields[fieldIndex]
            var firstValue = first[field]
            calendarBlocks.setProperty(firstIndex, field, second[field])
            calendarBlocks.setProperty(secondIndex, field, firstValue)
        }
        var firstDuration = Number(calendarBlocks.get(firstIndex).durationSeconds || 0)
        var secondDuration = Number(calendarBlocks.get(secondIndex).durationSeconds || 0)
        var firstStart = new Date(calendarBlocks.get(firstIndex).startUtc)
        var secondStart = new Date(calendarBlocks.get(secondIndex).startUtc)
        calendarBlocks.setProperty(firstIndex, "endUtc",
                                   new Date(firstStart.getTime() + firstDuration * 1000).toISOString())
        calendarBlocks.setProperty(secondIndex, "endUtc",
                                   new Date(secondStart.getTime() + secondDuration * 1000).toISOString())
        resolveOverlaps()
        selectedBlockIndex = secondIndex
        dirty = true
    }

    function resolveOverlaps() {
        sortBlocks()
        var previousEnd = null
        for (var index = 0; index < calendarBlocks.count; ++index) {
            var block = calendarBlocks.get(index)
            var start = new Date(block.startUtc)
            if (previousEnd && start.getTime() < previousEnd.getTime()) {
                start = new Date(previousEnd)
                calendarBlocks.setProperty(index, "startUtc", start.toISOString())
            }
            previousEnd = new Date(
                        start.getTime()
                        + Number(block.durationSeconds || 0) * 1000)
            calendarBlocks.setProperty(index, "endUtc", previousEnd.toISOString())
        }
        rebuildBlockIndex()
    }

    function selectedBlockTimeText() {
        if (selectedBlockIndex < 0
                || selectedBlockIndex >= calendarBlocks.count)
            return ""
        return Qt.formatTime(
                    new Date(calendarBlocks.get(selectedBlockIndex).startUtc),
                    "HH:mm")
    }

    function setSelectedTime(value) {
        if (selectedBlockIndex < 0
                || selectedBlockIndex >= calendarBlocks.count)
            return
        var match = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(
                    String(value || "").trim())
        if (!match) {
            feedbackMessage = "Enter an exact local time as HH:MM, for example 20:00."
            feedbackIsError = true
            return
        }
        var block = calendarBlocks.get(selectedBlockIndex)
        var start = new Date(block.startUtc)
        start.setHours(Number(match[1]), Number(match[2]), 0, 0)
        calendarBlocks.setProperty(selectedBlockIndex,
                                   "startUtc", start.toISOString())
        calendarBlocks.setProperty(
                    selectedBlockIndex,
                    "endUtc",
                    new Date(start.getTime()
                             + Number(block.durationSeconds || 0) * 1000).toISOString())
        resolveOverlaps()
        dirty = true
        exactTimeField.text = selectedBlockTimeText()
        feedbackMessage = "Selected program moved to "
                + Qt.formatDateTime(start, "ddd MMM d, h:mm AP") + "."
        feedbackIsError = false
    }

    function nudgeSelected(seconds) {
        if (selectedBlockIndex < 0
                || selectedBlockIndex >= calendarBlocks.count)
            return
        var block = calendarBlocks.get(selectedBlockIndex)
        var start = new Date(block.startUtc)
        start = new Date(start.getTime() + Number(seconds) * 1000)
        calendarBlocks.setProperty(selectedBlockIndex, "startUtc", start.toISOString())
        calendarBlocks.setProperty(
                    selectedBlockIndex,
                    "endUtc",
                    new Date(start.getTime()
                             + Number(block.durationSeconds || 0) * 1000).toISOString())
        resolveOverlaps()
        dirty = true
        feedbackMessage = "Selected program moved to "
                + Qt.formatDateTime(start, "ddd MMM d, h:mm AP") + "."
        feedbackIsError = false
    }

    function removeBlock(blockIndex) {
        if (blockIndex < 0 || blockIndex >= calendarBlocks.count)
            return
        calendarBlocks.remove(blockIndex)
        rebuildBlockIndex()
        selectedBlockIndex = Math.min(blockIndex, calendarBlocks.count - 1)
        dirty = true
        feedbackMessage = "Program removed from the draft. Uncovered time will use filler."
        feedbackIsError = false
    }

    function autoFillVisibleRange() {
        if (autoFillBusy)
            return
        if (!channelNameField.text.trim().length) {
            channelNameField.text = "Channel " + channelNumberField.text
        }
        var result = channelOS.startStudioAutoFill(
                    editorObject(),
                    visibleStart().toISOString(),
                    visibleEnd().toISOString())
        if (!result || !result.ok) {
            feedbackMessage = result && result.message
                    ? String(result.message)
                    : "Auto Fill failed."
            feedbackIsError = true
            return
        }

        feedbackMessage = String(result.message)
        feedbackIsError = false
    }

    function acceptAutoFillResult(result) {
        if (!result || !result.ok)
            return
        var startMs = new Date(result.startUtc).getTime()
        var endMs = new Date(result.endUtc).getTime()
        var replacement = []
        for (var index = 0; index < calendarBlocks.count; ++index) {
            var existing = calendarBlocks.get(index)
            var blockMs = new Date(existing.startUtc).getTime()
            var blockEndMs = new Date(existing.endUtc).getTime()
            if (!(blockMs < endMs && blockEndMs > startMs))
                replacement.push(blockObject(existing))
        }
        var blocks = result.blocks || []
        for (var blockIndex = 0; blockIndex < blocks.length; ++blockIndex)
            replacement.push(blockObject(blocks[blockIndex]))
        replacement.sort(function(left, right) {
            return new Date(left.startUtc).getTime()
                    - new Date(right.startUtc).getTime()
        })

        // ListModel insertion is intentionally chunked. A two-month range can
        // contain thousands of short clips, and appending them in one JavaScript
        // turn would freeze the same GUI thread the background worker protects.
        pendingAutoFillBlocks = replacement
        pendingAutoFillIndex = 0
        pendingAutoFillMessage = String(result.message)
        autoFillApplying = true
        calendarBlocks.clear()
        autoFillApplyTimer.start()
    }

    function applyAutoFillBatch() {
        var endIndex = Math.min(pendingAutoFillIndex + 128,
                                pendingAutoFillBlocks.length)
        while (pendingAutoFillIndex < endIndex) {
            calendarBlocks.append(
                        pendingAutoFillBlocks[pendingAutoFillIndex])
            ++pendingAutoFillIndex
        }
        if (pendingAutoFillIndex < pendingAutoFillBlocks.length)
            return

        autoFillApplyTimer.stop()
        pendingAutoFillBlocks = []
        pendingAutoFillIndex = 0
        autoFillApplying = false
        rebuildBlockIndex()
        selectedBlockIndex = calendarBlocks.count ? 0 : -1
        dirty = true
        feedbackMessage = pendingAutoFillMessage
                + ". Drag, reorder, or remove anything before Apply."
        pendingAutoFillMessage = ""
        feedbackIsError = false
        if (pendingExitDestination.length)
            requestExit(pendingExitDestination)
    }

    function clearVisibleRange() {
        if (autoFillBusy)
            return
        var startMs = visibleStart().getTime()
        var endMs = visibleEnd().getTime()
        var removed = 0
        for (var index = calendarBlocks.count - 1; index >= 0; --index) {
            var existing = calendarBlocks.get(index)
            var blockMs = new Date(existing.startUtc).getTime()
            var blockEndMs = new Date(existing.endUtc).getTime()
            if (blockMs < endMs && blockEndMs > startMs) {
                calendarBlocks.remove(index)
                ++removed
            }
        }
        rebuildBlockIndex()
        dirty = dirty || removed > 0
        selectedBlockIndex = -1
        feedbackMessage = removed > 0
                ? "Cleared " + removed + " fixed program blocks. The channel filler will cover those gaps."
                : "There were no fixed programs in this range."
        feedbackIsError = false
    }

    function applyDraft() {
        if (autoFillBusy) {
            feedbackMessage = "Wait for Auto Fill to finish, or cancel it, before applying."
            feedbackIsError = true
            return
        }
        if (calendarBlocks.count === 0) {
            feedbackMessage = "Add or Auto Fill at least one program before applying a calendar channel."
            feedbackIsError = true
            return
        }
        var result = editingChannelNumber > 0
                ? channelOS.updateChannel(editingChannelNumber, editorObject())
                : channelOS.createChannel(editorObject())
        if (!result || !result.ok) {
            feedbackMessage = result && result.message
                    ? String(result.message)
                    : "Channel could not be applied."
            feedbackIsError = true
            return
        }
        editingChannelNumber = Number(result.channelNumber || editingChannelNumber)
        if (hostWindow)
            hostWindow.studioChannelNumber = editingChannelNumber
        dirty = false
        feedbackMessage = String(result.message)
        feedbackIsError = false
    }

    function navigateRange(amount) {
        if (viewMode === "month")
            anchorDate = new Date(anchorDate.getFullYear(),
                                  anchorDate.getMonth() + Number(amount), 1)
        else
            anchorDate = addDays(anchorDate, Number(amount) * 7)
    }

    function requestExit(destination) {
        pendingExitDestination = String(destination)
        if (autoFillApplying) {
            feedbackMessage = "Finishing the prepared schedule before leaving Studio…"
            feedbackIsError = false
            return
        }
        if (autoFillState.active) {
            channelOS.cancelStudioAutoFill()
            feedbackMessage = "Cancelling Auto Fill before leaving Studio…"
            feedbackIsError = false
            return
        }
        if (dirty) {
            discardDraftDialog.open()
            return
        }
        finishExit()
    }

    function finishExit() {
        var destination = pendingExitDestination || "home"
        pendingExitDestination = ""
        dirty = false
        if (hostWindow)
            hostWindow.screen = destination
    }

    function leaveStudio() {
        requestExit("home")
    }

    function openBroadcaster() {
        requestExit("broadcaster")
    }

    function handleControllerIntent(intent) {
        if (!hostWindow || hostWindow.screen !== "studio")
            return
        if (autoFillBusy) {
            if (intent === "BACK")
                requestExit("home")
            return
        }
        if (intent === "BACK")
            leaveStudio()
        else if (intent === "LEFT")
            navigateRange(-1)
        else if (intent === "RIGHT")
            navigateRange(1)
    }

    onHostWindowChanged: {
        if (hostWindow && hostWindow.screen === "studio")
            loadDraft()
    }

    Connections {
        target: studioRoot.hostWindow
        function onScreenChanged() {
            if (studioRoot.hostWindow.screen === "studio")
                studioRoot.loadDraft()
            else if (studioRoot.autoFillBusy)
                channelOS.cancelStudioAutoFill()
        }
    }

    Timer {
        id: autoFillApplyTimer
        interval: 0
        repeat: true
        onTriggered: studioRoot.applyAutoFillBatch()
    }

    Connections {
        target: channelOS
        function onStudioAutoFillChanged() {
            var state = channelOS.studioAutoFill
            if (!state)
                return
            if (state.message)
                studioRoot.feedbackMessage = String(state.message)
            studioRoot.feedbackIsError = state.phase === "error"
            if (!state.active && state.phase === "cancelled"
                    && studioRoot.pendingExitDestination.length)
                studioRoot.requestExit(studioRoot.pendingExitDestination)
        }
        function onStudioAutoFillCompleted(result) {
            studioRoot.acceptAutoFillResult(result)
        }
    }

    FocusScope {
        id: studioSurface
        anchors.fill: parent
        visible: studioRoot.hostWindow && studioRoot.hostWindow.screen === "studio"
        focus: visible

        Shortcut {
            sequence: "Esc"
            enabled: studioSurface.visible && !discardDraftDialog.visible
                     && !studioRoot.autoFillBusy
            onActivated: studioRoot.leaveStudio()
        }

        Shortcut {
            sequence: "Ctrl+S"
            enabled: studioSurface.visible && !discardDraftDialog.visible
                     && !studioRoot.autoFillBusy
            onActivated: studioRoot.applyDraft()
        }

        Rectangle {
            anchors.fill: parent
            color: studioRoot.appBackground
        }

        Rectangle {
            id: studioHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 146
            color: "#071322"
            border.color: studioRoot.line

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.topMargin: 14
                anchors.bottomMargin: 12
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    Button {
                        text: "‹ Home"
                        onClicked: studioRoot.leaveStudio()
                    }

                    Button {
                        text: "Channels"
                        onClicked: studioRoot.openBroadcaster()
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Text {
                            text: editingChannelNumber > 0
                                  ? "CHANNEL STUDIO  /  EDIT " + channelNumberField.text
                                  : "CHANNEL STUDIO  /  NEW CHANNEL"
                            color: studioRoot.textPrimary
                            font.pixelSize: 22
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "Calendar programming with editable Broadcast Clock blocks"
                            color: studioRoot.textSecondary
                            font.pixelSize: 12
                        }
                    }

                    Rectangle {
                        visible: dirty
                        radius: 12
                        color: "#4b3717"
                        border.color: studioRoot.warning
                        implicitWidth: unsavedText.implicitWidth + 20
                        implicitHeight: 28
                        Text {
                            id: unsavedText
                            anchors.centerIn: parent
                            text: "UNAPPLIED DRAFT"
                            color: studioRoot.warning
                            font.pixelSize: 11
                            font.weight: Font.Bold
                        }
                    }

                    Button {
                        text: "Apply to Channel"
                        highlighted: true
                        enabled: !studioRoot.autoFillBusy
                        onClicked: studioRoot.applyDraft()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Label { text: "CH"; color: studioRoot.textSecondary }
                    TextField {
                        id: channelNumberField
                        Layout.preferredWidth: 72
                        placeholderText: "001"
                        inputMethodHints: Qt.ImhDigitsOnly
                        onTextEdited: studioRoot.dirty = true
                    }
                    TextField {
                        id: channelNameField
                        Layout.preferredWidth: 230
                        placeholderText: "Channel name"
                        onTextEdited: studioRoot.dirty = true
                    }
                    TextField {
                        id: descriptionField
                        Layout.fillWidth: true
                        placeholderText: "Optional description"
                        onTextEdited: studioRoot.dirty = true
                    }
                    Label { text: "GAPS"; color: studioRoot.textSecondary }
                    ComboBox {
                        id: fillerModeBox
                        model: ["Sequential", "Shuffle"]
                        Layout.preferredWidth: 130
                        onActivated: studioRoot.dirty = true
                    }
                    Label {
                        visible: fillerModeBox.currentIndex === 1
                        text: "NO REPEAT (DAYS)"
                        color: studioRoot.textSecondary
                    }
                    SpinBox {
                        id: repeatDays
                        visible: fillerModeBox.currentIndex === 1
                        from: 0
                        to: 365
                        editable: true
                        onValueModified: studioRoot.dirty = true
                    }
                }
            }
        }

        Rectangle {
            id: mediaPanel
            anchors.left: parent.left
            anchors.top: studioHeader.bottom
            anchors.bottom: timelinePanel.top
            width: Math.max(250, parent.width * 0.20)
            color: studioRoot.panel
            border.color: studioRoot.line

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Text {
                    text: "MEDIA BIN"
                    color: studioRoot.textPrimary
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
                Text {
                    text: mediaLibrary.length + " indexed assets • drag or click +"
                    color: studioRoot.textSecondary
                    font.pixelSize: 11
                }
                TextField {
                    id: mediaSearch
                    Layout.fillWidth: true
                    placeholderText: "Search indexed media…"
                }

                Text {
                    text: "FILLER SOURCES  •  " + draftSources.count + " selected"
                    color: studioRoot.textSecondary
                    font.pixelSize: 10
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 5
                    ComboBox {
                        id: fillerSourceBox
                        Layout.fillWidth: true
                        model: studioRoot.sourceChoices()
                    }
                    Button {
                        text: "Add"
                        enabled: fillerSourceBox.count > 0
                        onClicked: {
                            studioRoot.appendSource(fillerSourceBox.currentText)
                            studioRoot.dirty = true
                        }
                    }
                    Button {
                        text: "Clear"
                        enabled: draftSources.count > 0
                        onClicked: {
                            draftSources.clear()
                            studioRoot.dirty = true
                        }
                    }
                }

                ListView {
                    id: mediaList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 7
                    model: studioRoot.filteredMedia()

                    delegate: Rectangle {
                        id: mediaCard
                        required property var modelData
                        width: mediaList.width
                        height: 76
                        radius: 7
                        color: mediaMouse.containsMouse
                               ? "#14304a" : studioRoot.panelRaised
                        border.color: mediaMouse.containsMouse
                                      ? studioRoot.accentBright : studioRoot.line

                        property var assetData: modelData

                        Item {
                            id: mediaDragProxy
                            width: 1
                            height: 1
                            Drag.active: mediaMouse.drag.active
                            Drag.keys: ["channelos-media"]
                            Drag.hotSpot.x: 0
                            Drag.hotSpot.y: 0
                            Drag.source: mediaCard
                        }

                        Column {
                            anchors.left: parent.left
                            anchors.right: addMediaButton.left
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 12
                            anchors.rightMargin: 8
                            spacing: 4
                            Text {
                                width: parent.width
                                text: String(mediaCard.assetData.title || "Untitled")
                                color: studioRoot.textPrimary
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width
                                text: String(mediaCard.assetData.containerFormat || "MEDIA")
                                      + "  •  "
                                      + studioRoot.durationLabel(mediaCard.assetData.durationSeconds)
                                color: studioRoot.textSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }

                        Button {
                            id: addMediaButton
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.rightMargin: 8
                            width: 34
                            height: 34
                            text: "+"
                            onClicked: studioRoot.addAssetToDay(
                                           mediaCard.assetData,
                                           new Date(studioRoot.selectedDayKey + "T00:00:00"))
                        }

                        MouseArea {
                            id: mediaMouse
                            anchors.left: parent.left
                            anchors.right: addMediaButton.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            hoverEnabled: true
                            cursorShape: Qt.OpenHandCursor
                            drag.target: mediaDragProxy
                            onReleased: {
                                mediaDragProxy.Drag.drop()
                                mediaDragProxy.x = 0
                                mediaDragProxy.y = 0
                            }
                            onDoubleClicked: studioRoot.addAssetToDay(
                                                 mediaCard.assetData,
                                                 new Date(studioRoot.selectedDayKey + "T00:00:00"))
                        }
                    }

                    ScrollBar.vertical: ScrollBar { }
                }
            }
        }

        Rectangle {
            id: calendarPanel
            anchors.left: mediaPanel.right
            anchors.right: parent.right
            anchors.top: studioHeader.bottom
            anchors.bottom: timelinePanel.top
            color: "#091827"
            border.color: studioRoot.line

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Button { text: "‹"; onClicked: studioRoot.navigateRange(-1) }
                    Button { text: "Today"; onClicked: studioRoot.anchorDate = new Date() }
                    Button { text: "›"; onClicked: studioRoot.navigateRange(1) }

                    Text {
                        Layout.fillWidth: true
                        text: studioRoot.rangeLabel()
                        color: studioRoot.textPrimary
                        font.pixelSize: 20
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Button {
                        text: "Week"
                        checkable: true
                        checked: studioRoot.viewMode === "week"
                        onClicked: studioRoot.viewMode = "week"
                    }
                    Button {
                        text: "Month"
                        checkable: true
                        checked: studioRoot.viewMode === "month"
                        onClicked: studioRoot.viewMode = "month"
                    }
                    Button {
                        text: "Clear Range"
                        enabled: !studioRoot.autoFillBusy
                        onClicked: studioRoot.clearVisibleRange()
                    }
                    Button {
                        text: "Auto Fill Range"
                        highlighted: true
                        enabled: !studioRoot.autoFillBusy
                        onClicked: studioRoot.autoFillVisibleRange()
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Row {
                        id: weekGrid
                        anchors.fill: parent
                        spacing: 7
                        visible: studioRoot.viewMode === "week"

                        Repeater {
                            model: 7

                            Rectangle {
                                id: weekDay
                                required property int index
                                property date columnDate: studioRoot.addDays(
                                                              studioRoot.startOfWeek(studioRoot.anchorDate),
                                                              index)
                                width: (weekGrid.width - weekGrid.spacing * 6) / 7
                                height: weekGrid.height
                                radius: 7
                                color: studioRoot.selectedDayKey === studioRoot.dayKey(columnDate)
                                       ? "#102d49" : studioRoot.panel
                                border.color: studioRoot.dayKey(columnDate) === studioRoot.dayKey(new Date())
                                              ? studioRoot.accentBright : studioRoot.line
                                border.width: studioRoot.dayKey(columnDate) === studioRoot.dayKey(new Date()) ? 2 : 1

                                DropArea {
                                    anchors.fill: parent
                                    keys: ["channelos-media", "channelos-block"]
                                    onDropped: function(drop) {
                                        if (!drop.source)
                                            return
                                        if (drop.keys.indexOf("channelos-media") >= 0)
                                            studioRoot.addAssetToDay(drop.source.assetData, weekDay.columnDate)
                                        else if (drop.keys.indexOf("channelos-block") >= 0)
                                            studioRoot.moveBlockToDay(drop.source.blockIndex, weekDay.columnDate)
                                        drop.acceptProposedAction()
                                    }
                                }

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 7

                                    Text {
                                        Layout.fillWidth: true
                                        text: Qt.formatDate(weekDay.columnDate, "ddd").toUpperCase()
                                        color: studioRoot.textSecondary
                                        font.pixelSize: 11
                                        horizontalAlignment: Text.AlignHCenter
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: Qt.formatDate(weekDay.columnDate, "d")
                                        color: studioRoot.textPrimary
                                        font.pixelSize: 20
                                        font.weight: Font.DemiBold
                                        horizontalAlignment: Text.AlignHCenter
                                    }

                                    ListView {
                                        id: dayPrograms
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        clip: true
                                        spacing: 5
                                        model: studioRoot.blocksForDay(weekDay.columnDate)

                                        delegate: Rectangle {
                                            id: dayProgram
                                            required property var modelData
                                            width: dayPrograms.width
                                            height: 55
                                            radius: 5
                                            color: Number(modelData.modelIndex) === studioRoot.selectedBlockIndex
                                                   ? "#14558a" : studioRoot.panelRaised
                                            border.color: Number(modelData.modelIndex) === studioRoot.selectedBlockIndex
                                                          ? studioRoot.accentBright : studioRoot.line
                                            Text {
                                                anchors.left: parent.left
                                                anchors.right: parent.right
                                                anchors.top: parent.top
                                                anchors.margins: 6
                                                text: studioRoot.formatTime(dayProgram.modelData.startUtc)
                                                      + "  " + String(dayProgram.modelData.title)
                                                color: studioRoot.textPrimary
                                                font.pixelSize: 10
                                                elide: Text.ElideRight
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                onClicked: {
                                                    studioRoot.selectedDayKey = studioRoot.dayKey(weekDay.columnDate)
                                                    studioRoot.selectedBlockIndex = Number(dayProgram.modelData.modelIndex)
                                                }
                                            }
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "+ DROP MEDIA"
                                        color: studioRoot.textSecondary
                                        font.pixelSize: 9
                                        horizontalAlignment: Text.AlignHCenter
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    z: -1
                                    onClicked: studioRoot.selectedDayKey = studioRoot.dayKey(parent.columnDate)
                                }
                            }
                        }
                    }

                    Grid {
                        id: monthGrid
                        anchors.fill: parent
                        columns: 7
                        rows: 6
                        spacing: 6
                        visible: studioRoot.viewMode === "month"

                        Repeater {
                            model: 42

                            Rectangle {
                                id: monthDay
                                required property int index
                                property date cellDate: studioRoot.addDays(
                                                            studioRoot.monthGridStart(), index)
                                property var cellBlocks: studioRoot.blocksForDay(cellDate)
                                width: (monthGrid.width - monthGrid.spacing * 6) / 7
                                height: (monthGrid.height - monthGrid.spacing * 5) / 6
                                radius: 6
                                color: studioRoot.selectedDayKey === studioRoot.dayKey(cellDate)
                                       ? "#123b60" : studioRoot.panel
                                opacity: cellDate.getMonth() === studioRoot.anchorDate.getMonth()
                                         ? 1.0 : 0.52
                                border.color: studioRoot.dayKey(cellDate) === studioRoot.dayKey(new Date())
                                              ? studioRoot.accentBright : studioRoot.line

                                DropArea {
                                    anchors.fill: parent
                                    keys: ["channelos-media", "channelos-block"]
                                    onDropped: function(drop) {
                                        if (!drop.source)
                                            return
                                        if (drop.keys.indexOf("channelos-media") >= 0)
                                            studioRoot.addAssetToDay(drop.source.assetData, monthDay.cellDate)
                                        else if (drop.keys.indexOf("channelos-block") >= 0)
                                            studioRoot.moveBlockToDay(drop.source.blockIndex, monthDay.cellDate)
                                        drop.acceptProposedAction()
                                    }
                                }

                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 7
                                    spacing: 4
                                    Text {
                                        text: Qt.formatDate(monthDay.cellDate, "ddd d")
                                        color: studioRoot.textPrimary
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        width: parent.width
                                        text: monthDay.cellBlocks.length
                                              ? monthDay.cellBlocks.length + " programs"
                                              : "Filler"
                                        color: monthDay.cellBlocks.length
                                               ? studioRoot.accentBright : studioRoot.textSecondary
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        width: parent.width
                                        visible: monthDay.cellBlocks.length > 0
                                        text: visible
                                              ? String(monthDay.cellBlocks[0].title)
                                              : ""
                                        color: studioRoot.textSecondary
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: {
                                        studioRoot.anchorDate = monthDay.cellDate
                                        studioRoot.selectedDayKey = studioRoot.dayKey(monthDay.cellDate)
                                        studioRoot.viewMode = "week"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            id: timelinePanel
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: studioFooter.top
            height: 210
            color: "#06111e"
            border.color: studioRoot.line

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "PROGRAM TIMELINE"
                        color: studioRoot.textPrimary
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Drag cards to swap their slots • drag into calendar to move days • × removes a fixed block"
                        color: studioRoot.textSecondary
                        font.pixelSize: 11
                    }
                    Text {
                        text: studioRoot.visibleBlocks().length + " fixed blocks in range"
                        color: studioRoot.accentBright
                        font.pixelSize: 11
                    }
                    Button {
                        text: "Groups & Show Filler"
                        onClicked: programGroupDialog.open()
                    }
                    Button {
                        text: "−15 min"
                        enabled: studioRoot.selectedBlockIndex >= 0
                        onClicked: studioRoot.nudgeSelected(-900)
                    }
                    Button {
                        text: "+15 min"
                        enabled: studioRoot.selectedBlockIndex >= 0
                        onClicked: studioRoot.nudgeSelected(900)
                    }
                    TextField {
                        id: exactTimeField
                        Layout.preferredWidth: 88
                        enabled: studioRoot.selectedBlockIndex >= 0
                        placeholderText: "HH:MM"
                        text: studioRoot.selectedBlockTimeText()
                        validator: RegularExpressionValidator {
                            regularExpression: /^([01]?\d|2[0-3]):[0-5]\d$/
                        }
                        onAccepted: studioRoot.setSelectedTime(text)
                        ToolTip.visible: hovered
                        ToolTip.text: "Exact local start time"
                    }
                }

                ListView {
                    id: programTimeline
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    orientation: ListView.Horizontal
                    spacing: 8
                    clip: true
                    model: studioRoot.visibleBlocks()

                    delegate: Rectangle {
                        id: timelineCard
                        required property var modelData
                        property int blockIndex: Number(modelData.modelIndex)
                        property var blockData: modelData
                        width: Math.max(150, Math.min(300,
                                  130 + Math.log(Math.max(2, Number(modelData.durationSeconds))) * 12))
                        height: programTimeline.height - 12
                        radius: 7
                        color: blockIndex === studioRoot.selectedBlockIndex
                               ? "#14558a" : studioRoot.panelRaised
                        border.color: timelineDrop.containsDrag
                                      ? studioRoot.warning
                                      : (blockIndex === studioRoot.selectedBlockIndex
                                         ? studioRoot.accentBright : studioRoot.line)
                        border.width: timelineDrop.containsDrag ? 2 : 1

                        Item {
                            id: timelineDragProxy
                            width: 1
                            height: 1
                            Drag.active: timelineMouse.drag.active
                            Drag.keys: ["channelos-block"]
                            Drag.hotSpot.x: 0
                            Drag.hotSpot.y: 0
                            Drag.source: timelineCard
                        }

                        DropArea {
                            id: timelineDrop
                            anchors.fill: parent
                            keys: ["channelos-block"]
                            onDropped: function(drop) {
                                if (drop.source)
                                    studioRoot.swapPrograms(drop.source.blockIndex,
                                                            timelineCard.blockIndex)
                                drop.acceptProposedAction()
                            }
                        }

                        Column {
                            anchors.left: parent.left
                            anchors.right: removeProgram.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.margins: 10
                            spacing: 5
                            Text {
                                width: parent.width
                                text: studioRoot.formatTime(timelineCard.blockData.startUtc)
                                      + "  •  "
                                      + Qt.formatDate(new Date(timelineCard.blockData.startUtc), "ddd MMM d")
                                color: studioRoot.accentBright
                                font.pixelSize: 10
                            }
                            Text {
                                width: parent.width
                                text: String(timelineCard.blockData.title)
                                color: studioRoot.textPrimary
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width
                                text: studioRoot.durationLabel(timelineCard.blockData.durationSeconds)
                                color: studioRoot.textSecondary
                                font.pixelSize: 10
                            }
                            Text {
                                width: parent.width
                                visible: String(timelineCard.blockData.fillerGroupName || "").length > 0
                                text: "AFTER SHOW  •  "
                                      + String(timelineCard.blockData.fillerGroupName || "")
                                color: studioRoot.warning
                                font.pixelSize: 9
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Rectangle {
                                width: parent.width
                                height: 4
                                radius: 2
                                color: studioRoot.accent
                            }
                        }

                        Button {
                            id: removeProgram
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 6
                            width: 30
                            height: 30
                            text: "×"
                            onClicked: studioRoot.removeBlock(timelineCard.blockIndex)
                        }

                        MouseArea {
                            id: timelineMouse
                            anchors.left: parent.left
                            anchors.right: removeProgram.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            hoverEnabled: true
                            cursorShape: Qt.OpenHandCursor
                            drag.target: timelineDragProxy
                            onPressed: studioRoot.selectedBlockIndex = timelineCard.blockIndex
                            onReleased: {
                                timelineDragProxy.Drag.drop()
                                timelineDragProxy.x = 0
                                timelineDragProxy.y = 0
                            }
                        }
                    }

                    ScrollBar.horizontal: ScrollBar { }

                    Text {
                        anchors.centerIn: parent
                        visible: programTimeline.count === 0
                        text: "No fixed programs in this range — filler remains on air.\nAuto Fill the range or drag media onto a day."
                        color: studioRoot.textSecondary
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
        }

        Rectangle {
            id: studioFooter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 54
            color: studioRoot.feedbackIsError ? "#32151b" : "#071322"
            border.color: studioRoot.feedbackIsError
                          ? studioRoot.danger : studioRoot.line

            Text {
                anchors.left: parent.left
                anchors.right: footerHints.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 20
                text: studioRoot.feedbackMessage
                      || "Studio is a detached draft. Apply validates, backs up, and reloads the live lineup."
                color: studioRoot.feedbackIsError
                       ? studioRoot.danger : studioRoot.textSecondary
                font.pixelSize: 12
                elide: Text.ElideRight
            }
            Text {
                id: footerHints
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 20
                text: "CTRL+S  Apply     ESC  Back"
                color: studioRoot.textSecondary
                font.pixelSize: 11
            }
        }

        Rectangle {
            id: autoFillOverlay
            anchors.fill: parent
            visible: studioRoot.autoFillBusy
            z: 200
            color: "#cc02070d"

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
                hoverEnabled: true
            }

            Rectangle {
                anchors.centerIn: parent
                width: Math.min(parent.width - 80, 540)
                height: 230
                radius: 12
                color: studioRoot.panelRaised
                border.color: studioRoot.accent
                border.width: 2

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 28
                    spacing: 16

                    Text {
                        Layout.fillWidth: true
                        text: "BUILDING DETACHED SCHEDULE"
                        color: studioRoot.accentBright
                        font.pixelSize: 13
                        font.weight: Font.Bold
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Text {
                        Layout.fillWidth: true
                        text: studioRoot.autoFillApplying
                              ? "Adding prepared blocks to the detached draft…"
                              : String(studioRoot.autoFillState.message
                                       || "Preparing Studio Auto Fill…")
                        color: studioRoot.textPrimary
                        font.pixelSize: 16
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                    }

                    ProgressBar {
                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        value: studioRoot.autoFillApplying
                               ? studioRoot.autoFillApplyPercent
                               : Number(studioRoot.autoFillState.percent || 0)
                        indeterminate: !studioRoot.autoFillApplying
                                       && Number(studioRoot.autoFillState.total || 0) <= 0
                    }

                    Text {
                        Layout.fillWidth: true
                        text: studioRoot.autoFillApplying
                              ? studioRoot.autoFillApplyPercent + "%"
                              : Number(studioRoot.autoFillState.total || 0) > 0
                              ? Number(studioRoot.autoFillState.percent || 0) + "%"
                              : "Checking local media…"
                        color: studioRoot.textSecondary
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Button {
                        Layout.alignment: Qt.AlignHCenter
                        text: studioRoot.autoFillApplying
                              ? "Applying schedule…"
                              : studioRoot.autoFillState.phase === "cancelling"
                              ? "Cancelling…" : "Cancel Auto Fill"
                        enabled: !studioRoot.autoFillApplying
                                 && studioRoot.autoFillState.phase !== "cancelling"
                        onClicked: channelOS.cancelStudioAutoFill()
                    }
                }
            }
        }
    }

    Dialog {
        id: discardDraftDialog
        anchors.centerIn: parent
        modal: true
        title: "Discard unapplied Channel Studio changes?"
        standardButtons: Dialog.Yes | Dialog.Cancel
        onAccepted: studioRoot.finishExit()
        onRejected: studioRoot.pendingExitDestination = ""

        contentItem: Text {
            width: 390
            text: "This draft has changes that have not been applied to the channel."
            color: studioRoot.textPrimary
            wrapMode: Text.Wrap
        }
    }

    Dialog {
        id: programGroupDialog
        anchors.centerIn: parent
        width: Math.min(studioRoot.width - 80, 620)
        modal: true
        title: "Reusable Groups & Show-Specific Filler"
        standardButtons: Dialog.Close

        contentItem: ColumnLayout {
            width: 560
            spacing: 12

            Text {
                Layout.fillWidth: true
                text: "Save the unique fixed programs on "
                      + Qt.formatDate(new Date(studioRoot.selectedDayKey + "T00:00:00"),
                                      "dddd, MMMM d")
                      + " as a group reusable by every Channel Studio draft."
                color: studioRoot.textSecondary
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                TextField {
                    id: groupNameField
                    Layout.fillWidth: true
                    placeholderText: "Group name — e.g. Saturday Cartoons"
                }
                ComboBox {
                    id: groupModeBox
                    model: ["Sequential", "Shuffle"]
                    Layout.preferredWidth: 130
                }
                Button {
                    text: "Save Day as Group"
                    enabled: groupNameField.text.trim().length > 0
                             && studioRoot.selectedDayAssetIds().length > 0
                    onClicked: studioRoot.createGroupFromSelectedDay()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: studioRoot.line
            }

            Text {
                Layout.fillWidth: true
                text: "Attach a group to the selected show. Once that show ends, "
                      + "ChannelOS uses this group for the gap until the next fixed block."
                color: studioRoot.textPrimary
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                ComboBox {
                    id: groupChoiceBox
                    Layout.fillWidth: true
                    model: studioRoot.groupsLibrary
                    textRole: "name"
                }
                Button {
                    text: "Use After Selected Show"
                    enabled: groupChoiceBox.count > 0
                             && groupChoiceBox.currentIndex >= 0
                             && groupChoiceBox.currentIndex < studioRoot.groupsLibrary.length
                             && studioRoot.selectedBlockIndex >= 0
                             && Number(studioRoot.groupsLibrary[groupChoiceBox.currentIndex].availableCount || 0)
                                === Number(studioRoot.groupsLibrary[groupChoiceBox.currentIndex].memberCount || 0)
                    onClicked: studioRoot.assignSelectedGroupAsFiller()
                }
            }

            Text {
                Layout.fillWidth: true
                text: groupChoiceBox.currentIndex >= 0
                      && groupChoiceBox.currentIndex < studioRoot.groupsLibrary.length
                      ? Number(studioRoot.groupsLibrary[groupChoiceBox.currentIndex].availableCount || 0)
                        + " of "
                        + Number(studioRoot.groupsLibrary[groupChoiceBox.currentIndex].memberCount || 0)
                        + " local items available • "
                        + String(studioRoot.groupsLibrary[groupChoiceBox.currentIndex].mode || "sequential")
                      : "No reusable groups saved yet."
                color: studioRoot.textSecondary
                font.pixelSize: 11
            }

            RowLayout {
                Layout.fillWidth: true
                Button {
                    text: "Use Normal Filler After Show"
                    enabled: studioRoot.selectedBlockIndex >= 0
                    onClicked: studioRoot.clearSelectedShowFiller()
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Delete Reusable Group"
                    enabled: groupChoiceBox.count > 0
                    onClicked: studioRoot.deleteSelectedGroup()
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Applied channels embed the group's asset IDs. Deleting or editing "
                      + "the reusable authoring group cannot silently change a live channel."
                color: studioRoot.warning
                font.pixelSize: 10
                wrapMode: Text.Wrap
            }
        }
    }

    ListModel { id: draftSources }
    ListModel { id: calendarBlocks }
}
