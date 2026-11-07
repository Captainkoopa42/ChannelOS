"""Versioned time-block profiles contain intent, never media or progression."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path

from .contracts import AiringWindow, HistoricalAiring, PlannerDefinition, PlannerValidationError, identity, integer, mapping, sequence, text


def validate_profile(raw):
    raw = mapping(raw, {'id','version','name','slots','description'}, 'time-block profile')
    result = {'id':identity(raw.get('id'), 'profile ID'), 'version':integer(raw.get('version',1),'version',1),
              'name':text(raw.get('name'), 'profile name'), 'description':text(raw.get('description',''),'description',empty=True), 'slots':[]}
    seen = set()
    for slot in sequence(raw.get('slots',[]),'profile slots',1000):
        slot = mapping(slot, {'id','name','start','end','bracket_minutes','fit','max_overrun_minutes','scope','priority'},'profile slot')
        parsed = AiringWindow.parse({key:value for key,value in {**slot,'track_id':'unbound'}.items() if key!='name'})
        if parsed.id in seen:
            raise PlannerValidationError('duplicate profile slot ID')
        seen.add(parsed.id)
        result['slots'].append(deepcopy(slot))
    if not result['slots']:
        raise PlannerValidationError('a profile requires at least one named time slot')
    return result


def bind_profile(definition, profile, assignments, *, replace_binding=True):
    profile = validate_profile(profile)
    raw = definition.to_mapping()
    known = {track.id for track in definition.tracks}
    slots = {slot['id'] for slot in profile['slots']}
    if set(assignments) != slots or set(assignments.values()) - known:
        raise PlannerValidationError('Assign each profile slot to a track in this channel.')
    prefix = 'profile:' + profile['id'] + ':'
    previous = [window for window in raw['windows'] if window['id'].startswith(prefix)]
    if any(window['protected'] for window in previous):
        raise PlannerValidationError('This profile contains a protected local window. Resolve its override before reapplying.')
    if replace_binding:
        raw['windows'] = [window for window in raw['windows'] if not window['id'].startswith(prefix)]
        raw['profile_bindings'] = [binding for binding in raw['profile_bindings'] if binding['id']!=profile['id']]
    for slot in profile['slots']:
        raw['windows'].append({**{key:value for key,value in slot.items() if key!='name'},
            'id':prefix+slot['id'], 'track_id':assignments[slot['id']], 'profile_slot_id':slot['id']})
    raw['profile_bindings'].append({'id':profile['id'],'version':profile['version'],
        'snapshot':deepcopy(profile),'assignments':deepcopy(assignments)})
    return PlannerDefinition.from_mapping(raw)


class ProfileStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def list(self):
        if not self.directory.exists():
            return []
        profiles = []
        for path in sorted(self.directory.glob('*.json')):
            try:
                profiles.append(validate_profile(json.loads(path.read_text(encoding='utf-8'))))
            except (OSError, ValueError):
                continue
        latest = {}
        for profile in profiles:
            if profile['id'] not in latest or profile['version'] > latest[profile['id']]['version']:
                latest[profile['id']] = profile
        return sorted(latest.values(),key=lambda p:p['name'].casefold())

    def save(self, raw, *, duplicate=False):
        profile = validate_profile(raw)
        if duplicate:
            profile['id'], profile['version'] = uuid.uuid4().hex, 1
            profile['name'] += ' copy'
        else:
            versions = [p['version'] for p in self.list() if p['id']==profile['id']]
            profile['version'] = max(versions, default=0)+1
        self.directory.mkdir(parents=True,exist_ok=True)
        file_id=hashlib.sha256(profile['id'].encode()).hexdigest()
        target = self.directory/f"profile-{file_id}.v{profile['version']}.json"
        handle, temporary = tempfile.mkstemp(dir=self.directory,prefix='.profile-',suffix='.tmp')
        try:
            with os.fdopen(handle,'w',encoding='utf-8') as stream:
                json.dump(profile,stream,indent=2,allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return profile


def import_airings(content, format='json'):
    """User supplied records only. No external provenance is invented."""
    if len(content)>20_000_000:
        raise PlannerValidationError('The airing file exceeds 20 MB. Split it into smaller imports.')
    rows = list(csv.DictReader(io.StringIO(content))) if format=='csv' else json.loads(content)
    result = []
    for row in sequence(rows,'original airings',50000):
        row = {key:value for key,value in row.items() if value not in ('',None)}
        if format=='csv' and 'rerun' in row:
            if row['rerun'].lower() not in {'true','false','1','0'}:
                raise PlannerValidationError('CSV rerun must be true or false')
            row['rerun'] = row['rerun'].lower() in {'true','1'}
        result.append(HistoricalAiring.parse(row))
    return result
