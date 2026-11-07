"""Canonical planner ledger and lazy adapter for ChannelRuntime.

Only reconcile(actual_broadcast_time) records earned history. Calendar/Guide
projection and editor forecasts use the same compiler without calling it.
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..library import IndexedMedia, MediaAsset, MediaLocation
from ..models import ChannelDefinition
from ..portable import path_tree
from .advertising import AdPlanner
from .contracts import PlannerDefinition, PlannerValidationError
from .engine import Asset, Compiler, Segment, stable_id
from .timezones import get_zone, local_instant

TABLES = ('planner_revisions', 'planner_checkpoints', 'planner_occurrences', 'planner_completions', 'planner_cycles', 'planner_legacy', 'planner_manual_releases','planner_failures')


def initialize(connection):
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS planner_revisions(
            channel_number INTEGER NOT NULL, revision TEXT NOT NULL, applied_at TEXT NOT NULL,
            activation_at TEXT, status TEXT NOT NULL, payload TEXT NOT NULL, seed TEXT,
            PRIMARY KEY(channel_number,revision));
        CREATE INDEX IF NOT EXISTS idx_planner_revision_active ON planner_revisions(channel_number,status,activation_at);
        CREATE TABLE IF NOT EXISTS planner_checkpoints(
            channel_number INTEGER NOT NULL, revision TEXT NOT NULL, next_day TEXT NOT NULL,
            through_utc TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(channel_number,revision));
        CREATE TABLE IF NOT EXISTS planner_occurrences(
            channel_number INTEGER NOT NULL, revision TEXT NOT NULL, occurrence_id TEXT NOT NULL,
            starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(channel_number,occurrence_id));
        CREATE INDEX IF NOT EXISTS idx_planner_occurrence_time ON planner_occurrences(channel_number,starts_at,ends_at);
        CREATE INDEX IF NOT EXISTS idx_planner_occurrence_end ON planner_occurrences(channel_number,ends_at);
        CREATE TABLE IF NOT EXISTS planner_completions(
            channel_number INTEGER NOT NULL, revision TEXT NOT NULL, cycle_index INTEGER NOT NULL,
            track_id TEXT NOT NULL, completed_at TEXT NOT NULL, PRIMARY KEY(channel_number,revision,cycle_index,track_id));
        CREATE TABLE IF NOT EXISTS planner_cycles(
            channel_number INTEGER NOT NULL, revision TEXT NOT NULL, cycle_index INTEGER NOT NULL,
            closed_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(channel_number,revision,cycle_index));
        CREATE TABLE IF NOT EXISTS planner_legacy(
            channel_number INTEGER PRIMARY KEY, activation_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS planner_manual_releases(
            channel_number INTEGER NOT NULL, revision TEXT NOT NULL, cycle_index INTEGER NOT NULL,
            released_at TEXT NOT NULL, PRIMARY KEY(channel_number,revision,cycle_index));
        CREATE TABLE IF NOT EXISTS planner_failures(
            channel_number INTEGER NOT NULL, revision TEXT NOT NULL, parent_id TEXT NOT NULL,
            observed_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(channel_number,revision,parent_id));
    ''')


def assets_for(media):
    return tuple(Asset(item.asset.asset_id,float(item.asset.duration_seconds or 0),
                       item.location.path.stem,item.location.online) for item in media)


def _neutral_ad_settings(settings):
    from ..models import advertising_to_mapping
    def neutral(value):
        if isinstance(value,dict):
            return {key:([{'root':i} for i,_ in enumerate(item)] if key=='sources' else neutral(item)) for key,item in value.items()}
        if isinstance(value,list):
            return [neutral(item) for item in value]
        return value
    return neutral(advertising_to_mapping(settings))


def planner_ad_signature(channel):
    return stable_id(json.dumps(_neutral_ad_settings(channel.definition.advertising),sort_keys=True),
                     sorted(item.asset.asset_id for item in channel.ad_media))


def revision_key(channel):
    from ..broadcaster import _calendar_block_mapping
    manual=path_tree([_calendar_block_mapping(block) for block in channel.definition.programming.calendar],
                     lambda _: '<canonical-asset-location>')
    return stable_id(channel.definition.programming.planner.revision,
        json.dumps(_neutral_ad_settings(channel.definition.advertising),sort_keys=True),json.dumps(manual,sort_keys=True))


def effective_revision(connection, number, at):
    return connection.execute("SELECT * FROM planner_revisions WHERE channel_number=? AND activation_at<=? AND status!='superseded' ORDER BY activation_at DESC,applied_at DESC LIMIT 1",
                              (number,at.isoformat())).fetchone()


def latest_intent_revision(connection, number, intent):
    return connection.execute("SELECT * FROM planner_revisions WHERE channel_number=? AND (revision=? OR revision LIKE ?) ORDER BY applied_at DESC LIMIT 1",
                              (number,intent,intent+'.%')).fetchone()


def _slate():
    path = Path('Off air')
    return IndexedMedia(MediaAsset('planner:offair','',0,86400,'virtual'),
                        MediaLocation(path,str(path),'planner:offair',Path('.'),True))


def legacy_safe_start(definition,library,store,now, *, verify_files=True):
    from ..resolve import resolve_channel
    from ..runtime import ChannelRuntime
    resolved=resolve_channel(definition,library,allow_offline_ads=True,
        include_offline_programs=True,verify_ad_files=verify_files)
    if not resolved.media:
        return now
    old=ChannelRuntime.open(resolved,store,now=now,transient=True)
    try:
        selection=old.project_at(now)
        if selection.event.event_type not in {'program','advertisement','transition'}:
            return now
        safe=max(now,selection.parent_program_ends_at or selection.program_ends_at)
        for plan in old.break_plans_for_event(selection,at=now):
            end=plan.scheduled_at+timedelta(seconds=plan.duration_seconds)
            if plan.scheduled_at<=now<end:
                safe=max(safe,end)
        return safe
    finally:
        if old.break_store:
            old.break_store.close()


class PlannerTimeline:
    def __init__(self, channel, store, *, now, transient=False, revision=None):
        from ..runtime import ScheduledProgram
        self.channel = channel
        self.store = store
        self.number = channel.definition.channel
        self.rules = channel.definition.programming.planner
        self.intent_revision = revision_key(channel)
        self.revision = revision or self.intent_revision
        self.break_store = None
        self.media = {m.asset.asset_id:m for m in (*channel.media,*channel.ad_media)}
        # Archive metadata remains useful for Guide/history, while excluded
        # locations stay unavailable to the compiler. No filesystem probing.
        requested = {key for group in self.rules.groups for key in group.asset_ids} | set(self.rules.filler_asset_ids)
        requested.update(b.asset_id for b in channel.definition.programming.calendar)
        if channel.library and requested-self.media.keys():
            for item in channel.library.list_cached_media():
                if item.asset.asset_id in requested and item.asset.asset_id not in self.media:
                    self.media[item.asset.asset_id] = replace(item,location=replace(item.location,online=False))
        self.slate = _slate()
        self.programs = tuple(ScheduledProgram(item,index,float(item.asset.duration_seconds or 1)) for index,item in enumerate(channel.media))
        self.cycle_duration_seconds = sum(p.duration_seconds for p in self.programs) or 1
        self._days = OrderedDict()
        self._plans = OrderedDict()
        self._revision_cache = OrderedDict()
        self._legacy = None
        self._legacy_checked = False
        self._last_reconciled = None
        self._next_reconcile = None
        self.actual_source_roots = self._source_roots(channel.definition)
        self.activation = self.rules.start_at
        self.initial_seed = None
        if not transient:
            self._register(now)
        else:
            with store.connect() as connection:
                row = (connection.execute('SELECT * FROM planner_revisions WHERE channel_number=? AND revision=?',
                                          (self.number,revision)).fetchone() if revision else
                       latest_intent_revision(connection,self.number,self.intent_revision))
            if row and row['activation_at']:
                self.revision = row['revision']
                self.activation = datetime.fromisoformat(row['activation_at'])
                self.initial_seed = json.loads(row['seed']) if row['seed'] else None

    def _payload(self, definition):
        from ..broadcaster import channel_to_mapping
        raw = channel_to_mapping(definition)
        portable=self.store.portable or getattr(self.store,'_snapshot_portable',None)
        return path_tree(raw,portable.encode) if portable else raw

    def _decode(self, payload):
        raw = json.loads(payload)
        portable=self.store.portable or getattr(self.store,'_snapshot_portable',None)
        if portable:
            raw = path_tree(raw,portable.decode)
        return ChannelDefinition.from_mapping(raw)

    @staticmethod
    def _source_roots(definition):
        policies=(definition.advertising,)+tuple(p.policy for p in definition.advertising.placements)
        return frozenset(source.path for source in definition.sources)|frozenset(source.path for p in policies for source in p.sources)

    def _resolved_for_revision(self,definition):
        if self.channel.library is None:
            return replace(self.channel,definition=definition)
        from ..resolve import resolve_channel,MediaResolutionIndex
        index=MediaResolutionIndex(self.channel.library)
        resolved=resolve_channel(definition,self.channel.library,allow_offline_ads=True,index=index,verify_ad_files=False)
        if not getattr(self.store,'_read_only',False):
            from ..media_resilience import _transient_available_media
            resolved=replace(resolved,media=_transient_available_media(resolved,self.channel.library,index=index))
        return resolved

    def _register(self, now):
        with self.store.connect() as connection:
            existing = latest_intent_revision(connection,self.number,self.intent_revision)
            active = effective_revision(connection,self.number,now)
        if existing and (existing['status'] in {'active','pending'} or active and active['revision']==existing['revision']):
            self.revision = existing['revision']
            if existing['activation_at']:
                self.activation = datetime.fromisoformat(existing['activation_at'])
                self.initial_seed = json.loads(existing['seed']) if existing['seed'] else None
            with self.store.connect() as connection:
                self._supersede_unstarted(connection,now)
            return
        if existing:
            self.revision = self.intent_revision+'.'+stable_id(now.isoformat(),existing['revision'])[:16]
        activation = self.rules.start_at
        seed = None
        status = 'active'
        if active is None:
            with self.store.connect() as connection:
                legacy = connection.execute('SELECT payload FROM planner_legacy WHERE channel_number=?',(self.number,)).fetchone()
            if legacy and self.channel.library:
                activation=max(activation,legacy_safe_start(self._decode(legacy['payload']),self.channel.library,self.store,now))
        if active:
            old_definition = self._decode(active['payload'])
            previous = PlannerTimeline(self._resolved_for_revision(old_definition),self.store,now=now,transient=True,revision=active['revision'])
            self._revision_cache[previous.revision]=previous
            selection = previous.selection_at(previous.activation,now)
            safe = max(now, selection.parent_program_ends_at or selection.program_ends_at)
            if self.rules.edit_effect == 'next_cycle':
                # Find the first canonical closure after the edit. An unready
                # or manual-gated cycle keeps the revision pending, visibly.
                activation = previous.next_cycle_after(now)
                status = 'pending'
                if activation:
                    seed = previous.migration_seed(self.rules,activation,reset=True)
            else:
                activation = safe
                seed = previous.migration_seed(self.rules,activation)
                status = 'pending' if activation > now else 'active'
        if activation is not None:
            self.activation = activation
            if activation>now:
                status='pending'
        self.initial_seed = seed
        with self.store.connect() as connection:
            self._supersede_unstarted(connection,now)
            connection.execute('INSERT INTO planner_revisions VALUES(?,?,?,?,?,?,?)',
                (self.number,self.revision,now.isoformat(),activation.isoformat() if activation else None,status,
                 json.dumps(self._payload(self.channel.definition)), json.dumps(seed) if seed else None))

    def _supersede_unstarted(self,connection,now):
        connection.execute("UPDATE planner_revisions SET status='superseded' WHERE channel_number=? AND revision!=? AND status IN ('active','pending') AND (activation_at IS NULL OR activation_at>?)",
                           (self.number,self.revision,now.isoformat()))

    def _new_compiler(self, *, seed=None):
        ads = AdPlanner(tuple(self.media.values()),self.channel.ad_media,self.channel.definition.advertising,
                        planner_ad_signature(self.channel),self.number) if self.channel.definition.advertising.enabled else None
        with self.store.connect() as connection:
            releases = {row[0]:datetime.fromisoformat(row[1]) for row in connection.execute('SELECT cycle_index,released_at FROM planner_manual_releases WHERE channel_number=? AND revision=?',(self.number,self.revision))}
        return Compiler(self.rules,assets_for(tuple(self.media.values())),channel=self.number,ads=ads,manual_releases=releases,
                        manual=self.channel.definition.programming.calendar,activation=self.activation,
                        seed=seed or self.initial_seed)

    def _checkpoint(self, before):
        with self.store.connect() as connection:
            row = connection.execute('SELECT * FROM planner_checkpoints WHERE channel_number=? AND revision=? AND through_utc<=?',
                (self.number,self.revision,before.isoformat())).fetchone()
        return json.loads(row['payload']) if row else None

    def _remember(self, plan):
        self._days[plan.day] = plan
        self._days.move_to_end(plan.day)
        while len(self._days)>32:
            self._days.popitem(last=False)
        groups = {}
        for ad in plan.breaks:
            groups.setdefault(ad.occurrence_id,[]).append(ad)
        self._plans.update({key:tuple(values) for key,values in groups.items()})
        while len(self._plans)>10000:
            self._plans.popitem(last=False)

    def bind_break_store(self,store):
        self.break_store=store
        if self._legacy is not None:
            self._legacy=replace(self._legacy,break_store=store)
            if hasattr(self._legacy.timeline,'break_store'):
                self._legacy.timeline.break_store=store
        for previous in self._revision_cache.values():
            previous.bind_break_store(store)

    def _legacy_runtime(self, at):
        if self._legacy_checked:
            return self._legacy
        self._legacy_checked=True
        with self.store.connect() as connection:
            row=connection.execute('SELECT payload FROM planner_legacy WHERE channel_number=?',(self.number,)).fetchone()
        if row and self.channel.library:
            from ..resolve import resolve_channel
            from ..runtime import ChannelRuntime
            old=resolve_channel(self._decode(row['payload']),self.channel.library,
                allow_offline_ads=True,include_offline_programs=True,verify_ad_files=False)
            if not old.media:
                return None
            if not getattr(self.store,'_read_only',False):
                from ..media_resilience import _transient_available_media
                available={item.asset.asset_id for item in _transient_available_media(old,self.channel.library)}
                old=replace(old,media=tuple(item if item.asset.asset_id in available else
                    replace(item,location=replace(item.location,online=False)) for item in old.media))
            self._legacy=ChannelRuntime.open(old,self.store,now=at,transient=True)
            if self._legacy.break_store:
                self._legacy.break_store.close()
            self.bind_break_store(self.break_store)
        return self._legacy

    def plans_for_selection(self,selection):
        identity=selection.program_occurrence_id
        if identity in self._plans:
            return self._plans[identity]
        for previous in self._revision_cache.values():
            plans=previous.plans_for_selection(selection)
            if plans:
                return plans
        return ()

    def _day_at(self, at):
        day = at.astimezone(get_zone(self.rules.timezone)).date()
        if day in self._days and any(s.starts_at<=at<s.ends_at for s in self._days[day].segments):
            return self._days[day]
        compiler = self._new_compiler(seed=self._checkpoint(at))
        # A projection is bounded and detached; no future decisions are stored.
        for _ in range(36601):
            plan = compiler.day()
            if plan.day >= day or plan.end > at:
                self._remember(plan)
                return plan
        raise PlannerValidationError('Broadcast Planner requires a checkpoint for this date; the 100-year projection limit was reached.')

    def _revision_at(self, at):
        with self.store.connect() as connection:
            row = effective_revision(connection,self.number,at)
        if row and row['revision'] != self.revision:
            if row['revision'] in self._revision_cache:
                return self._revision_cache[row['revision']]
            definition = self._decode(row['payload'])
            previous = PlannerTimeline(self._resolved_for_revision(definition),self.store,now=at,transient=True,revision=row['revision'])
            previous.bind_break_store(self.break_store)
            self._revision_cache[row['revision']] = previous
            while len(self._revision_cache)>4:
                self._revision_cache.popitem(last=False)
            return previous
        return None

    def selection_at(self, epoch, at):
        from ..runtime import BroadcastSelection, ScheduledProgram
        # Past materialized occurrences survive subsequent rule edits.
        with self.store.connect() as connection:
            row = connection.execute('SELECT revision,payload FROM planner_occurrences WHERE channel_number=? AND starts_at<=? AND ends_at>? ORDER BY starts_at DESC LIMIT 1',
                (self.number,at.isoformat(),at.isoformat())).fetchone()
        if row and row['revision']!=self.revision:
            owner=self._revision_at(at)
            if owner:
                return owner.selection_at(owner.activation,at)
        segment = Segment.from_mapping(json.loads(row['payload'])) if row else None
        if segment is None:
            previous = self._revision_at(at)
            if previous is not None:
                return previous.selection_at(previous.activation,at)
            if at < self.activation:
                legacy=self._legacy_runtime(at)
                if legacy:
                    selected=legacy.project_at(at)
                    if selected.media.location.online:
                        return selected
                    begins=selected.segment_started_at or selected.program_started_at
                    ends=selected.segment_ends_at or selected.program_ends_at
                    return BroadcastSelection(ScheduledProgram(self.slate,0,(ends-begins).total_seconds()),
                        (at-begins).total_seconds(),begins,ends,selected.cycle_index,origin='offair')
                begins = at.replace(hour=0,minute=0,second=0,microsecond=0)
                segment = Segment(stable_id('before',at.date()),None,begins,min(self.activation,begins+timedelta(days=1)),'offair',None,None,0)
            else:
                plan = self._day_at(at)
                # An overnight program belongs to the previous local day's plan.
                segment = next((s for s in plan.segments if s.starts_at<=at<s.ends_at),None)
                if segment is None:
                    previous_day = self._day_at(at-timedelta(days=1))
                    segment = next((s for s in previous_day.segments if s.starts_at<=at<s.ends_at),None)
                if segment is None:
                    segment = Segment(stable_id('gap',at),None,at,at+timedelta(minutes=1),'offair',None,None,0)
        item = self.media.get(segment.asset_id,self.slate)
        kind = segment.kind if segment.asset_id is None or item is not self.slate else 'offair'
        parent_asset = None
        if segment.parent_id and kind != 'program':
            for plan in self._days.values():
                match = next((s for s in plan.segments if s.parent_id==segment.parent_id and s.kind=='program'),None)
                if match:
                    parent_asset = match.asset_id
                    break
            if not parent_asset:
                with self.store.connect() as connection:
                    rows = connection.execute("SELECT payload FROM planner_occurrences WHERE channel_number=? AND kind='program' AND starts_at>=? AND starts_at<=?",(self.number,(segment.parent_start or segment.starts_at).isoformat(),segment.starts_at.isoformat()))
                    match = next((json.loads(row[0]) for row in rows if json.loads(row[0]).get('parent_id')==segment.parent_id),None)
                parent_asset = match['asset_id'] if match else None
        starts = segment.parent_start if kind=='program' else segment.starts_at
        ends = segment.parent_end if kind=='program' else segment.ends_at
        return BroadcastSelection(ScheduledProgram(item,0,float(item.asset.duration_seconds or 1)),
            segment.source_offset+(at-segment.starts_at).total_seconds(),starts,ends,segment.cycle,
            origin=kind, parent_program_id=stable_id('program',parent_asset,segment.parent_id,'') if parent_asset else None,
            parent_program_asset_id=parent_asset, parent_program_started_at=segment.parent_start,
            parent_program_ends_at=segment.parent_end,program_occurrence_id=segment.parent_id,
            break_id=segment.break_id, break_occurrence_id=segment.break_id,
            segment_started_at=segment.starts_at,segment_ends_at=segment.ends_at,
            segment_source_offset_seconds=segment.source_offset)

    def reconcile(self, now, *, follow_revisions=True, stop_at=None):
        crossed_activation = self._last_reconciled is not None and self._last_reconciled<self.activation<=now
        if self._next_reconcile and self._last_reconciled and self._last_reconciled<=now<self._next_reconcile and not crossed_activation:
            return
        # Coalesce status polls only while no segment/revision boundary is due.
        # A short ad or transition must still earn its completion immediately.
        if self._last_reconciled and now < self._last_reconciled+timedelta(seconds=1) and not crossed_activation and (
            self._next_reconcile is None or now<self._next_reconcile
        ):
            return
        previous = self._revision_at(now) if follow_revisions else None
        if previous:
            self.actual_source_roots = previous._source_roots(previous.channel.definition)
            previous.bind_break_store(self.break_store)
            previous.observe_unavailable(now)
            previous.reconcile(now)
            self._next_reconcile = previous._next_reconcile
            self._last_reconciled = now
            return
        if now<self.activation:
            legacy=self._legacy_runtime(now)
            if legacy:
                self.actual_source_roots=self._source_roots(legacy.channel.definition)
                legacy.broadcast_at(now)
            self._last_reconciled=now
            return
        self.actual_source_roots = self._source_roots(self.channel.definition)
        if follow_revisions:
            with self.store.connect() as connection:
                old = effective_revision(connection,self.number,self.activation-timedelta(microseconds=1))
            if old and self.activation<=now:
                old_timeline = PlannerTimeline(self._resolved_for_revision(self._decode(old['payload'])),self.store,now=now,transient=True,revision=old['revision'])
                old_timeline.bind_break_store(self.break_store)
                old_timeline.reconcile(self.activation,follow_revisions=False,stop_at=self.activation)
        compiler = self._new_compiler(seed=self._checkpoint(now))
        for _ in range(36601):
            matured = [(compiler.cycle_index,key,c.completed_at) for key,c in compiler.cursors.items() if c.completed_at and c.completed_at<=now]
            plan = compiler.day(until=now)
            plan.completions.extend(matured)
            if plan.start > now:
                break
            self._remember(plan)
            committed = [s for s in plan.segments if s.starts_at<=now or s.parent_start and s.parent_start<=now]
            if stop_at:
                committed=[s for s in committed if s.starts_at<stop_at]
            committed = [replace(s,ends_at=min(s.ends_at,now)) if s.kind=='offair' else s for s in committed]
            committed = [s for s in committed if s.ends_at>s.starts_at]
            with self.store.connect() as connection:
                # Idle intervals extend only through actual observed time.
                # Merge adjacent pieces so a long off-air period remains one
                # history row rather than one row per status poll.
                for s in tuple(s for s in committed if s.kind=='offair'):
                    old_idle = connection.execute("SELECT occurrence_id,payload FROM planner_occurrences WHERE channel_number=? AND revision=? AND kind='offair' AND ends_at=? ORDER BY starts_at DESC LIMIT 1",(self.number,self.revision,s.starts_at.isoformat())).fetchone()
                    if old_idle:
                        previous_idle = Segment.from_mapping(json.loads(old_idle['payload']))
                        if previous_idle.cycle==s.cycle:
                            connection.execute('UPDATE planner_occurrences SET ends_at=?,payload=? WHERE channel_number=? AND occurrence_id=?',
                                (s.ends_at.isoformat(),json.dumps(replace(previous_idle,ends_at=s.ends_at).to_mapping()),self.number,old_idle['occurrence_id']))
                            committed.remove(s)
                connection.executemany('INSERT INTO planner_occurrences VALUES(?,?,?,?,?,?,?) ON CONFLICT(channel_number,occurrence_id) DO UPDATE SET ends_at=excluded.ends_at,payload=excluded.payload WHERE planner_occurrences.kind=\'offair\' AND planner_occurrences.ends_at<excluded.ends_at',
                    [(self.number,self.revision,s.id,s.starts_at.isoformat(),s.ends_at.isoformat(),s.kind,json.dumps(s.to_mapping())) for s in committed])
                connection.executemany('INSERT OR IGNORE INTO planner_completions VALUES(?,?,?,?,?)',
                    [(self.number,self.revision,cycle,track,at.isoformat()) for cycle,track,at in plan.completions if at<=now])
                connection.executemany('INSERT OR IGNORE INTO planner_cycles VALUES(?,?,?,?,?)',
                    [(self.number,self.revision,c['index'],c['end'],json.dumps(c)) for c in plan.closed_cycles if datetime.fromisoformat(c['end'])<=now])
                connection.execute('INSERT OR REPLACE INTO planner_checkpoints VALUES(?,?,?,?,?)',
                    (self.number,self.revision,compiler.next_day.isoformat(),min(now,max(plan.end,compiler.last_end)).isoformat(),json.dumps(compiler.snapshot())))
                connection.execute("UPDATE planner_revisions SET status='retired' WHERE channel_number=? AND status='active' AND revision!=?",(self.number,self.revision))
                connection.execute("UPDATE planner_revisions SET status='active' WHERE channel_number=? AND revision=? AND activation_at<=?",(self.number,self.revision,now.isoformat()))
            if self.break_store:
                for ad in plan.breaks:
                    if stop_at and ad.scheduled_at>=stop_at:
                        continue
                    if ad.scheduled_at<=now or any(s.parent_id==ad.occurrence_id and s.parent_start and s.parent_start<=now for s in committed):
                        self.break_store.commit(ad)
                self.break_store.reconcile_completed(self.number,through=now)
            if plan.end>now:
                boundaries = [value for s in plan.segments for value in (s.starts_at,s.ends_at) if value>now]
                # A partial-day checkpoint can retain the active break and a
                # pending cycle closure without repeating their segments here.
                boundaries.extend(value for value in (compiler.last_end,compiler.resume_at,compiler.ready_at,compiler.restart_at)
                                  if value is not None and value>now)
                boundaries.extend(at for _,_,at in plan.completions if at>now)
                boundaries.extend(datetime.fromisoformat(c['end']) for c in plan.closed_cycles if datetime.fromisoformat(c['end'])>now)
                if plan.next_change and plan.next_change>now:
                    boundaries.append(plan.next_change)
                boundaries.extend(c.completed_at for c in compiler.cursors.values() if c.completed_at and c.completed_at>now)
                self._next_reconcile = min(boundaries,default=now+timedelta(seconds=1))
                break
        self._last_reconciled = now

    def next_cycle_after(self, at, *, cancel=None):
        compiler = self._new_compiler(seed=self._checkpoint(at))
        compiler.cancel = cancel or (lambda:False)
        started = time.monotonic()
        for _ in range(3660):
            day = compiler.day()
            match = next((datetime.fromisoformat(c['end']) for c in day.closed_cycles if datetime.fromisoformat(c['end'])>at),None)
            if match:
                return match
            if compiler.blocked or compiler.closed:
                return None
            if time.monotonic()-started>3 or compiler.total_segments>250000:
                return None
        return None

    def migration_seed(self, new_rules, activation, *, reset=False):
        # Earned first-pass records are identity based. Keep unfinished media,
        # preserve completed groups, and never inherit another station's cursor.
        compiler = Compiler(new_rules,assets_for(tuple(self.media.values())),channel=self.number,activation=activation)
        with self.store.connect() as connection:
            rows = connection.execute("SELECT payload FROM planner_occurrences WHERE channel_number=? AND kind='program' AND ends_at<=? ORDER BY ends_at",(self.number,activation.isoformat())).fetchall()
        segments = [Segment.from_mapping(json.loads(r[0])) for r in rows]
        plan = self._day_at(activation-timedelta(microseconds=1))
        segments.extend(s for s in plan.segments if s.ends_at<=activation)
        latest_cycle = max((s.cycle for s in segments),default=0)
        compiler.cycle_index = latest_cycle+int(reset)
        compiler.reporting_cycle = compiler.cycle_index
        with self.store.connect() as connection:
            closed = connection.execute('SELECT closed_at FROM planner_cycles WHERE channel_number=? AND revision=? AND closed_at<=? ORDER BY closed_at DESC LIMIT 1',(self.number,self.revision,activation.isoformat())).fetchone()
        compiler.cycle_start = activation if reset else datetime.fromisoformat(closed[0]) if closed else self.activation
        for track in new_rules.tracks:
            if reset:
                continue
            members=set(compiler.groups[track.group_id].asset_ids)
            finished = {s.asset_id for s in segments if s.cycle==latest_cycle and s.track_id==track.id and s.finishes_asset and s.first_pass and s.asset_id in members}
            cursor = compiler.cursors[track.id]
            cursor.remaining = [key for key in cursor.remaining if key not in finished]
            if not cursor.remaining:
                cursor.completed_at = max((s.ends_at for s in segments if s.cycle==latest_cycle and s.track_id==track.id and s.finishes_asset),default=activation)
                compiler.first_finishes[track.id] = cursor.completed_at
            elif cursor.remaining:
                partial = [s for s in segments if s.cycle==latest_cycle and s.track_id==track.id and s.asset_id==cursor.remaining[0] and not s.finishes_asset]
                if partial:
                    cursor.offset = max(s.source_offset+(s.ends_at-s.starts_at).total_seconds() for s in partial)
            track_segments = [s for s in segments if s.cycle==latest_cycle and s.track_id==track.id and s.asset_id in members]
            if track_segments:
                compiler.first_starts[track.id] = min(s.starts_at for s in track_segments)
                compiler.content_seconds[track.id] = sum((s.ends_at-s.starts_at).total_seconds() for s in track_segments if s.kind=='program')
                compiler.occupied_seconds[track.id] = sum((s.ends_at-s.starts_at).total_seconds() for s in track_segments)
        seed = compiler.snapshot()
        if self.channel.definition.advertising.enabled:
            from ..ad_break_engine import BreakPlanStore
            from ..ad_scheduling import eligible_media
            from ..simple_ads import SimpleRotation
            ad_state = AdPlanner(tuple(self.media.values()),self.channel.ad_media,self.channel.definition.advertising,'',self.number)
            with self.store.connect() as connection:
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='ad_break_plans'").fetchone()
            if exists:
                store = BreakPlanStore(self.store.database_path,initialize=False)
                try:
                    ad_state.rotation = SimpleRotation(eligible_media(self.channel.ad_media,self.channel.definition.advertising),
                        self.channel.definition.advertising,self.number,store=store,before=activation)
                    ad_state.counts = store.rotation_counts(self.number,before=activation)
                finally:
                    store.close()
            candidates = [p for p in plan.breaks if p.scheduled_at<activation and p.rotation_revision==ad_state.rotation.revision]
            if candidates:
                last = max(candidates,key=lambda p:p.scheduled_at)
                ad_state.rotation.cycle,ad_state.rotation.remaining = last.rotation_cycle,list(last.rotation_remaining)
                ad_state.rotation.previous = next((p.asset_id for p in reversed(last.segments) if p.event_type=='advertisement'),'')
            seed['ads'] = ad_state.snapshot()
        return seed

    def release_manual_cycle(self, now):
        if self.rules.cycle.boundary!='manual':
            raise PlannerValidationError('This channel does not use a manual cycle boundary.')
        compiler = self._new_compiler(seed=self._checkpoint(now))
        for _ in range(36601):
            plan = compiler.day()
            if plan.end>now:
                break
        if compiler.ready_at is None or compiler.ready_at>now:
            raise PlannerValidationError('The content and date gates have not been met. A manual release cannot discard unfinished required media.')
        selection = self.selection_at(self.activation,now)
        safe = max(now,selection.parent_program_ends_at or selection.program_ends_at) if selection.origin!='offair' else now
        with self.store.connect() as connection:
            connection.execute('INSERT OR IGNORE INTO planner_manual_releases VALUES(?,?,?,?)',
                (self.number,self.revision,compiler.cycle_index,safe.isoformat()))
        return safe

    def observe_unavailable(self, now):
        """Record a known input failure without earning the interrupted episode.

        Preserve the reserved parent and ads, retain the original source intent
        in the failure ledger, and resume the unplayed source on its next slot.
        This runs only on an actual runtime open/recovery, never a projection.
        """
        seed = self._checkpoint(now)
        if seed is None:
            return
        with self.store.connect() as connection:
            rows = connection.execute("SELECT * FROM planner_occurrences WHERE channel_number=? AND revision=? AND ends_at>? AND kind='program' AND json_extract(payload,'$.parent_start')<=?",(self.number,self.revision,now.isoformat(),now.isoformat())).fetchall()
            by_parent = {}
            for row in rows:
                segment = Segment.from_mapping(json.loads(row['payload']))
                item = self.media.get(segment.asset_id)
                if item is None or not item.location.online:
                    by_parent.setdefault(segment.parent_id,[]).append(segment)
            for parent,segments in by_parent.items():
                if connection.execute('SELECT 1 FROM planner_failures WHERE channel_number=? AND revision=? AND parent_id=?',(self.number,self.revision,parent)).fetchone():
                    continue
                track = segments[0].track_id
                asset = segments[0].asset_id
                offset = max((s.source_offset+min((now-s.starts_at).total_seconds(),(s.ends_at-s.starts_at).total_seconds()) for s in segments if s.starts_at<=now),default=min(s.source_offset for s in segments))
                connection.execute('INSERT INTO planner_failures VALUES(?,?,?,?,?)',
                    (self.number,self.revision,parent,now.isoformat(),json.dumps({'asset_id':asset,'track_id':track,
                        'resume_offset':offset,'reason':'source unavailable during a committed program',
                        'original_segments':[s.to_mapping() for s in segments]})))
                for s in segments:
                    if s.ends_at<=now:
                        continue
                    if s.starts_at<now:
                        played = replace(s,ends_at=now,finishes_asset=False)
                        connection.execute('UPDATE planner_occurrences SET ends_at=?,payload=? WHERE channel_number=? AND occurrence_id=?',
                            (now.isoformat(),json.dumps(played.to_mapping()),self.number,s.id))
                    else:
                        connection.execute('DELETE FROM planner_occurrences WHERE channel_number=? AND occurrence_id=?',(self.number,s.id))
                    idle = Segment(stable_id('unavailable',s.id,now),None,max(now,s.starts_at),s.ends_at,'offair',None,s.window_id,s.cycle)
                    connection.execute('INSERT OR IGNORE INTO planner_occurrences VALUES(?,?,?,?,?,?,?)',
                        (self.number,self.revision,idle.id,idle.starts_at.isoformat(),idle.ends_at.isoformat(),'offair',json.dumps(idle.to_mapping())))
                if track in seed['cursors']:
                    cursor = seed['cursors'][track]
                    if asset not in cursor['remaining']:
                        cursor['remaining'].insert(0,asset)
                    cursor['offset'] = offset
                    earned = connection.execute('SELECT 1 FROM planner_completions WHERE channel_number=? AND revision=? AND cycle_index=? AND track_id=?',
                        (self.number,self.revision,seed['cycle_index'],track)).fetchone()
                    if not earned:
                        cursor['completed_at']=None
                        seed.get('first_finishes',{}).pop(track,None)
                        seed['ready_at']=seed['restart_at']=None
                seed['resume_at'] = max(datetime.fromisoformat(seed['resume_at']) if seed.get('resume_at') else now,
                                        max(s.parent_end or s.ends_at for s in segments)).isoformat()
                connection.execute('UPDATE planner_checkpoints SET through_utc=?,payload=? WHERE channel_number=? AND revision=?',
                    (now.isoformat(),json.dumps(seed),self.number,self.revision))


def open_runtime(channel, store, now, transient=False):
    from ..ad_break_engine import BreakPlanStore
    from ..runtime import ChannelRuntime, PersistedChannelRuntime, schedule_signature
    timeline = PlannerTimeline(channel,store,now=now,transient=transient)
    persisted = (store.load_channel(channel.definition.channel) or PersistedChannelRuntime(channel.definition.channel,schedule_signature(channel),timeline.activation)) if transient else store.ensure_channel(channel.definition.channel,schedule_signature(channel),now=now,preserve_clock_on_change=True)
    owner=timeline._revision_at(now)
    with store.connect() as connection:
        table=connection.execute("SELECT 1 FROM sqlite_master WHERE name='ad_break_plans'").fetchone()
        history=table and connection.execute('SELECT 1 FROM ad_break_plans WHERE channel_number=? LIMIT 1',(channel.definition.channel,)).fetchone()
        legacy_ads=connection.execute("SELECT 1 FROM planner_legacy WHERE channel_number=? AND json_extract(payload,'$.advertising.enabled')=1",(channel.definition.channel,)).fetchone()
    needs_breaks=channel.definition.advertising.enabled or bool(owner and owner.channel.definition.advertising.enabled) or bool(history) or bool(legacy_ads)
    breaks = BreakPlanStore(store.database_path) if needs_breaks else None
    if breaks and getattr(store,'_snapshot_portable',None):
        breaks.portable=breaks.connection.portable=store._snapshot_portable
    timeline.bind_break_store(breaks)
    if not transient:
        timeline.observe_unavailable(now)
        timeline.reconcile(now)
    return ChannelRuntime(channel,timeline,persisted.epoch_utc,schedule_signature(channel),breaks)
