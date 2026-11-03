"""Prepare bounded Studio model publications away from the Qt GUI thread."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def prepare_publication(result, editor, media, groups=()):
    by_id = {str(item['assetId']): item for item in media}
    group_names = {(str(group['mode']), tuple(group['assetIds'])): group['name'] for group in groups}

    def instant(text):
        value = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
        if value.tzinfo is None:
            raise ValueError('Studio publication requires timezone-aware starts')
        return value.astimezone(timezone.utc)

    def key(block):
        return instant(block['startUtc']), str(block['assetId'])

    updates = {key(block): block for block in result.get('updatedBlocks', ())}
    blocks = [dict(block, **updates.get(key(block), {})) for block in editor.get('calendarBlocks', ())]
    blocks.extend(result.get('blocks', ()))
    if len(blocks) > 10000:
        raise ValueError('This result would exceed the 10,000-block calendar limit')
    blocks.sort(key=key)
    rebuild = instant(result['rebuildFromUtc']) if result.get('rebuildFromUtc') else None
    rows, days = [], {}
    previous_end = None
    for block in blocks:
        item = by_id.get(str(block['assetId']), {})
        duration = float(block.get('durationSeconds') or item.get('durationSeconds') or 0)
        if duration <= 0:
            raise ValueError('A scheduled program no longer has a positive indexed duration')
        start = instant(block['startUtc'])
        end = start + timedelta(seconds=duration)
        saved = block.get('adPlan')
        if rebuild is not None and start >= rebuild:
            saved = None
        if saved and instant(saved['start_utc']) == start:
            end = max(end, instant(saved['end_utc']))
        if previous_end is not None and start < previous_end:
            raise ValueError('Auto Fill detected a schedule overlap. No draft changes were made.')
        previous_end = end
        filler_ids = list(block.get('fillerAssetIds', ()))
        filler_mode = str(block.get('fillerMode') or '')
        row = {
            'assetId': str(block['assetId']), 'title': str(item.get('title', 'Unavailable media')),
            'path': str(item.get('path', '')), 'sourceRoot': str(item.get('sourceRoot', '')),
            'durationSeconds': duration,
            'startUtc': start.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'endUtc': end.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'adPlanJson': json.dumps(saved, separators=(',', ':')),
            'fillerMode': filler_mode, 'fillerAssetIdsJson': json.dumps(filler_ids),
            'fillerGroupName': str(group_names.get((filler_mode, tuple(filler_ids)), 'Embedded group' if filler_ids else '')),
        }
        rows.append(row)
        day = start.astimezone().date().isoformat()
        days.setdefault(day, []).append({
            **{name: row[name] for name in ('assetId', 'title', 'path', 'sourceRoot', 'durationSeconds', 'startUtc', 'endUtc')},
            'modelIndex': len(rows) - 1,
        })
    return {**result, 'preparedRows': rows, 'preparedDays': days}
