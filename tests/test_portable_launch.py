from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from channelos import windows_app
from channelos.couch import _open_runtimes
from channelos.first_run import FIRST_RUN_OPEN_PORTABLE, PORTABLE_HANDOFF
from channelos.library import MediaLibrary
from channelos.portable import DATA_FOLDER, MANIFEST_NAME, PortableSetupError, SetupLock, load_setup
from channelos.portable_copy import inspect_setup
from channelos.runtime import RuntimeStore
from channelos.settings import CouchSettings, PortableSettingsStore
from test_portable_copy import source_setup, copy_setup


@pytest.fixture
def portable(tmp_path):
    library, service, store, runtime = source_setup(tmp_path)
    target = tmp_path / 'Drive E'
    try:
        copy_setup(library, service, store, target, copy_media=True)
        yield load_setup(target)
    finally:
        runtime.break_store.close()


def test_launcher_uses_moved_drive_for_all_state_and_holds_writer_lock(portable, tmp_path, monkeypatch):
    moved = tmp_path / 'different drive letter' / 'TV'
    moved.parent.mkdir()
    shutil.move(portable.root, moved)
    host = tmp_path / 'Second PC'
    monkeypatch.setenv('LOCALAPPDATA', str(host))
    monkeypatch.setenv('CHANNELOS_DATA_DIR', str(host / 'default setup'))
    received = []
    def run(arguments):
        received.extend(arguments)
        with pytest.raises(PortableSetupError, match='already open'):
            with SetupLock(load_setup(moved)):
                pass
        return 0
    monkeypatch.setattr(windows_app.couch, 'main', run)
    assert windows_app.main(['--portable-setup', str(moved), '--windowed']) == 0
    assert received == ['--db', str(moved / DATA_FOLDER / 'library.db'),
                        '--state-db', str(moved / DATA_FOLDER / 'runtime.db'),
                        '--channels-dir', str(moved / DATA_FOLDER / 'channels'), '--windowed']
    assert not (host / 'default setup').exists()
    assert not portable.root.exists()
    with SetupLock(load_setup(moved)):
        pass


