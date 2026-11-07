"""Pure, bounded broadcast compiler shared by forecasts, Guide and playback.

The compiler owns detached calculation state, never a database, decoder or clock.
Producing a future occurrence does not constitute an airing.
"""
from __future__ import annotations

import copy
import hashlib
import math
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

from .contracts import PlannerDefinition, PlannerValidationError, minute
from .timezones import get_zone, local_instant

UTC = timezone.utc


class PlannerCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class Asset:
    id: str
    seconds: float
    title: str = ''
    online: bool = True

    def __post_init__(self):
        if not math.isfinite(self.seconds) or self.seconds<0:
            object.__setattr__(self,'seconds',0.0)


@dataclass(frozen=True)
class Segment:
    id: str
    asset_id: str | None
    starts_at: datetime
    ends_at: datetime
    kind: str
    track_id: str | None
    window_id: str | None
    cycle: int
    source_offset: float = 0
    parent_id: str | None = None
    parent_start: datetime | None = None
    parent_end: datetime | None = None
    break_id: str | None = None
    finishes_asset: bool = False
    first_pass: bool = False

    def to_mapping(self):
        return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in asdict(self).items()}

    @classmethod
    def from_mapping(cls, raw):
        value = dict(raw)
        for key in ('starts_at', 'ends_at', 'parent_start', 'parent_end'):
            if value.get(key):
                value[key] = datetime.fromisoformat(value[key])
        return cls(**value)


@dataclass
class Cursor:
    remaining: list[str]
    offset: float = 0
    completed_at: datetime | None = None
    pass_number: int = 0
    skipped: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    window: object | None = None
    asset_id: str | None = None
    track_id: str | None = None
    identity: str = ''
    rerun: bool = False
    priority: int = 0
    protected: bool = False
    ad_snapshot: dict | None = None
    hard_end: datetime | None = None
    historical: bool = False


@dataclass
class DayPlan:
    day: date
    start: datetime
    end: datetime
    segments: list[Segment] = field(default_factory=list)
    completions: list[tuple[int, str, datetime]] = field(default_factory=list)
    closed_cycles: list[dict] = field(default_factory=list)
    breaks: list[object] = field(default_factory=list)
    next_change: datetime | None = None


def stable_id(*parts):
    return hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()


