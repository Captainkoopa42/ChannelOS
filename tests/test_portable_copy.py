from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import pickle
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.ad_catalog import AdCollection, AdCatalogStore
from channelos.broadcaster import BroadcasterService
from channelos.library import MediaLibrary
from channelos.loader import load_channel
from channelos.portable import DATA_FOLDER, MANIFEST_NAME, PortableSetupError, load_setup
from channelos.portable_copy import CopyCancelled, inspect_setup, plan_copy, publish_snapshot, snapshot_setup
from channelos.probe import MediaProbeResult
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore

EPOCH = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def source_setup(tmp_path: Path, media_root=None):
    data = tmp_path / 'PC data'
    data.mkdir()
    media_root = media_root or tmp_path / 'original media'
    library = MediaLibrary(data / 'library.db')
    for folder, name, duration in [('Shows', 'episode.mp4', 60), ('Ads', 'ad.mp4', 10)]:
        path = media_root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        library.upsert_file(path, path.parent, content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            probe=MediaProbeResult(duration_seconds=duration, container_format='mp4'))
    service = BroadcasterService([], data / 'channels', library)
    record = service.create({'channel': 7, 'name': 'Travel TV', 'sources': [str(media_root / 'Shows')],
        'mode': 'sequential', 'adBreaksEnabled': True, 'adSources': [str(media_root / 'Ads')],
        'adConfigVersion': '0.5', 'adBreakDurationSeconds': 10,
        'adBreakpointsSeconds': [20], 'adTriggers': ['breakpoint']}).record
    service.ad_catalog.save_collection(AdCollection('ads', 'Dynamic ads', (), (str(media_root / 'Ads'),), membership='dynamic'))
    resolved = resolve_channel(record.definition, library)
    store = RuntimeStore(data / 'runtime.db')
    runtime = ChannelRuntime.open(resolved, store, now=EPOCH)
    runtime.broadcast_at(EPOCH + timedelta(seconds=31))
    plan = runtime.break_store.plans_for_channel(7, start=EPOCH, end=EPOCH + timedelta(seconds=60))[0]
    runtime.break_store.record_viewed(plan.plan_id, 0, plan.segments[0].asset_id,
        consumed_seconds=plan.segments[0].duration_seconds, completed_at=EPOCH + timedelta(seconds=31))
    show_id = resolved.media[0].asset.asset_id
    store.save_on_demand_watch(show_id, 12, 60, now=EPOCH)
    service.create_studio_group('Programs', [show_id], 'sequential')
    (data / 'settings.json').write_text(json.dumps({'volume_percent': 42, 'audio_output_device_id': 'PC-only-speakers'}))
    return library, service, store, runtime


def copy_setup(library, service, store, destination, **kwargs):
    plan = plan_copy(library, service.paths, destination, **kwargs)
    snapshot = snapshot_setup(plan, library, store.database_path, service.managed_directory)
    return publish_snapshot(snapshot)


def test_complete_setup_copy_reuses_index_and_preserves_history_after_move(tmp_path):
    library, service, store, original = source_setup(tmp_path)
    history = original.break_store.play_counts()
    try:
        destination = tmp_path / 'External TV'
        result = copy_setup(library, service, store, destination, copy_media=True)
        assert result['mediaFilesToCopy'] == 2
        assert inspect_setup(destination)['channelCount'] == 1
        paths = load_setup(destination)
        copied_library = MediaLibrary(paths.data_directory / 'library.db')
        copied_service = BroadcasterService([], paths.data_directory / 'channels', copied_library)
        copied_definition = copied_service.records[0].definition
        copied_store = RuntimeStore(paths.data_directory / 'runtime.db')
        copied = ChannelRuntime.open(resolve_channel(copied_definition, copied_library),
            copied_store, now=EPOCH + timedelta(seconds=31))
        try:
            assert copied.epoch_utc == original.epoch_utc
            assert copied.break_store.play_counts() == history
            assert copied.break_store.viewer_counts() == original.break_store.viewer_counts()
            assert copied.project_at(EPOCH + timedelta(seconds=21)).event == original.project_at(EPOCH + timedelta(seconds=21)).event
            assert len(copied.break_store.plans_for_channel(7, start=EPOCH, end=EPOCH + timedelta(seconds=60))) == 1
            assert copied_service.studio_groups()[0]['name'] == 'Programs'
            watch = copied_store.load_on_demand_watch(copied.channel.media[0].asset.asset_id)
            assert watch.position_seconds == 12
            settings = json.loads((paths.data_directory / 'settings.json').read_text())
            assert settings['volume_percent'] == 42
            assert 'audio_output_device_id' not in settings
        finally:
            copied.break_store.close()
        moved = tmp_path / 'Second PC mount'
        shutil.move(destination, moved)
        new_paths = load_setup(moved)
        new_library = MediaLibrary(new_paths.data_directory / 'library.db')
        assert new_library.count_assets() == library.count_assets()
        for media in new_library.list_online_media():
            assert media.location.path.is_file()
            assert new_library.cached_asset_for_unchanged_path(media.location.path).asset_id == media.asset.asset_id
        catalog = AdCatalogStore(new_paths.data_directory / 'ad_catalog.sqlite')
        assert Path(catalog.get_collection('ads').source_paths[0]).is_relative_to(moved)
        assert 'portable://' in next((new_paths.data_directory / 'channels').glob('*.yaml')).read_text()
    finally:
        original.break_store.close()


