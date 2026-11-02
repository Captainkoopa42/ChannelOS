"""Release regressions for the second Windows ChannelOS publication."""
from dataclasses import replace
from pathlib import Path
import hashlib
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from channelos.broadcaster import BroadcasterError
from channelos.probe import MediaProbeResult
from channelos.loader import load_channel
from test_simple_ads import setup, START


@pytest.mark.parametrize('mode', ['sequential', 'shuffle', 'calendar'])
def test_library_add_preserves_full_channel_and_is_idempotent(tmp_path, mode):
    library, service, raw = setup(tmp_path)
    raw['mode'] = mode
    if mode == 'calendar':
        raw['calendarBlocks'] = service.auto_fill_studio(
            raw, START.isoformat(), START.replace(minute=10).isoformat())['blocks']
    original = service.create(raw).record
    extra = tmp_path / 'extra.mp4'
    extra.write_bytes(b'extra')
    library.upsert_file(extra, tmp_path,
        content_sha256=hashlib.sha256(b'extra').hexdigest(),
        probe=MediaProbeResult(duration_seconds=30, container_format='mp4'))
    item = next(item for item in library.list_online_media() if item.location.path == extra)
    saved = service.add_library_item(7, item.asset.asset_id, str(extra))
    expected = replace(original.definition, sources=saved.record.definition.sources)
    assert saved.record.definition == expected
    assert len(saved.record.definition.sources) == len(original.definition.sources) + 1
    assert load_channel(saved.record.path) == expected
    assert service.add_library_item(7, item.asset.asset_id, str(extra)).record == saved.record
    with pytest.raises(BroadcasterError, match='no longer available'):
        service.add_library_item(7, 'wrong-id', str(extra))


def test_startup_keeps_healthy_channel_and_supports_empty_recovery(tmp_path):
    from channelos.broadcaster import BroadcasterService
    from channelos.couch import _open_runtimes
    from channelos.couch_qt import CouchController
    from channelos.guide import GuideService
    from channelos.runtime import RuntimeStore, TelevisionRuntime, ChannelRuntimeError
    from test_broadcaster import make_library, editor
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    library, root = make_library(tmp_path)
    paths = sorted(root.glob('*.mp4'))
    service = BroadcasterService((), tmp_path / 'channels', library)
    service.create(editor(7, paths[0]))
    service.create(editor(8, paths[1]))
    store = RuntimeStore(tmp_path / 'runtime.db')
    paths[0].unlink()
    runtimes = _open_runtimes(service.paths, library, store)
    assert [r.channel_number for r in runtimes] == [8]
    for runtime in runtimes:
        if runtime.break_store: runtime.break_store.close()
    paths[1].unlink()
    assert _open_runtimes(service.paths, library, store) == ()
    tv = TelevisionRuntime((), store)
    controller = CouchController(GuideService((), definitions=tuple(record.definition for record in service.records)), tv, library)
    unavailable = [row for row in controller.snapshot['rows'] if row.get('isUnavailable')]
    assert {row['channelNumber'] for row in unavailable} == {7, 8}
    assert all(row['programs'][0]['title'] == 'MEDIA UNAVAILABLE' for row in unavailable)
    assert not controller.tuneChannel(7)['ok']
    assert 'Reconnect' in controller.tuneChannel(7)['message']
    assert not controller.playback.get('active')
    for action in (tv.channel_up, tv.channel_down):
        with pytest.raises(ChannelRuntimeError, match='No channels'):
            action()
    paths[0].write_bytes(b'reconnected')
    reopened = _open_runtimes(service.paths, library, store)
    assert [r.channel_number for r in reopened] == [7]
    assert len(service.records) == 2
    for runtime in reopened:
        if runtime.break_store: runtime.break_store.close()


def test_source_guard_covers_program_files_and_ads_and_checks_backend(tmp_path):
    from test_broadcaster import editor
    library, service, raw = setup(tmp_path)
    service.create(raw)
    program = next(item for item in library.list_online_media()
                   if item.location.path.name == 'show.mp4')
    service.create(editor(8, program.location.path))
    assert {item['channelNumber'] for item in service.source_dependencies(tmp_path / 'programs')} == {7, 8}
    assert {item['channelNumber'] for item in service.source_dependencies(tmp_path / 'commercials')} == {7}
    with pytest.raises(BroadcasterError, match='still used'):
        service.remove_library_source(tmp_path / 'commercials')
    assert all(item.location.path.is_file() for item in library.list_online_media())


