from __future__ import annotations

from datetime import datetime, timedelta

from .guide import GuideProgram, GuideService
from .runtime import require_aware_utc, utc_now


DEFAULT_GUIDE_HOURS = 3.0

# Programs this short become unreadable when projected individually across a
# multi-hour television Guide. They remain authoritative GuideProgram entries;
# only their visual representation is grouped.
SHORT_FORM_PROGRAM_SECONDS = 8 * 60.0
SHORT_FORM_BLOCK_SECONDS = 15 * 60.0


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


def _display_segments(programs: tuple[GuideProgram, ...]) -> list[dict[str, object]]:
    """Build readable Guide blocks without changing the underlying schedule.

    Long programs remain one visual segment per scheduled occurrence. Adjacent
    short programs are grouped into bounded short-form blocks. Program indexes
    are retained so QML can highlight the visual block containing the exact
    authoritative selection.
    """

    segments: list[dict[str, object]] = []
    index = 0

    while index < len(programs):
        first = programs[index]

        if first.duration_seconds > SHORT_FORM_PROGRAM_SECONDS:
            segments.append(
                {
                    "title": first.display_label,
                    "startMs": _epoch_milliseconds(first.start_utc),
                    "endMs": _epoch_milliseconds(first.end_utc),
                    "programCount": 1,
                    "firstProgramIndex": index,
                    "lastProgramIndex": index,
                    "isCluster": False,
                    "isCurrent": bool(first.is_current),
                }
            )
            index += 1
            continue

        first_index = index
        start = first.start_utc
        end = first.end_utc
        contains_current = bool(first.is_current)
        count = 1
        index += 1

        while index < len(programs):
            candidate = programs[index]

            if candidate.duration_seconds > SHORT_FORM_PROGRAM_SECONDS:
                break

            # Never visually bridge a real schedule gap.
            if candidate.start_utc != end:
                break

            proposed_seconds = (candidate.end_utc - start).total_seconds()

            # Prefer roughly fifteen-minute Guide blocks. Allow the second
            # program through even when two relatively short programs together
            # slightly exceed the target; a one-item "cluster" is meaningless.
            if proposed_seconds > SHORT_FORM_BLOCK_SECONDS and count >= 2:
                break

            end = candidate.end_utc
            contains_current = contains_current or bool(candidate.is_current)
            count += 1
            index += 1

        last_index = first_index + count - 1

        if count == 1:
            title = first.display_label
            is_cluster = False
        else:
            title = "SHORT-FORM BLOCK"
            is_cluster = True

        segments.append(
            {
                "title": title,
                "startMs": _epoch_milliseconds(start),
                "endMs": _epoch_milliseconds(end),
                "programCount": count,
                "firstProgramIndex": first_index,
                "lastProgramIndex": last_index,
                "isCluster": is_cluster,
                "isCurrent": contains_current,
            }
        )

    return segments


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
                # Exact occurrences remain the interaction/selection model.
                "programs": [_program_view(program) for program in row.programs],
                # The Guide strip gets a separate readable projection.
                "displaySegments": _display_segments(row.programs),
            }
        )

    return {
        "generatedAtMs": _epoch_milliseconds(reference),
        "horizonStartMs": _epoch_milliseconds(start),
        "horizonEndMs": _epoch_milliseconds(end),
        "rows": rows,
    }