def test_media_already_on_destination_is_not_copied_or_rehashed(tmp_path, monkeypatch):
    destination = tmp_path / 'External drive'
    library, service, store, runtime = source_setup(tmp_path, destination / 'Media')
    try:
        paths_before = {media.location.path: media.location.path.read_bytes() for media in library.list_online_media()}
        monkeypatch.setattr('channelos.library.sha256_file', lambda *args, **kwargs: pytest.fail('Full reindex is forbidden'))
        result = copy_setup(library, service, store, destination, copy_media=False)
        assert result['mediaFilesToCopy'] == 0
        assert result['mediaBytesToCopy'] == 0
        for path, content in paths_before.items():
            assert path.read_bytes() == content
        reopened = MediaLibrary(load_setup(destination).data_directory / 'library.db')
        assert all(reopened.cached_asset_for_unchanged_path(path) is not None for path in paths_before)
    finally:
        runtime.break_store.close()


def test_portable_setup_can_be_copied_again_without_losing_its_paths(tmp_path):
    library, service, store, runtime = source_setup(tmp_path)
    try:
        first = tmp_path / 'First copy'
        copy_setup(library, service, store, first, copy_media=True)
        paths = load_setup(first)
        first_library = MediaLibrary(paths.data_directory / 'library.db')
        first_service = BroadcasterService([], paths.data_directory / 'channels', first_library)
        second = tmp_path / 'Second copy'
        result = copy_setup(first_library, first_service, RuntimeStore(paths.data_directory / 'runtime.db'), second, copy_media=True)
        assert result['mediaFilesToCopy'] == 2
        assert inspect_setup(second)['assetCount'] == 2
        assert load_setup(first).setup_id != load_setup(second).setup_id
        second_library = MediaLibrary(load_setup(second).data_directory / 'library.db')
        assert all(item.location.path.is_file() for item in second_library.list_online_media())
    finally:
        runtime.break_store.close()


def test_cancel_and_changed_media_never_publish_an_incomplete_setup(tmp_path):
    library, service, store, runtime = source_setup(tmp_path)
    try:
        target = tmp_path / 'Cancelled'
        plan = plan_copy(library, service.paths, target, copy_media=True)
        snapshot = snapshot_setup(plan, library, store.database_path, service.managed_directory)
        with pytest.raises(CopyCancelled):
            publish_snapshot(snapshot, should_cancel=lambda: True)
        assert not (target / MANIFEST_NAME).exists()
        assert not (target / DATA_FOLDER).exists()
        source = library.list_online_media()[0].location.path
        source.write_bytes(b'changed media')
        plan = plan_copy(library, service.paths, target, copy_media=True)
        snapshot = snapshot_setup(plan, library, store.database_path, service.managed_directory)
        with pytest.raises(PortableSetupError, match='changed'):
            publish_snapshot(snapshot)
        assert not (target / MANIFEST_NAME).exists()
        assert source.read_bytes() == b'changed media'
    finally:
        runtime.break_store.close()


def test_sources_outside_destination_need_explicit_media_copy_and_existing_setups_are_kept(tmp_path):
    library, service, store, runtime = source_setup(tmp_path)
    try:
        target = tmp_path / 'Drive'
        with pytest.raises(PortableSetupError, match='outside'):
            plan_copy(library, service.paths, target, copy_media=False)
        copy_setup(library, service, store, target, copy_media=True)
        before = (target / MANIFEST_NAME).read_bytes()
        with pytest.raises(PortableSetupError, match='already contains'):
            plan_copy(library, service.paths, target, copy_media=True)
        assert (target / MANIFEST_NAME).read_bytes() == before
    finally:
        runtime.break_store.close()


