"""Shared calendar reservation validation and chronological queue replay."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta


def occurrence_id(channel: int, asset_id: str, start: datetime) -> str:
    return hashlib.sha256(f'calendar:{channel}:{asset_id}:{start.isoformat()}'.encode()).hexdigest()


def snapshot_matches(saved, media, start, revision, channel, ad_media, *, allow_legacy_ads=False, program_media=()) -> bool:
    """Bind a reservation to its parent, current durations and source bounds."""
    from .simple_ads import snapshot_plans, validate_snapshot
    if not saved:
        return False
    try:
        validate_snapshot(saved)
        if saved['revision'] != revision or datetime.fromisoformat(saved['start_utc']) != start:
            return False
        plans = snapshot_plans(saved)
        identity = occurrence_id(channel, media.asset.asset_id, start)
        duration = float(media.asset.duration_seconds)
        by_id = {item.asset.asset_id: item for item in ad_media}
        programs = {item.asset.asset_id: item for item in (*program_media, media)}
        elapsed = 0.0
        for plan in plans:
            position = (plan.scheduled_at - start).total_seconds() - elapsed
            if (plan.occurrence_id != identity or plan.channel_number != channel
                    or plan.policy_revision != revision or position < -.001 or position > duration + .001):
                return False
            if plan.trigger == 'between_programs' and abs(position - duration) > .001:
                return False
            for part in plan.segments:
                if part.source_offset_seconds < 0:
                    return False
                if part.event_type == 'advertisement':
                    item = by_id.get(part.asset_id)
                    expected_duration = (float(item.asset.duration_seconds) if item else
                                         part.original_duration_seconds if allow_legacy_ads else None)
                    if (expected_duration is None or part.source_offset_seconds != 0
                            or abs(expected_duration - part.duration_seconds) > .001):
                        return False
                elif part.event_type == 'filler':
                    item = programs.get(part.asset_id)
                    bound = float(item.asset.duration_seconds) if item else part.original_duration_seconds
                    if bound is None or part.source_offset_seconds + part.duration_seconds > bound + .001:
                        return False
            elapsed += plan.duration_seconds
        return abs((datetime.fromisoformat(saved['end_utc']) - start).total_seconds() - duration - elapsed) < .001
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def replay_blocks(resolved, blocks, *, store=None, replay_from=None):
    """Replay an affected suffix in order, preserving every fixed program start.

    This function changes only its returned blocks. Preview and Auto Fill use
    detached stores; runtime adoption and ledger retirement happen on Apply.
    """
    from .runtime import advertising_signature
    from .simple_ads import SimpleRotation, plan_program, snapshot, snapshot_plans
    if not blocks:
        return ()
    settings = resolved.definition.advertising
    revision = advertising_signature(resolved)
    channel = resolved.definition.channel
    ordered = sorted(blocks, key=lambda block: block.start_utc)
    by_id = {item.asset.asset_id: item for item in resolved.media}
    rotation = SimpleRotation(resolved.ad_media, settings, channel, store=store, before=ordered[0].start_utc)
    result = []
    for index, block in enumerate(ordered):
        media = by_id[block.asset_id]
        valid = snapshot_matches(block.ad_plan, media, block.start_utc, revision, channel, resolved.ad_media, program_media=resolved.media)
        preserve = replay_from is not None and block.start_utc < replay_from and block.ad_plan
        if preserve:
            preserve = snapshot_matches(block.ad_plan, media, block.start_utc, block.ad_plan['revision'],
                                        channel, resolved.ad_media, allow_legacy_ads=True, program_media=resolved.media)
        if preserve:
            saved = block.ad_plan
            plans = snapshot_plans(saved)
            if plans and plans[-1].rotation_revision == rotation.revision:
                rotation.cycle = plans[-1].rotation_cycle
                rotation.remaining = list(plans[-1].rotation_remaining)
                ads = [part.asset_id for plan in plans for part in plan.segments if part.event_type == 'advertisement']
                rotation.previous = ads[-1] if ads else rotation.previous
        else:
            boundary = ordered[index + 1].start_utc if index + 1 < len(ordered) else None
            plans, finish = plan_program(media, block.start_utc, settings, revision, channel,
                occurrence_id(channel, block.asset_id, block.start_utc), rotation,
                next_start=boundary, filler_media=resolved.media)
            saved = snapshot(plans, block.start_utc, finish, revision)
        result.append(replace(block, ad_plan=saved))
    return tuple(result)


def detached_store(runtime_path):
    """Copy rotation state for authoring without opening a live writable handle."""
    from contextlib import contextmanager, closing
    from pathlib import Path
    import sqlite3
    from .ad_break_engine import BreakPlanStore

    @contextmanager
    def copied():
        store = BreakPlanStore(':memory:')
        try:
            path = Path(runtime_path)
            if path.is_file():
                with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as original:
                    if original.execute("SELECT 1 FROM sqlite_master WHERE name='ad_plan_metadata'").fetchone():
                        original.backup(store.connection)
                store._initialize()
            yield store
        finally:
            store.close()
    return copied()


def portable_intent(value):
    """Compare logical decisions independently of host paths and copied hashes."""
    if isinstance(value, dict):
        return {key: portable_intent(item) for key, item in value.items()
                if key not in {'media_path', 'sources', 'revision', 'policy_revision'}}
    if isinstance(value, (list, tuple)):
        return [portable_intent(item) for item in value]
    return value
