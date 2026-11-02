"""Release regressions for the second Windows ChannelOS publication."""
from dataclasses import replace
from pathlib import Path
import hashlib

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
