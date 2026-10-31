"""Whole-clip ad schedules shared by authoring and the broadcast runtime."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .ad_break_engine import BreakPlan, PlannedSegment


def ordered_pool(media, settings):
    """The visible source order, then natural relative filenames; one canonical copy."""
    roots = [source.path.resolve(strict=False) for source in settings.sources]
    explicit = {asset_id: index for index, asset_id in enumerate(settings.asset_ids)}

    def key(item):
        path = item.location.path.resolve(strict=False)
        for index, root in enumerate(roots):
            if path.is_relative_to(root):
                return index, tuple(int(x) if x.isdigit() else x.casefold()
                                    for x in re.split(r"(\d+)", str(path.relative_to(root)))), item.asset.asset_id
        return len(roots), ("", explicit.get(item.asset.asset_id, 0)), item.asset.asset_id

    seen = set()
    return tuple(item for item in sorted(media, key=key)
                 if item.asset.asset_id not in seen and not seen.add(item.asset.asset_id))


class SimpleRotation:
    def __init__(self, media, settings, channel_number, *, store=None, before=None):
        self.media = ordered_pool(media, settings)
        self.by_id = {item.asset.asset_id: item for item in self.media}
        self.order = settings.play_order
        self.channel = channel_number
        self.revision = hashlib.sha256(json.dumps(
            [self.order, list(self.by_id)], separators=(",", ":")
        ).encode()).hexdigest()
        self.cycle = -1
        self.remaining = []
        self.previous = ""
        if store is not None and before is not None:
            row = store.connection.execute("""
                SELECT p.plan_id FROM ad_break_plans p
                JOIN ad_plan_metadata m ON p.plan_id = m.plan_id
                WHERE p.channel_number = ? AND p.scheduled_at < ?
                  AND json_extract(m.payload, '$.rotation_revision') = ?
                  AND (p.plan_id NOT IN (SELECT plan_id FROM ad_retired_plans)
                       OR p.plan_id IN (SELECT plan_id FROM ad_break_history))
                ORDER BY p.scheduled_at DESC, p.plan_id DESC LIMIT 1
            """, (channel_number, before.isoformat(), self.revision)).fetchone()
            if row:
                plan = store.load_plan(row[0])
                self.cycle = plan.rotation_cycle
                self.remaining = list(plan.rotation_remaining)
                ads = [part.asset_id for part in plan.segments if part.event_type == "advertisement"]
                self.previous = ads[-1] if ads else ""

    def take(self, budget=math.inf):
        if not self.media:
            return None
        if not self.remaining:
            self.cycle += 1
            self.remaining = list(self.by_id)
            if self.order == "shuffle":
                self.remaining.sort(key=lambda asset_id: hashlib.sha256(
                    f"{self.channel}:{self.revision}:{self.cycle}:{asset_id}".encode()
                ).digest())
                if len(self.remaining) > 1 and self.remaining[0] == self.previous:
                    self.remaining = self.remaining[1:] + self.remaining[:1]
        item = self.by_id[self.remaining[0]]
        if float(item.asset.duration_seconds) > budget + .0001:
            return None  # Preserve queue order; do not skip a long clip to find a shorter one.
        self.previous = self.remaining.pop(0)
        return item


def next_clock(at, settings):
    interval, offset = settings.clock_interval_seconds, settings.clock_offset_seconds
    stamp = (math.floor((at.timestamp() + offset + .00001) / interval) + 1) * interval - offset
    return datetime.fromtimestamp(stamp, timezone.utc)


def plan_program(program, starts_at, settings, revision, channel_number, occurrence_id,
                 rotation, *, next_start=None, activation=None, filler_media=()):
    """Plan a complete show, its clock interruptions and its following ad window."""
    remaining = float(program.asset.duration_seconds)
    cursor = starts_at
    plans = []

    def make_break(at, trigger, *, fill_to=None):
        item = rotation.take()
        if item is None:
            return at
        if next_start is not None and at + timedelta(seconds=float(item.asset.duration_seconds)) > next_start:
            raise ValueError("There is no room for a complete ad before the next fixed show. Clear the range and Auto Fill again, or move the next show.")
        parts = []
        elapsed = 0.0

        def add(media, seconds, event_type="advertisement"):
            nonlocal elapsed
            parts.append(PlannedSegment(
                media.asset.asset_id, elapsed, 0, seconds, media_path=str(media.location.path),
                original_duration_seconds=float(media.asset.duration_seconds), event_type=event_type,
            ))
            elapsed += seconds

        add(item, float(item.asset.duration_seconds))
        if fill_to is not None:
            target = (fill_to - at).total_seconds()
            while elapsed < target - .0001 and len(parts) < 10000:
                candidate = rotation.take(target - elapsed)
                if candidate is None:
                    break
                add(candidate, float(candidate.asset.duration_seconds))
            pool = filler_media or (program,)
            index = 0
            while elapsed < target - .0001 and len(parts) < 10000:
                filler = pool[index % len(pool)]
                add(filler, min(float(filler.asset.duration_seconds), target - elapsed), "filler")
                index += 1
            if elapsed < target - .0001:
                raise ValueError("An aligned ad window exceeds the 10000-segment limit. Use a shorter clock interval.")
        identity = hashlib.sha256(f"simple:{occurrence_id}:{revision}:{at.isoformat()}:{trigger}".encode()).hexdigest()
        plans.append(BreakPlan(
            identity, identity, occurrence_id, channel_number, at, elapsed, tuple(parts),
            "sequential" if settings.play_order == "sequential" else "complete_rotation", "strict_fit",
            trigger=trigger, policy_revision=revision,
            rotation_revision=rotation.revision, rotation_cycle=rotation.cycle,
            rotation_remaining=tuple(rotation.remaining),
        ))
        return at + timedelta(seconds=elapsed)

    for _ in range(10000):
        mark = next_clock(cursor, settings)
        until_mark = (mark - cursor).total_seconds()
        if settings.setup_mode != "timed" or remaining <= until_mark + 30:
            cursor += timedelta(seconds=remaining)
            break
        remaining -= until_mark
        cursor = mark
        if activation is None or cursor >= activation:
            cursor = make_break(cursor, "interval")
    else:
        raise ValueError("A show exceeds the 10000-break limit. Use a longer clock interval.")

    if activation is None or cursor >= activation:
        if settings.setup_mode == "aligned" and rotation.media:
            # At least the first whole ad must fit before the next grid start.
            item = rotation.by_id[rotation.remaining[0]] if rotation.remaining else None
            if item is None:
                # Refill without consuming; take is bounded to reject every positive clip.
                rotation.take(0)
                item = rotation.by_id[rotation.remaining[0]]
            finish = cursor + timedelta(seconds=float(item.asset.duration_seconds))
            edge = next_clock(finish - timedelta(microseconds=100), settings)
            if next_start is not None and edge > next_start:
                raise ValueError("The aligned show and its complete ad cross the next fixed start. Rebuild the range with Auto Fill.")
            cursor = make_break(cursor, "between_programs", fill_to=edge)
        else:
            cursor = make_break(cursor, "between_programs")
    if next_start is not None and cursor > next_start + timedelta(microseconds=100):
        raise ValueError("Ad breaks cross the next fixed show. Clear the range and Auto Fill again.")
    return tuple(plans), cursor


def snapshot(plans, start, end, revision):
    breaks = []
    for plan in plans:
        item = asdict(plan)
        item["scheduled_at"] = plan.scheduled_at.isoformat()
        breaks.append(item)
    return json.loads(json.dumps({"start_utc": start.isoformat(), "end_utc": end.isoformat(),
                                  "revision": revision, "breaks": breaks}, allow_nan=False))


def snapshot_plans(value):
    result = []
    for item in value["breaks"]:
        converted = dict(item)
        # Qt transports whole-number values as doubles in nested QVariantMaps.
        for field in ("rotation_cycle", "channel_number"):
            number = converted.get(field, -1)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or int(number) != number:
                raise ValueError(f"invalid calendar ad plan {field}")
            converted[field] = int(number)
        converted["scheduled_at"] = datetime.fromisoformat(item["scheduled_at"])
        converted["segments"] = tuple(PlannedSegment(**part) for part in item["segments"])
        result.append(BreakPlan(**converted))
    return tuple(result)


def validate_snapshot(value):
    if not isinstance(value, dict) or set(value) != {"start_utc", "end_utc", "revision", "breaks"}:
        raise ValueError("invalid calendar ad plan snapshot")
    if not isinstance(value["breaks"], list) or len(value["breaks"]) > 10000:
        raise ValueError("invalid calendar ad break list")
    start, end = (datetime.fromisoformat(value[key]) for key in ("start_utc", "end_utc"))
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise ValueError("calendar ad plan requires aware, ordered timestamps")
    previous = start
    for plan in snapshot_plans(value):
        finish = plan.scheduled_at + timedelta(seconds=plan.duration_seconds)
        if plan.scheduled_at < previous or finish > end:
            raise ValueError("calendar ad plan segments overlap or exceed their window")
        previous = finish
    return json.loads(json.dumps(value, allow_nan=False))


def auto_fill(resolved, ordered, raw, start, end, runtime_path, *, publish, check_cancelled):
    """Choose exact clips in a detached draft, without advancing the live queue."""
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    from .ad_break_engine import BreakPlanStore
    from .runtime import advertising_signature

    settings = resolved.definition.advertising
    revision = advertising_signature(resolved)
    channel = resolved.definition.channel
    if not resolved.ad_media:
        raise ValueError("Select indexed clips in the Ad Bin before Auto Fill with ads.")
    by_id = {item.asset.asset_id: item for item in resolved.media}
    existing = sorted(raw.get("calendarBlocks", []), key=lambda block: block["startUtc"])
    queue_store = BreakPlanStore(":memory:")
    try:
        path = Path(runtime_path)
        if path.is_file():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as original:
                if original.execute("SELECT 1 FROM sqlite_master WHERE name='ad_plan_metadata'").fetchone():
                    original.backup(queue_store.connection)
        earliest = min([start] + [datetime.fromisoformat(block["startUtc"]) for block in existing])
        rotation = SimpleRotation(resolved.ad_media, settings, channel, store=queue_store, before=earliest)
    finally:
        queue_store.close()

    blocks = []
    cursor = start
    index = 0
    windows = 0
    reserved = 0.0

    def build(media, begins, boundary=None):
        identity = hashlib.sha256(f"calendar:{channel}:{media.asset.asset_id}:{begins.isoformat()}".encode()).hexdigest()
        return plan_program(media, begins, settings, revision, channel, identity, rotation,
                            next_start=boundary, filler_media=ordered)

    def fill_to(boundary):
        nonlocal cursor, index, windows, reserved
        if settings.setup_mode == "aligned":
            cursor = next_clock(cursor - timedelta(microseconds=100), settings)
        while cursor < boundary and len(blocks) < 10000:
            check_cancelled()
            media = ordered[index % len(ordered)]
            duration = float(media.asset.duration_seconds)
            saved_state = rotation.cycle, list(rotation.remaining), rotation.previous
            plans, finish = build(media, cursor)
            if finish > boundary:
                rotation.cycle, rotation.remaining, rotation.previous = saved_state
                return
            blocks.append({
                "assetId": media.asset.asset_id, "title": media.location.path.stem,
                "path": str(media.location.path), "sourceRoot": str(media.location.source_root),
                "durationSeconds": duration, "startUtc": cursor.isoformat(),
                "endUtc": (cursor + timedelta(seconds=duration)).isoformat(),
                "adPlan": snapshot(plans, cursor, finish, revision),
            })
            windows += len(plans)
            reserved += sum(plan.duration_seconds for plan in plans)
            cursor = finish
            index += 1
            publish(min(int((cursor-start).total_seconds()), int((end-start).total_seconds())),
                    int((end-start).total_seconds()), f"Scheduled {len(blocks)} shows with their selected ads…")

    for block_index, block in enumerate(existing):
        check_cancelled()
        begins = datetime.fromisoformat(block["startUtc"])
        if begins >= end:
            break
        media = by_id.get(block["assetId"])
        if media is None:
            raise ValueError("An existing show is outside the selected program sources.")
        if begins > cursor:
            fill_to(min(begins, end))
        saved = block.get("adPlan")
        if saved and saved["revision"] == revision and datetime.fromisoformat(saved["start_utc"]) == begins:
            plans = snapshot_plans(saved)
            finish = datetime.fromisoformat(saved["end_utc"])
            if plans and plans[-1].rotation_revision == rotation.revision:
                rotation.cycle = plans[-1].rotation_cycle
                rotation.remaining = list(plans[-1].rotation_remaining)
                ads = [part.asset_id for part in plans[-1].segments if part.event_type == "advertisement"]
                rotation.previous = ads[-1] if ads else rotation.previous
        else:
            next_start = datetime.fromisoformat(existing[block_index+1]["startUtc"]) if block_index+1 < len(existing) else None
            plans, finish = build(media, begins, next_start)
        cursor = max(cursor, finish)
    if cursor < end:
        fill_to(end)
    warnings = []
    if not blocks and existing:
        warnings.append("This range is already filled. Clear Range, then Auto Fill to rebuild it with the new ad settings.")
    message = f"Scheduled {len(blocks)} shows and {windows} ad windows, preserving existing shows."
    if warnings:
        message = " ".join(warnings) + " " + message
    publish(int((end-start).total_seconds()), int((end-start).total_seconds()), "Schedule ready")
    return {"ok": True, "message": message, "startUtc": start.isoformat(), "endUtc": end.isoformat(),
            "completeThroughUtc": min(cursor, end).isoformat(), "hitBlockLimit": len(blocks) >= 10000,
            "adSlotCount": windows, "adReservedSeconds": reserved, "adWarnings": warnings, "blocks": blocks}
