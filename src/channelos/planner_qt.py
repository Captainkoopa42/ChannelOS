"""Cancellable worker bridge. Planner drafts never run expensive work on Qt."""
import copy
import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import QFileDialog

from .broadcast_planner.engine import PlannerCancelled
from .broadcast_planner.service import PlannerService


class _Task(QObject):
    result = Signal(int,str,str)
    finished = Signal()

    def __init__(self, service, generation, action, payload, cancel):
        super().__init__()
        self.service,self.generation,self.action,self.payload,self.cancel = service,generation,action,payload,cancel

    @Slot()
    def run(self):
        try:
            result = PlannerService(self.service).task(self.action,self.payload,self.cancel.is_set)
            if not self.cancel.is_set():
                self.result.emit(self.generation,self.action,json.dumps({'ok':True,**result,'token':self.payload.get('token')},allow_nan=False))
        except PlannerCancelled:
            pass
        except Exception as exc:
            if not self.cancel.is_set():
                self.result.emit(self.generation,self.action,json.dumps({'ok':False,'message':str(exc)}))
        finally:
            self.finished.emit()


def install_planner_support(module):
    if getattr(module,'_planner_support',False):
        return
    base = module.BroadcasterCouchController

    class PlannerController(base):
        plannerStateChanged = Signal()
        plannerResult = Signal(str,str)

        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self._planner_state={'busy':False,'generation':0}
            self._planner_thread=None
            self._planner_cancel=threading.Event()
            self._planner_pending=None
            self._planner_generation=0

        @Property(str,notify=plannerStateChanged)
        def plannerStateJson(self):
            return json.dumps(self._planner_state)

        @Slot(str,str)
        def plannerTask(self,action,payload_json):
            try:
                if len(payload_json)>20_000_000:
                    raise ValueError('The planner draft exceeds the 20 MB editing limit. Split this network into smaller channels.')
                payload=json.loads(payload_json)
                if not isinstance(payload,dict):
                    raise ValueError('Planner input must be an object')
                if action in {'export_profile','import_profile','import_airings'}:
                    if action=='export_profile':
                        path,_=QFileDialog.getSaveFileName(None,'Export time-block profile','','JSON (*.json)')
                    else:
                        path,_=QFileDialog.getOpenFileName(None,'Import original airings' if action=='import_airings' else 'Import time-block profile','',
                            'Original airings (*.json *.csv)' if action=='import_airings' else 'JSON (*.json)')
                    if not path:
                        return
                    if action=='export_profile' and not Path(path).suffix:
                        path += '.json'
                    payload['path']=path
                self._planner_generation+=1
                self._planner_pending=(self._planner_generation,action,payload)
                self._planner_cancel.set()
                if self._planner_thread is None:
                    self._start_planner_task()
            except (TypeError,ValueError) as exc:
                self.plannerResult.emit(action,json.dumps({'ok':False,'message':str(exc)}))

        def _start_planner_task(self):
            if self._planner_pending is None:
                return
            generation,action,payload=self._planner_pending
            self._planner_pending=None
            service=copy.copy(self._broadcaster)
            service._records=dict(service._records)
            service._definition_cache=dict(service._definition_cache)
            self._planner_cancel=threading.Event()
            thread=QThread(self)
            worker=_Task(service,generation,action,payload,self._planner_cancel)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.result.connect(self._planner_result,Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(self._planner_finished)
            thread.finished.connect(thread.deleteLater)
            self._planner_thread,self._planner_worker=thread,worker
            self._planner_state={'busy':True,'generation':generation,'action':action}
            self.plannerStateChanged.emit()
            thread.start()

        @Slot(int,str,str)
        def _planner_result(self,generation,action,result):
            if generation==self._planner_generation:
                self.plannerResult.emit(action,result)

        @Slot()
        def _planner_finished(self):
            self._planner_thread=None
            self._planner_worker=None
            if self._planner_pending:
                self._start_planner_task()
            else:
                self._planner_state={'busy':False,'generation':self._planner_generation}
                self.plannerStateChanged.emit()

        @Slot()
        def cancelPlannerTask(self):
            self._planner_generation+=1
            self._planner_pending=None
            self._planner_cancel.set()

        @Slot()
        def stop(self):
            self.cancelPlannerTask()
            if self._planner_thread:
                self._planner_thread.quit()
                self._planner_thread.wait()
            parent=getattr(super(),'stop',None)
            if parent:
                parent()

    module.BroadcasterCouchController=PlannerController
    module._planner_support=True
