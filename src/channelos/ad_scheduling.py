"""Shared placement rules for sequential, shuffled and fixed-calendar programs."""
from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from datetime import timedelta

from .ad_break_engine import (BreakOpportunity, BreakOpportunityScheduler, BreakPolicy,
                              PlannedSegment, ProgramOccurrence)
from .models import AdvertisingDefinition


def configured_policies(settings: AdvertisingDefinition):
    if settings.placements:
        return tuple((item.placement_id, item.trigger, item.policy) for item in settings.placements)
    # Preserve pre-placement channels: their historical default list did not
    # insert an extra between-program break after an interrupted episode.
    return tuple(("default", trigger, settings) for trigger in settings.triggers
                 if trigger != "between_programs" or not (
                     settings.breakpoints_seconds or settings.interval_seconds))


def program_opportunities(settings: AdvertisingDefinition, occurrence: ProgramOccurrence,
                          revision: str):
    choices = {}
    for identity, trigger, policy in configured_policies(settings):
        if not settings.enabled or not policy.enabled:
            continue
        opportunities = ()
        if trigger in {"breakpoint", "interval"}:
            opportunities = BreakOpportunityScheduler.for_occurrence(
                occurrence, BreakPolicy(
                    enabled=True,
                    interval_seconds=policy.interval_seconds if trigger == "interval" else None,
                    breakpoints_seconds=policy.breakpoints_seconds if trigger == "breakpoint" else (),
                    duration_seconds=policy.break_duration_seconds, priority=policy.priority,
                ), revision=f"{revision}:{identity}",
            )
        elif trigger in {"between_programs", "fixed_slot"}:
            at = occurrence.ends_at
            budget = policy.break_duration_seconds
            if trigger == "fixed_slot":
                if policy.slot_seconds is None:
                    continue
                boundary = math.ceil((at.timestamp() - 1e-6) / policy.slot_seconds) * policy.slot_seconds
                budget = boundary - at.timestamp()
                if budget <= .001:
                    budget = policy.slot_seconds
            opportunity_id = hashlib.sha256(
                f"{occurrence.occurrence_id}:{revision}:{identity}:{trigger}".encode()
            ).hexdigest()
            opportunities = (BreakOpportunity(
                opportunity_id, occurrence.occurrence_id, occurrence.channel_number,
                trigger, at, budget, policy.priority,
            ),)
        for opportunity in opportunities:
            choices[opportunity.opportunity_id] = (opportunity, policy)
    winners = BreakOpportunityScheduler.arbitrate(tuple(item[0] for item in choices.values()))
    return tuple((item, choices[item.opportunity_id][1]) for item in winners)


def eligible_media(media, policy: AdvertisingDefinition):
    requested = set(policy.asset_ids)
    excluded = set(policy.excluded_asset_ids)
    roots = tuple(source.path.expanduser().resolve(strict=False) for source in policy.sources)
    return tuple(item for item in media if item.asset.asset_id not in excluded and (
        not requested and not roots or item.asset.asset_id in requested or any(
            item.location.path.resolve(strict=False).is_relative_to(root) for root in roots
        )
    ))


def snapshot_segments(segments, media) -> tuple[PlannedSegment, ...]:
    indexed = {item.asset.asset_id: item for item in media}
    return tuple(replace(segment,
                         media_path=str(indexed[segment.asset_id].location.path),
                         original_duration_seconds=indexed[segment.asset_id].asset.duration_seconds)
                 for segment in segments)


def select_segments(media, budget: float, policy: AdvertisingDefinition, *, seed: str,
                    counts=None, expand_max_seconds: float = 0.0):
    """Fit media and transition time together before committing the clock."""
    from .ad_break_engine import AdCandidate, AdSelectionEngine
    hold = policy.transition_seconds if policy.transition_behavior == "hold" else 0.0
    selected = AdSelectionEngine().select(
        tuple(AdCandidate(item.asset.asset_id, float(item.asset.duration_seconds) + hold) for item in media),
        budget, strategy=policy.selection_strategy, seed=seed, play_counts=counts,
        timing_policy=policy.timing_policy,
        smoosh_minimum_seconds=policy.smoosh_minimum_seconds + hold,
        smoosh_max_trim_seconds=policy.smoosh_max_trim_seconds,
        expand_max_seconds=expand_max_seconds,
    )
    result = []
    for segment in snapshot_segments(selected, media):
        duration = segment.duration_seconds - hold
        if duration <= 0:
            continue
        result.append(replace(segment, duration_seconds=duration))
        if hold:
            result.append(replace(segment,
                                  start_offset_seconds=segment.start_offset_seconds + duration,
                                  source_offset_seconds=max(0.0, duration - .001),
                                  duration_seconds=hold, trimmed_seconds=0,
                                  event_type="transition"))
    return tuple(result)


def indexed_media_for_segment(segment: PlannedSegment, pool, library=None):
    from pathlib import Path
    from .library import IndexedMedia, MediaAsset, MediaLocation
    for item in pool:
        if item.asset.asset_id == segment.asset_id:
            return item
    if library is not None:
        # Older plans predate source-location snapshots. Recover their exact
        # canonical asset even if a profile now uses a different collection.
        for location in library.locations_for_asset(segment.asset_id):
            if location.online:
                asset = library.cached_asset_for_unchanged_path(location.path)
                if asset is not None and asset.asset_id == segment.asset_id:
                    return IndexedMedia(asset, location)
    if not segment.media_path:
        raise ValueError(f"committed ad asset has no saved location: {segment.asset_id}")
    path = Path(segment.media_path)
    return IndexedMedia(MediaAsset(
        asset_id=segment.asset_id, content_sha256=segment.asset_id.removeprefix("sha256:"),
        size_bytes=0, duration_seconds=segment.original_duration_seconds or segment.duration_seconds,
        container_format=path.suffix.lstrip("."),
    ), MediaLocation(path=path, path_key=str(path), asset_id=segment.asset_id,
                     source_root=path.parent, online=path.is_file()))