def test_packaged_executable_discovers_portable_setup_without_first_run(portable, tmp_path, monkeypatch):
    app = portable.root / 'ChannelOS-App'
    app.mkdir()
    exe = app / 'ChannelOS.exe'
    exe.touch()
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'Host'))
    monkeypatch.setattr(windows_app.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(windows_app.sys, 'executable', str(exe))
    monkeypatch.setattr(windows_app, '_run_first_run_helper', lambda *_: pytest.fail('Portable setups must not enter first run'))
    received = []
    monkeypatch.setattr(windows_app.couch, 'main', lambda args: received.extend(args) or 0)
    assert windows_app.main([]) == 0
    assert received[1] == str(portable.data_directory / 'library.db')


def test_unavailable_or_incompatible_setup_does_not_create_replacement_state(portable, tmp_path, monkeypatch):
    messages = []
    host = tmp_path / 'Host'
    monkeypatch.setenv('CHANNELOS_DATA_DIR', str(host))
    monkeypatch.setattr(windows_app, '_show_error', messages.append)
    monkeypatch.setattr(windows_app.couch, 'main', lambda *_: pytest.fail('Invalid setup must not launch'))
    missing = tmp_path / 'Disconnected drive'
    assert windows_app.main(['--portable-setup', str(missing)]) == 6
    assert not missing.exists() and not host.exists()
    manifest = portable.root / MANIFEST_NAME
    raw = json.loads(manifest.read_text())
    raw['version'] = 99
    manifest.write_text(json.dumps(raw))
    before = {path: path.read_bytes() for path in portable.root.rglob('*') if path.is_file()}
    assert windows_app.main(['--portable-setup', str(portable.root)]) == 6
    assert before == {path: path.read_bytes() for path in before}
    assert not host.exists()
    assert len(messages) == 2


def test_portable_launch_rejects_mixed_local_databases(portable, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(windows_app, '_show_error', messages.append)
    custom = tmp_path / 'unrelated.db'
    assert windows_app.main(['--portable-setup', str(portable.root), '--db=' + str(custom)]) == 6
    assert not custom.exists()
    assert 'together' in messages[0]


def test_new_pc_first_run_can_open_existing_setup_without_indexing(portable, tmp_path, monkeypatch):
    host = tmp_path / 'Host setup'
    monkeypatch.setenv('CHANNELOS_DATA_DIR', str(host))
    monkeypatch.setattr(windows_app.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(windows_app, 'first_run_required', lambda *_: True)
    def select_existing(data):
        (data / PORTABLE_HANDOFF).write_text(json.dumps({'root': str(portable.root)}))
        return FIRST_RUN_OPEN_PORTABLE
    monkeypatch.setattr(windows_app, '_run_first_run_helper', select_existing)
    received = []
    monkeypatch.setattr(windows_app.couch, 'main', lambda args: received.extend(args) or 0)
    assert windows_app.main([]) == 0
    assert received[1] == str(portable.data_directory / 'library.db')
    assert not (host / 'library.db').exists()
    assert not (host / PORTABLE_HANDOFF).exists()


def test_offline_portable_channel_opens_using_cached_metadata_without_resetting_clock(portable):
    library = MediaLibrary(portable.data_directory / 'library.db')
    store = RuntimeStore(portable.data_directory / 'runtime.db')
    before = store.load_channel(7)
    for media in library.list_cached_media():
        media.location.path.unlink()
    with library.connect() as db:
        db.execute('UPDATE media_locations SET online=0')
    paths = tuple((portable.data_directory / 'channels').glob('*.yaml'))
    opened = _open_runtimes(paths, library, store)
    try:
        assert len(opened) == 1
        assert len(opened[0].channel.media) == 1
        assert opened[0].epoch_utc == before.epoch_utc
        assert store.load_channel(7) == before
        assert store.load_on_demand_watch(opened[0].channel.media[0].asset.asset_id).position_seconds == 12
    finally:
        for runtime in opened:
            if runtime.break_store:
                runtime.break_store.close()


def test_host_audio_device_is_separate_while_preferences_follow_the_drive(portable, tmp_path):
    shared = portable.data_directory / 'settings.json'
    pc_a = PortableSettingsStore(shared, portable, tmp_path / 'PC A' / 'device.json')
    pc_b = PortableSettingsStore(shared, portable, tmp_path / 'PC B' / 'device.json')
    pc_a.save(CouchSettings(volume_percent=35, audio_output_device_id='headphones-A'))
    assert pc_b.load().volume_percent == 35
    assert pc_b.load().audio_output_device_id == ''
    pc_b.save(CouchSettings(volume_percent=50, audio_output_device_id='speakers-B'))
    assert pc_a.load().volume_percent == 50
    assert pc_a.load().audio_output_device_id == 'headphones-A'
    assert 'audio_output_device_id' not in json.loads(shared.read_text())


def test_future_history_schema_is_rejected_before_migration(portable):
    path = portable.data_directory / 'runtime.db'
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE runtime_meta SET value='999' WHERE key='schema_version'")
        db.commit()
    before = path.read_bytes()
    with pytest.raises(PortableSetupError, match='history'):
        inspect_setup(portable.root)
    assert path.read_bytes() == before


def test_invalid_channel_is_reported_before_portable_startup_writes(portable, monkeypatch):
    channel = next((portable.data_directory / 'channels').glob('*.yaml'))
    channel.write_text('channel: []\nname: Broken\n')
    messages = []
    monkeypatch.setattr(windows_app, '_show_error', messages.append)
    monkeypatch.setattr(windows_app.couch, 'main', lambda *_: pytest.fail('Invalid channel must not launch'))
    assert windows_app.main(['--portable-setup', str(portable.root)]) == 6
    assert messages and 'could not open' in messages[0]
    assert not (portable.data_directory / 'logs').exists()
