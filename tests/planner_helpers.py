from copy import deepcopy


def planner_rules(**changes):
    raw = {
        'start_at':'2026-06-01T00:00:00+00:00', 'timezone':'UTC',
        'groups':[{'id':'show','name':'Series A','asset_ids':['episode-1','episode-2','episode-3']}],
        'tracks':[{'id':'primary','group_id':'show','post_completion':'filler'}],
        'windows':[{'id':'noon','track_id':'primary','start':'12:00','end':'15:00',
                    'bracket_minutes':60,'scope':{'weekdays':[0,1,2,3,4]}}],
        'gap_filler':False,
    }
    raw.update(deepcopy(changes))
    return raw
