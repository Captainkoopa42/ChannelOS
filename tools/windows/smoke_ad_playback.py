"""Exercise Qt HWND + bundled libVLC with generated, user-owned AVI fixtures.

Run after package_windows.py on a Windows desktop (including windows-latest).
This uses the GDI software output so CI does not depend on a physical GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return kind + struct.pack('<I', len(payload)) + payload + b'\0' * (len(payload) % 2)


def create_test_video(path: Path, seconds: float, *, color: tuple[int, int, int]) -> None:
    width, height, fps = 96, 64, 20
    frames = round(seconds * fps)
    frame = bytes(color) * width * height
    main = struct.pack('<14I', 1000000 // fps, len(frame) * fps, 0, 16,
                       frames, 0, 1, len(frame), width, height, 0, 0, 0, 0)
    stream = struct.pack('<4s4sIHH8I4h', b'vids', b'DIB ', 0, 0, 0,
                         0, 1, fps, 0, frames, len(frame), 0xFFFFFFFF, 0,
                         0, 0, width, height)
    bitmap = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(frame), 0, 0, 0, 0)
    headers = _chunk(b'LIST', b'hdrl' + _chunk(b'avih', main)
                     + _chunk(b'LIST', b'strl' + _chunk(b'strh', stream) + _chunk(b'strf', bitmap)))
    data = b''.join(_chunk(b'00db', frame) for _ in range(frames))
    index = b''.join(struct.pack('<4sIII', b'00db', 16,
                                4 + i * (8 + len(frame)), len(frame)) for i in range(frames))
    path.write_bytes(_chunk(b'RIFF', b'AVI ' + headers + _chunk(b'LIST', b'movi' + data) + _chunk(b'idx1', index)))


def run(vlc_dir: Path) -> None:
    if os.name != 'nt':
        raise RuntimeError('The native HWND smoke test requires Windows')
    os.environ['CHANNELOS_VLC_DIR'] = str(vlc_dir.resolve())
    from PySide6.QtWidgets import QApplication, QWidget
    from channelos.library import MediaLibrary
    from channelos.models import ChannelDefinition
    from channelos.playback import LibVLCBackend, NativeVideoSurface
    from channelos.probe import MediaProbeResult
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore, TelevisionRuntime
    from channelos.television import TelevisionSession

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(640, 360)
    window.setWindowTitle('ChannelOS native ad playback verification')
    window.show()
    app.processEvents()
    observed = []
    with tempfile.TemporaryDirectory(prefix='channelos-native-ads-') as temporary:
        root = Path(temporary)
        programs, ads = root / 'owned programs', root / 'owned commercials'
        programs.mkdir()
        ads.mkdir()
        library = MediaLibrary(root / 'library.sqlite')
        for folder, seconds, color in [(programs, 4.0, (190, 70, 35)), (ads, 1.0, (30, 160, 230))]:
            path = folder / 'test.avi'
            create_test_video(path, seconds, color=color)
            library.upsert_file(path, folder, content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                probe=MediaProbeResult(duration_seconds=seconds, container_format='avi'))
        ad_id = library.list_online_media_for_source(ads)[0].asset.asset_id
        for behavior in ['cut', 'fade', 'hold']:
            definition = ChannelDefinition.from_mapping({
                'schema_version': '0.5', 'channel': 7, 'name': 'Native ad smoke',
                'sources': [{'path': str(programs)}], 'programming': {'mode': 'sequential'},
                'advertising': {'enabled': True, 'asset_ids': [ad_id], 'breakpoints_seconds': [1.5],
                                'break_duration_seconds': 1.25, 'triggers': ['breakpoint'],
                                'transition_behavior': behavior, 'transition_seconds': .2},
            })
            epoch = datetime.now(timezone.utc)
            store = RuntimeStore(root / (behavior + '.sqlite'))
            runtime = ChannelRuntime.open(resolve_channel(definition, library), store, now=epoch)
            backend = None
            try:
                backend = LibVLCBackend('--no-audio', '--vout=wingdi', '--avcodec-hw=none', '--no-video-title-show')
                backend.attach_video_surface(NativeVideoSurface('windows', int(window.winId())))
                session = TelevisionSession(TelevisionRuntime((runtime,), store), backend)
                session.tune(7, now=epoch)
                seen = set()
                native_output = False
                deadline = time.monotonic() + 5.5
                while time.monotonic() < deadline:
                    app.processEvents()
                    decision = session.sync()
                    seen.add(decision.viewer_selection.event.event_type)
                    native_output = native_output or bool(backend._player.has_vout())
                    if decision.viewer_selection.offset_seconds < 0:
                        raise AssertionError('negative resume offset')
                    time.sleep(.025)
                assert {'program', 'advertisement'} <= seen, (behavior, seen)
                if behavior == 'hold':
                    assert 'transition' in seen
                assert native_output, f'{behavior}: libVLC never created a native video output'
                backend.set_volume(37)
                assert backend.get_volume() == 37
                backend.set_muted(True)
                assert backend.get_muted()
                session.stop()
                assert backend.get_volume() == 37
            finally:
                if backend is not None:
                    backend.stop()
                    backend._player.release()
                    backend._instance.release()
                runtime.break_store.close()
            observed.append({'behavior': behavior, 'events': sorted(seen), 'nativeVideo': native_output})
    window.close()
    print(json.dumps({'nativeAdPlayback': 'passed', 'results': observed}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vlc-dir', type=Path, default=Path('dist/windows/ChannelOS/runtime/vlc'))
    run(parser.parse_args().vlc_dir)
