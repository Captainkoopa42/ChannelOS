"""Prepare only requested Guide rows in short Qt tasks using owned SQL handles."""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import timedelta

from PySide6.QtCore import QTimer, Slot

from .couch_model import DEFAULT_GUIDE_HOURS, _floor_to_half_hour, build_couch_snapshot
from .guide import GuideChannelRow, GuideService
from .runtime import utc_now

logger = logging.getLogger(__name__)


def install_incremental_guide_support(module):
    base = module.BroadcasterCouchController
    if getattr(base, '_channelos_incremental_guide', False):
        return

    class IncrementalGuideController(base):
        _channelos_incremental_guide = True

        def __init__(self, *args, **kwargs):
            self._guide_cache = {}
            self._guide_context = None
            self._guide_range = None
            self._guide_queue = []
            self._guide_work = None
            self._guide_errors = set()
            super().__init__(*args, **kwargs)
            self._guide_timer = QTimer(self)
            self._guide_timer.setSingleShot(True)
            self._guide_timer.timeout.connect(self._advance_guide)

        def _build_guide_snapshot(self):
            now = utc_now()
            start = _floor_to_half_hour(now)
            identity = (start, tuple((r.channel_number, id(r)) for r in self._service._runtimes))
            if identity != self._guide_context:
                old = dict(self._guide_context[1]) if self._guide_context and self._guide_context[0] == start else {}
                retained = {number for number, runtime_id in identity[1] if old.get(number) == runtime_id}
                self._guide_context = identity
                self._guide_cache = {number: row for number, row in self._guide_cache.items() if number in retained}
                self._guide_errors.clear()
                self._guide_queue.clear()
                self._guide_work = None
            rows = []
            for row in self._guide_cache.values():
                rows.append(replace(row, programs=tuple(replace(program,
                    is_current=program.start_utc <= now < program.end_utc,
                    is_past=program.end_utc <= now, is_future=program.start_utc > now)
                    for program in row.programs)))
            pending = ()
            if getattr(self, '_defer_initial_views', False) or getattr(self, '_startup_state', {}).get('active'):
                pending = tuple(definition.channel for definition in self._service.definitions)
            snapshot = build_couch_snapshot(self._service, at=now, prepared_rows=rows,
                                           pending_numbers=pending, failed_numbers=self._guide_errors)
            self._queue_requested_rows(snapshot)
            return snapshot

        def _queue_requested_rows(self, snapshot):
            if self._guide_range is None:
                return
            first, last = self._guide_range
            rows = snapshot['rows']
            wanted = [int(row['channelNumber']) for row in rows[first:last + 1]
                      if int(row['channelNumber']) in self._actions.runtime.channels]
            active = self._guide_work[0].channel_number if self._guide_work else None
            if active not in wanted:
                self._guide_work = None
            self._guide_queue = [number for number in wanted if number not in self._guide_cache
                                 and number not in self._guide_errors and number != active]
            # Bound retained dense schedules while scrolling through a large lineup.
            if len(self._guide_cache) > 26:
                self._guide_cache = {number: row for number, row in self._guide_cache.items() if number in wanted}
            if hasattr(self, '_guide_timer') and (self._guide_queue or self._guide_work):
                self._guide_timer.start(0)

        @Slot(int, int)
        def requestGuideRows(self, first, last):
            self._guide_range = None if first < 0 else (max(0, first), max(first, last))
            if self._guide_range is None:
                self._guide_queue.clear()
                self._guide_work = None
                self._guide_timer.stop()
            else:
                self._queue_requested_rows(self._snapshot)

        @Slot()
        def _advance_guide(self):
            if self._guide_range is None:
                return
            # Keep all projections on Qt's thread: runtime ad-plan connections
            # must never be shared with workers. Yield between occurrences.
            deadline = time.perf_counter() + .004
            published = False
            while time.perf_counter() < deadline:
                if self._guide_work is None:
                    if not self._guide_queue:
                        break
                    number = self._guide_queue.pop(0)
                    runtime = self._actions.runtime.channels.get(number)
                    if runtime is None:
                        continue
                    start = self._guide_context[0]
                    iterator = GuideService.iter_programs(runtime, start,
                        start + timedelta(hours=DEFAULT_GUIDE_HOURS), utc_now())
                    self._guide_work = (runtime, iterator, [])
                runtime, iterator, programs = self._guide_work
                try:
                    programs.append(next(iterator))
                except StopIteration:
                    self._guide_cache[runtime.channel_number] = GuideChannelRow(runtime.channel_number,
                        runtime.channel.definition.name, tuple(programs))
                    self._guide_work = None
                    published = True
                except Exception:
                    logger.exception('Guide row %s could not be projected', runtime.channel_number)
                    self._guide_errors.add(runtime.channel_number)
                    self._guide_work = None
                    published = True
                    break
            if published:
                self._snapshot = self._build_guide_snapshot()
                self.snapshotChanged.emit()
            if self._guide_queue or self._guide_work:
                self._guide_timer.start(0)

        @Slot()
        def refresh(self):
            self._guide_errors.clear()
            super().refresh()

        @Slot()
        def stop(self):
            self._guide_timer.stop()
            self._guide_work = None
            super().stop()

    module.BroadcasterCouchController = IncrementalGuideController