@pytest.mark.parametrize('crash_point,recovers', [('first_rename', False), ('before_manifest', True)])
def test_process_death_recovers_a_complete_copy_or_discards_only_owned_partial_files(tmp_path, crash_point, recovers):
    library, service, store, runtime = source_setup(tmp_path)
    target = tmp_path / 'Interrupted drive'
    target.mkdir()
    unrelated = target / 'my notes.txt'
    unrelated.write_text('keep this')
    plan = plan_copy(library, service.paths, target, copy_media=True)
    snapshot = snapshot_setup(plan, library, store.database_path, service.managed_directory)
    payload = tmp_path / 'snapshot.pickle'
    payload.write_bytes(pickle.dumps((plan, snapshot.root)))
    script = '''
import os, pickle, sys
from pathlib import Path
from types import SimpleNamespace
from channelos import portable_copy as copy
plan, root = pickle.loads(Path(sys.argv[1]).read_bytes())
snapshot = SimpleNamespace(plan=plan, root=root, artifact_source=None, close=lambda: None)
point = sys.argv[2]
atomic = copy._atomic_json
rename = Path.rename
def crash_atomic(path, value):
    if point == 'before_manifest' and path.name == copy.MANIFEST_NAME:
        os._exit(77)
    return atomic(path, value)
def crash_rename(path, target):
    result = rename(path, target)
    if point == 'first_rename' and path.is_relative_to(plan.destination / ('.channelos-copy-' + plan.setup_id)):
        os._exit(77)
    return result
copy._atomic_json = crash_atomic
Path.rename = crash_rename
copy.publish_snapshot(snapshot)
'''
    try:
        result = subprocess.run([sys.executable, '-c', script, str(payload), crash_point], capture_output=True, text=True, timeout=30)
        assert result.returncode == 77, result.stderr
        assert not (target / MANIFEST_NAME).exists()
        from channelos.portable_copy import PENDING_COPY, recover_incomplete_copy
        assert (target / PENDING_COPY).exists()
        assert recover_incomplete_copy(target) is recovers
        assert unrelated.read_text() == 'keep this'
        assert not (target / PENDING_COPY).exists()
        if recovers:
            assert inspect_setup(target)['assetCount'] == 2
            copied = MediaLibrary(load_setup(target).data_directory / 'library.db')
            assert all(item.location.path.is_file() for item in copied.list_online_media())
        else:
            assert not (target / DATA_FOLDER).exists()
            assert list(target.rglob('*.mp4')) == []
            copy_setup(library, service, store, target, copy_media=True)
            assert inspect_setup(target)['assetCount'] == 2
    finally:
        snapshot.close()
        runtime.break_store.close()


@pytest.mark.parametrize('app_on_destination', [False, True])
def test_application_copy_is_self_locating_and_media_offline_metadata_is_retained(tmp_path, app_on_destination):
    library, service, store, runtime = source_setup(tmp_path)
    target = tmp_path / 'Portable'
    app = target / 'Other app folder' if app_on_destination else tmp_path / 'App'
    (app / '_internal').mkdir(parents=True)
    (app / 'ChannelOS.exe').write_bytes(b'packaged executable')
    (app / '_internal' / 'runtime.dll').write_bytes(b'bundled dependency')
    missing = library.list_online_media()[0].location.path
    missing.unlink()
    try:
        result = copy_setup(library, service, store, target, copy_media=True, application_directory=app)
        assert result['offlineFiles'] == 1
        from channelos.portable import APP_FOLDER, find_setup
        executable = target / APP_FOLDER / 'ChannelOS.exe'
        assert executable.read_bytes() == b'packaged executable'
        assert (executable.parent / '_internal' / 'runtime.dll').read_bytes() == b'bundled dependency'
        assert find_setup(executable).root == target
        copied = MediaLibrary(load_setup(target).data_directory / 'library.db')
        assert len(copied.list_cached_media()) == 2
        assert len(copied.list_online_media()) == 1
        assert inspect_setup(target)['assetCount'] == 2
    finally:
        runtime.break_store.close()


def test_retired_ad_plan_paths_and_history_survive_after_source_removed_from_index(tmp_path):
    library, service, store, runtime = source_setup(tmp_path)
    try:
        ad_path = next(media.location.path for media in library.list_online_media() if media.location.source_root.name == 'Ads')
        history = runtime.break_store.play_counts()
        # The old channel, collection and location no longer name the retired
        # source, while durable airing plans intentionally still do.
        import yaml
        raw = yaml.safe_load(service.records[0].path.read_text())
        raw['advertising'] = {'enabled': False}
        service.records[0].path.write_text(yaml.safe_dump(raw))
        service.refresh()
        with closing(sqlite3.connect(service.ad_catalog.database)) as db:
            db.execute('DELETE FROM ad_collections')
            db.commit()
        library.remove_source_from_index(ad_path.parent)
        target = tmp_path / 'History copy'
        copy_setup(library, service, store, target, copy_media=True)
        from channelos.ad_break_engine import BreakPlanStore
        with_store = BreakPlanStore(load_setup(target).data_directory / 'runtime.db')
        try:
            assert with_store.play_counts() == history
            plans = with_store.plans_for_channel(7, start=EPOCH, end=EPOCH + timedelta(seconds=60))
            assert plans and Path(plans[0].segments[0].media_path).is_file()
            assert Path(plans[0].segments[0].media_path).is_relative_to(target)
        finally:
            with_store.close()
    finally:
        runtime.break_store.close()


def test_reused_changed_media_still_needs_a_rescan_instead_of_claiming_a_valid_hash(tmp_path):
    target = tmp_path / 'Drive'
    library, service, store, runtime = source_setup(tmp_path, target / 'Media')
    changed = library.list_online_media()[0].location.path
    changed.write_bytes(b'new file contents with different size')
    try:
        copy_setup(library, service, store, target)
        reopened = MediaLibrary(load_setup(target).data_directory / 'library.db')
        assert reopened.cached_asset_for_unchanged_path(changed) is None
    finally:
        runtime.break_store.close()
