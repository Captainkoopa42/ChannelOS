"""Beta 2 channel continuity: a library change never restarts a quick channel.

These follow the scenarios GPT ran against Beta 1 (4b5bb89), where each of
them reset the channel, with the continuity expectations agreed for Beta 2.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from channelos import channel_revisions
from channelos.guide import GuideService
from channelos.library import MediaLibrary
from channelos.models import ChannelDefinition
from channelos.probe import MediaProbeResult
from channelos.resolve import ResolvedChannel, resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, ViewerClock, datetime_to_text, schedule_signature

UTC = timezone.utc
EPOCH = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
HOUR = 3600.0


class Show:
    """A folder of episodes in a real library, with one channel on it."""

    def __init__(self, tmp_path: Path, durations, *, mode: str = "sequential", number: int = 7) -> None:
        self.tmp = tmp_path
        self.folder = tmp_path / f"show-{number}"
        self.folder.mkdir()
        self.library = MediaLibrary(tmp_path / "library.db")
        self.definition = ChannelDefinition.from_mapping({
            "schema_version": "0.1", "channel": number, "name": "Sci-Fi Classics",
            "sources": [{"path": str(self.folder)}], "programming": {"mode": mode}})
        self.store = RuntimeStore(tmp_path / "runtime.db")
        for index, duration in enumerate(durations, start=1):
            self.add(index, duration)

    def path(self, episode: int) -> Path:
        return self.folder / f"Show - S01E{episode:02d}.mp4"

    def add(self, episode: int, duration: float) -> None:
        path = self.path(episode)
        payload = f"episode-{episode}".encode()
        path.write_bytes(payload)
        self.library.upsert_file(path, self.folder, content_sha256=hashlib.sha256(payload).hexdigest(),
                                 probe=MediaProbeResult(duration_seconds=duration, container_format="mp4"))

    def resolved(self) -> ResolvedChannel:
        return resolve_channel(self.definition, self.library)

    def open(self, at: datetime, *, resolved: ResolvedChannel | None = None, transient: bool = False) -> ChannelRuntime:
        return ChannelRuntime.open(resolved or self.resolved(), self.store, now=at, transient=transient)

    def revisions(self):
        return channel_revisions.load_revisions(self.store, self.definition.channel)


def episode(selection) -> str:
    return selection.media.location.path.stem.rsplit("E", 1)[-1]


def test_appending_an_episode_keeps_whats_on_and_airs_it_in_order(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    now = EPOCH + timedelta(hours=17, minutes=30)
    before = show.open(now).broadcast_at(now)
    assert (episode(before), before.offset_seconds) == ("03", 1800.0)
    show.store.save_viewer(7, ViewerClock(now - timedelta(minutes=5), now, running=False), now=now)

    show.add(4, HOUR)
    after = show.open(now)
    on_now = after.broadcast_at(now)
    assert (episode(on_now), on_now.offset_seconds) == ("03", 1800.0), "nothing on air is interrupted"
    assert after.epoch_utc == EPOCH
    assert show.store.load_viewer(7) is not None, "the viewer's place survives"
    # Episode 4 airs after episode 3, then the order wraps to episode 1.
    boundary = on_now.program_ends_at
    assert [episode(after.broadcast_at(boundary + timedelta(minutes=m))) for m in (1, 61, 121)] == ["04", "01", "02"]
    pending = show.revisions()[-1]
    assert pending.effective_utc == boundary and pending.reason == "library change"


def test_order_is_kept_when_the_new_episode_is_not_next(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    now = EPOCH + timedelta(minutes=30)          # episode 1 is on
    show.add(4, HOUR)
    runtime = show.open(now)
    boundary = runtime.broadcast_at(now).program_ends_at
    assert [episode(runtime.broadcast_at(boundary + timedelta(minutes=1 + 60 * n))) for n in range(4)] == \
        ["02", "03", "04", "01"]


def test_a_tiny_duration_change_never_moves_the_schedule(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    now = EPOCH + timedelta(hours=17, minutes=30)
    expected = show.open(now).broadcast_at(now)
    # Probe noise of a few milliseconds is not a change at all.
    show.add(2, HOUR + 0.004)
    show.open(now)
    assert len(show.revisions()) == 1
    # A real correction (0.1 s, Beta 1 restarted on this) waits for the next program.
    show.add(2, HOUR + 0.1)
    runtime = show.open(now)
    on_now = runtime.broadcast_at(now)
    assert (episode(on_now), on_now.offset_seconds) == (episode(expected), expected.offset_seconds)
    assert runtime.epoch_utc == EPOCH and len(show.revisions()) == 2


def test_unchanged_rescans_and_reopens_write_nothing(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR])
    show.open(EPOCH)
    for hours in (1, 5, 30):
        show.add(1, HOUR)
        show.open(EPOCH + timedelta(hours=hours))
    assert [revision.revision for revision in show.revisions()] == [0]


def test_closed_across_the_boundary_matches_staying_open(tmp_path: Path) -> None:
    def run(folder: Path, reopen: bool):
        folder.mkdir()
        show = Show(folder, [HOUR, HOUR, HOUR])
        show.open(EPOCH)
        change_at = EPOCH + timedelta(hours=1, minutes=10)
        show.add(4, HOUR)
        runtime = show.open(change_at)
        later = EPOCH + timedelta(hours=9, minutes=20)
        if reopen:   # closed before the boundary, reopened long after it
            runtime = show.open(later)
        selection = runtime.broadcast_at(later)
        return episode(selection), selection.offset_seconds, selection.program_started_at

    assert run(tmp_path / "open", reopen=False) == run(tmp_path / "closed", reopen=True)


def test_several_edits_before_the_boundary_merge_into_one_change(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    show.add(4, HOUR)
    first = show.open(EPOCH + timedelta(minutes=10))
    boundary = first.broadcast_at(EPOCH + timedelta(minutes=10)).program_ends_at
    show.add(5, HOUR)
    second = show.open(EPOCH + timedelta(minutes=40))
    revisions = show.revisions()
    assert [revision.revision for revision in revisions] == [0, 1]
    assert revisions[1].effective_utc == boundary and len(revisions[1].lineup) == 5
    assert [episode(second.broadcast_at(boundary + timedelta(minutes=1 + 60 * n))) for n in range(5)] == \
        ["02", "03", "04", "05", "01"]


def test_paused_viewer_resumes_the_same_spot_after_a_change(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    runtime = show.open(EPOCH)
    paused_at = EPOCH + timedelta(minutes=20)
    watched = runtime.selection_for_viewer_time(paused_at)
    show.store.save_viewer(7, ViewerClock(paused_at, paused_at, running=False), now=paused_at)
    show.add(4, HOUR)
    later = EPOCH + timedelta(hours=6)
    reopened = show.open(later)
    clock = show.store.load_viewer(7)
    resumed = reopened.selection_for_viewer_time(clock.current(later))
    assert (episode(resumed), resumed.offset_seconds) == (episode(watched), watched.offset_seconds)


def test_shuffle_finishes_its_pass_before_new_media_and_never_repeats_early(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR] * 6, mode="shuffle")
    runtime = show.open(EPOCH)
    now = EPOCH + timedelta(hours=2, minutes=10)
    aired = [runtime.broadcast_at(EPOCH + timedelta(hours=h, minutes=5)).media.asset.asset_id for h in range(3)]
    show.add(7, HOUR)
    changed = show.open(now)
    boundary = changed.broadcast_at(now).program_ends_at
    upcoming = [changed.broadcast_at(boundary + timedelta(hours=h, minutes=5)).media.asset.asset_id for h in range(4)]
    assert not set(upcoming[:3]) & set(aired), "the rest of this pass plays before anything repeats"
    new_id = [item.asset.asset_id for item in show.resolved().media if item.location.path == show.path(7)][0]
    assert new_id == upcoming[3]


def test_missing_media_keeps_its_slot_and_writes_nothing(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    resolved = show.resolved()
    missing = resolved.media[1]
    missing.location.path.unlink()   # really gone, not just left out
    unplugged = replace(resolved, media=tuple(item for item in resolved.media if item is not missing))
    at = EPOCH + timedelta(hours=1, minutes=15)
    runtime = show.open(at, resolved=unplugged, transient=True)
    slot = runtime.broadcast_at(at)
    assert slot.media.asset.asset_id == missing.asset.asset_id and not slot.media.location.online
    assert slot.origin == "unavailable" and slot.event.event_type == "offair", "nothing tries to play it"
    assert (slot.program_started_at, slot.offset_seconds) == (EPOCH + timedelta(hours=1), 900.0)
    assert episode(runtime.broadcast_at(EPOCH + timedelta(hours=2, minutes=1))) == "03", "no time is compressed"
    assert len(show.revisions()) == 1


def test_clock_corrections_never_duplicate_or_reset(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    show.add(4, HOUR)
    show.open(EPOCH + timedelta(hours=5, minutes=10))
    pending = show.revisions()
    # The PC clock jumps back an hour, then forward a day.
    for at in (EPOCH + timedelta(hours=4, minutes=10), EPOCH + timedelta(days=1, hours=5)):
        runtime = show.open(at)
        assert runtime.epoch_utc == EPOCH
        assert show.revisions() == pending
        assert show.store.load_channel(7).epoch_utc == EPOCH


def _beta1_clock(show: Show, signature: str, epoch: datetime) -> None:
    """Write a channel clock the way Beta 1 left it (before revisions existed)."""
    with show.store.connect() as connection:
        connection.execute("INSERT INTO channel_runtime(channel_number, schedule_signature, epoch_utc, updated_at)"
                           " VALUES(7, ?, ?, ?)", (signature, datetime_to_text(epoch), datetime_to_text(epoch)))
        connection.execute("INSERT INTO channel_beta1_clocks(channel_number, schedule_signature, epoch_utc)"
                           " VALUES(7, ?, ?)", (signature, datetime_to_text(epoch)))


def test_beta1_channel_with_the_same_lineup_carries_over_exactly(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    _beta1_clock(show, schedule_signature(show.resolved()), EPOCH)
    paused = EPOCH + timedelta(days=40, minutes=20)
    show.store.save_viewer(7, ViewerClock(paused, paused, running=False), now=paused)
    runtime = show.open(EPOCH + timedelta(days=41))
    assert runtime.epoch_utc == EPOCH and show.store.load_viewer(7) is not None
    assert [revision.reason for revision in show.revisions()] == ["migrated"]
    assert channel_revisions.pending_notices(show.store) == []


def test_beta1_channel_whose_lineup_changed_restarts_honestly(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    _beta1_clock(show, "a-lineup-beta-1-can-no-longer-rebuild", EPOCH)
    now = EPOCH + timedelta(days=41, hours=3)
    runtime = show.open(now)
    assert runtime.epoch_utc == now
    assert [revision.reason for revision in show.revisions()] == ["migrated-restart"]
    assert channel_revisions.pending_notices(show.store) == [{"channelNumber": 7, "migratedAt": datetime_to_text(now)}]
    channel_revisions.mark_notices_shown(show.store)
    assert channel_revisions.pending_notices(show.store) == []
    guide = GuideService((runtime,)).horizon(now - timedelta(hours=2), now + timedelta(hours=1), generated_at=now)
    labels = [program.display_label for program in guide.rows[0].programs]
    assert labels[0] == "Schedule history unavailable" and "Off air" not in labels


def test_restart_is_the_only_way_to_start_over(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR])
    show.open(EPOCH)
    show.store.restart_channel(7)
    now = EPOCH + timedelta(hours=7, minutes=3)
    runtime = show.open(now)
    assert runtime.epoch_utc == now and episode(runtime.broadcast_at(now)) == "01"
    assert [revision.reason for revision in show.revisions()] == ["created"]


def test_deleting_a_channel_removes_its_revisions(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR])
    show.open(EPOCH)
    archive = show.store.delete_channel(7)
    assert show.revisions() == ()
    show.store.restore_deleted_channel(archive)
    assert len(show.revisions()) == 1


def test_saved_viewer_position_names_the_program_and_revision(tmp_path: Path) -> None:
    from channelos.runtime import TelevisionRuntime
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    runtime = show.open(EPOCH)
    tv = TelevisionRuntime((runtime,), show.store)
    at = EPOCH + timedelta(hours=1, minutes=5)
    tv.tune(7, now=at)
    tv.pause(now=at)
    with show.store.connect() as connection:
        row = connection.execute("SELECT asset_id, revision FROM viewer_runtime WHERE channel_number=7").fetchone()
    assert row["asset_id"] == runtime.broadcast_at(at).media.asset.asset_id and row["revision"] == 0


def test_an_unavailable_slot_stops_the_player_instead_of_erroring(tmp_path: Path) -> None:
    from channelos.runtime import TelevisionRuntime
    from channelos.television import TelevisionSession
    from test_television import FakeBackend
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    resolved = show.resolved()
    resolved.media[1].location.path.unlink()
    unplugged = replace(resolved, media=resolved.media[:1] + resolved.media[2:])
    at = EPOCH + timedelta(hours=1, minutes=15)
    runtime = show.open(at, resolved=unplugged, transient=True)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((runtime,), show.store), backend)
    decision = session.tune(7, now=at)
    assert decision.viewer_selection.event.event_type == "offair"
    assert session.sync(now=at + timedelta(minutes=1)).viewer_selection.origin == "unavailable"
    later = session.sync(now=EPOCH + timedelta(hours=2, minutes=1))
    assert episode(later.viewer_selection) == "03" and later.viewer_selection.event.event_type == "program"


def test_editor_shows_pending_changes_and_restarts_on_request(tmp_path: Path) -> None:
    from test_performance_operations import controller_fixture
    _app, controller, root = controller_fixture(tmp_path)
    try:
        assert controller.channelSchedule(7) == {"quick": True, "pending": False}
        runtime = controller._actions.runtime.channels[7]
        from channelos.runtime import utc_now
        now = utc_now()
        new = root / "04-delta.mp4"
        new.write_bytes(b"04-delta-owned")
        library = runtime.channel.library
        library.upsert_file(new, root, content_sha256=hashlib.sha256(new.read_bytes()).hexdigest(),
                            probe=MediaProbeResult(duration_seconds=600, container_format="mp4"))
        controller._reload_lineup()
        info = controller.channelSchedule(7)
        assert info["quick"] and info["pending"] and info["afterTitle"] and info["at"]
        assert info["effectiveMs"] > int(now.timestamp() * 1000)
        assert controller._actions.runtime.channels[7].epoch_utc == runtime.epoch_utc, "no restart"
        result = controller.restartChannel(7)
        assert result["ok"], result
        restarted = controller._actions.runtime.channels[7]
        assert restarted.epoch_utc > runtime.epoch_utc
        assert controller.channelSchedule(7) == {"quick": True, "pending": False}
        assert controller.takeMigrationNotice() == ""
    finally:
        controller.stop()


# ---------------------------------------------------------------------------
# Regressions from GPT's audit of 72d908b (each failed on that commit).

def test_audit1_a_normal_rescan_queues_the_change_through_the_recovery_worker(tmp_path: Path) -> None:
    import threading
    from PySide6.QtGui import QGuiApplication
    from channelos.broadcaster import BroadcasterService
    from channelos.recovery_jobs import RecoveryWorker
    QGuiApplication.instance() or QGuiApplication([])
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    service = BroadcasterService((), tmp_path / "channels", show.library)
    service.create({"channel": 7, "name": "Sci-Fi Classics", "sources": [str(show.folder)], "mode": "sequential"})
    definition = service.records[0].definition
    ChannelRuntime.open(resolve_channel(definition, show.library), show.store)
    show.add(4, HOUR)
    worker = RecoveryWorker(show.library, service, show.store, {}, (), threading.Event())
    results = []
    worker.completed.connect(results.append)
    worker.run()
    assert 7 in results[0]["prepared"]
    assert len(show.revisions()) == 2, "the rescan itself queued the new lineup"


def test_audit2_removing_a_readable_current_item_lets_it_finish(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    now = EPOCH + timedelta(hours=1, minutes=20)          # episode 2 is on
    resolved = show.resolved()
    current = resolved.media[1]
    without = replace(resolved, media=tuple(item for item in resolved.media if item is not current))
    runtime = show.open(now, resolved=without)
    on_now = runtime.broadcast_at(now)
    assert episode(on_now) == "02" and on_now.origin != "unavailable" and on_now.media.location.online
    assert episode(runtime.broadcast_at(EPOCH + timedelta(hours=2, minutes=1))) == "03"
    assert episode(runtime.broadcast_at(EPOCH + timedelta(hours=3, minutes=1))) == "01"


def test_audit3_a_disconnected_source_keeps_its_schedule_for_when_it_returns(tmp_path: Path) -> None:
    from channelos.couch import _open_runtimes
    from channelos.broadcaster import BroadcasterService
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    service = BroadcasterService((), tmp_path / "channels", show.library)
    service.create({"channel": 7, "name": "Sci-Fi Classics", "sources": [str(show.folder)], "mode": "sequential"})
    definition = service.records[0].definition
    reference = ChannelRuntime.open(resolve_channel(definition, show.library), show.store, now=EPOCH)
    expected = reference.project_at(EPOCH + timedelta(hours=26, minutes=10))
    saved = show.revisions()
    # The whole drive goes away: the channel shows as unavailable (no runtime)
    # and nothing about its schedule is written or compressed.
    hidden = tmp_path / "unplugged"
    show.folder.rename(hidden)
    assert _open_runtimes(service.paths, show.library, show.store) == ()
    assert show.revisions() == saved and show.store.load_channel(7).epoch_utc == EPOCH
    hidden.rename(show.folder)
    back = ChannelRuntime.open(resolve_channel(definition, show.library), show.store,
                               now=EPOCH + timedelta(hours=26))
    again = back.project_at(EPOCH + timedelta(hours=26, minutes=10))
    assert (again.media.asset.asset_id, again.offset_seconds) == (expected.media.asset.asset_id, expected.offset_seconds)


def test_audit4_snapshots_and_rollback_carry_revisions_and_the_beta2_marker(tmp_path: Path) -> None:
    from channelos.runtime_snapshot import channel_snapshot, restore_channel_snapshot
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    show.add(4, HOUR)
    show.open(EPOCH + timedelta(minutes=10))
    assert len(show.revisions()) == 2
    copy = channel_snapshot(show.store.database_path, tmp_path / "snapshot.db", 7)
    assert len(channel_revisions.load_revisions(copy, 7)) == 2
    assert not copy.clock_written_before_revisions(7), "a Beta 2 clock is never mistaken for Beta 1"
    with show.store.connect() as connection:
        connection.execute("DELETE FROM channel_revisions WHERE channel_number=7 AND revision=1")
    restore_channel_snapshot(tmp_path / "snapshot.db", show.store.database_path, 7)
    assert len(show.revisions()) == 2


def test_audit5_a_clock_set_back_never_reopens_an_aired_revision(tmp_path: Path) -> None:
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    show.open(EPOCH)
    show.add(4, HOUR)
    runtime = show.open(EPOCH + timedelta(minutes=10))
    boundary = show.revisions()[1].effective_utc
    watched_at = boundary + timedelta(minutes=10)
    watched = runtime.broadcast_at(watched_at)                  # live airing passed the boundary
    # The PC clock is set back to before the boundary, then the library changes.
    show.add(5, HOUR)
    back = show.open(EPOCH + timedelta(minutes=20))
    revisions = show.revisions()
    assert len(revisions[1].lineup) == 4, "the revision that aired is unchanged"
    assert revisions[-1].revision == 2 and revisions[-1].effective_utc > watched_at
    again = back.project_at(watched_at)
    assert (episode(again), again.offset_seconds) == (episode(watched), watched.offset_seconds)


def test_audit6_an_interrupted_migration_changes_nothing(tmp_path: Path, monkeypatch) -> None:
    import pytest
    show = Show(tmp_path, [HOUR, HOUR, HOUR])
    _beta1_clock(show, "a-lineup-beta-1-can-no-longer-rebuild", EPOCH)
    real = channel_revisions.lineup_to_text
    monkeypatch.setattr(channel_revisions, "lineup_to_text", lambda lineup: (_ for _ in ()).throw(OSError("power cut")))
    with pytest.raises(OSError):
        show.open(EPOCH + timedelta(days=41))
    assert show.store.load_channel(7).schedule_signature == "a-lineup-beta-1-can-no-longer-rebuild"
    assert show.revisions() == () and channel_revisions.pending_notices(show.store) == []
    monkeypatch.setattr(channel_revisions, "lineup_to_text", real)
    now = EPOCH + timedelta(days=41, hours=1)
    runtime = show.open(now)
    assert show.revisions()[0].history_unknown_before == now
    guide = GuideService((runtime,)).horizon(now - timedelta(hours=1), now + timedelta(hours=1), generated_at=now)
    assert guide.rows[0].programs[0].display_label == "Schedule history unavailable"


def test_audit7_pending_change_is_reported_on_the_wall_clock_with_ads(tmp_path: Path) -> None:
    import hashlib as _hashlib
    from test_ad_broadcast_integration import EPOCH as AD_EPOCH, open_runtime, setup
    library, definition, _ = setup(tmp_path, break_duration_seconds=15)
    runtime, store = open_runtime(tmp_path, library, definition)
    for second in range(0, 400, 5):
        runtime.broadcast_at(AD_EPOCH + timedelta(seconds=second))
    runtime.break_store.close()
    path = tmp_path / "programs" / "added.mp4"
    path.write_bytes(b"added")
    library.upsert_file(path, path.parent, content_sha256=_hashlib.sha256(b"added").hexdigest(),
                        probe=MediaProbeResult(duration_seconds=45, container_format="mp4"))
    changed_at = AD_EPOCH + timedelta(seconds=400)
    changed, _ = open_runtime(tmp_path, library, definition, now=changed_at)
    pending = changed.pending_change(changed_at)
    assert pending is not None
    # Walk the real airing: the change must still be pending until the
    # program it follows has actually finished on the wall clock.
    activation = None
    for second in range(0, 600):
        at = changed_at + timedelta(seconds=second)
        if changed.broadcast_at(at).media.location.path == path:
            activation = at
            break
    assert activation is not None
    assert changed.pending_change(activation - timedelta(seconds=15)) is not None
    assert changed.pending_change(activation - timedelta(seconds=1)) is not None
    assert changed.pending_change(activation + timedelta(seconds=1)) is None
    # The shown time can only be early (breaks not planned yet), never late, and says "about".
    assert pending["approximate"] and pending["effective_utc"] <= activation


def test_audit8_a_transient_ad_projection_writes_nothing(tmp_path: Path) -> None:
    import sqlite3
    from test_ad_broadcast_integration import EPOCH as AD_EPOCH, setup
    library, definition, _ = setup(tmp_path, break_duration_seconds=15)
    store = RuntimeStore(tmp_path / "runtime.sqlite")
    first = ChannelRuntime.open(resolve_channel(definition, library), store, now=AD_EPOCH)
    first.broadcast_at(AD_EPOCH + timedelta(seconds=30))
    first.break_store.close()

    def state():
        with sqlite3.connect(store.database_path) as connection:
            return [connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in ("ad_break_plans", "ad_break_catchup_state", "ad_program_clock", "ad_break_history")]

    before = state()
    transient = ChannelRuntime.open(resolve_channel(definition, library), store, now=AD_EPOCH, transient=True)
    for second in range(0, 900, 10):
        transient.broadcast_at(AD_EPOCH + timedelta(seconds=second))
        transient.project_at(AD_EPOCH + timedelta(seconds=second))
    assert state() == before
