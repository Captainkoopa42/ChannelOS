"""Dated schedule revisions for quick (sequential and shuffle) channels.

Beta 1 stored one start time (epoch) and a fingerprint per channel. Any change
to the indexed media, even a 0.1 s re-probe, changed the fingerprint and
restarted the channel from its first program, deleting the viewer's place.

From Beta 2 a quick channel keeps a log of revisions. Each revision freezes
the lineup it plays (asset order and durations) and says when it takes
effect. "What is on at time T" uses the revision active at T, so:

* past revisions are never rewritten, and the Guide's history stays true;
* a library change becomes a *pending* revision that takes effect when the
  program airing at that moment ends, continuing in episode order;
* the pending revision is stored at once, so closing ChannelOS before the
  boundary and reopening after it gives the same schedule as staying open;
* a missing file or drive keeps its time slot (see ``unavailable_media``);
* only "Restart channel from the beginning" starts a channel over.

Times here are the timeline's own clock. For channels without ad breaks that
is wall-clock UTC; with ad breaks it is program-content time, the same clock
the rest of the sequential ad engine already uses.
"""
from __future__ import annotations

import hashlib
import json
import logging
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from .library import IndexedMedia, MediaAsset, MediaLocation

logger = logging.getLogger(__name__)

# Re-probes that differ by less than this are noise, not a lineup change.
DURATION_PRECISION = 2   # decimal places of a second (10 ms)

UNAVAILABLE_ASSET_PREFIX = "unavailable:"

SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_revisions (
    channel_number INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    effective_utc TEXT NOT NULL,
    virtual_epoch_utc TEXT NOT NULL,
    lineup TEXT NOT NULL,
    content_signature TEXT NOT NULL,
    reason TEXT NOT NULL,
    history_unknown_before TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (channel_number, revision)
);

CREATE TABLE IF NOT EXISTS channel_migrations (
    channel_number INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    old_epoch_utc TEXT,
    old_signature TEXT,
    new_epoch_utc TEXT NOT NULL,
    old_viewer TEXT,
    migrated_at TEXT NOT NULL,
    notice_shown INTEGER NOT NULL DEFAULT 0
);
"""

REVISION_TABLES = ("channel_revisions", "channel_migrations")


@dataclass(frozen=True, slots=True)
class LineupEntry:
    asset_id: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class Revision:
    channel_number: int
    revision: int
    effective_utc: datetime
    virtual_epoch_utc: datetime
    lineup: tuple[LineupEntry, ...]
    content_signature: str
    reason: str
    history_unknown_before: datetime | None = None


# --------------------------------------------------------------------------
# Signatures and lineups

def rounded_duration(value: float | None) -> float:
    return round(float(value or 0.0), DURATION_PRECISION)


def content_signature(programming, media: Sequence[IndexedMedia]) -> str:
    """What the user's channel *asks for*: its settings and its eligible media.

    Durations are rounded so probe noise does not count as a change. For
    shuffle the media order does not matter, only the set.
    """
    items = [(item.asset.asset_id, rounded_duration(item.asset.duration_seconds)) for item in media]
    if programming.mode == "shuffle":
        items = sorted(items)
    payload = {
        "schema": 1,
        "mode": programming.mode,
        "preserve_episode_order": bool(programming.preserve_episode_order),
        "avoid_repeat_days": int(programming.avoid_repeat_days),
        "media": items,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def lineup_of(media: Iterable[IndexedMedia]) -> tuple[LineupEntry, ...]:
    return tuple(LineupEntry(item.asset.asset_id, float(item.asset.duration_seconds))
                 for item in media
                 if item.asset.duration_seconds is not None and float(item.asset.duration_seconds) > 0)


def lineup_to_text(lineup: Sequence[LineupEntry]) -> str:
    return json.dumps([[entry.asset_id, entry.duration_seconds] for entry in lineup], separators=(",", ":"))


def lineup_from_text(text: str) -> tuple[LineupEntry, ...]:
    return tuple(LineupEntry(str(asset_id), float(duration)) for asset_id, duration in json.loads(text))


def start_offset(lineup: Sequence[LineupEntry], index: int) -> float:
    return sum(entry.duration_seconds for entry in lineup[:index])


# --------------------------------------------------------------------------
# Storage (inside the runtime database)

def ensure_schema(connection) -> None:
    connection.executescript(SCHEMA)


def _dt(text: str | None):
    from .runtime import datetime_from_text
    return datetime_from_text(text) if text else None


def _text(value: datetime | None):
    from .runtime import datetime_to_text
    return datetime_to_text(value) if value is not None else None


def load_revisions(store, channel_number: int) -> tuple[Revision, ...]:
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM channel_revisions WHERE channel_number=? ORDER BY revision",
            (int(channel_number),)).fetchall()
    return tuple(Revision(
        channel_number=int(row["channel_number"]), revision=int(row["revision"]),
        effective_utc=_dt(row["effective_utc"]), virtual_epoch_utc=_dt(row["virtual_epoch_utc"]),
        lineup=lineup_from_text(row["lineup"]), content_signature=str(row["content_signature"]),
        reason=str(row["reason"]), history_unknown_before=_dt(row["history_unknown_before"]),
    ) for row in rows)


def write_revision(store, revision: Revision, *, now: datetime, replace_pending: bool = False) -> None:
    """Store one revision. ``replace_pending`` overwrites that revision number."""
    with store.connect() as connection:
        verb = "INSERT OR REPLACE" if replace_pending else "INSERT"
        connection.execute(
            f"""{verb} INTO channel_revisions(
                channel_number, revision, effective_utc, virtual_epoch_utc, lineup,
                content_signature, reason, history_unknown_before, created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
            (revision.channel_number, revision.revision, _text(revision.effective_utc),
             _text(revision.virtual_epoch_utc), lineup_to_text(revision.lineup), revision.content_signature,
             revision.reason, _text(revision.history_unknown_before), _text(now)))


