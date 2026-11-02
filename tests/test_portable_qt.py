from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QObject, QMetaObject, QUrl, Qt, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow

import channelos
from channelos import broadcaster_qt, couch_model, couch_qt, guide, runtime
from channelos.broadcaster import BroadcasterService
from channelos.couch import _open_runtimes
from channelos.guide import GuideService
from channelos.library import MediaLibrary
from channelos.portable import MANIFEST_NAME, PortableUnavailableError, load_setup
from channelos.portable_copy import inspect_setup
from channelos.portable_qt import install_portable_support
from channelos.runtime import RuntimeStore, TelevisionRuntime
from test_portable_copy import EPOCH, source_setup, copy_setup


@pytest.fixture
def controller_factory(tmp_path, monkeypatch):
    app = QGuiApplication.instance() or QGuiApplication([])
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'Host PC'))
    for module in (runtime, guide, couch_model, couch_qt):
        monkeypatch.setattr(module, 'utc_now', lambda: EPOCH)
    module = SimpleNamespace(BroadcasterCouchController=broadcaster_qt.BroadcasterCouchController)
    install_portable_support(module)
    library, broadcaster, store, original = source_setup(tmp_path)
    controllers = []
    def create(root=None):
        if root:
            paths = load_setup(root)
            lib = MediaLibrary(paths.data_directory / 'library.db')
            state = RuntimeStore(paths.data_directory / 'runtime.db')
            service = BroadcasterService([], paths.data_directory / 'channels', lib)
        else:
            lib, state, service = library, store, broadcaster
        runtimes = _open_runtimes(service.paths, lib, state)
        controller = module.BroadcasterCouchController(GuideService(runtimes),
            TelevisionRuntime(runtimes, state), lib, service, state)
        controllers.append(controller)
        return controller
    yield app, create, (library, broadcaster, store)
    for controller in controllers:
        controller.stop()
        for item in controller._actions.runtime.channels.values():
            if item.break_store:
                item.break_store.close()
        controller.deleteLater()
    original.break_store.close()
    app.processEvents()


def wait_for(app, condition):
    deadline = time.monotonic() + 15
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert condition()


def test_settings_copy_runs_in_background_and_opens_with_explicit_drive_path(controller_factory, tmp_path, monkeypatch):
    app, create, _ = controller_factory
    controller = create()
    target = tmp_path / 'External drive'
    assert not controller.previewPortableCopy(str(target), False, False, False)['ok']
    review = controller.previewPortableCopy(str(target), True, False, False)
    assert review['ok'] and review['channelCount'] == 1 and review['mediaFilesToCopy'] == 2
    assert controller.startPortableCopy(str(target), True, False, False)['ok']
    assert controller.portableCopy['active'] is True
    wait_for(app, lambda: controller._portable_thread is None)
    assert controller.portableCopy['phase'] == 'ready', controller.portableCopy
    assert inspect_setup(target)['assetCount'] == 2
    # Copy keeps the original session active until the explicit Open action.
    assert controller.portableSetup['active'] is False
    launched = []
    from channelos import portable_qt
    monkeypatch.setattr(portable_qt.QProcess, 'startDetached', lambda exe, args: launched.append((exe, args)) or (True, 123))
    monkeypatch.setattr(portable_qt.QTimer, 'singleShot', lambda *_: None)
    assert not controller.openPortableSetup(str(target), 'another-setup')['ok']
    assert launched == []
    assert controller.openPortableSetup(str(target))['ok']
    assert launched[0][1][-2:] == ['--portable-setup', str(target)]


def test_drive_disconnect_stops_writes_and_reopens_fresh_connections_on_return(controller_factory, tmp_path):
    app, create, source = controller_factory
    target = tmp_path / 'Drive'
    copy_setup(*source, target, copy_media=True)
    controller = create(target)
    before = controller._runtime_store.load_channel(7)
    marker = target / MANIFEST_NAME
    saved_marker = marker.with_suffix('.disconnected')
    marker.rename(saved_marker)
    assert controller.checkPortableDrive() is False
    assert controller.portableSetup['available'] is False
    parked = tmp_path / 'Drive unplugged'
    target.rename(parked)
    controller.refresh()
    controller.refreshPlayback()
    controller.refreshOnDemand()
    with pytest.raises(PortableUnavailableError):
        controller._settings_store.save(controller._settings)
    assert not target.exists()
    parked.rename(target)
    saved_marker.rename(marker)
    assert controller.checkPortableDrive() is True, controller.portableSetup
    assert controller._runtime_store.load_channel(7) == before
    assert controller.portableSetup['available'] is True
    assert controller._actions.runtime.channels[7].break_store.connection.execute('SELECT 1').fetchone()[0] == 1
    marker.rename(saved_marker)
    assert controller.checkPortableDrive() is False
    controller.stop()
    saved_marker.rename(marker)
    app.processEvents()


def test_portable_dialog_opens_with_review_controls_and_no_qml_errors(controller_factory):
    app, create, _ = controller_factory
    controller = create()
    surface = QQuickWindow()
    surface.resize(1280, 900)
    surface.show()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('channelOS', controller)
    messages = []
    handler = qInstallMessageHandler(lambda _mode, _context, message: messages.append(message))
    dialog = None
    try:
        component = QQmlComponent(engine)
        qml = Path(channelos.__file__).parent / 'qml' / 'PortableSetupDialog.qml'
        component.loadUrl(QUrl.fromLocalFile(str(qml)))
        if component.isLoading():
            app.processEvents()
        assert component.isReady(), '\n'.join(error.toString() for error in component.errors())
        dialog = component.create()
        assert dialog is not None
        dialog.setProperty('parent', surface.contentItem())
        assert QMetaObject.invokeMethod(dialog, 'open', Qt.ConnectionType.DirectConnection)
        app.processEvents()
        assert dialog.property('visible') is True
        assert dialog.findChild(QObject, 'portableDestination') is not None
        assert dialog.findChild(QObject, 'portableReview') is not None
        assert dialog.findChild(QObject, 'portableStartCopy').property('enabled') is False
    finally:
        if dialog:
            dialog.close()
            dialog.deleteLater()
        surface.close()
        app.processEvents()
        qInstallMessageHandler(handler)
    assert not [message for message in messages if 'Portable' in message and (': Error' in message or 'ReferenceError' in message or 'TypeError' in message)], messages
