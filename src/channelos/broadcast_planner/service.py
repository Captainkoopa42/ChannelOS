"""Detached planner authoring. Applying uses the existing channel transaction."""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..broadcaster import definition_from_editor
from ..resolve import _semantic_sequence_key, resolve_channel, MediaResolutionIndex
from .runtime import planner_ad_signature
from .advertising import AdPlanner
from .contracts import PlannerDefinition
from .engine import Asset, Segment, forecast, stable_id, PlannerCancelled
from .timezones import get_zone, local_instant
from .profiles import ProfileStore, bind_profile, import_airings, validate_profile


class PlannerService:
    def __init__(self, broadcaster):
        self.broadcaster = broadcaster
        self.profiles = ProfileStore(broadcaster.managed_directory/'studio'/'time-block-profiles')

    def load(self, number=0):
        editor = self.broadcaster.studio_draft(number)
        rows = self.broadcaster.library.list_cached_media()
        canonical = {}
        for item in rows:
            key = item.asset.asset_id
            if key not in canonical or item.location.online and not canonical[key].location.online:
                canonical[key] = item
        grouped = defaultdict(list)
        for item in canonical.values():
            path, root = item.location.path, item.location.source_root
            try:
                relative = path.relative_to(root)
                name = relative.parts[0] if len(relative.parts)>1 else root.name
            except ValueError:
                name = path.parent.name
            grouped[(str(root),name)].append(item)
        bins = []
        for (root,name), items in grouped.items():
            items.sort(key=lambda item:_semantic_sequence_key(str(item.location.path)))
            bins.append({'id':'bin-'+stable_id(root,name)[:20],'name':name,'kind':'movie' if len(items)==1 else 'series',
                'asset_ids':[m.asset.asset_id for m in items],'count':len(items),
                'seconds':sum(float(m.asset.duration_seconds or 0) for m in items),
                'missing':sum(not m.location.online or not m.asset.duration_seconds for m in items),
                'source':root})
        bins.sort(key=lambda g:g['name'].casefold())
        existing = self.broadcaster._records.get(int(number))
        if existing and existing.definition.programming.planner:
            rules = existing.definition.programming.planner.to_mapping()
        else:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            rules = {'start_at':now.isoformat(),'timezone':'UTC','groups':[],'tracks':[],'windows':[],
                'cycle':{'action':'restart','completion':'all','boundary':'safe'},'gap_filler':False,
                'layers':[],'suspensions':[],'profile_bindings':[],'historical_airings':[],
                'historical_mode':'none','edit_effect':'next_cycle'}
            if existing:
                # Existing manual blocks remain protected fixed intent. Classic
                # conversion starts as a detached primary track in source order.
                resolved = resolve_channel(existing.definition,self.broadcaster.library,allow_offline_ads=True)
                if resolved.media:
                    group = {'id':'converted','name':existing.definition.name,'kind':'collection',
                             'asset_ids':[m.asset.asset_id for m in resolved.media]}
                    rules['groups']=[group]
                    rules['tracks']=[{'id':'primary','group_id':'converted','post_completion':'filler','required':True}]
        editor['mode'],editor['planner'] = 'planner',rules
        editor.pop('media',None)
        return {'editor':editor,'bin':bins,'profiles':self.profiles.list(),
                'mediaRows':[{'assetId':key,'title':item.location.path.stem,'path':str(item.location.path),
                              'sourceRoot':str(item.location.source_root),'durationSeconds':float(item.asset.duration_seconds or 0),
                              'locations':[{'path':str(item.location.path),'sourceRoot':str(item.location.source_root)}]}
                             for key,item in canonical.items() if item.location.online],
                'media':{key:{'title':item.location.path.stem,'seconds':float(item.asset.duration_seconds or 0),'online':item.location.online}
                         for key,item in canonical.items()},
                'message':'Draft loaded. Live TV changes only when you apply.'}

    def preview(self, editor, *, view_start=None, view_days=7, cancel=None):
        from .contracts import day
        definition = definition_from_editor(editor)
        index = MediaResolutionIndex(self.broadcaster.library)
        resolved = resolve_channel(definition,self.broadcaster.library,allow_offline_ads=True,index=index,verify_ad_files=False)
        # Include offline canonical IDs in the contract. Missing members hold
        # their own track instead of silently advancing to the next episode.
        media = {m.asset.asset_id:m for m in index.rows}
        media.update({m.asset.asset_id:m for m in index.online})
        ads = AdPlanner(tuple(media.values()),resolved.ad_media,definition.advertising,
                        planner_ad_signature(resolved),definition.channel) if definition.advertising.enabled else None
        activation, seed, pending, releases, previous, store = None, None, False, None, None, None
        changed_revision=False
        if self.broadcaster.runtime_database_path.is_file():
            from ..runtime import RuntimeStore
            from .runtime import PlannerTimeline, revision_key, effective_revision
            store = RuntimeStore.read_only(self.broadcaster.runtime_database_path)
            now=datetime.now(timezone.utc)
            with store.connect() as connection:
                active = effective_revision(connection,definition.channel,now)
            if active:
                raw = json.loads(active['payload'])
                if store.portable:
                    from ..portable import path_tree
                    raw = path_tree(raw,store.portable.decode)
                from ..models import ChannelDefinition
                old = ChannelDefinition.from_mapping(raw)
                previous = PlannerTimeline(resolve_channel(old,self.broadcaster.library,allow_offline_ads=True,index=index,verify_ad_files=False),store,now=now,transient=True,revision=active['revision'])
                if previous.intent_revision != revision_key(resolved):
                    changed_revision=True
                    now = datetime.now(timezone.utc)
                    if definition.programming.planner.edit_effect=='next_cycle':
                        activation = previous.next_cycle_after(now,cancel=cancel)
                        pending = activation is None
                        if activation:
                            seed = previous.migration_seed(definition.programming.planner,activation,reset=True)
                    else:
                        selection = previous.selection_at(previous.activation,now)
                        activation = max(now,selection.parent_program_ends_at or selection.program_ends_at) if selection.origin!='offair' else now
                        seed = previous.migration_seed(definition.programming.planner,activation)
                else:
                    activation = datetime.fromisoformat(active['activation_at'])
                    seed = previous._checkpoint(datetime.now(timezone.utc)) or (json.loads(active['seed']) if active['seed'] else None)
                    if seed and seed.get('reporting_cycle',0)!=seed['cycle_index']:
                        seed['reporting_cycle']=seed['cycle_index']
                        seed['first_starts'],seed['content_seconds'],seed['occupied_seconds']={},{},{}
                        seed['first_finishes']={key:c['completed_at'] for key,c in seed['cursors'].items() if c['completed_at']}
                        with store.connect() as connection:
                            cursor=connection.execute("SELECT payload FROM planner_occurrences WHERE channel_number=? AND revision=? AND json_extract(payload,'$.cycle')=?",(definition.channel,active['revision'],seed['cycle_index']))
                            for n,row in enumerate(cursor):
                                if n%1000==0 and cancel and cancel():
                                    raise PlannerCancelled('Forecast cancelled')
                                segment=Segment.from_mapping(json.loads(row[0]))
                                if segment.track_id:
                                    seed['first_starts'].setdefault(segment.track_id,segment.starts_at.isoformat())
                                    seed['occupied_seconds'][segment.track_id]=seed['occupied_seconds'].get(segment.track_id,0)+(segment.ends_at-segment.starts_at).total_seconds()
                                    if segment.kind=='program':
                                        seed['content_seconds'][segment.track_id]=seed['content_seconds'].get(segment.track_id,0)+(segment.ends_at-segment.starts_at).total_seconds()
                    with store.connect() as connection:
                        releases = {row[0]:datetime.fromisoformat(row[1]) for row in connection.execute('SELECT cycle_index,released_at FROM planner_manual_releases WHERE channel_number=? AND revision=?',(definition.channel,active['revision']))}
            else:
                existing=self.broadcaster._records.get(definition.channel)
                legacy=existing.definition if existing and existing.definition.programming.planner is None else None
                if legacy is None:
                    with store.connect() as connection:
                        row=connection.execute('SELECT payload FROM planner_legacy WHERE channel_number=?',(definition.channel,)).fetchone()
                    if row:
                        legacy=PlannerTimeline(resolved,store,now=now,transient=True)._decode(row['payload'])
                if legacy:
                    import tempfile
                    from ..runtime_snapshot import channel_snapshot
                    from .runtime import legacy_safe_start
                    with tempfile.TemporaryDirectory(prefix='channelos-planner-preview-') as temporary:
                        detached=channel_snapshot(store.database_path,Path(temporary)/'runtime.db',definition.channel)
                        activation=max(definition.programming.planner.start_at,
                            legacy_safe_start(legacy,self.broadcaster.library,detached,now,verify_files=False))
        result = forecast(definition.programming.planner,
            [Asset(key,float(m.asset.duration_seconds or 0),m.location.path.stem,m.location.online) for key,m in media.items()],
            channel=definition.channel,ads=ads,manual=definition.programming.calendar,cancel=cancel,
            view_start=day(view_start,'view date'),view_days=view_days,activation=activation,seed=seed,manual_releases=releases)
        if pending:
            result.update(confidence='Blocked',media_ends=None,cycle_ready=None,actual_restart=None)
            result['issues'].insert(0,{'blocking':True,'message':'The current cycle has no known closing boundary. Choose Safe Future to review an earlier migration, or resolve its content/date gates.'})
        if previous and store:
            self._attach_existing_view(result,previous,store,view_start,view_days,activation,definition.programming.planner,cancel,changed_revision)
        return result

    def _attach_existing_view(self,result,previous,store,view_start,view_days,activation,rules,cancel,changed_revision):
        """Merge immutable past/current occurrences with the detached future."""
        from .contracts import day
        zone=get_zone(rules.timezone)
        first=day(view_start,'view date') or rules.start_at.astimezone(zone).date()
        last=first+timedelta(days=min(31,max(1,view_days)))
        begins=local_instant(first,'00:00',zone)
        ends=local_instant(last,'00:00',zone)
        saved=[]
        counts={}
        with store.connect() as connection:
            cursor=connection.execute('SELECT payload FROM planner_occurrences WHERE channel_number=? AND starts_at<? AND ends_at>? ORDER BY starts_at',
                                      (previous.number,ends.isoformat(),begins.isoformat()))
            for n,row in enumerate(cursor):
                if n%1000==0 and cancel and cancel():
                    raise PlannerCancelled('Forecast cancelled')
                segment=Segment.from_mapping(json.loads(row[0]))
                local=max(segment.starts_at,begins).astimezone(zone)
                if segment.kind=='program':
                    counts.setdefault(local.date().isoformat(),set()).add(segment.parent_id or segment.id)
                if view_days<=7 and len(saved)<3000:
                    saved.append({**segment.to_mapping(),'display_start':local.strftime('%Y-%m-%d %H:%M'),'local_day':local.date().isoformat()})
        # Until a new revision activates, its predecessor still owns the future
        # schedule. Simulate only requested nearby days; do not persist them.
        if changed_revision and activation and activation>datetime.now(timezone.utc):
            compiler=previous._new_compiler(seed=previous._checkpoint(datetime.now(timezone.utc)))
            compiler.cancel=cancel or (lambda:False)
            for _ in range(3660):
                plan=compiler.day()
                if plan.start>=min(ends,activation):
                    break
                if plan.end<=begins:
                    continue
                for segment in plan.segments:
                    if segment.starts_at>=activation or segment.ends_at<=begins or segment.starts_at>=ends:
                        continue
                    local=max(segment.starts_at,begins).astimezone(zone)
                    if segment.kind=='program':
                        counts.setdefault(local.date().isoformat(),set()).add(segment.parent_id or segment.id)
                    if view_days<=7 and len(saved)<3000:
                        saved.append({**segment.to_mapping(),'display_start':local.strftime('%Y-%m-%d %H:%M'),'local_day':local.date().isoformat()})
                if plan.day>=last:
                    break
        merged={row['id']:row for row in saved}
        merged.update({row['id']:row for row in result['segments']})
        result['segments']=sorted(merged.values(),key=lambda s:(s['starts_at'],s['id']))[:3000]
        for value,parents in counts.items():
            total=result['calendar_days'].setdefault(value,{'programs':0,'ads':0,'filler':0})
            total['programs']+=len(parents)

    def task(self, action, payload, cancel):
        if action=='load':
            return self.load(int(payload.get('number',0)))
        if action=='preview':
            return self.preview(payload['editor'],view_start=payload.get('view_start'),view_days=payload.get('view_days',7),cancel=cancel)
        if action in {'save_profile','duplicate_profile','import_profile'}:
            if action=='import_profile' and Path(payload['path']).stat().st_size>2_000_000:
                raise ValueError('The time-block profile exceeds the 2 MB import limit.')
            raw = payload['profile'] if action!='import_profile' else json.loads(Path(payload['path']).read_text(encoding='utf-8-sig'))
            saved = self.profiles.save(raw,duplicate=action=='duplicate_profile')
            return {'profile':saved,'profiles':self.profiles.list()}
        if action=='bind_profile':
            rules = PlannerDefinition.from_mapping(payload['planner'])
            return {'planner':bind_profile(rules,payload['profile'],payload['assignments']).to_mapping()}
        if action=='export_profile':
            raw = validate_profile(payload['profile'])
            self.broadcaster._atomic_write(Path(payload['path']),json.dumps(raw,indent=2,allow_nan=False))
            return {'message':'Profile exported'}
        if action=='import_airings':
            path = Path(payload['path'])
            if path.stat().st_size>20_000_000:
                raise ValueError('The original-airing file exceeds 20 MB. Split it into smaller imports.')
            records = import_airings(path.read_text(encoding='utf-8-sig'),'csv' if path.suffix.lower()=='.csv' else 'json')
            # Normalize dates through the same portable contract serializer.
            raw = payload['planner']
            from dataclasses import asdict
            raw['historical_airings'] = [{key:(value.isoformat() if isinstance(value,datetime) else value) for key,value in asdict(record).items()} for record in records]
            if records and not raw.get('tracks'):
                unique = list(dict.fromkeys(r.substitute_id or r.asset_id for r in records if not r.rerun))
                if unique:
                    raw['groups']=[{'id':'original-records','name':'Original airings','asset_ids':unique,'kind':'collection'}]
                    raw['tracks']=[{'id':'original-primary','group_id':'original-records','required':True}]
                    for airing in raw['historical_airings']:
                        if not airing.get('track_id'):
                            airing['track_id']='original-primary'
            return {'planner':PlannerDefinition.from_mapping(raw).to_mapping(),'imported':len(records)}
        raise ValueError('Unknown Broadcast Planner operation')