def record_migration(store, channel_number: int, path: str, *, old_epoch, old_signature,
                     new_epoch: datetime, old_viewer: dict | None, now: datetime) -> None:
    with store.connect() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO channel_migrations(
                channel_number, path, old_epoch_utc, old_signature, new_epoch_utc, old_viewer, migrated_at)
                VALUES(?,?,?,?,?,?,?)""",
            (int(channel_number), path, _text(old_epoch), old_signature, _text(new_epoch),
             json.dumps(old_viewer) if old_viewer else None, _text(now)))
    logger.info("Channel %s migrated to schedule revisions: %s (old epoch %s, new epoch %s)",
                channel_number, path, old_epoch, new_epoch)


def pending_notices(store) -> list[dict]:
    """Channels that restarted when upgrading from Beta 1 and haven't been told yet."""
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT channel_number, migrated_at FROM channel_migrations WHERE path='restarted' AND notice_shown=0"
            " ORDER BY channel_number").fetchall()
    return [{"channelNumber": int(row["channel_number"]), "migratedAt": str(row["migrated_at"])} for row in rows]


def mark_notices_shown(store) -> None:
    with store.connect() as connection:
        connection.execute("UPDATE channel_migrations SET notice_shown=1 WHERE notice_shown=0")


def clear_channel(store, channel_number: int) -> None:
    with store.connect() as connection:
        for table in REVISION_TABLES:
            connection.execute(f"DELETE FROM {table} WHERE channel_number=?", (int(channel_number),))


# --------------------------------------------------------------------------
# Missing media keeps its slot

def unavailable_media(asset_id: str, duration: float) -> IndexedMedia:
    """A stand-in for a program whose file is missing: it keeps the time slot."""
    path = Path(f"{UNAVAILABLE_ASSET_PREFIX}{asset_id}") / "Unavailable program"
    return IndexedMedia(
        asset=MediaAsset(asset_id=asset_id, content_sha256="", size_bytes=0,
                         duration_seconds=float(duration), container_format=None),
        location=MediaLocation(path=path, path_key=str(path), asset_id=asset_id,
                               source_root=path, online=False))


def is_unavailable(media: IndexedMedia) -> bool:
    return str(media.location.path).startswith(UNAVAILABLE_ASSET_PREFIX) or not media.location.online


def resolve_lineup(lineup: Sequence[LineupEntry], available: dict[str, IndexedMedia],
                   lookup=None) -> tuple[IndexedMedia, ...]:
    """Media for a frozen lineup, with frozen durations.

    ``available`` is the channel's usable media by asset id. Anything else is
    looked up (an offline copy keeps its title) or becomes a placeholder; in
    both cases it keeps exactly its scheduled duration.
    """
    result = []
    for entry in lineup:
        item = available.get(entry.asset_id)
        if item is None and lookup is not None:
            item = lookup(entry.asset_id)
            if item is not None:
                item = replace(item, location=replace(item.location, online=False))
        if item is None:
            item = unavailable_media(entry.asset_id, entry.duration_seconds)
        if item.asset.duration_seconds != entry.duration_seconds:
            item = replace(item, asset=replace(item.asset, duration_seconds=entry.duration_seconds))
        result.append(item)
    return tuple(result)


# --------------------------------------------------------------------------
# The timeline over revisions

