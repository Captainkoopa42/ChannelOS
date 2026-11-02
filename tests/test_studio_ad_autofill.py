"""Studio authoring must leave enough broadcast time for the actual ad engine."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from channelos.ad_catalog import AdCollection, BreakProfile, ChannelAdAssignment
from channelos.broadcaster import BroadcasterService
from channelos.guide import GuideService
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore
from test_ad_portable import indexed
from test_broadcaster import editor

START = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def author(tmp_path, **settings):
    library, programs, ads = indexed(tmp_path)
    service = BroadcasterService((), tmp_path / 'channels', library)
    raw = editor(7, programs, mode='calendar')
    raw.update(adBreaksEnabled=True, adSources=[str(ads)], adConfigVersion='0.5',
               adBreakDurationSeconds=10, adTriggers=['calendar_boundary'])
    raw.update(settings)
    return library, service, raw


@pytest.mark.parametrize('settings,spacing,ad_count', [
    ({'adTriggers': ['calendar_boundary']}, 70, 1),
    ({'adTriggers': ['between_programs']}, 70, 1),
    ({'adTriggers': ['between_programs'], 'adBreakpointsSeconds': [20], 'adIntervalSeconds': 20}, 70, 1),
    ({'adTriggers': ['interval'], 'adIntervalSeconds': 20}, 80, 2),
    ({'adTriggers': ['breakpoint'], 'adBreakpointsSeconds': [20, 40]}, 80, 2),
    ({'adTriggers': ['breakpoint', 'calendar_boundary'], 'adBreakpointsSeconds': [20]}, 80, 2),
    ({'adTriggers': ['fixed_slot'], 'adSlotSeconds': 90}, 90, 2),
])
def test_autofill_reservations_become_real_ad_events_after_save_and_reopen(tmp_path, settings, spacing, ad_count):
    library, service, raw = author(tmp_path, **settings)
    result = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=360)).isoformat())
    assert result['adSlotCount'] > 0
    assert result['adReservedSeconds'] > 0
    assert not result['adWarnings']
    assert datetime.fromisoformat(result['blocks'][1]['startUtc']) == START + timedelta(seconds=spacing)
    raw['calendarBlocks'] = result['blocks']
    saved = service.create(raw).record.definition
    resolved = resolve_channel(saved, library)
    assert len(resolved.media) == 1
    store = RuntimeStore(tmp_path / 'runtime.sqlite')
    for _ in range(2):
        runtime = ChannelRuntime.open(resolved, store, now=START)
        try:
            events = runtime.events_between(START, START + timedelta(seconds=spacing))
            assert sum(event.event_type == 'advertisement' for event in events) == ad_count
            assert runtime.broadcast_at(START + timedelta(seconds=spacing + 1)).offset_seconds == 1
            assert runtime.break_store.play_counts()  # completed ads, not authoring guesses
            GuideService((runtime,)).horizon(START, START + timedelta(seconds=360), generated_at=START)
        finally:
            runtime.break_store.close()
    assert service.preview(raw)['adPreview']


def test_autofill_protects_existing_show_and_its_ad_room(tmp_path):
    library, service, raw = author(tmp_path)
    asset_id = library.list_online_media_for_source(raw['sources'][0])[0].asset.asset_id
    fixed_start = START + timedelta(seconds=100)
    raw['calendarBlocks'] = [{'assetId': asset_id, 'startUtc': fixed_start.isoformat(),
                              'endUtc': (fixed_start + timedelta(seconds=60)).isoformat()}]
    before = deepcopy(raw)
    result = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=360)).isoformat())
    assert raw == before
    for block in result['blocks']:
        begins, ends = map(datetime.fromisoformat, (block['startUtc'], block['endUtc']))
        assert ends <= fixed_start or begins >= fixed_start + timedelta(seconds=70)


def test_packed_existing_range_explains_how_to_rebuild_with_ads(tmp_path):
    library, service, raw = author(tmp_path)
    asset_id = library.list_online_media_for_source(raw['sources'][0])[0].asset.asset_id
    raw['calendarBlocks'] = [{'assetId': asset_id, 'startUtc': (START + timedelta(seconds=60 * i)).isoformat(),
                              'endUtc': (START + timedelta(seconds=60 * (i + 1))).isoformat()}
                             for i in range(4)]
    before = deepcopy(raw)
    result = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=240)).isoformat())
    assert raw == before
    assert result['blocks'] == []
    assert 'Clear Range' in result['message']
    assert result['adWarnings']


@pytest.mark.parametrize('timing', ['strict_fit', 'expand'])
def test_autofill_reports_ads_that_cannot_fit_instead_of_silently_claiming_success(tmp_path, timing):
    _, service, raw = author(tmp_path, adBreakDurationSeconds=5, adTimingPolicy=timing, adExpandMaxSeconds=10)
    result = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=240)).isoformat())
    assert any('No ad fits' in warning for warning in result['adWarnings'])
    assert 'shorter clips' in result['message']


def test_autofill_resolves_assigned_profile_before_reserving_space(tmp_path):
    library, service, raw = author(tmp_path)
    ids = tuple(item.asset.asset_id for item in library.list_online_media_for_source(raw['adSources'][0]))
    service.ad_catalog.save_collection(AdCollection('ads', 'Ads', ids))
    service.ad_catalog.save_profile(BreakProfile('standard', 'Standard', {
        'enabled': True, 'duration_seconds': 15, 'triggers': ['calendar_boundary']}))
    service.ad_catalog.assign_channel(ChannelAdAssignment(7, 'ads', 'standard'))
    raw['adSources'] = []
    raw.pop('adTriggers')
    raw.pop('adBreakDurationSeconds')
    result = service.auto_fill_studio(raw, START.isoformat(), (START + timedelta(seconds=240)).isoformat())
    assert datetime.fromisoformat(result['blocks'][1]['startUtc']) == START + timedelta(seconds=75)
    assert not result['adWarnings']