def test_channel_deletion_archives_history_and_reuse_starts_fresh(tmp_path):
    import json
    from datetime import timedelta
    from channelos.ad_catalog import AdCollection, BreakProfile, ChannelAdAssignment
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore
    from test_broadcaster import editor
    library, service, raw = setup(tmp_path)
    original = service.create(raw).record
    service.create(editor(8, tmp_path / 'programs'))
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(tmp_path / 'commercials'))
    service.ad_catalog.save_collection(AdCollection('ads', 'Ads', ids))
    service.ad_catalog.save_profile(BreakProfile('profile', 'Profile', {'enabled': True, 'duration_seconds': 10}))
    service.ad_catalog.assign_channel(ChannelAdAssignment(7, 'ads', 'profile'))
    store = RuntimeStore(service.runtime_database_path)
    runtime = ChannelRuntime.open(resolve_channel(original.definition, library), store, now=START)
    runtime.events_between(START, START + timedelta(seconds=300))
    runtime.break_store.reconcile_completed(7, through=START + timedelta(seconds=300))
    assert runtime.break_store.play_counts()
    runtime.break_store.close()
    before = store.load_channel(7)
    deleted = service.delete(7)
    assert service.ad_catalog.get_assignment(7) is None
    assert store.load_channel(7) is None
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM ad_program_clock WHERE channel_number=7').fetchone()[0] == 0
        archive = json.loads(db.execute('SELECT payload FROM deleted_channel_archives WHERE archive_id=?', (deleted.archive_id,)).fetchone()[0])
    assert archive['ad_break_history']
    assert archive['ad_program_clock']
    service.restore_deleted(deleted)
    assert store.load_channel(7) == before
    assert service.ad_catalog.get_assignment(7).profile_id == 'profile'
    service.delete(7)
    fresh = editor(7, tmp_path / 'programs')
    fresh['adBreaksEnabled'] = False
    definition = service.create(fresh).record.definition
    assert not definition.advertising.enabled
    assert not definition.advertising.profile_id
    reopened = ChannelRuntime.open(resolve_channel(definition, library), store, now=START + timedelta(seconds=310))
    try:
        selected = reopened.project_at(START + timedelta(seconds=310))
        assert selected.origin != 'advertisement'
        assert selected.offset_seconds == 0
        assert reopened.break_store is None
    finally:
        if reopened.break_store: reopened.break_store.close()


def test_interrupted_delete_recovers_without_stale_assignment(tmp_path, monkeypatch):
    from channelos.broadcaster import BroadcasterService
    from channelos.ad_catalog import AdCollection, BreakProfile, ChannelAdAssignment
    from test_broadcaster import editor
    library, service, raw = setup(tmp_path)
    service.create(raw)
    service.create(editor(8, tmp_path / 'programs'))
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(tmp_path / 'commercials'))
    service.ad_catalog.save_collection(AdCollection('ads', 'Ads', ids))
    service.ad_catalog.save_profile(BreakProfile('p', 'Profile', {'enabled': True}))
    service.ad_catalog.assign_channel(ChannelAdAssignment(7, 'ads', 'p'))
    monkeypatch.setattr(service.ad_catalog, 'clear_channel_assignment', lambda number: (_ for _ in ()).throw(SystemExit('power loss')))
    with pytest.raises(SystemExit):
        service.delete(7)
    assert list((tmp_path / 'channels').glob('channel-deletion-*.json'))
    recovered = BroadcasterService((), tmp_path / 'channels', library)
    assert recovered.channel_numbers == (8,)
    assert recovered.ad_catalog.get_assignment(7) is None
    assert not list((tmp_path / 'channels').glob('channel-deletion-*.json'))


