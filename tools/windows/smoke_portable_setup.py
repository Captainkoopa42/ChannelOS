"""Verify a copied frozen executable resolves a relocated active setup.

Run after package_windows.py. This exercises both explicit setup opening and
double-click-equivalent discovery through the real packaged entry point.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def run(package_root: Path) -> None:
    if os.name != 'nt':
        raise RuntimeError('The frozen executable probe requires Windows')
    from channelos.broadcaster import BroadcasterService
    from channelos.library import MediaLibrary
    from channelos.portable import APP_FOLDER, load_setup
    from channelos.portable_copy import inspect_setup, plan_copy, publish_snapshot, snapshot_setup
    from channelos.probe import MediaProbeResult
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime, RuntimeStore

    package_root = package_root.resolve(strict=True)
    assert (package_root / 'ChannelOS.exe').is_file()
    with tempfile.TemporaryDirectory(prefix='cos-portable-') as temporary:
        root = Path(temporary)
        data, media = root / 'PC setup', root / 'Drive E' / 'My media'
        media.mkdir(parents=True)
        video = media / 'owned fixture.mp4'
        video.write_bytes(b'Indexed metadata fixture; help probes do not decode video')
        library = MediaLibrary(data / 'library.db')
        library.upsert_file(video, media,
            content_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
            probe=MediaProbeResult(duration_seconds=60, container_format='mp4'))
        broadcaster = BroadcasterService([], data / 'channels', library)
        record = broadcaster.create({'channel': 7, 'name': 'Portable probe',
            'sources': [str(media)], 'mode': 'sequential'}).record
        store = RuntimeStore(data / 'runtime.db')
        runtime = ChannelRuntime.open(resolve_channel(record.definition, library), store)
        asset_id = runtime.channel.media[0].asset.asset_id
        epoch = runtime.epoch_utc
        store.save_on_demand_watch(asset_id, 21, 60)
        if runtime.break_store:
            runtime.break_store.close()
        target = root / 'Drive E'
        plan = plan_copy(library, broadcaster.paths, target,
                         application_directory=package_root)
        assert plan.summary()['mediaFilesToCopy'] == 0
        publish_snapshot(snapshot_setup(plan, library, store.database_path, broadcaster.managed_directory))
        moved = root / 'Drive F'
        target.rename(moved)
        paths = load_setup(moved)
        environment = os.environ.copy()
        environment['LOCALAPPDATA'] = str(root / 'Second PC')
        unrelated = root / 'Unrelated local setup'
        environment['CHANNELOS_DATA_DIR'] = str(unrelated)
        executable = moved / APP_FOLDER / 'ChannelOS.exe'
        for arguments in (['--portable-setup', str(moved), '--help'], ['--help']):
            subprocess.run([str(executable), *arguments], env=environment,
                           cwd=root, check=True, timeout=60)
        assert not unrelated.exists(), 'The portable launcher fell back to local data'
        assert (paths.data_directory / 'logs' / 'channelos.log').is_file()
        reopened_library = MediaLibrary(paths.data_directory / 'library.db')
        assert reopened_library.cached_asset_for_unchanged_path(moved / 'My media' / video.name).asset_id == asset_id
        reopened_store = RuntimeStore(paths.data_directory / 'runtime.db')
        assert reopened_store.load_channel(7).epoch_utc == epoch
        assert reopened_store.load_on_demand_watch(asset_id).position_seconds == 21
        assert inspect_setup(moved)['channelCount'] == 1
        print(json.dumps({'packagedPortableSetup': 'passed', 'relocatedIndexReuse': True,
                          'historyContinuity': True, 'explicitOpen': True,
                          'applicationDiscovery': True, 'localFallback': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-root', type=Path, default=Path('dist/windows/ChannelOS'))
    run(parser.parse_args().package_root)
