"""Exercise the real staged Qt launcher and lazy management screens on a fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def run(*, skip_video=False, vlc_dir=None):
    if vlc_dir is not None:
        os.environ['CHANNELOS_VLC_DIR'] = str(vlc_dir.resolve())
    from PySide6.QtCore import QTimer
    from PySide6.QtQml import QQmlExpression
    from PySide6.QtWidgets import QApplication
    from channelos.broadcaster import BroadcasterService
    from channelos.couch import run_couch, _open_runtimes
    from channelos.library import MediaLibrary
    from channelos.probe import MediaProbeResult
    from channelos.runtime import RuntimeStore, TelevisionRuntime
    from smoke_ad_playback import create_test_video
    app = QApplication.instance() or QApplication([])
    start = time.perf_counter()
    ticks, results, errors = [], {}, []
    with tempfile.TemporaryDirectory(prefix='channelos-startup-smoke-') as temporary:
        root = Path(temporary)
        media = root / 'owned'
        media.mkdir()
        path = media / 'startup.avi'
        create_test_video(path, 30, color=(80, 150, 210))
        library = MediaLibrary(root / 'library.db')
        library.upsert_file(path, media, content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            probe=MediaProbeResult(duration_seconds=30, container_format='avi'))
        broadcaster = BroadcasterService([], root / 'channels', library)
        for number in (1, 7, 8):
            broadcaster.create({'channel': number, 'name': f'Startup {number}',
                'sources': [str(media)], 'mode': 'sequential'})
        store = RuntimeStore(broadcaster.runtime_database_path)
        runtimes = _open_runtimes(broadcaster.paths, library, store)
        TelevisionRuntime(runtimes, store).tune(7)
        for runtime in runtimes:
            if runtime.break_store:
                runtime.break_store.close()
        start = time.perf_counter()
        assert run_couch([], db=library.database_path, state_db=store.database_path,
                         channels_dir=broadcaster.managed_directory, windowed=True) == 0
        bootstrap = app._channelos_bootstrap[1]
        results['bootstrapVisible'] = bootstrap.isVisible()
        bootstrap.frameSwapped.connect(lambda: results.setdefault('bootstrapFrameMs', (time.perf_counter() - start) * 1000))
        timer = QTimer()
        timer.setInterval(5)
        stage = 0
        def check():
            nonlocal stage
            ticks.append(time.perf_counter())
            window = getattr(app, '_channelos_window', None)
            controller = getattr(window, '_channelos_controller', None) if window is not None else None
            try:
                assert time.perf_counter() - start < 45, 'Startup smoke timed out'
                if window is None:
                    return
                controller = window._channelos_controller
                results.setdefault('mainWindowMs', (time.perf_counter() - start) * 1000)
                if controller.startupState['active']:
                    return
                if stage == 0:
                    assert set(controller._actions.runtime.channels) == {1, 7, 8}
                    assert controller.librarySnapshot['count'] == 1
                    assert all(getattr(window, '_channelos_' + name + '_item') is None
                               for name in ('library', 'broadcaster', 'studio', 'planner', 'settings'))
                    assert not controller._guide_cache, 'Home projected the Guide eagerly'
                    results['dataReadyMs'] = (time.perf_counter() - start) * 1000
                    window.setProperty('screen', 'guide')
                    stage = 1
                elif stage == 1:
                    if any(row.get('isPending') for row in controller.snapshot['rows']):
                        return
                    results['guideReady'] = True
                    window.setProperty('screen', 'broadcaster')
                    assert window._channelos_broadcaster_item is not None
                    window.setProperty('screen', 'library')
                    assert window._channelos_library_item is not None
                    window.setProperty('studioChannelNumber', 7)
                    window.setProperty('screen', 'studio')
                    assert window._channelos_studio_item is not None
                    window.setProperty('screen', 'settings')
                    assert window._channelos_settings_item is not None
                    window.setProperty('plannerChannelNumber',7)
                    window.setProperty('screen','planner')
                    assert window._channelos_planner_item is not None
                    stage = 2
                elif stage == 2:
                    item=window._channelos_planner_item
                    if not item.property('loaded') or controller._planner_thread is not None:
                        return
                    expression=QQmlExpression(window._channelos_component_engine.contextForObject(item),item,
                        'mutate(function(r) { Draft.addWindow(r,"primary") })')
                    expression.evaluate()
                    assert not expression.hasError(),expression.error().toString()
                    stage = 3
                elif stage == 3:
                    item=window._channelos_planner_item
                    if not item.property('previewCurrent') or controller._planner_thread is not None:
                        return
                    expression=QQmlExpression(window._channelos_component_engine.contextForObject(item),item,'forecast.confidence')
                    value,_=expression.evaluate()
                    value=value.toVariant() if hasattr(value,'toVariant') else value
                    assert value=='Exact',value
                    assert controller._broadcaster._records[7].definition.programming.mode=='sequential'
                    results['plannerDraftVerified']=True
                    window.setProperty('screen', 'home')
                    results['lazyScreens'] = True
                    stage = 4
                elif skip_video or controller.playback.get('active'):
                    results['playbackActive'] = bool(controller.playback.get('active'))
                    assert skip_video or controller.playback['channelNumber'] == 7
                    results['heartbeatTicks'] = len(ticks)
                    timer.stop()
                    app.quit()
            except Exception as exc:
                # Always stop: a failure while describing the failure must not
                # leave the loop running until the CI job is cancelled.
                timer.stop()
                try:
                    item=getattr(window,'_channelos_planner_item',None) if window else None
                    detail={'stage':stage,'mainWindow':window is not None,
                            'startupState':dict(controller.startupState) if controller else None,
                            'playback':{k: v for k, v in dict(controller.playback).items()
                                        if isinstance(v, (str, int, float, bool))} if controller else None,
                            'screen':window.property('screen') if window else None,
                            'statusMessage':window.property('statusMessage') if window else None,
                            'plannerFeedback':item.property('feedback') if item else None,
                            'plannerLoaded':item.property('loaded') if item else None,
                            'plannerWorker':getattr(controller,'_planner_state',None) if controller else None}
                    errors.append(str(exc)+' '+json.dumps(detail, default=str))
                except Exception as inner:
                    errors.append(f'{exc} (details unavailable: {inner})')
                app.quit()
        timer.timeout.connect(check)
        timer.start()
        app.exec()
        assert not errors, errors
        assert results.get('lazyScreens') and results['bootstrapVisible'], results
        print(json.dumps(results, sort_keys=True))
        window = getattr(app, '_channelos_window', None)
        if window:
            window.close()
        app.processEvents()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-video', action='store_true', help='Check shell loading without requiring a native decoder')
    parser.add_argument('--vlc-dir', type=Path, default=Path('dist/windows/ChannelOS/runtime/vlc'))
    options = parser.parse_args()
    run(skip_video=options.skip_video, vlc_dir=options.vlc_dir if options.vlc_dir.exists() else None)