def test_advanced_edits_override_profile_in_preview_apply_and_restart(tmp_path):
    from channelos.ad_catalog import AdCollection, BreakProfile, ChannelAdAssignment
    library, service, raw = setup(tmp_path)
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(tmp_path / 'commercials'))
    service.ad_catalog.save_collection(AdCollection('ads', 'Ads', ids))
    service.ad_catalog.save_profile(BreakProfile('p', 'Ten seconds', {
        'enabled': True, 'duration_seconds': 10, 'timing_policy': 'strict_fit', 'triggers': ['breakpoint']}))
    service.ad_catalog.assign_channel(ChannelAdAssignment(7, 'ads', 'p'))
    raw.update(adSetupMode='advanced', adEditedKeys=[])
    service.create(raw)
    draft = service.studio_draft(7)
    draft.update(adBreakDurationSeconds=30, adTimingPolicy='smoosh', adSmooshMaxTrimSeconds=2,
                 adTransitionSeconds=0, adBreakpointsSeconds=[], adTriggers=['between_programs'],
                 adEditedKeys=['adBreakDurationSeconds', 'adTimingPolicy', 'adSmooshMaxTrimSeconds',
                               'adTransitionSeconds', 'adBreakpointsSeconds', 'adTriggers'])
    original = service.ad_catalog.get_assignment(7)
    preview_policy = service._configured_definition(draft).advertising
    service.preview(draft)
    assert service.ad_catalog.get_assignment(7) == original
    assert preview_policy.break_duration_seconds == 30
    assert preview_policy.timing_policy == 'smoosh'
    assert preview_policy.smoosh_max_trim_seconds == 2
    assert preview_policy.transition_seconds == 0
    assert preview_policy.breakpoints_seconds == ()
    assert service.update(7, draft).record.definition.advertising == preview_policy
    reopened = service.studio_draft(7)
    reopened['adEditedKeys'] = []
    assert service._configured_definition(reopened).advertising == preview_policy
    reopened['adBreaksEnabled'] = False
    assert not service._configured_definition(reopened).advertising.enabled


def test_staged_assignment_is_pure_until_channel_saved(tmp_path):
    from channelos.ad_catalog import AdCollection, BreakProfile
    library, service, raw = setup(tmp_path)
    service.create(raw)
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(tmp_path / 'commercials'))
    service.ad_catalog.save_collection(AdCollection('ads', 'Ads', ids))
    service.ad_catalog.save_profile(BreakProfile('p', 'Profile', {'enabled': True, 'duration_seconds': 10}))
    draft = service.studio_draft(7)
    draft.update(adSetupMode='advanced', adCollectionId='ads', adProfileId='p', adEditedKeys=[],
        adCatalogAssignment={'collectionId': 'ads', 'profileId': 'p', 'overrides': {'priority': 0}, 'placements': []})
    service.preview(draft)
    assert service.ad_catalog.get_assignment(7) is None
    service.update(7, draft)
    assert service.ad_catalog.get_assignment(7).profile_id == 'p'


@pytest.mark.parametrize('order', ['sequential', 'shuffle'])
def test_calendar_insertion_replays_future_reservations_without_repeat(tmp_path, order):
    from datetime import timedelta
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore
    library, service, raw = setup(tmp_path, order=order)
    raw['mode'] = 'calendar'
    raw['calendarBlocks'] = service.auto_fill_studio(raw,
        (START + timedelta(seconds=90)).isoformat(), (START + timedelta(seconds=180)).isoformat())['blocks']
    service.create(raw)
    original_start = raw['calendarBlocks'][0]['startUtc']
    filled = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=180)).isoformat())
    assert filled['updatedBlocks'][0]['startUtc'] == original_start
    raw['calendarBlocks'] = filled['blocks'] + filled['updatedBlocks']
    prepared = sorted(raw['calendarBlocks'], key=lambda block: block['startUtc'])
    assert prepared[0]['adPlan']['breaks'][0]['segments'][0]['asset_id'] != prepared[1]['adPlan']['breaks'][0]['segments'][0]['asset_id']
    definition = service.update(7, raw).record.definition
    runtime = ChannelRuntime.open(resolve_channel(definition, library), RuntimeStore(service.runtime_database_path), now=START)
    try:
        events = runtime.events_between(START, START + timedelta(seconds=180))
        ads = [event for event in events if event.event_type == 'advertisement']
        assert len(ads) == 2
        assert ads[0].asset_id != ads[1].asset_id
        assert [event.asset_id for event in ads] == [block['adPlan']['breaks'][0]['segments'][0]['asset_id'] for block in prepared]
    finally:
        runtime.break_store.close()


