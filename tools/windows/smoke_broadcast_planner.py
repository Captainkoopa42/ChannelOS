"""Native Windows playout check using generated, owned AVI fixtures.

Explicit simulated broadcast timestamps cover minute brackets without slowing
CI by a minute. libVLC still decodes each real program/ad on a real Qt HWND.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def run(vlc_dir):
    if os.name!='nt':
        raise RuntimeError('Native Planner smoke requires Windows')
    os.environ['CHANNELOS_VLC_DIR']=str(vlc_dir.resolve())
    from PySide6.QtWidgets import QApplication,QWidget
    from channelos.broadcaster import BroadcasterService
    from channelos.guide import GuideService
    from channelos.library import MediaLibrary
    from channelos.playback import LibVLCBackend,NativeVideoSurface
    from channelos.probe import MediaProbeResult
    from channelos.resolve import resolve_channel
    from channelos.runtime import ChannelRuntime,RuntimeStore,TelevisionRuntime
    from channelos.television import TelevisionSession
    from channelos.broadcast_planner.timezones import get_zone
    from smoke_ad_playback import create_test_video
    app=QApplication.instance() or QApplication([])
    window=QWidget()
    window.resize(640,360)
    window.show()
    app.processEvents()
    assert get_zone('America/Los_Angeles').key=='America/Los_Angeles'
    observed=[]
    with tempfile.TemporaryDirectory(prefix='channelos-native-planner-') as temporary:
        root=Path(temporary)
        programs,ads=root/'programs',root/'ads'
        programs.mkdir(); ads.mkdir()
        library=MediaLibrary(root/'library.db')
        for folder,name,seconds,color in [(programs,'episode-1.avi',4,(180,80,35)),
                (programs,'episode-2.avi',4,(70,170,95)),(ads,'commercial.avi',1,(30,150,220))]:
            path=folder/name
            create_test_video(path,seconds,color=color)
            library.upsert_file(path,folder,content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                probe=MediaProbeResult(duration_seconds=seconds,container_format='avi'))
        assets=library.list_online_media_for_source(programs)
        ad=library.list_online_media_for_source(ads)[0]
        epoch=datetime.now(timezone.utc).replace(second=0,microsecond=0)
        rule={'start_at':epoch.isoformat(),'timezone':'UTC',
            'groups':[{'id':'show','name':'Native Planner','asset_ids':[m.asset.asset_id for m in assets]}],
            'tracks':[{'id':'primary','group_id':'show'}],
            'windows':[{'id':'daily','track_id':'primary','start':epoch.strftime('%H:%M'),
                'end':(epoch+timedelta(minutes=10)).strftime('%H:%M'),'bracket_minutes':1}],
            'cycle':{'action':'once'},'gap_filler':False}
        broadcaster=BroadcasterService([],root/'channels',library)
        saved=broadcaster.create({'channel':7,'name':'Native Planner','sources':[str(programs)],
            'mode':'planner','planner':rule,'adBreaksEnabled':True,'adSources':[str(ads)],
            'adAssetIds':[ad.asset.asset_id],'adSetupMode':'after_show','adPlayOrder':'sequential'}).record.definition
        store=RuntimeStore(broadcaster.runtime_database_path)
        runtime=ChannelRuntime.open(resolve_channel(saved,library),store,now=epoch)
        backend=LibVLCBackend('--no-audio','--vout=wingdi','--avcodec-hw=none','--no-video-title-show')
        backend.attach_video_surface(NativeVideoSurface('windows',int(window.winId())))
        session=TelevisionSession(TelevisionRuntime((runtime,),store),backend)
        try:
            for second,expected in [(0.4,'program'),(4.2,'advertisement'),(60.4,'program'),(64.2,'advertisement'),(65.1,'offair')]:
                at=epoch+timedelta(seconds=second)
                decision=session.tune(7,now=at,return_behavior='live')
                assert decision.viewer_selection.event.event_type==expected
                if expected!='offair':
                    deadline=time.monotonic()+3
                    while not backend._player.has_vout() and time.monotonic()<deadline:
                        app.processEvents(); time.sleep(.025)
                    assert backend._player.has_vout(),(second,expected)
                if expected=='program':
                    assert GuideService((runtime,)).now_next(7,at=at).now.asset_id==decision.viewer_selection.media.asset.asset_id
                observed.append({'at':second,'event':expected,'offset':decision.viewer_selection.offset_seconds})
            with store.connect() as connection:
                ledger={'cycles':connection.execute('SELECT COUNT(*) FROM planner_cycles').fetchone()[0],
                        'completions':connection.execute('SELECT COUNT(*) FROM planner_completions').fetchone()[0]}
                assert ledger=={'cycles':1,'completions':1},{'ledger':ledger,'events':observed}
        finally:
            session.stop()
            backend._player.release(); backend._instance.release()
            runtime.break_store.close()
    window.close()
    print(json.dumps({'nativePlannerPlayback':'passed','simulatedBroadcastTimestamps':True,'ledger':ledger,'events':observed}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vlc-dir',type=Path,default=Path('dist/windows/ChannelOS/runtime/vlc'))
    run(parser.parse_args().vlc_dir)
