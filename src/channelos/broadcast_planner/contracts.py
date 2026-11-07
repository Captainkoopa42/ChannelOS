"""Versioned, media-independent broadcast intent. No runtime state lives here."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any
from .timezones import get_zone


class PlannerValidationError(ValueError):
    pass


class _FrozenObject(dict):
    def _immutable(self,*args,**kwargs):
        raise TypeError('Pinned profile snapshots are immutable; create a new version.')
    __setitem__=__delitem__=clear=pop=popitem=setdefault=update=__ior__=_immutable

    def __deepcopy__(self,memo):
        return self


def _freeze(value):
    if isinstance(value,dict):
        return _FrozenObject((key,_freeze(item)) for key,item in value.items())
    if isinstance(value,(list,tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def mapping(value, fields, label):
    if not isinstance(value, dict):
        raise PlannerValidationError(f'{label} must be an object')
    unknown = set(value) - set(fields)
    if unknown:
        raise PlannerValidationError(f'{label}: unknown fields {", ".join(sorted(str(key) for key in unknown))}')
    return value


def text(value, label, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise PlannerValidationError(f'{label} must be text' + ('' if empty else ' and cannot be empty'))
    if len(value) > 2000:
        raise PlannerValidationError(f'{label} is too long')
    return value.strip()


def identity(value, label):
    value = text(value, label)
    if len(value) > 160 or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
        raise PlannerValidationError(f'{label} must be a stable identifier')
    return value


def integer(value, label, minimum=0, maximum=1000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or not minimum <= value <= maximum:
        raise PlannerValidationError(f'{label} must be an integer from {minimum} to {maximum}')
    return int(value)


def choice(value, options, label):
    if value not in options:
        raise PlannerValidationError(f'{label} must be one of {", ".join(options)}')
    return value


def flag(value, label):
    if type(value) is not bool:
        raise PlannerValidationError(f'{label} must be true or false')
    return value


def sequence(value, label, maximum=10000):
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise PlannerValidationError(f'{label} must be a list with at most {maximum} entries')
    return value


def ids(value, label, maximum=50000):
    result = tuple(text(item, label) for item in sequence(value, label, maximum))
    if len(result) != len(set(result)):
        raise PlannerValidationError(f'{label} contains duplicate identities')
    return result


def day(value, label):
    if value in (None, ''):
        return None
    try:
        return value if type(value) is date else date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise PlannerValidationError(f'{label} must be an ISO date') from exc


def instant(value, label):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError('missing offset')
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise PlannerValidationError(f'{label} must be an ISO timestamp with a UTC offset') from exc


def clock(value, label, *, end=False):
    value = text(value, label)
    if end and value == '24:00':
        return value
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise PlannerValidationError(f'{label} must use HH:MM')
    return value


def minute(value):
    hour, part = map(int, value.split(':'))
    return hour * 60 + part


@dataclass(frozen=True)
class DateScope:
    from_date: date | None = None
    until_date: date | None = None
    months: tuple[int, ...] = ()
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    years: tuple[int, ...] = ()

    @classmethod
    def parse(cls, raw=None):
        raw = mapping({} if raw is None else raw, {'from_date', 'until_date', 'months', 'weekdays', 'years'}, 'date scope')
        first, last = day(raw.get('from_date'), 'from date'), day(raw.get('until_date'), 'until date')
        if first and last and last < first:
            raise PlannerValidationError('date scope ends before it begins')
        months = tuple(integer(v, 'month', 1, 12) for v in sequence(raw.get('months', []), 'months', 12))
        weekdays = tuple(integer(v, 'weekday', 0, 6) for v in sequence(raw.get('weekdays', list(range(7))), 'weekdays', 7))
        years = tuple(integer(v, 'year', 1900, 2500) for v in sequence(raw.get('years', []), 'years', 601))
        if len(months) != len(set(months)) or len(weekdays) != len(set(weekdays)) or len(years) != len(set(years)):
            raise PlannerValidationError('date scope contains duplicate values')
        return cls(first, last, months, weekdays, years)

    def matches(self, value: date):
        return (not self.from_date or value >= self.from_date) and (not self.until_date or value <= self.until_date) and (not self.months or value.month in self.months) and value.weekday() in self.weekdays and (not self.years or value.year in self.years)


@dataclass(frozen=True)
class MediaGroup:
    id: str
    name: str
    asset_ids: tuple[str, ...]
    kind: str = 'series'

    @classmethod
    def parse(cls, raw):
        raw = mapping(raw, {'id', 'name', 'asset_ids', 'kind'}, 'media group')
        assets = ids(raw.get('asset_ids', []), 'group assets')
        if not assets:
            raise PlannerValidationError('a media group needs at least one indexed asset')
        return cls(identity(raw.get('id'), 'group ID'), text(raw.get('name'), 'group name'), assets,
                   choice(raw.get('kind', 'series'), ('series', 'movie', 'collection'), 'group kind'))


@dataclass(frozen=True)
class Track:
    id: str
    group_id: str
    mode: str = 'primary'
    order: str = 'sequential'
    post_completion: str = 'filler'
    successor_id: str | None = None
    required: bool = True
    start_index: int = 0

    @classmethod
    def parse(cls, raw):
        raw = mapping(raw, {'id', 'group_id', 'mode', 'order', 'post_completion', 'successor_id', 'required', 'start_index'}, 'progression track')
        mode = choice(raw.get('mode', 'primary'), ('primary', 'rerun'), 'track mode')
        post = choice(raw.get('post_completion', 'filler'), ('loop', 'filler', 'rerun', 'unassigned', 'successor'), 'after media finishes')
        successor = raw.get('successor_id') or None
        if successor:
            successor = identity(successor, 'successor track')
        if post == 'successor' and not successor:
            raise PlannerValidationError('choose a successor track')
        required = flag(raw.get('required', mode == 'primary'), 'required track')
        if mode == 'rerun' and required:
            raise PlannerValidationError('an independent rerun track cannot satisfy a first-pass completion gate')
        return cls(identity(raw.get('id'), 'track ID'), identity(raw.get('group_id'), 'group reference'), mode,
                   choice(raw.get('order', 'sequential'), ('sequential', 'shuffle'), 'episode order'), post, successor,
                   required, integer(raw.get('start_index', 0), 'first episode', 0, 49999))


@dataclass(frozen=True)
class AiringWindow:
    id: str
    track_id: str
    start: str
    end: str
    bracket_minutes: int = 60
    fit: str = 'strict'
    max_overrun_minutes: int = 0
    priority: int = 0
    layer_id: str | None = None
    scope: DateScope = DateScope()
    protected: bool = False
    profile_slot_id: str | None = None

    @classmethod
    def parse(cls, raw):
        raw = mapping(raw, {'id', 'track_id', 'start', 'end', 'bracket_minutes', 'fit', 'max_overrun_minutes', 'priority', 'layer_id', 'scope', 'protected', 'profile_slot_id'}, 'airing window')
        start, end = clock(raw.get('start'), 'window start'), clock(raw.get('end'), 'window end', end=True)
        if minute(start) == minute(end):
            raise PlannerValidationError('an airing window needs a nonzero duration; use 00:00–24:00 for a full day')
        layer = identity(raw['layer_id'], 'layer reference') if raw.get('layer_id') else None
        slot = identity(raw['profile_slot_id'], 'profile slot') if raw.get('profile_slot_id') else None
        fit = choice(raw.get('fit', 'strict'), ('strict', 'overrun', 'carryover', 'next_fit'), 'window fitting')
        overrun = integer(raw.get('max_overrun_minutes', 0), 'maximum overrun', 0, 480)
        if fit == 'overrun' and overrun <= 0:
            raise PlannerValidationError('bounded overrun requires an explicit maximum')
        return cls(identity(raw.get('id'), 'window ID'), identity(raw.get('track_id'), 'track reference'), start, end,
                   integer(raw.get('bracket_minutes', 60), 'bracket minutes', 1, 480), fit, overrun,
                   integer(raw.get('priority', 0), 'window priority', -1000, 1000), layer, DateScope.parse(raw.get('scope')),
                   flag(raw.get('protected', False), 'protected start'), slot)


@dataclass(frozen=True)
class CalendarLayer:
    id: str
    name: str
    scope: DateScope = DateScope()
    priority: int = 100
    replace_scope: str = 'overlap'

    @classmethod
    def parse(cls, raw):
        raw = mapping(raw, {'id', 'name', 'scope', 'priority', 'replace_scope'}, 'calendar layer')
        return cls(identity(raw.get('id'), 'layer ID'), text(raw.get('name'), 'layer name'), DateScope.parse(raw.get('scope')),
                   integer(raw.get('priority', 100), 'layer priority', 1, 1000),
                   choice(raw.get('replace_scope', 'overlap'), ('overlap', 'channel'), 'layer replacement scope'))


@dataclass(frozen=True)
class Suspension:
    id: str
    target: str
    target_id: str | None = None
    scope: DateScope = DateScope()
    resume: str = 'continue'
    name: str = ''

    @classmethod
    def parse(cls, raw):
        raw = mapping(raw, {'id', 'target', 'target_id', 'scope', 'resume', 'name'}, 'suspension')
        target = choice(raw.get('target'), ('track', 'group', 'window', 'layer', 'filler', 'advertising', 'channel'), 'suspension target')
        target_id = identity(raw['target_id'], 'suspension target ID') if raw.get('target_id') else None
        if target in {'track', 'group', 'window', 'layer'} and not target_id:
            raise PlannerValidationError('select the item to suspend')
        return cls(identity(raw.get('id'), 'suspension ID'), target, target_id, DateScope.parse(raw.get('scope')),
                   choice(raw.get('resume', 'continue'), ('continue', 'restart', 'skip'), 'resume policy'),
                   text(raw.get('name', ''), 'suspension name', empty=True))


@dataclass(frozen=True)
class CompletionGate:
    op: str
    track_id: str | None = None
    children: tuple['CompletionGate', ...] = ()

    @classmethod
    def parse(cls, raw, depth=0):
        if depth > 8:
            raise PlannerValidationError('completion gate exceeds eight nested groups')
        raw = mapping(raw, {'op', 'track_id', 'children'}, 'completion gate')
        op = choice(raw.get('op'), ('all', 'any', 'track'), 'gate operator')
        if op == 'track':
            if raw.get('children'):
                raise PlannerValidationError('a track gate cannot contain child gates')
            return cls(op, identity(raw.get('track_id'), 'gate track'))
        children = tuple(cls.parse(item, depth + 1) for item in sequence(raw.get('children', []), 'gate children', 1000))
        if not children or raw.get('track_id'):
            raise PlannerValidationError('an ALL/ANY gate needs child conditions')
        return cls(op, None, children)

    def references(self):
        return frozenset((self.track_id,)) if self.op == 'track' else frozenset().union(*(child.references() for child in self.children))

    def satisfied(self, completions):
        if self.op == 'track':
            return self.track_id in completions
        values = (child.satisfied(completions) for child in self.children)
        return all(values) if self.op == 'all' else any(values)


@dataclass(frozen=True)
class CycleRule:
    action: str = 'restart'
    completion: str = 'all'
    required_tracks: tuple[str, ...] = ()
    custom_gate: CompletionGate | None = None
    not_before: datetime | None = None
    gate_mode: str = 'and'
    allow_unfinished: bool = False
    boundary: str = 'safe'
    boundary_weekday: int = 0
    boundary_time: str = '00:00'
    period_days: int = 7
    after_once: str = 'slate'
    restart_tracks: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw=None):
        raw = mapping({} if raw is None else raw, set(cls.__dataclass_fields__), 'channel cycle')
        completion = choice(raw.get('completion', 'all'), ('all', 'any', 'selected_all', 'selected_any', 'custom', 'none'), 'completion condition')
        required = ids(raw.get('required_tracks', []), 'required tracks', 1000)
        gate = CompletionGate.parse(raw['custom_gate']) if raw.get('custom_gate') is not None else None
        if completion == 'custom' and gate is None:
            raise PlannerValidationError('a custom completion condition needs an ALL/ANY gate')
        if completion.startswith('selected_') and not required:
            raise PlannerValidationError('select at least one required track')
        at = instant(raw['not_before'], 'earliest cycle date') if raw.get('not_before') else None
        mode = choice(raw.get('gate_mode', 'and'), ('and', 'or'), 'gate combination')
        force = flag(raw.get('allow_unfinished', False), 'early completion acknowledgement')
        if (mode == 'or' or completion == 'none') and (not force or at is None):
            raise PlannerValidationError('date-only / OR completion requires a date and explicit unfinished-content acknowledgement')
        return cls(choice(raw.get('action', 'restart'), ('restart', 'once'), 'channel end action'), completion, required, gate, at,
                   mode, force, choice(raw.get('boundary', 'safe'), ('safe', 'day', 'week', 'month', 'quarter', 'year', 'period', 'manual'), 'restart boundary'),
                   integer(raw.get('boundary_weekday', 0), 'boundary weekday', 0, 6), clock(raw.get('boundary_time', '00:00'), 'boundary time'),
                   integer(raw.get('period_days', 7), 'period days', 1, 3660), choice(raw.get('after_once', 'slate'), ('slate', 'offair', 'filler'), 'finished channel output'),
                   ids(raw.get('restart_tracks', []), 'restart tracks', 1000))


@dataclass(frozen=True)
class HistoricalAiring:
    id: str
    asset_id: str
    starts_at: datetime
    ends_at: datetime | None = None
    track_id: str | None = None
    source: str = ''
    accuracy: str = 'exact'
    substitute_id: str | None = None
    rerun: bool = False

    @classmethod
    def parse(cls, raw):
        raw = mapping(raw, set(cls.__dataclass_fields__), 'original airing')
        begins = instant(raw.get('starts_at'), 'original airing start')
        ends = instant(raw['ends_at'], 'original airing end') if raw.get('ends_at') else None
        if ends is not None and ends <= begins:
            raise PlannerValidationError('original airing end must follow its start')
        return cls(identity(raw.get('id'), 'original airing ID'), text(raw.get('asset_id'), 'original asset'), begins, ends,
                   identity(raw['track_id'], 'historical track') if raw.get('track_id') else None,
                   text(raw.get('source', ''), 'historical source', empty=True),
                   choice(raw.get('accuracy', 'exact'), ('exact', 'estimated'), 'historical accuracy'),
                   text(raw['substitute_id'], 'explicit substitute') if raw.get('substitute_id') else None,
                   flag(raw.get('rerun', False), 'original rerun'))


@dataclass(frozen=True)
class ProfileBinding:
    id: str
    version: int
    snapshot: dict
    assignments: tuple[tuple[str, str], ...]

    @classmethod
    def parse(cls, raw):
        raw = mapping(raw, {'id', 'version', 'snapshot', 'assignments'}, 'programming profile binding')
        snapshot = raw.get('snapshot', {})
        assignments = raw.get('assignments', {})
        if not isinstance(snapshot, dict) or not isinstance(assignments, dict):
            raise PlannerValidationError('profile snapshot and media bindings must be objects')
        if len(assignments) > 1000:
            raise PlannerValidationError('profile has too many assignments')
        from .profiles import validate_profile
        snapshot = validate_profile(snapshot)
        if snapshot['id'] != raw.get('id') or snapshot['version'] != raw.get('version'):
            raise PlannerValidationError('the embedded profile snapshot must match its pinned ID and version')
        if set(assignments) != {slot['id'] for slot in snapshot['slots']}:
            raise PlannerValidationError('each pinned profile slot needs an explicit channel-local assignment')
        return cls(identity(raw.get('id'), 'programming profile ID'), integer(raw.get('version'), 'profile version', 1),
                   _freeze(json.loads(json.dumps(snapshot, allow_nan=False))),
                   tuple((identity(slot, 'profile slot ID'), identity(track, 'bound track')) for slot, track in assignments.items()))


@dataclass(frozen=True)
class PlannerDefinition:
    start_at: datetime
    timezone: str
    groups: tuple[MediaGroup, ...]
    tracks: tuple[Track, ...]
    windows: tuple[AiringWindow, ...]
    layers: tuple[CalendarLayer, ...] = ()
    suspensions: tuple[Suspension, ...] = ()
    cycle: CycleRule = CycleRule()
    gap_filler: bool = True
    filler_asset_ids: tuple[str, ...] = ()
    historical_airings: tuple[HistoricalAiring, ...] = ()
    historical_mode: str = 'none'
    reference_year: int | None = None
    replay_start: date | None = None
    era_name: str = ''
    profile_bindings: tuple[ProfileBinding, ...] = ()
    dst_fold: str = 'first'
    dst_gap: str = 'next_valid'
    edit_effect: str = 'next_cycle'
    contract_version: str = '1.0'

    @classmethod
    def from_mapping(cls, raw):
        raw = mapping(raw, set(cls.__dataclass_fields__), 'broadcast planner')
        if raw.get('contract_version', '1.0') != '1.0':
            raise PlannerValidationError('unsupported broadcast planner contract version')
        zone = text(raw.get('timezone', 'UTC'), 'channel time zone')
        try:
            get_zone(zone)
        except (OSError, ModuleNotFoundError, ValueError) as exc:
            raise PlannerValidationError(f'Channel time zone {zone!r} is unavailable. Use an IANA zone from the packaged time-zone list.') from exc
        groups = tuple(MediaGroup.parse(item) for item in sequence(raw.get('groups', []), 'media groups', 1000))
        if sum(len(group.asset_ids) for group in groups)>100000:
            raise PlannerValidationError('a planner definition cannot contain more than 100000 total media references')
        tracks = tuple(Track.parse(item) for item in sequence(raw.get('tracks', []), 'progression tracks', 1000))
        windows = tuple(AiringWindow.parse(item) for item in sequence(raw.get('windows', []), 'airing windows'))
        layers = tuple(CalendarLayer.parse(item) for item in sequence(raw.get('layers', []), 'calendar layers', 1000))
        suspensions = tuple(Suspension.parse(item) for item in sequence(raw.get('suspensions', []), 'suspensions'))
        airings = tuple(HistoricalAiring.parse(item) for item in sequence(raw.get('historical_airings', []), 'original airings', 50000))
        bindings = tuple(ProfileBinding.parse(item) for item in sequence(raw.get('profile_bindings', []), 'profile bindings', 1000))
        for label, values in [('group', groups), ('track', tracks), ('window', windows), ('layer', layers), ('suspension', suspensions), ('airing', airings), ('profile binding', bindings)]:
            identities = [item.id for item in values]
            if len(identities) != len(set(identities)):
                raise PlannerValidationError(f'duplicate {label} ID')
        group_map, track_map, layer_map = ({item.id: item for item in values} for values in (groups, tracks, layers))
        if any(track.successor_id and track.successor_id not in track_map for track in tracks):
            raise PlannerValidationError('a progression track references an unknown successor')
        for track in tracks:
            if track.group_id not in group_map:
                raise PlannerValidationError(f'{track.id}: unknown media group {track.group_id}')
            if track.start_index >= len(group_map[track.group_id].asset_ids):
                raise PlannerValidationError(f'{track.id}: first episode is outside this media group')
            if track.successor_id and track.successor_id not in track_map:
                raise PlannerValidationError(f'{track.id}: unknown successor')
            seen = {track.id}
            successor = track.successor_id
            while successor:
                if successor in seen:
                    raise PlannerValidationError('successor tracks form a cycle; use the explicit media-loop option')
                seen.add(successor)
                successor = track_map[successor].successor_id
        for window in windows:
            if window.track_id not in track_map or window.layer_id and window.layer_id not in layer_map:
                raise PlannerValidationError(f'{window.id}: unknown track or calendar layer')
        namespaces = {'track':track_map, 'group':group_map, 'window':{w.id:w for w in windows}, 'layer':layer_map}
        for pause in suspensions:
            if pause.target in namespaces and pause.target_id not in namespaces[pause.target]:
                raise PlannerValidationError(f'{pause.id}: unknown suspension target')
        cycle = CycleRule.parse(raw.get('cycle'))
        references = set(cycle.required_tracks) | set(cycle.restart_tracks)
        if cycle.custom_gate:
            references.update(cycle.custom_gate.references())
        if references - set(track_map):
            raise PlannerValidationError('cycle conditions reference unknown progression tracks')
        if any(track_map[value].mode == 'rerun' for value in (cycle.custom_gate.references() if cycle.custom_gate else cycle.required_tracks)):
            raise PlannerValidationError('rerun tracks cannot be first-pass completion conditions')
        if any(airing.track_id and airing.track_id not in track_map for airing in airings):
            raise PlannerValidationError('an original airing references an unknown track')
        if any(track not in track_map for binding in bindings for _, track in binding.assignments):
            raise PlannerValidationError('a profile assignment references an unknown track')
        history = choice(raw.get('historical_mode', 'none'), ('none', 'era', 'original', 'replay'), 'historical scheduling')
        replay = day(raw.get('replay_start'), 'historical replay date')
        if history == 'replay' and replay is None:
            raise PlannerValidationError('choose a date to replay the original airings')
        result = cls(instant(raw.get('start_at'), 'broadcast start'), zone, groups, tracks, windows, layers, suspensions, cycle,
                   flag(raw.get('gap_filler', True), 'automatic gap filler'), ids(raw.get('filler_asset_ids', []), 'filler assets'),
                   tuple(sorted(airings, key=lambda item:(item.starts_at,item.id))), history,
                   integer(raw['reference_year'], 'reference year', 1900, 2500) if raw.get('reference_year') is not None else None,
                   replay, text(raw.get('era_name', ''), 'era name', empty=True), bindings,
                   choice(raw.get('dst_fold', 'first'), ('first', 'second'), 'repeated clock time'),
                   choice(raw.get('dst_gap', 'next_valid'), ('next_valid', 'skip'), 'skipped clock time'),
                   choice(raw.get('edit_effect', 'next_cycle'), ('next_cycle', 'safe_future'), 'active-cycle edit policy'))
        if cycle.restart_tracks and cycle.completion != 'none' and result.completion_satisfied(result.required_tracks - set(cycle.restart_tracks)):
            raise PlannerValidationError('The selected restart tracks leave the completion gate already satisfied. Reset a track required by each satisfied branch of the gate.')
        return result

    def to_mapping(self):
        def convert(value):
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, dict):
                return {key:convert(item) for key,item in value.items()}
            if isinstance(value, (tuple,list)):
                return [convert(item) for item in value]
            return value
        result = convert(asdict(self))
        for binding in result['profile_bindings']:
            binding['assignments'] = dict(binding['assignments'])
        return result

    @property
    def revision(self):
        return hashlib.sha256(json.dumps(self.to_mapping(), sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest()

    @property
    def required_tracks(self):
        if self.cycle.completion == 'none':
            return frozenset()
        if self.cycle.completion == 'custom':
            return self.cycle.custom_gate.references()
        if self.cycle.required_tracks or self.cycle.completion.startswith('selected_'):
            return frozenset(self.cycle.required_tracks)
        return frozenset(track.id for track in self.tracks if track.required and track.mode == 'primary')

    def completion_satisfied(self, completed):
        if self.cycle.completion == 'none':
            return True
        if self.cycle.completion == 'custom':
            return self.cycle.custom_gate.satisfied(completed)
        required = self.required_tracks
        if not required:
            return False
        return bool(required & set(completed)) if self.cycle.completion in {'any','selected_any'} else required <= set(completed)