def test_removed_future_blocks_never_enter_airing_ledger(tmp_path):
    from datetime import timedelta
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore
    library, service, raw = setup(tmp_path)
    raw['mode'] = 'calendar'
    raw['calendarBlocks'] = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=240)).isoformat())['blocks']
    definition = service.create(raw).record.definition
    store = RuntimeStore(service.runtime_database_path)
    runtime = ChannelRuntime.open(resolve_channel(definition, library), store, now=START)
    runtime.events_between(START, START + timedelta(seconds=240))
    assert len(runtime.break_store.plans_for_channel(7, start=START, end=START + timedelta(seconds=240))) == 3
    runtime.break_store.close()
    changed = replace(definition, programming=replace(definition.programming, calendar=definition.programming.calendar[:1]))
    reopened = ChannelRuntime.open(resolve_channel(changed, library), store, now=START + timedelta(seconds=1))
    try:
        events = reopened.events_between(START, START + timedelta(seconds=240))
        reopened.broadcast_at(START + timedelta(seconds=239))
        assert sum(event.event_type == 'advertisement' for event in events) == 1
        assert sum(reopened.break_store.play_counts(7).values()) == 1
        assert reopened.break_store.connection.execute('SELECT COUNT(*) FROM ad_superseded_plans').fetchone()[0] == 2
    finally:
        reopened.break_store.close()


def test_real_studio_swap_discards_wrong_parent_snapshot(tmp_path):
    from datetime import timedelta
    from PySide6.QtCore import QUrl, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression
    from test_channel_studio_qml_runtime import FakeStudioController, FakeStudioHost
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore
    import channelos
    library, service, raw = setup(tmp_path)
    raw['mode'] = 'calendar'
    raw['calendarBlocks'] = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=90)).isoformat())['blocks']
    path = tmp_path / 'programs' / 'short.mp4'
    path.write_bytes(b'short')
    asset, _ = library.upsert_file(path, path.parent, content_sha256=hashlib.sha256(b'short').hexdigest(),
        probe=MediaProbeResult(duration_seconds=30, container_format='mp4'))
    raw['calendarBlocks'].append({'assetId': asset.asset_id, 'durationSeconds': 30,
        'startUtc': (START + timedelta(seconds=90)).isoformat()})
    service.create(raw)

    class Controller(FakeStudioController):
        @Slot(int, result='QVariantMap')
        def loadChannelStudio(self, number):
            return {'ok': True, 'draft': service.studio_draft(number)}

    app = QGuiApplication.instance() or QGuiApplication([])
    controller, host = Controller(), FakeStudioHost()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('channelOS', controller)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(Path(channelos.__file__).parent / 'qml/ChannelStudioScreen.qml')))
    item = component.create()
    assert item is not None, [error.toString() for error in component.errors()]
    item.setProperty('hostWindow', host)
    app.processEvents()
    expression = QQmlExpression(engine.rootContext(), item, 'swapPrograms(0,1); editorObject()')
    value, _ = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    updated = value.toVariant()
    assert updated['calendarBlocks'][0]['assetId'] == asset.asset_id
    assert updated['calendarBlocks'][0]['adPlan'] is None
    saved = service.update(7, updated).record.definition
    runtime = ChannelRuntime.open(resolve_channel(saved, library), RuntimeStore(service.runtime_database_path), now=START)
    try:
        events = runtime.events_between(START, START + timedelta(seconds=90))
        assert events[0].end_utc == START + timedelta(seconds=30)
        assert events[1].event_type == 'advertisement'
        assert events[1].start_utc == events[0].end_utc
        assert all(left.end_utc <= right.start_utc for left, right in zip(events, events[1:]))
    finally:
        runtime.break_store.close()
        item.deleteLater()
        app.processEvents()