class RevisionTimeline:
    """A SequentialTimeline per revision, each valid from its effective time.

    ``selection_at(epoch, at)`` keeps SequentialTimeline's signature so the
    rest of the runtime (ads, Guide, viewer) is unchanged; the epoch argument
    is ignored because each revision carries its own.
    """

    def __init__(self, revisions: Sequence[Revision], timelines: Sequence) -> None:
        if not revisions or len(revisions) != len(timelines):
            raise ValueError("a revision timeline needs one timeline per revision")
        self.revisions = tuple(revisions)
        self.timelines = tuple(timelines)
        self._starts = [revision.effective_utc for revision in self.revisions]

    # Compatibility with SequentialTimeline for Guide explanations, repeat
    # validation and anything that inspects "the" lineup: the latest one.
    @property
    def current(self):
        return self.timelines[-1]

    @property
    def programs(self):
        return self.current.programs

    @property
    def cycle_duration_seconds(self) -> float:
        return self.current.cycle_duration_seconds

    @property
    def begins_at(self) -> datetime:
        return self.revisions[0].effective_utc

    @property
    def history_unknown_before(self) -> datetime | None:
        return self.revisions[0].history_unknown_before

    def index_at(self, at: datetime) -> int:
        return max(0, bisect_right(self._starts, at) - 1)

    def revision_at(self, at: datetime) -> Revision:
        return self.revisions[self.index_at(at)]

    def selection_at(self, epoch, at: datetime):
        index = self.index_at(at)
        selection = self.timelines[index].selection_at(self.revisions[index].virtual_epoch_utc, at)
        # Programs never cross a boundary by construction (each boundary is a
        # program end), but guard against rounding at microsecond scale.
        if is_unavailable(selection.media):
            # The file or its drive is missing: keep the slot, play nothing.
            selection = replace(selection, origin="unavailable")
        if index + 1 < len(self.revisions):
            boundary = self.revisions[index + 1].effective_utc
            if selection.program_ends_at > boundary:
                selection = replace(selection, program_ends_at=boundary)
        return selection


# --------------------------------------------------------------------------
# Planning a change

def plan_change(timeline: RevisionTimeline, *, now: datetime, new_lineup_media: Sequence[IndexedMedia],
                mode: str, signature: str, channel_number: int) -> Revision:
    """The revision that applies a lineup change after the program airing now.

    If a change is already pending, its boundary is kept and only its lineup
    is replaced, so several edits before the boundary merge predictably.
    """
    revisions = timeline.revisions
    latest = revisions[-1]
    pending = latest.effective_utc > now
    if pending:
        boundary = latest.effective_utc
        number = latest.revision
        base_index = len(revisions) - 2
    else:
        boundary = timeline.selection_at(None, now).program_ends_at
        number = latest.revision + 1
        base_index = len(revisions) - 1
    # What is airing just before the boundary, in the revision that will be
    # replaced at that boundary.
    before = boundary - timedelta(microseconds=1)
    base_revision = revisions[base_index]
    current = timeline.timelines[base_index].selection_at(base_revision.virtual_epoch_utc, before)
    old_lineup = base_revision.lineup
    current_position = current.program.index
    current_asset = current.media.asset.asset_id

    new_entries = lineup_of(new_lineup_media)
    if not new_entries:
        raise ValueError("a revision needs at least one program")
    new_ids = [entry.asset_id for entry in new_entries]

    if mode == "shuffle":
        # Everything not yet aired in this pass comes first: the rest of the
        # pass, then newly added media. What already aired comes last, so
        # nothing repeats early. Each group keeps the shuffle order.
        new_by_id = {entry.asset_id: entry for entry in new_entries}
        old_ids = {entry.asset_id for entry in old_lineup}
        remaining = []
        for entry in old_lineup[current_position + 1:]:
            if entry.asset_id in new_by_id and entry.asset_id not in remaining:
                remaining.append(entry.asset_id)
        added = [asset for asset in new_ids if asset not in old_ids]
        aired = [asset for asset in new_ids if asset not in remaining and asset not in added]
        ordered = tuple(new_by_id[asset] for asset in remaining + added + aired)
        start = 0
    else:
        ordered = new_entries
        if current_asset in new_ids:
            start = (new_ids.index(current_asset) + 1) % len(new_ids)
        else:
            # The program that just aired was removed: continue with the next
            # one from the old order that still exists.
            start = 0
            for entry in old_lineup[current_position + 1:] + old_lineup[:current_position]:
                if entry.asset_id in new_ids:
                    start = new_ids.index(entry.asset_id)
                    break
    virtual_epoch = boundary - timedelta(seconds=start_offset(ordered, start))
    return Revision(channel_number=channel_number, revision=number, effective_utc=boundary,
                    virtual_epoch_utc=virtual_epoch, lineup=ordered, content_signature=signature,
                    reason="library change")