class Compiler:
    def __init__(self, definition: PlannerDefinition, assets, *, channel=1, ads=None,
                 manual=(), cancel=None, activation=None, seed=None, manual_releases=None):
        self.definition = definition
        self.revision = definition.revision
        self.assets = {a.id: a for a in assets}
        self.channel = channel
        self.ads = ads
        self.manual = tuple(manual)
        self.manual_releases = manual_releases or {}
        self.cancel = cancel or (lambda: False)
        self.zone = get_zone(definition.timezone)
        self.groups = {g.id: g for g in definition.groups}
        self.tracks = {t.id: t for t in definition.tracks}
        self.layers = {l.id: l for l in definition.layers}
        self.activation = activation or definition.start_at
        self.cycle_start = self.activation
        self.cycle_index = 0
        self.cursors = {t.id: Cursor(self._order(t.id, 0)[t.start_index:]) for t in definition.tracks}
        self.ready_at = None
        self.restart_at = None
        self.closed = False
        self.blocked = False
        self.last_end = self.activation
        self.resume_at = None
        self._cutoff = None
        self.next_day = self.activation.astimezone(self.zone).date()
        self.active_pauses = set()
        self.issues = {}
        if self.ads and self.ads.invalid_reason:
            self.issue('advertising-unavailable',self.ads.invalid_reason,True)
        if definition.gap_filler and definition.filler_asset_ids and not any(
            key in self.assets and self.assets[key].online and self.assets[key].seconds>0 for key in definition.filler_asset_ids):
            self.issue('filler-unavailable','The selected filler pool has no online clips with a known duration; gaps remain off air.')
        self.first_starts = {}
        self.first_finishes = {}
        self.content_seconds = {}
        self.occupied_seconds = {}
        self.filler_index = 0
        self.total_segments = 0
        self.reporting_cycle = 0
        self._history_cache = None
        self._manual_by_day = {}
        for block in self.manual:
            self._manual_by_day.setdefault(block.start_utc.astimezone(self.zone).date(),[]).append(block)
        if seed:
            self.restore(seed)
        if not definition.tracks and definition.historical_mode not in {'original', 'replay'}:
            self.issue('empty', 'Add a media track and an airing window.', True)
        if definition.tracks and not definition.windows and not self.manual and definition.historical_mode not in {'original','replay'}:
            self.issue('no-windows','Add an airing window before applying this channel.',True)
        reachable = {w.track_id for w in definition.windows if w.scope.weekdays} | {a.track_id for a in definition.historical_airings if a.track_id}
        for _ in range(len(self.tracks)):
            expanded = reachable | {self.tracks[key].successor_id for key in reachable if key in self.tracks and self.tracks[key].successor_id}
            if expanded==reachable:
                break
            reachable = expanded
        if definition.required_tracks-reachable:
            self.issue('unassigned-required','Required tracks have no airing window or successor route: '+', '.join(sorted(definition.required_tracks-reachable)),True)
        if definition.historical_mode in {'original','replay'} and not definition.historical_airings:
            self.issue('empty-history','Import your original-airing records before using historical playback.',True)
        if definition.historical_mode == 'era':
            self.issue('era', 'Era recreation uses your rules and owned media; it is an approximation.')
        if any(a.accuracy == 'estimated' or not a.source for a in definition.historical_airings):
            self.issue('history-source', 'Some original airings are estimated or have no provenance.')

    def issue(self, key, message, blocked=False):
        self.issues[key] = {'message': message, 'blocking': blocked}
        self.blocked |= blocked

    def check_cancel(self):
        if self.cancel():
            raise PlannerCancelled('Forecast cancelled')

    def _order(self, track_id, pass_number):
        track = self.tracks[track_id]
        values = list(self.groups[track.group_id].asset_ids)
        if track.order == 'shuffle':
            values.sort(key=lambda asset: stable_id(self.channel, track_id, self.cycle_index, pass_number, asset))
        return values

    def snapshot(self):
        return {
            'cycle_start': self.cycle_start.isoformat(), 'cycle_index': self.cycle_index,
            'ready_at': self.ready_at.isoformat() if self.ready_at else None,
            'restart_at': self.restart_at.isoformat() if self.restart_at else None,
            'closed': self.closed, 'last_end': self.last_end.isoformat(),
            'next_day': self.next_day.isoformat(), 'active_pauses': sorted(self.active_pauses),
            'resume_at':self.resume_at.isoformat() if self.resume_at else None,
            'filler_index': self.filler_index,
            'cursors': {key: {'remaining': list(c.remaining), 'offset': c.offset,
                              'completed_at': c.completed_at.isoformat() if c.completed_at else None,
                              'pass_number': c.pass_number, 'skipped': sorted(c.skipped)}
                        for key, c in self.cursors.items()},
            'ads': self.ads.snapshot() if self.ads else None,
            'reporting_cycle':self.reporting_cycle,
            'first_starts':{key:value.isoformat() for key,value in self.first_starts.items()},
            'first_finishes':{key:value.isoformat() for key,value in self.first_finishes.items()},
            'content_seconds':dict(self.content_seconds),'occupied_seconds':dict(self.occupied_seconds),
        }

    def restore(self, seed):
        self.cycle_start = datetime.fromisoformat(seed['cycle_start'])
        self.cycle_index = seed['cycle_index']
        self.ready_at = datetime.fromisoformat(seed['ready_at']) if seed.get('ready_at') else None
        self.restart_at = datetime.fromisoformat(seed['restart_at']) if seed.get('restart_at') else None
        self.closed = seed['closed']
        self.last_end = datetime.fromisoformat(seed['last_end'])
        self.resume_at = datetime.fromisoformat(seed['resume_at']) if seed.get('resume_at') else None
        self.next_day = date.fromisoformat(seed['next_day'])
        self.active_pauses = set(seed['active_pauses'])
        self.filler_index = seed['filler_index']
        self.reporting_cycle = seed.get('reporting_cycle',self.cycle_index)
        self.first_starts = {key:datetime.fromisoformat(value) for key,value in seed.get('first_starts',{}).items()}
        self.first_finishes = {key:datetime.fromisoformat(value) for key,value in seed.get('first_finishes',{}).items()}
        self.content_seconds = dict(seed.get('content_seconds',{}))
        self.occupied_seconds = dict(seed.get('occupied_seconds',{}))
        for key, value in seed['cursors'].items():
            if key in self.cursors:
                self.cursors[key] = Cursor(list(value['remaining']), value['offset'],
                    datetime.fromisoformat(value['completed_at']) if value['completed_at'] else None,
                    value['pass_number'], set(value.get('skipped', [])))
        if self.ads and seed.get('ads'):
            self.ads.restore(seed['ads'])

    def _local(self, value, clock):
        return local_instant(value, clock, self.zone, fold=self.definition.dst_fold, gap=self.definition.dst_gap)

    def _pauses(self, value):
        return [p for p in self.definition.suspensions if p.scope.matches(self.scope_day(value))]

    def scope_day(self,value):
        """Optional era calendar mapped onto real broadcast days, never OS time."""
        if self.definition.historical_mode!='era' or self.definition.reference_year is None:
            return value
        anchor=self.definition.start_at.astimezone(self.zone).date()
        try:
            reference=anchor.replace(year=self.definition.reference_year)
        except ValueError:  # February 29 in a non-leap reference year.
            reference=date(self.definition.reference_year,2,28)
        return reference+(value-anchor)

    def _suspended(self, pauses, window=None, track_id=None, kind=None):
        track = self.tracks.get(track_id)
        return any(p.target == 'channel' or p.target == kind or
                   p.target == 'track' and p.target_id == track_id or
                   p.target == 'group' and track and p.target_id == track.group_id or
                   p.target == 'window' and window and p.target_id == window.id or
                   p.target == 'layer' and window and p.target_id == window.layer_id for p in pauses)

    def _resume(self, pauses):
        active = {p.id for p in pauses}
        for pause in self.definition.suspensions:
            if pause.id not in self.active_pauses - active or pause.resume == 'continue':
                continue
            targets = [t for t in self.definition.tracks if pause.target == 'channel' or
                       pause.target == 'track' and pause.target_id == t.id or
                       pause.target == 'group' and pause.target_id == t.group_id or
                       any(w.track_id == t.id and (pause.target == 'window' and pause.target_id == w.id or
                           pause.target == 'layer' and pause.target_id == w.layer_id) for w in self.definition.windows)]
            for track in targets:
                cursor = self.cursors[track.id]
                if pause.resume == 'restart':
                    cursor.remaining = self._order(track.id, cursor.pass_number)[track.start_index:]
                    cursor.offset = 0
                    cursor.skipped.clear()
                elif cursor.remaining:
                    cursor.skipped.add(cursor.remaining.pop(0))
                    cursor.offset = 0
                    self.issue('skipped:' + track.id, f'{track.id}: an explicitly skipped episode does not earn first-pass completion.')
        self.active_pauses = active

    def _intervals(self, value, pauses):
        result = []
        def precedence(scope, layer=False):
            if scope.from_date and scope.from_date==scope.until_date:
                return 3000
            if layer or scope.months or scope.years or scope.from_date or scope.until_date:
                return 2000
            return 1000 if set(scope.weekdays)!=set(range(7)) else 0
        scoped = self.scope_day(value)
        active_layers = {l.id for l in self.definition.layers if l.scope.matches(scoped) and not any(p.target=='layer' and p.target_id==l.id for p in pauses)}
        whole = max((precedence(self.layers[key].scope,True)+self.layers[key].priority for key in active_layers if self.layers[key].replace_scope == 'channel'), default=-1001)
        if self.definition.historical_mode not in {'original', 'replay'}:
            for w in self.definition.windows:
                if not w.scope.matches(scoped) or w.layer_id and w.layer_id not in active_layers:
                    continue
                priority = (precedence(self.layers[w.layer_id].scope,True)+self.layers[w.layer_id].priority) if w.layer_id else precedence(w.scope)+w.priority
                if w.protected:
                    priority = 10000
                if priority < whole or self._suspended(pauses, w, w.track_id):
                    continue
                start = self._local(value, w.start)
                last_day = value + timedelta(days=int(minute(w.end) <= minute(w.start)))
                end = self._local(last_day, w.end)
                if start is not None and end is not None and end > start:
                    result.append(Interval(start, end, w, track_id=w.track_id, identity=w.id,
                                           priority=priority, protected=w.protected))
        for raw in self._manual_by_day.get(value,()):
            start = raw.start_utc
            if start.astimezone(self.zone).date() != value:
                continue
            asset = self.assets.get(raw.asset_id)
            duration = asset.seconds if asset and asset.online else 0
            end = datetime.fromisoformat(raw.ad_plan['end_utc']) if raw.ad_plan else start + timedelta(seconds=duration)
            if duration <= 0:
                self.issue('manual:' + raw.asset_id, 'A protected manual block has missing media.', True)
            else:
                result.append(Interval(start, end, asset_id=raw.asset_id, identity='manual:' + start.isoformat(), priority=10000, protected=True,ad_snapshot=raw.ad_plan))
        if self.definition.historical_mode in {'original', 'replay'}:
            records = self.definition.historical_airings
            anchor = records[0].starts_at.astimezone(self.zone).date() if records else value
            if self._history_cache is None or self._history_cache[0]!=self.cycle_index:
                by_day = {}
                for n,record in enumerate(records):
                    if n%1000==0:
                        self.check_cancel()
                    when = record.starts_at
                    if self.definition.historical_mode=='replay' or self.cycle_index>0:
                        original = when.astimezone(self.zone)
                        base = self.cycle_start.astimezone(self.zone)
                        first = (base.date()+timedelta(days=int(any((base.hour,base.minute,base.second)))) if self.cycle_index>0 else self.definition.replay_start)
                        when = self._local(first+(original.date()-anchor),original.strftime('%H:%M'))
                    if when is not None:
                        by_day.setdefault(when.astimezone(self.zone).date(),[]).append(record)
                self._history_cache = (self.cycle_index,by_day)
            for record in self._history_cache[1].get(value,()):
                start = record.starts_at
                if self.definition.historical_mode == 'replay':
                    original = start.astimezone(self.zone)
                    replay_day = self.definition.replay_start + (original.date() - anchor)
                    start = self._local(replay_day, original.strftime('%H:%M'))
                    if start is None:
                        continue
                if self.cycle_index>0:
                    original = record.starts_at.astimezone(self.zone)
                    base = self.cycle_start.astimezone(self.zone)
                    first = base.date()+timedelta(days=int(base.hour!=0 or base.minute!=0 or base.second!=0))
                    start = self._local(first+(original.date()-anchor),original.strftime('%H:%M'))
                    if start is None:
                        continue
                if start.astimezone(self.zone).date() != value:
                    continue
                asset_id = record.substitute_id or record.asset_id
                asset = self.assets.get(asset_id)
                seconds = asset.seconds if asset and asset.online else 0
                if seconds <= 0:
                    self.issue('historical:' + record.id, f'Original airing {record.id} has missing media; choose an explicit substitute.', True)
                    continue
                end = start + timedelta(seconds=seconds)
                if record.ends_at and seconds > (record.ends_at - record.starts_at).total_seconds() + .001:
                    self.issue('historical-fit:' + record.id, f'Original airing {record.id} is shorter than the owned recording; resolve its duration.', True)
                hard_end = start+(record.ends_at-record.starts_at) if record.ends_at else None
                result.append(Interval(start, end, asset_id=asset_id, track_id=record.track_id,
                                       identity='original:' + record.id, rerun=record.rerun, priority=10000, protected=True,
                                       hard_end=hard_end,historical=True))
        result.sort(key=lambda item: (-item.priority, not item.protected, item.start, item.identity))
        accepted = []
        for item in result:
            pieces = [(item.start, item.end)]
            for previous in accepted:
                if previous.end <= item.start or previous.start >= item.end:
                    continue
                if previous.priority == item.priority:
                    self.issue('overlap:' + ':'.join(sorted((item.identity, previous.identity))),
                               f'Conflicting starts: {item.identity} and {previous.identity}. Choose a priority or move a window.', True)
                if item.protected and previous.protected:
                    self.issue('protected:' + item.identity, 'Protected blocks overlap; resolve the conflict explicitly.', True)
                clipped = []
                for a, b in pieces:
                    if b <= previous.start or a >= previous.end:
                        clipped.append((a, b))
                    else:
                        if a < previous.start:
                            clipped.append((a, previous.start))
                        if b > previous.end:
                            clipped.append((previous.end, b))
                pieces = clipped
            for a, b in pieces:
                accepted.append(replace(item,start=a,end=b))
        return sorted(accepted, key=lambda item: (item.start, item.identity))

    def _boundary(self, ready):
        rule = self.definition.cycle
        if rule.boundary == 'manual':
            release = self.manual_releases.get(self.cycle_index)
            return max(ready,release) if release else None
        if rule.boundary == 'safe':
            return ready
        value = ready.astimezone(self.zone).date()
        for _ in range(3661):
            candidate = self._local(value, rule.boundary_time)
            permitted = (rule.boundary == 'day' or
                rule.boundary == 'week' and value.weekday() == rule.boundary_weekday or
                rule.boundary == 'month' and value.day == 1 or
                rule.boundary == 'quarter' and value.day == 1 and value.month in (1, 4, 7, 10) or
                rule.boundary == 'year' and value.day == 1 and value.month == 1 or
                rule.boundary == 'period' and (value - self.cycle_start.astimezone(self.zone).date()).days % rule.period_days == 0)
            if permitted and candidate is not None and candidate >= ready:
                return candidate
            value += timedelta(days=1)
        self.issue('boundary', 'No restart boundary exists inside the ten-year calculation horizon.', True)
        return None

    def _gate(self, at):
        dates = sorted({c.completed_at for c in self.cursors.values() if c.completed_at and c.completed_at <= at})
        completion_at = next((value for value in dates if self.definition.completion_satisfied(
            {key for key, c in self.cursors.items() if c.completed_at and c.completed_at <= value})), None)
        media = completion_at is not None or self.definition.cycle.completion == 'none'
        after = self.definition.cycle.not_before
        if after and self.cycle_index>0 and after<=self.cycle_start:
            # An absolute forced date is a one-time override. Explicit periodic
            # boundaries repeat; a safe/OR rule subsequently waits for content.
            after = (self._boundary(self.cycle_start+timedelta(microseconds=1))
                     if self.definition.cycle.boundary not in {'safe','manual'} else None)
            if self.definition.cycle.completion=='none' and after is None:
                return
        date_ready = after is not None and at >= after
        ready = ((media or date_ready) if self.definition.cycle.gate_mode == 'or' else
                 (media and (after is None or date_ready)))
        if ready:
            candidates = [value for value in (completion_at, after) if value is not None]
            ready_at = (min(candidates) if self.definition.cycle.gate_mode == 'or' else max(candidates)) if candidates else at
            if self.ready_at is None:
                self.ready_at = ready_at
            if self.restart_at is None:
                self.restart_at = self._boundary(max(self.ready_at, self.last_end))

    def _advance_cycle(self, at, day_plan):
        if self._cutoff is not None and at>self._cutoff:
            return
        self._gate(at)
        if self.closed or self.restart_at is None or self.restart_at > at:
            return
        end = max(self.restart_at, self.last_end)
        if end > at:
            return
        day_plan.closed_cycles.append({'index': self.cycle_index, 'start': self.cycle_start.isoformat(),
            'end': end.isoformat(), 'ready_at': self.ready_at.isoformat(),
            'completed_tracks': sorted(key for key,c in self.cursors.items() if c.completed_at),
            'unfinished_tracks': sorted(self.definition.required_tracks - {key for key,c in self.cursors.items() if c.completed_at})})
        if self.definition.cycle.action == 'once':
            self.closed = True
            return
        reset = set(self.definition.cycle.restart_tracks) or set(self.cursors)
        self.cycle_index += 1
        self.cycle_start = end
        for key in reset:
            track = self.tracks[key]
            self.cursors[key] = Cursor(self._order(key, 0)[track.start_index:])
        self.ready_at = self.restart_at = None

    def _track_for(self, track_id):
        for _ in range(len(self.tracks) + 1):
            track, cursor = self.tracks[track_id], self.cursors[track_id]
            if cursor.remaining:
                return track, cursor
            if track.post_completion == 'successor':
                track_id = track.successor_id
                continue
            if track.mode == 'rerun' or track.post_completion in {'loop', 'rerun'}:
                cursor.pass_number += 1
                cursor.remaining = self._order(track_id, cursor.pass_number)
                cursor.offset = 0
                return track, cursor
            return track, None
        raise PlannerValidationError('successor track cycle')

    def _finish(self, track_id, asset_id, at, day_plan, *, rerun=False):
        cursor = self.cursors.get(track_id)
        if not cursor or rerun:
            return
        if asset_id in cursor.remaining:
            cursor.remaining.remove(asset_id)
        cursor.skipped.discard(asset_id)
        cursor.offset = 0
        if not cursor.remaining and cursor.completed_at is None and not cursor.skipped:
            cursor.completed_at = at
            day_plan.completions.append((self.cycle_index, track_id, at))
            self.first_finishes.setdefault(track_id, at)

    def _add(self, day_plan, asset_id, start, end, kind, track=None, window=None, offset=0,
             parent=None, parent_start=None, parent_end=None, break_id=None, finishes=False, first=False):
        if end <= start:
            return
        self.total_segments += 1
        if len(day_plan.segments) >= 10000:
            raise PlannerValidationError('A day exceeds 10000 segments. Increase brackets or reduce tiny filler clips.')
        day_plan.segments.append(Segment(stable_id(self.channel, self.revision, self.cycle_index,
            asset_id, start.isoformat(), kind, offset, window), asset_id, start, end, kind, track,
            window, self.cycle_index, offset, parent, parent_start, parent_end, break_id, finishes, first))

    def _gap(self, plan, start, end, pauses, *, finished=False):
        if end <= start:
            return
        if self._cutoff is not None and start>=self._cutoff:
            return
        if not self.closed:
            self._gate(end)
            boundary = self.restart_at
            if boundary is not None and start<=boundary<end and boundary>=self.last_end:
                self._gap(plan,start,boundary,pauses,finished=finished)
                if self._cutoff is None or boundary<=self._cutoff:
                    self._advance_cycle(boundary,plan)
                    self._gap(plan,boundary,end,pauses,finished=self.closed)
                return
        filler = [self.assets[key] for key in self.definition.filler_asset_ids if key in self.assets
                  and self.assets[key].online and self.assets[key].seconds > 0]
        use_filler = self.definition.cycle.after_once == 'filler' if finished else self.definition.gap_filler
        if use_filler and filler and not self._suspended(pauses, kind='filler'):
            while start < end:
                if self._cutoff is not None and start>=self._cutoff:
                    break
                self.check_cancel()
                item = filler[self.filler_index % len(filler)]
                finish = min(end, start + timedelta(seconds=item.seconds))
                self._add(plan, item.id, start, finish, 'filler')
                start = finish
                self.filler_index += 1
        else:
            self._add(plan, None, start, min(end,self._cutoff) if self._cutoff else end, 'offair')

    def _program(self, plan, asset, start, end, track, window, offset, complete, ad_plans=()):
        parent = ad_plans[0].occurrence_id if ad_plans else stable_id(self.channel, self.revision, self.cycle_index, track, window, asset.id, start, offset)
        content_cursor, source = start, offset
        first = bool(track and self.cursors[track].completed_at is None)
        program_finish = start + timedelta(seconds=asset.seconds-offset)
        for ad in ad_plans:
            if ad.scheduled_at > content_cursor:
                finish = min(ad.scheduled_at, start + timedelta(seconds=asset.seconds-offset) +
                             sum((timedelta(seconds=p.duration_seconds) for p in ad_plans if p.scheduled_at < ad.scheduled_at), timedelta()))
                self._add(plan, asset.id, content_cursor, finish, 'program', track, window, source,
                          parent, start, end, finishes=complete and source + (finish-content_cursor).total_seconds() >= asset.seconds-.001, first=first)
                source += (finish-content_cursor).total_seconds()
            for part in ad.segments:
                begins = ad.scheduled_at + timedelta(seconds=part.start_offset_seconds)
                self._add(plan, part.asset_id, begins, begins+timedelta(seconds=part.duration_seconds), part.event_type,
                          track, window, part.source_offset_seconds, parent, start, end, ad.plan_id)
            content_cursor = ad.scheduled_at + timedelta(seconds=ad.duration_seconds)
            program_finish = max(program_finish, ad.scheduled_at)
        remaining = min(asset.seconds-source, (end-content_cursor).total_seconds())
        if remaining > .0001:
            self._add(plan, asset.id, content_cursor, content_cursor+timedelta(seconds=remaining), 'program',
                      track, window, source, parent, start, end, finishes=complete, first=first)
            program_finish = content_cursor+timedelta(seconds=remaining)
        if track and self.cycle_index == self.reporting_cycle:
            self.first_starts.setdefault(track, start)
            self.content_seconds[track] = self.content_seconds.get(track, 0) + (asset.seconds-offset if complete else (end-start).total_seconds())
            self.occupied_seconds[track] = self.occupied_seconds.get(track, 0) + (end-start).total_seconds()
        if complete:
            self._finish(track, asset.id, program_finish, plan)
        self.last_end = max(self.last_end, end)
        plan.breaks.extend(ad_plans)

    def day(self, *, until=None):
        """Compile one local day. Caller decides whether anything actually aired."""
        self.check_cancel()
        self._cutoff = until
        value = self.next_day
        start = local_instant(value,'00:00',self.zone,gap='next_valid')
        end = local_instant(value+timedelta(days=1),'00:00',self.zone,gap='next_valid')
        self.next_day += timedelta(days=1)
        if start is None or end is None or end <= start:
            # A skipped civil date has no real broadcast time.
            return DayPlan(value, self.activation, self.activation)
        plan = DayPlan(value, start, end)
        pauses = self._pauses(value)
        self._resume(pauses)
        position = max(start, self.activation, self.last_end,self.resume_at or start)
        intervals = self._intervals(value, pauses)
        for index, interval in enumerate(intervals):
            self.check_cancel()
            begins, until = max(position, interval.start, self.activation), interval.end
            if interval.window:
                step = interval.window.bracket_minutes*60
                origin = self._local(value,interval.window.start)
                if origin:
                    begins = origin+timedelta(seconds=math.ceil(max(0,(begins-origin).total_seconds())/step-1e-9)*step)
            if until <= begins:
                continue
            self._gap(plan, position, begins, pauses, finished=self.closed)
            if self._cutoff is not None and begins>self._cutoff:
                plan.next_change = begins
                position = max(position,self._cutoff)
                break
            position = begins
            if interval.asset_id:
                if begins != interval.start:
                    self.issue('fixed:' + interval.identity, 'A fixed airing conflicts with a committed program.', True)
                    continue
                self._advance_cycle(begins, plan)
                if self.closed:
                    continue
                asset = self.assets[interval.asset_id]
                ads = ()
                if interval.ad_snapshot:
                    from ..simple_ads import snapshot_plans
                    ads = snapshot_plans(interval.ad_snapshot)
                elif interval.historical and self.ads and not self._suspended(pauses,kind='advertising'):
                    hard = min(interval.hard_end or end+timedelta(days=1),intervals[index+1].start if index+1<len(intervals) else end+timedelta(days=1))
                    before_ads = self.ads.snapshot()
                    try:
                        ads, until = self.ads.plan(asset.id,begins,stable_id(self.revision,self.cycle_index,interval.identity,begins),hard)
                    except ValueError:
                        self.ads.restore(before_ads)
                        self.issue('history-ads:'+interval.identity,'The original airing and complete configured ads cross the next fixed start.',True)
                        continue
                self._program(plan, asset, begins, until, interval.track_id, interval.identity, 0, not interval.rerun,ads)
                position = until
                self._gate(until)
                before_cycle = self.cycle_index
                self._advance_cycle(until,plan)
                if interval.historical and before_cycle!=self.cycle_index:
                    break
                continue
            w = interval.window
            next_start = intervals[index+1].start if index+1 < len(intervals) else end + timedelta(days=1)
            while position < until:
                if self._cutoff is not None and position>self._cutoff:
                    plan.next_change = position
                    break
                self.check_cancel()
                self._advance_cycle(position, plan)
                if self.closed:
                    break
                track, cursor = self._track_for(w.track_id)
                if cursor is None or self._suspended(pauses, w, track.id):
                    break
                asset_id = cursor.remaining[0]
                asset = self.assets.get(asset_id)
                if not asset or not asset.online or not math.isfinite(asset.seconds) or asset.seconds <= 0:
                    self.issue('missing:' + asset_id, f'{self.groups[track.group_id].name}: {asset_id} is missing, offline or has no duration. Its progression is held.', True)
                    break
                bracket_end = min(position+timedelta(minutes=w.bracket_minutes), until)
                hard_end = min(until + timedelta(minutes=w.max_overrun_minutes), next_start,
                               bracket_end+timedelta(minutes=w.max_overrun_minutes))
                limit = hard_end if w.fit == 'overrun' else bracket_end
                before_ads = self.ads.snapshot() if self.ads else None

                def attempt(candidate, source_offset):
                    plans = ()
                    finish = position+timedelta(seconds=candidate.seconds-source_offset)
                    if self.ads and not self._suspended(pauses, kind='advertising'):
                        try:
                            plans, finish = self.ads.plan(candidate.id, position,
                                stable_id(self.revision, self.cycle_index, track.id, position, candidate.id), limit,source_offset=source_offset)
                        except ValueError:
                            return (), limit+timedelta(seconds=1)
                    return plans, finish

                plans, finish = attempt(asset, cursor.offset)
                if finish > limit + timedelta(microseconds=100):
                    if self.ads:
                        self.ads.restore(before_ads)
                    if w.fit == 'next_fit' and cursor.offset == 0:
                        found = False
                        for candidate_id in cursor.remaining[1:]:
                            candidate = self.assets.get(candidate_id)
                            if not candidate or not candidate.online or candidate.seconds <= 0:
                                continue
                            plans, finish = attempt(candidate, 0)
                            if finish <= limit:
                                asset, asset_id, found = candidate, candidate_id, True
                                break
                            if self.ads:
                                self.ads.restore(before_ads)
                        if not found:
                            break
                    elif w.fit == 'carryover':
                        if cursor.offset == 0 and asset_id != cursor.remaining[0]:
                            raise PlannerValidationError('carryover cursor mismatch')
                        partial_end, partial_plans = bracket_end, ()
                        prefix = (bracket_end-position).total_seconds()
                        if self.ads and not self._suspended(pauses,kind='advertising'):
                            try:
                                partial_plans,partial_end,prefix = self.ads.plan_partial(asset.id,position,
                                    stable_id(self.revision,self.cycle_index,track.id,position,asset.id,'carry'),bracket_end,cursor.offset)
                            except ValueError as exc:
                                self.issue('carry-ads:'+w.id,str(exc),True)
                                break
                        self._program(plan, asset, position, partial_end, track.id, w.id, cursor.offset, False,partial_plans)
                        cursor.offset += prefix
                        self._gap(plan,partial_end,bracket_end,pauses,finished=self.closed)
                        position = bracket_end
                        continue
                    else:
                        self.issue('fit:' + w.id + ':' + asset_id,
                                   f'{w.id}: the next complete program and ads do not fit. Move it to a larger bracket or explicitly choose another fitting policy.')
                        break
                self._program(plan, asset, position, finish, track.id, w.id, cursor.offset, True, plans)
                self._gate(finish)
                # A cycle becomes ready only after the committed complete break.
                self._advance_cycle(finish, plan)
                next_position = max(finish, bracket_end)
                if origin:
                    next_position = origin+timedelta(seconds=math.ceil((next_position-origin).total_seconds()/step-1e-9)*step)
                self._gap(plan, finish, next_position, pauses, finished=self.closed)
                position = next_position
            self._gap(plan, position, max(position, until), pauses, finished=self.closed)
            position = max(position, until)
        last = min(end,self._cutoff) if self._cutoff else end
        self._gap(plan, position, last, pauses, finished=self.closed)
        self._advance_cycle(last, plan)
        if self._cutoff is not None and self._cutoff<end:
            self.next_day = value
            self.resume_at = max(self._cutoff,self.last_end,max((s.ends_at for s in plan.segments),default=self._cutoff))
        else:
            self.resume_at = None
        plan.segments.sort(key=lambda s: (s.starts_at, s.id))
        return plan