def test_partial_offline_lineup_never_uses_an_old_program_clock(tmp_path):
    from datetime import timedelta
    from channelos.resolve import resolve_channel
    from channelos.broadcaster import definition_from_editor
    from channelos.runtime import ChannelRuntime, RuntimeStore
    from channelos.media_resilience import _resolved_runtime
    library, service, raw = setup(tmp_path)
    other = tmp_path / 'other'
    other.mkdir()
    path = other / 'short.mp4'
    path.write_bytes(b'short')
    library.upsert_file(path, other, content_sha256=hashlib.sha256(b'short').hexdigest(),
        probe=MediaProbeResult(duration_seconds=30, container_format='mp4'))
    raw['sources'].append(str(other))
    definition = definition_from_editor(raw)
    store = RuntimeStore(service.runtime_database_path)
    original = ChannelRuntime.open(resolve_channel(definition, library), store, now=START)
    original.events_between(START, START + timedelta(seconds=300))
    original.break_store.close()
    clock = store.load_channel(7)
    (tmp_path / 'programs').rename(tmp_path / 'unplugged')
    partial = _resolved_runtime(definition, library, store, persistent_when_complete=True, verify_files=True)
    try:
        for seconds in (1, 35, 61, 90, 120):
            selected = partial.project_at(START + timedelta(seconds=seconds))
            assert 0 <= selected.offset_seconds < selected.program.duration_seconds
        assert store.load_channel(7) == clock
    finally:
        partial.break_store.close()
    (tmp_path / 'unplugged').rename(tmp_path / 'programs')
    restored = _resolved_runtime(definition, library, store, persistent_when_complete=True, verify_files=True)
    try:
        assert store.load_channel(7) == clock
        assert len(restored.channel.media) == 2
    finally:
        restored.break_store.close()


def test_profile_reset_restores_inheritance_without_preview_writes(tmp_path):
    from channelos.ad_catalog import AdCollection, BreakProfile, ChannelAdAssignment
    library, service, raw = setup(tmp_path)
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(tmp_path / 'commercials'))
    service.ad_catalog.save_collection(AdCollection('ads', 'Ads', ids))
    service.ad_catalog.save_profile(BreakProfile('p', 'Profile', {'enabled': True, 'duration_seconds': 10}))
    service.ad_catalog.assign_channel(ChannelAdAssignment(7, 'ads', 'p', {'duration_seconds': 30}))
    raw.update(adSetupMode='advanced', adEditedKeys=[])
    service.create(raw)
    draft = service.studio_draft(7)
    draft.update(adCatalogAssignment={'collectionId': 'ads', 'profileId': 'p', 'overrides': {}, 'placements': []}, adEditedKeys=[])
    values = service.preview_ad_settings(7, draft)
    assert values['adBreakDurationSeconds'] == 10
    assert service.ad_catalog.get_assignment(7).overrides['duration_seconds'] == 30
    draft.update(values)
    service.update(7, draft)
    assert not service.ad_catalog.get_assignment(7).overrides
    service.ad_catalog.save_profile(BreakProfile('p', 'Profile', {'enabled': True, 'duration_seconds': 20}))
    current = service.studio_draft(7)
    current['adEditedKeys'] = []
    assert service._configured_definition(current).advertising.break_duration_seconds == 20


