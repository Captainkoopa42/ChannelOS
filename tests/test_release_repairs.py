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


@pytest.mark.parametrize('calendar', [False, True])
def test_library_add_preserves_full_channel_and_is_idempotent(tmp_path, calendar):
    library, service, raw = setup(tmp_path)
    if calendar:
        raw['mode'] = 'calendar'
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
    controller = CouchController(GuideService(()), tv, library)
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