def forecast(definition, assets, *, channel=1, ads=None, manual=(), cancel=None, activation=None, seed=None,manual_releases=None,
             view_start=None, view_days=7, max_days=3660, max_seconds=5, max_segments=250000,max_view_segments=3000):
    compiler = Compiler(definition, assets, channel=channel, ads=ads, manual=manual, cancel=cancel,activation=activation,seed=seed,manual_releases=manual_releases)
    view_start = view_start or definition.start_at.astimezone(compiler.zone).date()
    view_until = view_start + timedelta(days=min(31, max(1, view_days)))
    rows, cycles, calendar = [], [], {}
    truncated = False
    started = time.monotonic()
    complete = False
    last_day = None
    for _ in range(max_days):
        plan = compiler.day()
        last_day = plan.day
        if view_start <= plan.day < view_until:
            calendar[plan.day.isoformat()] = {'programs':len({s.parent_id or s.id for s in plan.segments if s.kind=='program'}),
                'ads':sum(s.kind=='advertisement' for s in plan.segments),'filler':sum(s.kind=='filler' for s in plan.segments)}
            if view_days<=7:
                room = max_view_segments-len(rows)
                rows.extend({**s.to_mapping(),'display_start':s.starts_at.astimezone(compiler.zone).strftime('%Y-%m-%d %H:%M'),'local_day':s.starts_at.astimezone(compiler.zone).date().isoformat()} for s in plan.segments[:room])
                truncated |= len(plan.segments)>room
        cycles.extend(plan.closed_cycles)
        if (cycles or compiler.closed) and plan.day >= view_until - timedelta(days=1):
            complete = True
            break
        if time.monotonic()-started > max_seconds or compiler.total_segments > max_segments:
            break
    if not complete:
        compiler.issue('horizon', 'The calculation reached its bounded horizon. Unresolved milestones are estimated or blocked; extend the rules or calculation range.')
    if truncated:
        compiler.issue('view-limit','This view exceeds 3000 segments. Narrow the visible dates; calendar totals and milestones still use the complete calculation.')
    required_done = definition.required_tracks <= set(compiler.first_finishes)
    tracks = []
    for track in definition.tracks:
        group = compiler.groups[track.group_id]
        members = [compiler.assets.get(key) for key in group.asset_ids]
        tracks.append({'id':track.id,'name':group.name,'count':len(group.asset_ids),
            'actual_hours':sum(item.seconds for item in members if item and item.seconds > 0)/3600,
            'first_airing':compiler.first_starts.get(track.id).isoformat() if track.id in compiler.first_starts else None,
            'last_airing':compiler.first_finishes.get(track.id).isoformat() if track.id in compiler.first_finishes else None,
            'occupied_hours':compiler.occupied_seconds.get(track.id,0)/3600,
            'elapsed_days':((compiler.first_finishes[track.id]-compiler.first_starts[track.id]).total_seconds()/86400
                            if track.id in compiler.first_finishes and track.id in compiler.first_starts else None),
            'missing':sum(not item or not item.online or item.seconds <= 0 for item in members),
            'required':track.id in definition.required_tracks,'post_completion':track.post_completion})
    ready = cycles[0]['ready_at'] if cycles else compiler.ready_at.isoformat() if compiler.ready_at else None
    restart = cycles[0]['end'] if cycles else compiler.restart_at.isoformat() if compiler.restart_at else None
    media_end = max(compiler.first_finishes.values()).isoformat() if required_done and compiler.first_finishes else None
    estimated = definition.historical_mode == 'era' or any(a.accuracy == 'estimated' or not a.source for a in definition.historical_airings)
    confidence = 'Blocked' if compiler.blocked else 'Exact' if complete and not estimated else 'Estimated'
    return {'revision':definition.revision,'confidence':confidence,'tracks':tracks,'segments':rows,
        'calendar_days':calendar,'view_truncated':truncated,
        'effective_start':compiler.activation.isoformat(),
        'calendar_clock':'reference year' if definition.historical_mode=='era' and definition.reference_year else 'actual dates',
        'media_ends':media_end,'cycle_ready':ready,'actual_restart':restart,
        'cycle_state':'BLOCKED' if compiler.blocked else 'CLOSED' if compiler.closed else
            'READY_WAITING_FOR_BOUNDARY' if compiler.ready_at else
            'READY_WAITING_FOR_DATE' if required_done else 'WAITING_FOR_REQUIRED_TRACKS',
        'cycles':cycles[:10],'issues':list(compiler.issues.values()),
        'calculated_through':last_day.isoformat() if last_day else None,'bounded':not complete}
