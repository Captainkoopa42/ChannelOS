from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from channelos.broadcaster import BroadcasterService
from channelos.library import MediaLibrary
from channelos.loader import load_channel
from channelos.portable import (DATA_FOLDER, MANIFEST_NAME, PortableSetupError,
                               PortableUnavailableError, SetupLock, load_setup)
from channelos.probe import MediaProbeResult
from channelos.resolve import resolve_channel
from channelos.runtime import ChannelRuntime, RuntimeStore, advertising_signature


def make_setup(root: Path, *, case_sensitive=True):
    (root / DATA_FOLDER).mkdir(parents=True)
    (root / MANIFEST_NAME).write_text(json.dumps({
        'format': 'channelos-portable', 'version': 1,
        'setup_id': str(uuid.uuid4()), 'case_sensitive': case_sensitive,
        'roots': [{'source_id': 'media', 'relative_path': 'Media', 'sort_rank': 0}],
    }))
    return load_setup(root)


def index(library, path, duration):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(path.name.encode())
    library.upsert_file(path, path.parent,
        content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        probe=MediaProbeResult(duration_seconds=duration, container_format='mp4'))
    return library.list_online_media_for_source(path.parent)[0]


def test_portable_index_channel_and_committed_ads_follow_a_moved_setup(tmp_path):
    root = tmp_path / 'drive E'
    paths = make_setup(root)
    library = MediaLibrary(paths.data_directory / 'library.db')
    show = index(library, root / 'Media' / 'Shows' / 'show.mp4', 60)
    ad = index(library, root / 'Media' / 'Ads' / 'ad.mp4', 10)
    service = BroadcasterService([], paths.data_directory / 'channels', library)
    created = service.create({'channel': 7, 'name': 'Portable TV',
        'sources': [str(show.location.source_root)], 'mode': 'sequential',
        'adBreaksEnabled': True, 'adSources': [str(ad.location.source_root)],
        'adConfigVersion': '0.5', 'adBreakpointsSeconds': [20],
        'adBreakDurationSeconds': 10, 'adTriggers': ['breakpoint']})
    assert 'portable://' in created.record.path.read_text()
    with closing(sqlite3.connect(library.database_path)) as db:
        assert all(row[0].startswith('portable://') for row in db.execute('SELECT path FROM media_locations'))
    definition = load_channel(created.record.path)
    resolved = resolve_channel(definition, library)
    signature = advertising_signature(resolved)
    epoch = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    runtime = ChannelRuntime.open(resolved, RuntimeStore(paths.data_directory / 'runtime.db'), now=epoch)
    first = runtime.project_at(epoch + timedelta(seconds=21))
    runtime.broadcast_at(epoch + timedelta(seconds=31))
    history = runtime.break_store.play_counts()
    runtime.break_store.close()
    with closing(sqlite3.connect(paths.data_directory / 'runtime.db')) as db:
        assert 'portable://' in db.execute('SELECT payload FROM ad_break_plans').fetchone()[0]

    moved = tmp_path / 'another mount' / 'My TV'
    moved.parent.mkdir()
    shutil.move(root, moved)
    with pytest.raises(PortableUnavailableError):
        library.list_online_media()
    assert not root.exists()
    moved_paths = load_setup(moved)
    reopened_library = MediaLibrary(moved_paths.data_directory / 'library.db')
    assert reopened_library.cached_asset_for_unchanged_path(moved / 'Media' / 'Shows' / 'show.mp4').asset_id == show.asset.asset_id
    reopened_definition = load_channel(moved_paths.data_directory / 'channels' / created.record.path.name)
    reopened_resolved = resolve_channel(reopened_definition, reopened_library)
    assert advertising_signature(reopened_resolved) == signature
    reopened = ChannelRuntime.open(reopened_resolved,
        RuntimeStore(moved_paths.data_directory / 'runtime.db'), now=epoch + timedelta(seconds=31))
    try:
        assert reopened.epoch_utc == epoch
        assert reopened.project_at(epoch + timedelta(seconds=21)).event == first.event
        assert reopened.break_store.play_counts() == history
        plan = reopened.break_store.load_plan(first.event.break_id)
        assert reopened._media_for_segment(plan.segments[0]).location.path == moved / 'Media' / 'Ads' / 'ad.mp4'
    finally:
        reopened.break_store.close()


@pytest.mark.parametrize('reference', ['portable://../escape', 'portable:///escape', 'portable://x/../../escape', 'portable://C:/file', 'portable://x\\..\\escape'])
def test_portable_paths_reject_escapes(tmp_path, reference):
    paths = make_setup(tmp_path / 'setup')
    with pytest.raises(PortableSetupError):
        paths.decode(reference)


def test_setup_lock_is_exclusive_and_recovers_after_release(tmp_path):
    paths = make_setup(tmp_path / 'setup')
    with SetupLock(paths):
        with pytest.raises(PortableSetupError, match='already open'):
            with SetupLock(paths):
                pass
    with SetupLock(paths):
        pass


def test_changed_drive_identity_prevents_writes_to_the_wrong_setup(tmp_path):
    paths = make_setup(tmp_path / 'setup')
    library = MediaLibrary(paths.data_directory / 'library.db')
    state = RuntimeStore(paths.data_directory / 'runtime.db')
    marker = paths.root / MANIFEST_NAME
    raw = json.loads(marker.read_text())
    raw['setup_id'] = str(uuid.uuid4())
    marker.write_text(json.dumps(raw))
    with pytest.raises(PortableUnavailableError):
        library.count_assets()
    with pytest.raises(PortableUnavailableError):
        state.load_channel(7)


def test_newer_manifest_is_rejected_before_modifying_anything(tmp_path):
    paths = make_setup(tmp_path / 'setup')
    marker = paths.root / MANIFEST_NAME
    raw = json.loads(marker.read_text())
    raw['version'] = 100
    marker.write_text(json.dumps(raw))
    before = marker.read_bytes()
    with pytest.raises(PortableSetupError, match='compatible'):
        MediaLibrary(paths.data_directory / 'library.db')
    assert marker.read_bytes() == before
    assert not (paths.data_directory / 'library.db').exists()


def test_recent_shortcuts_do_not_accept_a_different_setup_at_the_same_drive_path(tmp_path, monkeypatch):
    from channelos.portable import recent_setups, remember_setup
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'Host'))
    paths = make_setup(tmp_path / 'Drive E')
    remember_setup(paths)
    assert recent_setups()[0]['available'] is True
    marker = paths.root / MANIFEST_NAME
    raw = json.loads(marker.read_text())
    raw['setup_id'] = str(uuid.uuid4())
    marker.write_text(json.dumps(raw))
    assert recent_setups()[0]['available'] is False
