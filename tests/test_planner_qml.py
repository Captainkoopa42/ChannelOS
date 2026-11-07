import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import QCoreApplication, QUrl, Qt, QEvent
from PySide6.QtGui import QGuiApplication,QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlExpression

from channelos import broadcaster_qt
from channelos.channel_jobs import install_channel_operations_support
from channelos.planner_qt import install_planner_support
from channelos.runtime import RuntimeStore
from channelos.control import ControlIntent,ControlCommand
from test_studio_autofill_qt import _controller


def until(predicate,seconds=20):
    end=time.monotonic()+seconds
    while not predicate() and time.monotonic()<end:
        QCoreApplication.processEvents()
        time.sleep(.005)
    assert predicate()


def test_native_planner_load_forecast_profile_and_real_channel_apply(tmp_path,monkeypatch):
    app=QGuiApplication.instance() or QGuiApplication([])
    original,_=_controller(tmp_path)
    module=SimpleNamespace(BroadcasterCouchController=broadcaster_qt.BroadcasterCouchController,
                           BroadcasterKeyFilter=broadcaster_qt.BroadcasterKeyFilter)
    install_channel_operations_support(module)
    install_planner_support(module)
    controller=module.BroadcasterCouchController(original._service,original._actions.runtime,
        original._library,original._broadcaster,original._runtime_store)
    engine=QQmlApplicationEngine()
    engine.rootContext().setContextProperty('channelOS',controller)
    engine.loadData(b'import QtQuick; import QtQuick.Controls; ApplicationWindow { width:1600; height:1000; visible:true; property string screen:"planner"; property int plannerChannelNumber:0 }')
    host=engine.rootObjects()[0]
    component=QQmlComponent(engine,QUrl.fromLocalFile(str(Path('src/channelos/qml/BroadcastPlannerScreen.qml').resolve())))
    until(lambda:not component.isLoading())
    assert component.isReady(),[e.toString() for e in component.errors()]
    item=component.create()
    item.setParentItem(host.contentItem())
    item.setProperty('hostWindow',host)
    host._channelos_planner_item=item
    key_filter=module.BroadcasterKeyFilter(controller,host)
    host.installEventFilter(key_filter)

    def evaluate(code):
        expression=QQmlExpression(engine.contextForObject(item),item,code)
        value,_=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return value.toVariant() if hasattr(value,'toVariant') else value

    try:
        until(lambda:item.property('loaded') and controller._planner_thread is None)
        assert evaluate('mediaBin.length')==1
        before={r.channel_number:r.definition for r in controller._broadcaster.records}
        evaluate('setEditor("name","Native Planner"); addTrack(mediaBin[0],false);')
        until(lambda:evaluate('previewCurrent') and controller._planner_thread is None)
        assert evaluate('forecast.confidence')=='Exact',evaluate('feedback')
        assert {r.channel_number:r.definition for r in controller._broadcaster.records}==before
        evaluate('task("save_profile",{profile:Draft.profile(rules,"Morning profile")})')
        until(lambda:controller._planner_thread is None)
        assert evaluate('profiles.length')==1
        evaluate('selectedTab=3')
        app.processEvents()
        assert evaluate('forecast.tracks.length')==1
        assert evaluate('canApply')
        evaluate('apply()')
        until(lambda:controller._mutation_thread is None)
        assert not item.property('feedbackError'),evaluate('feedback')
        saved=controller._broadcaster._records[int(evaluate('editor.channel'))].definition
        assert saved.programming.mode=='planner'
        assert saved.programming.planner.profile_bindings==()
        assert saved.programming.planner.tracks
        assert not item.property('dirty')
        evaluate('loadDraft()')
        until(lambda:item.property('loaded') and controller._planner_thread is None)
        until(lambda:evaluate('previewCurrent') and controller._planner_thread is None)
        assert evaluate('editor.fillerMode')=='sequential'
        assert evaluate('rules.tracks.length')==1
        assert evaluate('forecast.confidence')=='Exact',evaluate('feedback')
        # Opening the existing Manual Studio must retain the planner contract.
        manual=controller._broadcaster.studio_draft(int(evaluate('editor.channel')))
        assert manual['planner']==saved.programming.planner.to_mapping()
        host.requestActivate()
        evaluate('channelNameField.forceActiveFocus(); channelNameField.selectAll()')
        app.processEvents()
        assert evaluate('channelNameField.activeFocus')
        for key,text in [(Qt.Key.Key_H,'h'),(Qt.Key.Key_1,'1'),(Qt.Key.Key_2,'2'),(Qt.Key.Key_3,'3')]:
            QCoreApplication.sendEvent(host,QKeyEvent(QEvent.Type.KeyPress,key,Qt.KeyboardModifier.NoModifier,text))
            QCoreApplication.sendEvent(host,QKeyEvent(QEvent.Type.KeyRelease,key,Qt.KeyboardModifier.NoModifier,text))
        assert evaluate('channelNameField.text')=='h123'
        assert host.property('screen')=='planner'
        key_filter.dispatch_command(ControlCommand(ControlIntent.DOWN))
        app.processEvents()
        key_filter.dispatch_command(ControlCommand(ControlIntent.HOME))
        assert host.property('screen')=='planner' and evaluate('discardDialog.visible')
        evaluate('discardDialog.close()')
        assert controller._broadcaster._records[saved.channel].definition.name=='Native Planner'
        # All six native views must instantiate without binding exceptions.
        for tab in range(6):
            evaluate(f'selectedTab={tab}')
            app.processEvents()
        evaluate('selectedTab=0')
        app.processEvents()
        for width,height in [(1600,1000),(1100,700)]:
            host.setWidth(width); host.setHeight(height)
            for _ in range(4):
                app.processEvents()
                time.sleep(.02)
            assert evaluate('tracksCard.x+tracksCard.width<=planner.width')
            assert evaluate('milestoneRow.height<=milestonesCard.height-27')
            if os.environ.get('CHANNELOS_PLANNER_SCREENSHOTS'):
                directory=Path(os.environ['CHANNELOS_PLANNER_SCREENSHOTS'])
                directory.mkdir(parents=True,exist_ok=True)
                image=host.grabWindow()
                assert not image.isNull()
                assert image.save(str(directory/f'native-planner-{width}.png'),'PNG')
    finally:
        host.removeEventFilter(key_filter)
        controller.stop()
        original.stop()
        item.deleteLater()
        host.close()
        app.processEvents()
