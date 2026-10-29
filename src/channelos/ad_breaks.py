from __future__ import annotations

"""Deterministic advertisement selection for ChannelOS broadcast gaps.

The planner is deliberately pure: it never starts a player, mutates the
Broadcast Clock, or changes the canonical media library. Given the same gap,
ad pool, strategy, and seed, it produces the same ordered segments.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal

from .library import IndexedMedia

AdSelectionStrategy = Literal["best_fit", "largest", "smallest", "sequential"]
SUPPORTED_AD_STRATEGIES = {"best_fit", "largest", "smallest", "sequential"}


@dataclass(frozen=True, slots=True)
class PlannedAd:
    media: IndexedMedia
    start_offset_seconds: float
    duration_seconds: float

    @property
    def end_offset_seconds(self) -> float:
        return self.start_offset_seconds + self.duration_seconds


def _stable_key(asset_id: str, seed: str) -> bytes:
    return hashlib.sha256((seed + "\\0" + asset_id).encode("utf-8")).digest()


def plan_ad_break(
    media: tuple[IndexedMedia, ...],
    available_seconds: float,
    *,
    strategy: str = "best_fit",
    seed: str = "",
) -> tuple[PlannedAd, ...]:
    """Pack unique ads into a fixed time budget without ever overrunning it.

    `best_fit` prefers the largest ad that fits the remaining time, with a
    stable hash tie-breaker. `largest` and `smallest` use the corresponding
    duration ordering. `sequential` walks a stable, seed-rotated ordering and
    skips ads that do not fit. An ad is used at most once in one break.
    """
    if strategy not in SUPPORTED_AD_STRATEGIES:
        raise ValueError(
            f"unsupported ad selection strategy {strategy!r}; "
            f"expected one of {sorted(SUPPORTED_AD_STRATEGIES)}"
        )
    budget = max(0.0, float(available_seconds))
    if budget <= 0.0 or not media:
        return ()

    candidates = [
        item for item in media
        if item.asset.duration_seconds is not None
        and float(item.asset.duration_seconds) > 0.0
    ]
    if not candidates:
        return ()

    if strategy == "sequential":
        ordered = sorted(
            candidates,
            key=lambda item: (_stable_key(item.asset.asset_id, seed), item.asset.asset_id),
        )
    elif strategy == "smallest":
        ordered = sorted(
            candidates,
            key=lambda item: (
                float(item.asset.duration_seconds),
                _stable_key(item.asset.asset_id, seed),
                item.asset.asset_id,
            ),
        )
    else:
        ordered = sorted(
            candidates,
            key=lambda item: (
                -float(item.asset.duration_seconds),
                _stable_key(item.asset.asset_id, seed),
                item.asset.asset_id,
            ),
        )

    result: list[PlannedAd] = []
    elapsed = 0.0
    remaining_items = list(ordered)

    while remaining_items and budget - elapsed > 0.001:
        remaining = budget - elapsed
        fitting = [
            item for item in remaining_items
            if float(item.asset.duration_seconds or 0.0) <= remaining + 0.001
        ]
        if not fitting:
            break

        if strategy == "sequential":
            selected = fitting[0]
        elif strategy == "smallest":
            selected = min(
                fitting,
                key=lambda item: (
                    float(item.asset.duration_seconds or 0.0),
                    _stable_key(item.asset.asset_id, seed),
                    item.asset.asset_id,
                ),
            )
        else:
            selected = max(
                fitting,
                key=lambda item: (
                    float(item.asset.duration_seconds or 0.0),
                    bytes(255 - byte for byte in _stable_key(item.asset.asset_id, seed)),
                    item.asset.asset_id,
                ),
            )

        duration = float(selected.asset.duration_seconds or 0.0)
        if duration <= 0.0 or duration > remaining + 0.001:
            break
        result.append(
            PlannedAd(
                media=selected,
                start_offset_seconds=elapsed,
                duration_seconds=duration,
            )
        )
        elapsed += duration
        remaining_items.remove(selected)

    return tuple(result)
