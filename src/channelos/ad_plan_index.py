"""Derived, recoverable time indexes over immutable advertising plans.

Canonical plans and airing/viewing history remain the source of truth. Triggers
journal edits, imports, restores and other connections without copying history
into every playback refresh. No JSON SQL extension is required.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def install(connection):
    connection.executescript('''
        CREATE INDEX IF NOT EXISTS idx_ad_break_plans_occurrence ON ad_break_plans(occurrence_id, scheduled_at);
        CREATE TABLE IF NOT EXISTS ad_plan_bounds (
            plan_id TEXT PRIMARY KEY REFERENCES ad_break_plans(plan_id) ON DELETE CASCADE,
            channel_number INTEGER NOT NULL, starts_at REAL NOT NULL,
            reserved_end REAL NOT NULL, actual_end REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_ad_plan_bounds_range ON ad_plan_bounds(channel_number,reserved_end,starts_at);
        CREATE INDEX IF NOT EXISTS idx_ad_plan_bounds_active ON ad_plan_bounds(channel_number,actual_end,starts_at);
        CREATE TABLE IF NOT EXISTS ad_pending_airings (
            plan_id TEXT NOT NULL REFERENCES ad_break_plans(plan_id) ON DELETE CASCADE,
            segment_index INTEGER NOT NULL, channel_number INTEGER NOT NULL,
            asset_id TEXT NOT NULL, ends_at REAL NOT NULL,
            PRIMARY KEY(plan_id,segment_index));
        CREATE INDEX IF NOT EXISTS idx_ad_pending_airings_due ON ad_pending_airings(channel_number,ends_at);
        CREATE TABLE IF NOT EXISTS ad_plan_index_changes(plan_id TEXT PRIMARY KEY,channel_number INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_ad_plan_changes_channel ON ad_plan_index_changes(channel_number);
        CREATE TABLE IF NOT EXISTS ad_plan_cache_generation (singleton INTEGER PRIMARY KEY CHECK(singleton=1), value INTEGER NOT NULL);
        INSERT OR IGNORE INTO ad_plan_cache_generation VALUES(1,0);
    ''')
    for table in ('ad_break_plans', 'ad_plan_metadata', 'ad_retired_plans'):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            prefix = 'OLD' if event == 'DELETE' else 'NEW'
            selection = (f'SELECT {prefix}.plan_id, {prefix}.channel_number' if table == 'ad_break_plans'
                         else f'SELECT plan_id,channel_number FROM ad_break_plans WHERE plan_id={prefix}.plan_id')
            connection.execute(f'''CREATE TRIGGER IF NOT EXISTS cos_index_{table}_{event.lower()}
                AFTER {event} ON {table} BEGIN
                  INSERT OR REPLACE INTO ad_plan_index_changes(plan_id,channel_number) {selection};
                  UPDATE ad_plan_cache_generation SET value=value+1 WHERE singleton=1; END''')
    connection.executescript('''
        CREATE TRIGGER IF NOT EXISTS cos_index_history_insert AFTER INSERT ON ad_break_history BEGIN
            DELETE FROM ad_pending_airings WHERE plan_id=NEW.plan_id AND segment_index=NEW.segment_index; END;
        CREATE TRIGGER IF NOT EXISTS cos_index_history_delete AFTER DELETE ON ad_break_history BEGIN
            INSERT OR REPLACE INTO ad_plan_index_changes(plan_id,channel_number)
            SELECT plan_id,channel_number FROM ad_break_plans WHERE plan_id=OLD.plan_id; END;
        INSERT OR IGNORE INTO ad_plan_index_changes(plan_id,channel_number)
            SELECT p.plan_id,p.channel_number FROM ad_break_plans p
            LEFT JOIN ad_plan_bounds b ON b.plan_id=p.plan_id WHERE b.plan_id IS NULL;
    ''')
    connection.commit()


def sync(connection, *, channel_number=None, plan_id=None):
    where, values = '', ()
    if plan_id is not None:
        where, values = ' WHERE j.plan_id=?', (str(plan_id),)
    elif channel_number is not None:
        where, values = ' WHERE j.channel_number=?', (int(channel_number),)
    # A savepoint respects callers that already own a larger transaction.
    connection.execute('SAVEPOINT cos_sync_plan_index')
    try:
        changed = connection.execute('''SELECT j.plan_id,j.channel_number,p.scheduled_at,
            p.reserved_seconds,p.payload,r.plan_id FROM ad_plan_index_changes j
            LEFT JOIN ad_break_plans p ON p.plan_id=j.plan_id
            LEFT JOIN ad_retired_plans r ON r.plan_id=j.plan_id''' + where, values).fetchall()
        if not changed:
            connection.execute('RELEASE cos_sync_plan_index')
            return ()
        completed = {(str(row[0]), int(row[1])) for row in connection.execute('''
            SELECT h.plan_id,h.segment_index FROM ad_break_history h
            JOIN ad_plan_index_changes j ON j.plan_id=h.plan_id''' + where, values)}
        bounds, pending, identities = [], [], []
        for identity, channel, text, reserved, payload, retired in changed:
            identities.append((str(identity),))
            if text is None:
                continue
            start = datetime.fromisoformat(str(text))
            if start.tzinfo is None:
                raise ValueError('An advertising plan has no UTC offset')
            start = start.astimezone(timezone.utc)
            segments = json.loads(payload)
            finish = max((float(part['start_offset_seconds']) + float(part['duration_seconds']) for part in segments), default=0)
            bounds.append((identity,channel,start.timestamp(),(start+timedelta(seconds=float(reserved))).timestamp(),(start+timedelta(seconds=finish)).timestamp()))
            if retired is not None:
                continue
            for index, segment in enumerate(segments):
                if segment.get('event_type','advertisement') == 'advertisement' and (str(identity),index) not in completed:
                    ended = start + timedelta(seconds=float(segment['start_offset_seconds'])+float(segment['duration_seconds']))
                    pending.append((identity,index,channel,str(segment['asset_id']),ended.timestamp()))
        connection.executemany('DELETE FROM ad_pending_airings WHERE plan_id=?',identities)
        connection.executemany('DELETE FROM ad_plan_bounds WHERE plan_id=?',identities)
        connection.executemany('INSERT INTO ad_plan_bounds VALUES(?,?,?,?,?)',bounds)
        connection.executemany('INSERT INTO ad_pending_airings VALUES(?,?,?,?,?)',pending)
        connection.executemany('DELETE FROM ad_plan_index_changes WHERE plan_id=?',identities)
        connection.execute('RELEASE cos_sync_plan_index')
        return tuple(value[0] for value in identities)
    except Exception:
        connection.execute('ROLLBACK TO cos_sync_plan_index')
        connection.execute('RELEASE cos_sync_plan_index')
        raise
