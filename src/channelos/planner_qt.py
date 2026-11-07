"""Cancellable worker bridge. Planner drafts never run expensive work on Qt."""
import copy
import json
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

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


@lru_cache(maxsize=1)
def planner_timezones():
    """IANA zones for the picker: UTC first, then alphabetical regions."""
    zones = sorted(zone for zone in available_timezones()
                   if '/' in zone and not zone.startswith(('Etc/', 'SystemV/', 'posix/', 'right/')))
    return ['UTC'] + zones


def _zone(name):
    try:
        return ZoneInfo(str(name or 'UTC'))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f'Unknown time zone: {name}') from exc


def planner_local_to_iso(date_text, time_text, zone_name):
    """Wall-clock date and time in a zone -> ISO timestamp with its UTC offset."""
    try:
        local = datetime.fromisoformat(f'{str(date_text).strip()}T{str(time_text).strip()}')
    except ValueError:
        return {'ok': False, 'message': 'Choose a valid date and a time as HH:MM'}
    try:
        zone = _zone(zone_name)
    except ValueError as exc:
        return {'ok': False, 'message': str(exc)}
    aware = local.replace(tzinfo=zone)
    # A wall time skipped by a daylight-saving jump does not exist; say so.
    if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
        return {'ok': False, 'message': f'{local:%H:%M} does not exist on {local:%Y-%m-%d} in {zone_name} (clocks change)'}
    return {'ok': True, 'iso': aware.isoformat(timespec='seconds')}


def planner_iso_to_local(iso_text, zone_name):
    """ISO timestamp -> date and HH:MM in the planner's zone, for the pickers."""
    try:
        moment = datetime.fromisoformat(str(iso_text))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        local = moment.astimezone(_zone(zone_name))
    except ValueError:
        now = datetime.now(timezone.utc)
        return {'ok': False, 'date': now.date().isoformat(), 'time': '00:00', 'zoneLabel': 'UTC'}
    offset = local.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = '+' if minutes >= 0 else '-'
    label = f'{local.tzname() or zone_name} (UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d})'
    return {'ok': True, 'date': local.date().isoformat(), 'time': local.strftime('%H:%M'), 'zoneLabel': label}


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

        @Property('QVariantList',constant=True)
        def plannerTimezones(self):
            return planner_timezones()

        @Slot(str,str,str,result='QVariantMap')
        def plannerLocalToIso(self,date_text,time_text,zone_name):
            return planner_local_to_iso(date_text,time_text,zone_name)

        @Slot(str,str,result='QVariantMap')
        def plannerIsoToLocal(self,iso_text,zone_name):
            return planner_iso_to_local(iso_text,zone_name)

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