def test_calendar_edits_preserve_active_break_and_reject_viewed_future_change(tmp_path):
    from datetime import timedelta
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore, ChannelRuntimeError
    library, service, raw = setup(tmp_path)
    raw['mode'] = 'calendar'
    raw['calendarBlocks'] = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=240)).isoformat())['blocks']
    definition = service.create(raw).record.definition
    store = RuntimeStore(service.runtime_database_path)
    runtime = ChannelRuntime.open(resolve_channel(definition, library), store, now=START)
    runtime.events_between(START, START + timedelta(seconds=240))
    at = START + timedelta(seconds=61)
    active = runtime.project_at(at)
    assert active.origin == 'advertisement'
    runtime.break_store.close()
    trimmed = replace(definition, programming=replace(definition.programming, calendar=definition.programming.calendar[:2]))
    reopened = ChannelRuntime.open(resolve_channel(trimmed, library), store, now=at)
    try:
        continued = reopened.project_at(at)
        assert (continued.break_id, continued.media, continued.offset_seconds,
                continued.program_started_at, continued.program_ends_at) == (
                    active.break_id, active.media, active.offset_seconds,
                    active.program_started_at, active.program_ends_at)
        future = reopened.break_store.plans_for_channel(7, start=START + timedelta(seconds=90), end=START + timedelta(seconds=240))[0]
        part = future.segments[0]
        reopened.break_store.record_viewed(future.plan_id, 0, part.asset_id,
            consumed_seconds=part.duration_seconds, completed_at=at)
    finally:
        reopened.break_store.close()
    clock = store.load_channel(7)
    rejected = replace(trimmed, programming=replace(trimmed.programming, calendar=trimmed.programming.calendar[:1]))
    with pytest.raises(ChannelRuntimeError, match='previously aired or viewed'):
        ChannelRuntime.open(resolve_channel(rejected, library), store, now=at)
    assert store.load_channel(7) == clock


def test_legacy_orphan_airings_are_retained_and_flagged_for_review(tmp_path):
    from datetime import timedelta
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore
    library, service, raw = setup(tmp_path)
    raw['mode'] = 'calendar'
    raw['calendarBlocks'] = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=240)).isoformat())['blocks']
    definition = service.create(raw).record.definition
    store = RuntimeStore(service.runtime_database_path)
    runtime = ChannelRuntime.open(resolve_channel(definition, library), store, now=START)
    runtime.events_between(START, START + timedelta(seconds=240))
    runtime.break_store.reconcile_completed(7, through=START + timedelta(seconds=239))
    with runtime.break_store.connection:
        runtime.break_store.connection.execute('DELETE FROM ad_calendar_state')  # Legacy setup has no intent provenance.
    runtime.break_store.close()
    trimmed = replace(definition, programming=replace(definition.programming, calendar=definition.programming.calendar[:1]))
    reopened = ChannelRuntime.open(resolve_channel(trimmed, library), store, now=START + timedelta(seconds=240))
    try:
        assert sum(reopened.break_store.play_counts(7).values()) == 3  # Evidence is not silently rewritten.
        assert reopened.break_store.diagnostics(7)['legacyHistoryReviewCount'] == 2
        assert service.ad_catalog_snapshot()['historyReviewCount'] == 2
    finally:
        reopened.break_store.close()


def test_source_removal_allows_duplicates_inside_permitted_source_union(tmp_path):
    from test_broadcaster import make_library, editor, FixedProbe
    from channelos.broadcaster import BroadcasterService
    from channelos.scanner import MediaScanner
    library, first = make_library(tmp_path)
    second = tmp_path / 'second'
    second.mkdir()
    for path in first.glob('*.mp4'):
        (second / path.name).write_bytes(path.read_bytes())
    MediaScanner(library, FixedProbe()).scan(second)
    service = BroadcasterService((), tmp_path / 'channels', library)
    raw = editor(7, first)
    raw['sources'].append(str(second))
    service.create(raw)
    service.create(editor(8, sorted(first.glob('*.mp4'))[0]))
    assert [item['channelNumber'] for item in service.source_dependencies(first)] == [8]
    service.delete(8)
    assert service.source_dependencies(first) == []
    service.remove_library_source(first)
    assert all(path.is_file() for path in first.glob('*.mp4'))
    assert library.list_online_media_for_source(second)


def test_source_removal_protects_unassigned_saved_ad_collection(tmp_path):
    from channelos.ad_catalog import AdCollection
    library, service, raw = setup(tmp_path)
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(tmp_path / 'commercials'))
    service.ad_catalog.save_collection(AdCollection('unassigned', 'Saved commercials', ids))
    report = service.source_dependencies(tmp_path / 'commercials')
    assert report[0]['kind'] == 'collection'
    assert report[0]['name'] == 'Saved commercials'
    with pytest.raises(BroadcasterError, match='ad collection'):
        service.remove_library_source(tmp_path / 'commercials')
