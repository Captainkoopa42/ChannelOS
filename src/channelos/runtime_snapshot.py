"""Consistent channel-scoped authoring snapshots without copying other archives."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .ad_break_engine import BreakPlanStore
from .portable import find_setup
from .runtime import RuntimeStore

CHANNEL_TABLES = (
    'channel_runtime', 'viewer_runtime', 'ad_break_plans', 'ad_plan_metadata',
    'ad_break_history', 'ad_view_history', 'ad_view_progress', 'ad_retired_plans',
    'ad_history_review', 'ad_program_clock', 'ad_break_policy_state',
    'ad_break_catchup_state', 'ad_calendar_state', 'ad_superseded_plans',
    'planner_revisions', 'planner_checkpoints', 'planner_occurrences', 'planner_completions', 'planner_cycles', 'planner_legacy', 'planner_manual_releases', 'planner_failures',
)


def restore_channel_snapshot(snapshot_path, live_path, channel_number):
    """Rollback only this operation's station, retaining other live stations."""
    with closing(sqlite3.connect(snapshot_path)) as source, closing(sqlite3.connect(live_path)) as target:
        source.execute('BEGIN')
        target.execute('PRAGMA foreign_keys=ON')
        tables = {row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with target:
            for table in reversed(CHANNEL_TABLES):
                if table not in tables:
                    continue
                columns = [row[1] for row in target.execute(f'PRAGMA table_info({table})')]
                where = 'channel_number=?' if 'channel_number' in columns else 'plan_id IN (SELECT plan_id FROM ad_break_plans WHERE channel_number=?)'
                target.execute(f'DELETE FROM {table} WHERE {where}', (channel_number,))
            for table in CHANNEL_TABLES:
                if table not in tables:
                    continue
                columns = [row[1] for row in source.execute(f'PRAGMA table_info({table})')]
                if not columns:
                    continue
                where = 'channel_number=?' if 'channel_number' in columns else 'plan_id IN (SELECT plan_id FROM ad_break_plans WHERE channel_number=?)'
                rows = source.execute(f'SELECT * FROM {table} WHERE {where}', (channel_number,))
                target.executemany(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", rows)


def channel_snapshot(source_path, target_path, channel_number: int) -> RuntimeStore:
    target = RuntimeStore(target_path)
    destination = BreakPlanStore(target_path)
    try:
        path = Path(source_path)
        if path.is_file():
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as source:
                source.execute('BEGIN')
                tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                with destination.connection:
                    for table in CHANNEL_TABLES:
                        if table not in tables:
                            continue
                        columns = [row[1] for row in source.execute(f'PRAGMA table_info({table})')]
                        where = ('channel_number=?' if 'channel_number' in columns else
                                 'plan_id IN (SELECT plan_id FROM ad_break_plans WHERE channel_number=?)')
                        rows = source.execute(f'SELECT * FROM {table} WHERE {where}', (int(channel_number),))
                        destination.connection.executemany(
                            f"INSERT OR REPLACE INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", rows)
        target._break_schema_ready = True
        target._snapshot_portable = find_setup(source_path)
        return target
    finally:
        destination.close()
