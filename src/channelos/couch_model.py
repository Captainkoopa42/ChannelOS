from __future__ import annotations

from datetime import datetime, timedelta

from .guide import GuideProgram, GuideService
from .runtime import require_aware_utc, utc_now


DEFAULT_GUIDE_HOURS = 3.0


def _epoch_milliseconds(value: datetime) -> int:
    return int(require_aware_utc(value).timestamp() * 1000)


def _floor_to_half_hour(value: datetime) -> datetime:
    current = require_aware_utc(value)
    minute = 0 if current.minute < 30 else 30
    return current.replace(minute=minute, second=0, microsecond=0)


def _program_view(program: GuideProgram) -> dict[str, object]:
    return {
        "scheduleId": program.schedule_id,
        "channelNumber": program.channel_number,
        "assetId": program.asset_id,
        "title": program.display_label,
        "startMs": _epoch_milliseconds(program.start_utc),
        "endMs": _epoch_milliseconds(program.end_utc),
        "durationSeconds": float(program.duration_seconds),
        "isCurrent": bool(program.is_current),
        "isPast": bool(program.is_past),
        "isFuture": bool(program.is_future),
    }


def build_couch_snapshot(
    service: GuideService,
    *,
    at: datetime | None = None,
    guide_hours: float = DEFAULT_GUIDE_HOURS,
) -> dict[str, object]:
    """Project the authoritative Guide into a QML-friendly couch UI snapshot."""
    if guide_hours <= 0:
        raise ValueError("guide_hours must be greater than zero")

    reference = require_aware_utc(at or utc_now())
    start = _floor_to_half_hour(reference)
    end = start + timedelta(hours=float(guide_hours))
    horizon = service.horizon(start, end, generated_at=reference)

    rows: list[dict[str, object]] = []
    for row in horizon.rows:
        rows.append(
            {
                "channelNumber": row.channel_number,
                "displayNumber": f"{row.channel_number:03d}",
                "channelName": row.channel_name,
                "programs": [_program_view(program) for program in row.programs],
            }
        )

    return {
        "generatedAtMs": _epoch_milliseconds(reference),
        "horizonStartMs": _epoch_milliseconds(start),
        "horizonEndMs": _epoch_milliseconds(end),
        "rows": rows,
    }
