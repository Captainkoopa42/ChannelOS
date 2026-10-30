"""Behavioral acceptance tests spanning runtime, persistence, Guide and decoder."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from channelos.ad_catalog import (AdCatalogStore, AdCollection, AdPlacementAssignment,
                                  BreakProfile, ChannelAdAssignment, export_portable_channel)
from channelos.broadcaster import channel_to_mapping
from channelos.guide import GuideService
from channelos.models import ChannelDefinition
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
from channelos.television import TelevisionSession
from test_ad_portable import indexed, config
from test_television import FakeBackend

EPOCH = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def setup(tmp_path, **settings):
    library, root, ads = indexed(tmp_path)
    ids = [item.asset.asset_id for item in library.list_online_media_for_source(ads)]
    raw = channel_to_mapping(config(root, ids))
    raw['advertising'].update(settings)
    return library, ChannelDefinition.from_mapping(raw), ids


def open_runtime(tmp_path, library, definition, name='runtime', now=EPOCH):
    store = RuntimeStore(tmp_path / (name + '.sqlite'))
    return ChannelRuntime.open(resolve_channel(definition, library), store, now=now), store


def test_guide_projection_never_records_future_airings_and_does_not_bias_rotation(tmp_path):
    library, definition, _ = setup(tmp_path, selection_strategy='least_played', break_duration_seconds=15)
    projected, _ = open_runtime(tmp_path, library, definition, 'projected')
    GuideService((projected,)).horizon(EPOCH, EPOCH + timedelta(seconds=600), generated_at=EPOCH)
    assert projected.break_store.play_counts() == {}
    direct, _ = open_runtime(tmp_path, library, definition, 'direct')
    for second in range(0, 601, 5):
        direct.broadcast_at(EPOCH + timedelta(seconds=second))
    now = EPOCH + timedelta(seconds=600)
    actual = projected.broadcast_at(now)
    expected = direct.broadcast_at(now)
    assert (actual.media.asset.asset_id, actual.offset_seconds) == (expected.media.asset.asset_id, expected.offset_seconds)
    assert projected.break_store.play_counts() == direct.break_store.play_counts()


def test_long_offline_catchup_matches_continuous_rotation(tmp_path):
    library, definition, _ = setup(tmp_path, selection_strategy='complete_rotation', break_duration_seconds=15)
    direct, _ = open_runtime(tmp_path, library, definition, 'direct')
    missed, _ = open_runtime(tmp_path, library, definition, 'missed')
    missed.project_at(EPOCH)
    missed.break_store.close()
    for second in range(0, 3601, 30):
        direct.broadcast_at(EPOCH + timedelta(seconds=second))
    recovered, _ = open_runtime(tmp_path, library, definition, 'missed', now=EPOCH + timedelta(hours=1))
    actual = recovered.broadcast_at(EPOCH + timedelta(hours=1))
    expected = direct.broadcast_at(EPOCH + timedelta(hours=1))
    assert actual.event == expected.event
    assert actual.offset_seconds == pytest.approx(expected.offset_seconds)
    assert recovered.break_store.play_counts() == direct.break_store.play_counts()


def test_event_segments_cover_program_content_once_across_multiple_interruptions(tmp_path):
    library, definition, _ = setup(tmp_path, breakpoints_seconds=[10, 30, 50],
                                  break_duration_seconds=10, triggers=['breakpoint'])
    runtime, _ = open_runtime(tmp_path, library, definition)
    events = runtime.events_between(EPOCH, EPOCH + timedelta(seconds=90))
    assert [item.event_type for item in events] == ['program', 'advertisement'] * 3 + ['program']
    assert len({item.segment_id for item in events}) == len(events)
    content = [item for item in events if item.event_type == 'program']
    assert [(item.source_offset_seconds, item.source_offset_end_seconds) for item in content] == [
        (0, 10), (10, 30), (30, 50), (50, 60)]
    assert all(left.end_utc == right.start_utc for left, right in zip(events, events[1:]))
    assert runtime.break_store.play_counts() == {}


def test_placement_profiles_export_and_play_separate_collections_without_catalog(tmp_path):
    library, definition, ids = setup(tmp_path)
    catalog = AdCatalogStore(tmp_path / 'catalog.sqlite')
    for i, asset_id in enumerate(ids):
        catalog.save_collection(AdCollection(f'c{i}', f'Collection {i}', (asset_id,)))
    catalog.save_profile(BreakProfile('inside', 'Inside', {
        'enabled': True, 'breakpoints_seconds': [20], 'duration_seconds': 15}))
    catalog.save_profile(BreakProfile('between', 'Between', {'enabled': True, 'duration_seconds': 15}))
    catalog.assign_channel(ChannelAdAssignment(7, 'c0', 'inside', placements=(
        AdPlacementAssignment('during', 'breakpoint', 'c0', 'inside'),
        AdPlacementAssignment('after', 'between_programs', 'c1', 'between'),
    )))
    portable = export_portable_channel(definition, catalog, library)
    portable = ChannelDefinition.from_mapping(channel_to_mapping(portable))
    runtime, _ = open_runtime(tmp_path, library, portable)
    inside = runtime.broadcast_at(EPOCH + timedelta(seconds=21))
    assert inside.media.asset.asset_id == ids[0]
    first_duration = library.list_online_media_for_source(tmp_path / 'commercials')[0].asset.duration_seconds
    between_start = EPOCH + timedelta(seconds=60 + first_duration)
    after = runtime.broadcast_at(between_start + timedelta(seconds=1))
    assert after.origin == 'advertisement'
    assert after.media.asset.asset_id == ids[1]
    assert len(runtime.channel.media) == 1


def test_calendar_guide_handles_interruptions_gap_and_resume(tmp_path):
    library, definition, ids = setup(tmp_path, breakpoints_seconds=[20], break_duration_seconds=10)
    show = resolve_channel(definition, library).media[0].asset.asset_id
    raw = channel_to_mapping(definition)
    raw['programming'] = {'mode': 'calendar', 'calendar': [
        {'asset_id': show, 'start_utc': EPOCH.isoformat()},
        {'asset_id': show, 'start_utc': (EPOCH + timedelta(seconds=100)).isoformat()},
    ]}
    runtime, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw))
    for second in [21, 31, 71, 90, 101]:
        horizon = GuideService((runtime,)).horizon(
            EPOCH + timedelta(seconds=second), EPOCH + timedelta(seconds=130), generated_at=EPOCH)
        assert horizon.rows[0].programs
    assert runtime.broadcast_at(EPOCH + timedelta(seconds=101)).offset_seconds == 1


def test_calendar_missed_gaps_have_same_rotation_as_live_queries(tmp_path):
    library, definition, ids = setup(tmp_path, selection_strategy='least_played', triggers=['calendar_boundary'])
    show = resolve_channel(definition, library).media[0].asset.asset_id
    raw = channel_to_mapping(definition)
    raw['programming'] = {'mode': 'calendar', 'calendar': [
        {'asset_id': show, 'start_utc': (EPOCH + timedelta(seconds=90 * i)).isoformat()}
        for i in range(6)
    ]}
    definition = ChannelDefinition.from_mapping(raw)
    baseline, _ = open_runtime(tmp_path, library, definition, 'baseline')
    offline, _ = open_runtime(tmp_path, library, definition, 'offline')
    offline.broadcast_at(EPOCH)
    offline.break_store.close()
    for second in range(0, 451, 5):
        baseline.broadcast_at(EPOCH + timedelta(seconds=second))
    recovered, _ = open_runtime(tmp_path, library, definition, 'offline', now=EPOCH + timedelta(seconds=450))
    recovered.broadcast_at(EPOCH + timedelta(seconds=450))
    assert recovered.break_store.play_counts() == baseline.break_store.play_counts()


def test_disabling_ads_preserves_active_plan_and_program_clock(tmp_path):
    library, definition, ids = setup(tmp_path, break_duration_seconds=15)
    runtime, _ = open_runtime(tmp_path, library, definition)
    active = runtime.broadcast_at(EPOCH + timedelta(seconds=22))
    runtime.break_store.close()
    disabled = replace(definition, advertising=replace(definition.advertising, enabled=False))
    reopened, _ = open_runtime(tmp_path, library, disabled, now=EPOCH + timedelta(seconds=23))
    assert reopened.epoch_utc == EPOCH
    assert reopened.broadcast_at(EPOCH + timedelta(seconds=23)).break_id == active.break_id
    assert reopened.broadcast_at(EPOCH + timedelta(seconds=36)).offset_seconds == 21
    assert reopened.broadcast_at(EPOCH + timedelta(seconds=96)).origin == 'cycle'


def test_hold_occupies_planned_time_and_does_not_count_as_another_ad(tmp_path):
    library, definition, _ = setup(tmp_path, transition_behavior='hold', transition_seconds=.5,
                                  break_duration_seconds=11, triggers=['breakpoint'])
    runtime, store = open_runtime(tmp_path, library, definition)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((runtime,), store), backend)
    during = session.tune(7, now=EPOCH + timedelta(seconds=30.25))
    assert during.viewer_selection.event.event_type == 'transition'
    assert backend.events[-1] == 'pause'
    assert not session.paused
    resumed = session.sync(now=EPOCH + timedelta(seconds=30.75))
    assert resumed.viewer_selection.offset_seconds == pytest.approx(20.25)
    assert sum(runtime.break_store.play_counts().values()) == 1


class FadeBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.levels = []

    def set_transition_level(self, level):
        self.levels.append(level)


def test_fade_follows_viewer_clock_and_restores_after_channel_change(tmp_path):
    library, definition, _ = setup(tmp_path, transition_behavior='fade', transition_seconds=1,
                                  break_duration_seconds=10)
    runtime, store = open_runtime(tmp_path, library, definition)
    other = ChannelRuntime.open(resolve_channel(replace(definition, channel=8,
        advertising=replace(definition.advertising, enabled=False)), library), store, now=EPOCH)
    backend = FadeBackend()
    session = TelevisionSession(TelevisionRuntime((runtime, other), store), backend)
    session.tune(7, now=EPOCH + timedelta(seconds=20.25))
    assert backend.levels[-1] == pytest.approx(.25)
    session.pause(now=EPOCH + timedelta(seconds=20.25))
    session.sync(now=EPOCH + timedelta(seconds=27))
    assert backend.levels[-1] == pytest.approx(.25)
    session.tune(8, now=EPOCH + timedelta(seconds=28))
    assert backend.levels[-1] == 1


@pytest.mark.parametrize('source,priority,first_end,next_offset', [
    ('schedule_shift', 'program', 75, 1),
    ('current_program', 'advertising', 70, 1),
    ('next_event', 'advertising', 75, 6),
    ('schedule_shift', 'fixed', 70, 1),
])
def test_expand_sources_and_priority_have_explicit_content_effects(tmp_path, source, priority, first_end, next_offset):
    library, definition, ids = setup(tmp_path, break_duration_seconds=10, timing_policy='expand',
        expand_max_seconds=5, expand_source=source, schedule_priority=priority, triggers=['breakpoint'])
    runtime, _ = open_runtime(tmp_path, library, definition)
    first = runtime.broadcast_at(EPOCH + timedelta(seconds=21))
    assert first.origin == 'advertisement'
    assert runtime.break_store.program_clock(first.program_occurrence_id)[1] == EPOCH + timedelta(seconds=first_end)
    next_program = runtime.broadcast_at(EPOCH + timedelta(seconds=first_end + 1))
    assert next_program.offset_seconds == pytest.approx(next_offset)


def test_fixed_slot_uses_actual_content_end_after_mid_program_break(tmp_path):
    library, definition, ids = setup(tmp_path)
    raw = channel_to_mapping(definition)
    raw['advertising']['placements'] = [
        {'id': 'mid', 'trigger': 'breakpoint', 'policy': {'breakpoints_seconds': [20], 'break_duration_seconds': 10}},
        {'id': 'slot', 'trigger': 'fixed_slot', 'policy': {'slot_seconds': 90, 'timing_policy': 'smoosh', 'smoosh_max_trim_seconds': 10}},
    ]
    runtime, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw))
    next_program = runtime.broadcast_at(EPOCH + timedelta(seconds=91))
    assert next_program.origin == 'cycle'
    assert next_program.program_started_at == EPOCH + timedelta(seconds=90)
    assert next_program.offset_seconds == 1


def test_ad_scope_exclusion_also_applies_when_program_source_contains_ad_folder(tmp_path):
    library, definition, ids = setup(tmp_path)
    raw = channel_to_mapping(definition)
    raw['sources'] = [{'path': str(tmp_path)}]
    resolved = resolve_channel(ChannelDefinition.from_mapping(raw), library)
    assert not {item.asset.asset_id for item in resolved.media} & set(ids)


def test_legacy_versions_remain_ad_disabled(tmp_path):
    library, definition, _ = setup(tmp_path)
    raw = channel_to_mapping(definition)
    raw.pop('advertising')
    for version in ['0.1', '0.2', '0.3', '0.4', '0.5']:
        raw['schema_version'] = version
        legacy = ChannelDefinition.from_mapping(raw)
        assert not legacy.advertising.enabled
        assert resolve_channel(legacy, library).ad_media == ()


def test_fade_backend_keeps_user_volume_and_mute_separate_from_envelope():
    from channelos.playback import LibVLCBackend
    from types import SimpleNamespace
    backend = object.__new__(LibVLCBackend)
    outputs = []
    state = {'muted': False}
    backend._player = SimpleNamespace(
        audio_set_volume=lambda value: outputs.append(value) or 0,
        audio_get_volume=lambda: 70,
        video_set_adjust_int=lambda *args: None,
        video_set_adjust_float=lambda *args: None,
        audio_set_mute=lambda value: state.update(muted=value),
        audio_get_mute=lambda: state['muted'],
    )
    backend._vlc = SimpleNamespace(VideoAdjustOption=SimpleNamespace(Enable=0, Brightness=1))
    backend._user_volume = None
    backend._transition_level = 1
    backend.set_volume(80)
    backend.set_transition_level(.5)
    assert outputs[-1] == 40
    assert backend.get_volume() == 80
    backend.set_muted(True)
    backend.set_volume(60)
    assert outputs[-1] == 30
    backend.set_transition_level(1)
    assert outputs[-1] == 60
    assert backend.get_muted()


def test_viewer_rewind_cannot_count_same_half_twice_and_progress_survives_restart(tmp_path):
    library, definition, _ = setup(tmp_path, break_duration_seconds=10)
    runtime, store = open_runtime(tmp_path, library, definition)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((runtime,), store), backend)
    session.tune(7, now=EPOCH + timedelta(seconds=20))
    for second in [1, 2, 3, 4, 5]:
        backend.position = second
        session.sync(now=EPOCH + timedelta(seconds=20 + second))
    session.skip(-5, now=EPOCH + timedelta(seconds=25))
    for second in [1, 2, 3, 4, 5]:
        backend.position = second
        session.sync(now=EPOCH + timedelta(seconds=25 + second))
    session.stop()
    assert runtime.break_store.viewer_counts() == {}
    assert runtime.break_store.diagnostics(7)['viewerCompletionRate'] == pytest.approx(.5)
    session.watch_from_beginning(7, EPOCH, now=EPOCH + timedelta(seconds=40))
    session.skip(25, now=EPOCH + timedelta(seconds=40))
    for second in [6, 7, 8, 9, 10]:
        backend.position = second
        session.sync(now=EPOCH + timedelta(seconds=40 + second - 5))
    assert sum(runtime.break_store.viewer_counts().values()) == 1


def test_offline_ad_pool_does_not_prevent_runtime_startup_or_enter_program_pool(tmp_path):
    library, definition, ids = setup(tmp_path)
    for item in library.list_online_media_for_source(tmp_path / 'commercials'):
        item.location.path.unlink()
    resolved = resolve_channel(definition, library, allow_offline_ads=True)
    assert resolved.ad_media == ()
    assert len(resolved.media) == 1
    runtime = ChannelRuntime.open(resolved, RuntimeStore(tmp_path / 'runtime.sqlite'), now=EPOCH)
    assert runtime.broadcast_at(EPOCH + timedelta(seconds=23)).origin == 'cycle'


def test_decoder_failure_on_ad_recovers_at_program_boundary_without_schedule_change(tmp_path):
    library, definition, _ = setup(tmp_path, break_duration_seconds=10)
    runtime, store = open_runtime(tmp_path, library, definition)
    class RecoveringBackend(FakeBackend):
        def load(self, path):
            super().load(path)
            self.error_message = None
    backend = RecoveringBackend()
    session = TelevisionSession(TelevisionRuntime((runtime,), store), backend)
    session.tune(7, now=EPOCH + timedelta(seconds=21))
    backend.error_message = 'ad decoder failed'
    from channelos.playback import PlaybackError
    with pytest.raises(PlaybackError):
        session.sync(now=EPOCH + timedelta(seconds=22))
    recovered = session.sync(now=EPOCH + timedelta(seconds=31))
    assert recovered.viewer_selection.offset_seconds == 21
    assert recovered.viewer_selection.origin == 'cycle'
    assert runtime.epoch_utc == EPOCH


def test_calendar_expand_can_borrow_current_content_only_with_explicit_ad_priority(tmp_path):
    library, definition, _ = setup(tmp_path, breakpoints_seconds=[20], break_duration_seconds=10,
        timing_policy='expand', expand_max_seconds=15, expand_source='current_program',
        schedule_priority='advertising', triggers=['breakpoint'])
    show = resolve_channel(definition, library).media[0].asset.asset_id
    raw = channel_to_mapping(definition)
    raw['programming'] = {'mode': 'calendar', 'calendar': [
        {'asset_id': show, 'start_utc': EPOCH.isoformat()},
        {'asset_id': show, 'start_utc': (EPOCH + timedelta(seconds=60)).isoformat()},
    ]}
    runtime, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw))
    during = runtime.broadcast_at(EPOCH + timedelta(seconds=21))
    assert during.origin == 'advertisement'
    plan = runtime.break_store.load_plan(during.break_id)
    assert plan.content_cut_seconds == 15
    assert runtime.broadcast_at(EPOCH + timedelta(seconds=61)).offset_seconds == 1


def test_enabling_configured_ad_scope_keeps_program_lineup_and_signature(tmp_path):
    from channelos.runtime import schedule_signature
    library, definition, _ = setup(tmp_path)
    definition = replace(definition, sources=(replace(definition.sources[0], path=tmp_path),))
    disabled = replace(definition, advertising=replace(definition.advertising, enabled=False))
    assert schedule_signature(resolve_channel(definition, library)) == schedule_signature(resolve_channel(disabled, library))


def test_studio_assignment_is_resolved_before_enabled_snapshot_validation(tmp_path):
    from channelos.broadcaster import BroadcasterService
    library, definition, ids = setup(tmp_path)
    service = BroadcasterService((), tmp_path / 'channels', library)
    service.save_ad_collection({'collectionId': 'ads', 'name': 'Ads', 'assetIds': ids})
    service.save_ad_profile({'profileId': 'profile', 'name': 'Standard', 'defaults': {
        'enabled': True, 'breakpoints_seconds': [20], 'duration_seconds': 15}})
    service.assign_ad_profile({'channelNumber': 7, 'collectionId': 'ads', 'profileId': 'profile'})
    editor = {'channel': 7, 'name': 'Studio', 'mode': 'sequential',
              'sources': [str(tmp_path / 'programs')], 'adBreaksEnabled': True,
              'adCollectionId': 'ads', 'adProfileId': 'profile', 'adConfigVersion': '0.5'}
    preview = service.preview(editor)
    assert preview['ok'] and preview['adPreview']
    assert preview['adDiagnostics']['completedAirings'] == 0
    created = service.create(editor)
    assert created.record.definition.advertising.enabled
    editor.update(adBreaksEnabled=False, adAssetIds=ids)
    changed = service.update(7, editor)
    assert not changed.record.definition.advertising.enabled


def test_rotation_is_scoped_to_channel_not_tune_order(tmp_path):
    library, definition, _ = setup(tmp_path, selection_strategy='least_played', break_duration_seconds=15)
    baseline, _ = open_runtime(tmp_path, library, definition, 'baseline')
    shared = RuntimeStore(tmp_path / 'shared.sqlite')
    a = ChannelRuntime.open(resolve_channel(definition, library), shared, now=EPOCH)
    b = ChannelRuntime.open(resolve_channel(replace(definition, channel=8), library), shared, now=EPOCH)
    b.broadcast_at(EPOCH + timedelta(seconds=1000))
    actual = a.broadcast_at(EPOCH + timedelta(seconds=21))
    expected = baseline.broadcast_at(EPOCH + timedelta(seconds=21))
    assert actual.media.asset.asset_id == expected.media.asset.asset_id
    assert actual.offset_seconds == expected.offset_seconds


def test_dynamic_portable_collection_follows_new_index_entries_and_exclusions(tmp_path):
    import hashlib
    from channelos.probe import MediaProbeResult
    library, definition, ids = setup(tmp_path)
    catalog = AdCatalogStore(tmp_path / 'catalog.sqlite')
    catalog.save_collection(AdCollection('dynamic', 'Dynamic', (), (str(tmp_path / 'commercials'),),
                                          (ids[0],), 'dynamic'))
    catalog.save_profile(BreakProfile('p', 'Profile', {'enabled': True}))
    catalog.assign_channel(ChannelAdAssignment(7, 'dynamic', 'p'))
    portable = ChannelDefinition.from_mapping(channel_to_mapping(export_portable_channel(definition, catalog, library)))
    path = tmp_path / 'commercials' / 'new-ad.mp4'
    path.write_bytes(b'new-ad')
    new = library.upsert_file(path, path.parent, content_sha256=hashlib.sha256(b'new-ad').hexdigest(),
                              probe=MediaProbeResult(duration_seconds=7, container_format='mp4'))
    resolved = resolve_channel(portable, library)
    actual = {item.asset.asset_id for item in resolved.ad_media}
    assert actual == {ids[1], "sha256:" + hashlib.sha256(b"new-ad").hexdigest()}


def test_fixed_slot_falls_back_to_timed_filler_without_starting_next_show_early(tmp_path):
    library, definition, ids = setup(tmp_path)
    raw = channel_to_mapping(definition)
    raw['advertising']['placements'] = [
        {'id': 'slot', 'trigger': 'fixed_slot', 'policy': {'slot_seconds': 90, 'asset_ids': [ids[1]]}},
    ]
    runtime, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw))
    inside = runtime.broadcast_at(EPOCH + timedelta(seconds=89))
    assert inside.origin == 'filler'
    next_show = runtime.broadcast_at(EPOCH + timedelta(seconds=91))
    assert next_show.program_started_at == EPOCH + timedelta(seconds=90)
    assert next_show.offset_seconds == 1
    assert sum(runtime.break_store.play_counts().values()) == 1


def test_program_schedule_edit_retires_old_clock_and_preserves_completed_history(tmp_path):
    import hashlib
    from channelos.probe import MediaProbeResult
    library, definition, _ = setup(tmp_path, break_duration_seconds=10)
    original, _ = open_runtime(tmp_path, library, definition)
    original.broadcast_at(EPOCH + timedelta(seconds=80))
    prior_counts = original.break_store.play_counts()
    assert sum(prior_counts.values()) == 1
    original.break_store.close()
    path = tmp_path / 'programs' / 'second.mp4'
    path.write_bytes(b'second')
    library.upsert_file(path, path.parent, content_sha256=hashlib.sha256(b'second').hexdigest(),
                        probe=MediaProbeResult(duration_seconds=45, container_format='mp4'))
    reset_at = EPOCH + timedelta(seconds=80)
    changed, _ = open_runtime(tmp_path, library, definition, now=reset_at)
    assert changed.epoch_utc == reset_at
    assert changed.broadcast_at(reset_at + timedelta(seconds=1)).offset_seconds == 1
    assert changed.break_store.play_counts() == prior_counts
    assert changed.break_store.connection.execute('SELECT COUNT(*) FROM ad_retired_plans').fetchone()[0] > 0


def test_between_program_break_follows_content_borrow_without_crossing_next_show(tmp_path):
    library, definition, ids = setup(tmp_path)
    raw = channel_to_mapping(definition)
    raw['advertising']['placements'] = [
        {'id': 'mid', 'trigger': 'breakpoint', 'policy': {
            'breakpoints_seconds': [20], 'break_duration_seconds': 10,
            'timing_policy': 'expand', 'expand_max_seconds': 5,
            'expand_source': 'current_program', 'schedule_priority': 'advertising'}},
        {'id': 'between', 'trigger': 'between_programs', 'policy': {'break_duration_seconds': 10}},
    ]
    runtime, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw))
    selected = runtime.broadcast_at(EPOCH + timedelta(seconds=71))
    assert selected.origin == 'advertisement'
    assert selected.program_started_at == EPOCH + timedelta(seconds=70)
    assert runtime.broadcast_at(EPOCH + timedelta(seconds=81)).offset_seconds == 1


def test_watch_from_beginning_respects_explicit_next_event_content_borrow(tmp_path):
    library, definition, ids = setup(tmp_path, break_duration_seconds=10, timing_policy='expand',
        expand_max_seconds=5, expand_source='next_event', schedule_priority='advertising')
    runtime, store = open_runtime(tmp_path, library, definition)
    runtime.broadcast_at(EPOCH + timedelta(seconds=76))
    session = TelevisionSession(TelevisionRuntime((runtime,), store), FakeBackend())
    decision = session.watch_from_beginning(7, EPOCH + timedelta(seconds=75), now=EPOCH + timedelta(seconds=80))
    assert decision.viewer_selection.offset_seconds == 5


def test_calendar_policy_removing_trigger_keeps_its_active_time_in_resume_mapping(tmp_path):
    library, definition, _ = setup(tmp_path, breakpoints_seconds=[10, 20],
        break_duration_seconds=10, triggers=['breakpoint'])
    show = resolve_channel(definition, library).media[0].asset.asset_id
    raw = channel_to_mapping(definition)
    raw['programming'] = {'mode': 'calendar', 'calendar': [
        {'asset_id': show, 'start_utc': EPOCH.isoformat()},
        {'asset_id': show, 'start_utc': (EPOCH + timedelta(seconds=100)).isoformat()},
    ]}
    first, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw))
    active = first.broadcast_at(EPOCH + timedelta(seconds=11))
    first.break_store.close()
    raw['advertising']['breakpoints_seconds'] = [20]
    revised, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw),
                              now=EPOCH + timedelta(seconds=12))
    assert revised.broadcast_at(EPOCH + timedelta(seconds=12)).break_id == active.break_id
    following = revised.broadcast_at(EPOCH + timedelta(seconds=31))
    assert following.origin == 'advertisement'
    assert following.program_started_at == EPOCH + timedelta(seconds=30)
    assert revised.broadcast_at(EPOCH + timedelta(seconds=41)).offset_seconds == 21


def test_empty_triggers_and_zero_trim_are_explicit_channel_overrides(tmp_path):
    from channelos.broadcaster import definition_from_editor
    library, definition, ids = setup(tmp_path)
    editor = {'channel': 7, 'name': 'No triggers', 'mode': 'sequential',
              'sources': [str(tmp_path / 'programs')], 'adBreaksEnabled': True,
              'adConfigVersion': '0.5', 'adAssetIds': ids, 'adBreakpointsSeconds': [20],
              'adSmooshMaxTrimSeconds': 0, 'adTriggers': []}
    result = definition_from_editor(editor)
    assert result.advertising.triggers == ()
    assert result.advertising.smoosh_max_trim_seconds == 0
    runtime, _ = open_runtime(tmp_path, library, result)
    assert runtime.broadcast_at(EPOCH + timedelta(seconds=21)).origin == 'cycle'


def test_mute_intent_survives_absent_audio_output_and_is_reapplied():
    from channelos.playback import LibVLCBackend
    from types import SimpleNamespace
    calls = []
    backend = object.__new__(LibVLCBackend)
    backend._player = SimpleNamespace(audio_set_mute=lambda value: calls.append(value),
                                      audio_get_mute=lambda: False)
    backend.set_muted(True)
    assert backend.get_muted()
    backend._apply_audio_settings()
    assert calls == [True, True]
    backend.set_muted(False)
    assert not backend.get_muted()


def test_hold_reuses_the_preceding_decoder_and_frame(tmp_path):
    library, definition, _ = setup(tmp_path, transition_behavior='hold', transition_seconds=.5,
                                  break_duration_seconds=11, triggers=['breakpoint'])
    runtime, store = open_runtime(tmp_path, library, definition)
    backend = FakeBackend()
    session = TelevisionSession(TelevisionRuntime((runtime,), store), backend)
    session.tune(7, now=EPOCH + timedelta(seconds=29.5))
    backend.position = 10
    held = session.sync(now=EPOCH + timedelta(seconds=30.25))
    assert held.viewer_selection.origin == 'transition'
    assert backend.events.count('load') == 1
    session.sync(now=EPOCH + timedelta(seconds=30.3))
    assert backend.events.count('load') == 1


@pytest.mark.parametrize('mode', ['sequential', 'calendar'])
def test_legacy_plan_without_location_snapshot_recovers_from_canonical_library(tmp_path, mode):
    import json
    library, definition, ids = setup(tmp_path, break_duration_seconds=10, triggers=['breakpoint'])
    raw = channel_to_mapping(definition)
    if mode == 'calendar':
        show = resolve_channel(definition, library).media[0].asset.asset_id
        raw['programming'] = {'mode': mode, 'calendar': [
            {'asset_id': show, 'start_utc': EPOCH.isoformat()},
            {'asset_id': show, 'start_utc': (EPOCH + timedelta(seconds=100)).isoformat()},
        ]}
    first, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw))
    active = first.broadcast_at(EPOCH + timedelta(seconds=21))
    assert active.origin == 'advertisement'
    row = first.break_store.connection.execute('SELECT payload FROM ad_break_plans WHERE plan_id = ?',
                                               (active.break_id,)).fetchone()
    payload = json.loads(row[0])
    for segment in payload:
        for key in ['media_path', 'original_duration_seconds', 'event_type']:
            segment.pop(key, None)
    first.break_store.connection.execute('UPDATE ad_break_plans SET payload = ? WHERE plan_id = ?',
                                        (json.dumps(payload), active.break_id))
    first.break_store.connection.commit()
    first.break_store.close()
    raw['advertising']['asset_ids'] = [asset_id for asset_id in ids if asset_id != active.media.asset.asset_id]
    reopened, _ = open_runtime(tmp_path, library, ChannelDefinition.from_mapping(raw),
                              now=EPOCH + timedelta(seconds=22))
    recovered = reopened.broadcast_at(EPOCH + timedelta(seconds=23))
    assert recovered.break_id == active.break_id
    assert recovered.media.asset.asset_id == active.media.asset.asset_id
    assert recovered.offset_seconds == 3
