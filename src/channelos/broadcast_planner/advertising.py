"""Detached adapters to ChannelOS's existing ad selectors and whole-clip rotation."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import math

from ..ad_break_engine import BreakPlan, BreakOpportunity, ProgramOccurrence
from ..ad_scheduling import eligible_media, program_opportunities, select_segments, configured_policies, calendar_gap_policy
from ..simple_ads import SimpleRotation, plan_program


class AdPlanner:
    def __init__(self, media, ad_media, settings, revision, channel):
        self.media = {m.asset.asset_id:m for m in media}
        self.ads = tuple(m for m in ad_media if m.location.online and m.asset.duration_seconds is not None
                         and math.isfinite(float(m.asset.duration_seconds)) and m.asset.duration_seconds>0)
        self.settings = settings
        self.revision, self.channel = revision, channel
        self.rotation = SimpleRotation(eligible_media(self.ads, settings), settings, channel)
        active = [(trigger,policy) for _,trigger,policy in configured_policies(settings) if settings.enabled and policy.enabled]
        usable = any(eligible_media(self.ads,policy) for _,policy in active) if settings.setup_mode=='advanced' else bool(self.rotation.media)
        needed = bool(active) if settings.setup_mode=='advanced' else settings.enabled
        self.invalid_reason = 'No eligible advertising clips have a finite duration and an online location.' if needed and not usable else None
        self.counts = {}

    def snapshot(self):
        return {'cycle': self.rotation.cycle, 'remaining':list(self.rotation.remaining),
                'previous':self.rotation.previous, 'counts':dict(self.counts),'revision':self.rotation.revision}

    def restore(self, raw):
        if raw.get('revision',self.rotation.revision)!=self.rotation.revision:
            return
        self.rotation.cycle, self.rotation.remaining = raw['cycle'], list(raw['remaining'])
        self.rotation.previous, self.counts = raw['previous'], dict(raw['counts'])

    def plan(self, asset_id, start, occurrence, limit, *, source_offset=0,content_seconds=None,include_after=True):
        if self.invalid_reason:
            raise ValueError(self.invalid_reason)
        item = self.media[asset_id]
        seconds = float(item.asset.duration_seconds)-source_offset if content_seconds is None else content_seconds
        if self.settings.setup_mode != 'advanced':
            remaining = replace(item,asset=replace(item.asset,duration_seconds=seconds))
            return plan_program(remaining, start, self.settings, self.revision, self.channel,
                                occurrence, self.rotation, next_start=limit,after_program=include_after)
        end = start+timedelta(seconds=seconds)
        parent = ProgramOccurrence(occurrence, self.channel, asset_id, start-timedelta(seconds=source_offset), end)
        plans, shift = [], 0.0
        opportunities=list(program_opportunities(self.settings,parent,self.revision))
        gap=calendar_gap_policy(self.settings)
        if include_after and gap and gap[1]=='calendar_boundary':
            identity,trigger,policy=gap
            key=hashlib.sha256(f'{occurrence}:{self.revision}:{identity}:calendar-gap'.encode()).hexdigest()
            opportunities.append((BreakOpportunity(key,occurrence,self.channel,trigger,parent.ends_at,policy.break_duration_seconds,policy.priority),policy))
        for opportunity, policy in sorted(opportunities,key=lambda pair:(pair[0].scheduled_at,pair[0].opportunity_id)):
            if opportunity.scheduled_at<start:
                continue
            if not include_after and opportunity.trigger not in {'breakpoint','interval'}:
                continue
            pool = eligible_media(self.ads, policy)
            segments = select_segments(pool, opportunity.duration_seconds, policy,
                seed=opportunity.opportunity_id, counts=self.counts,
                expand_max_seconds=policy.expand_max_seconds if policy.timing_policy == 'expand' else 0)
            if not segments:
                continue
            duration = max(p.start_offset_seconds+p.duration_seconds for p in segments)
            at = opportunity.scheduled_at+timedelta(seconds=shift)
            if end+timedelta(seconds=shift+duration) > limit:
                raise ValueError('The program and complete configured ad break do not fit this bracket.')
            plans.append(BreakPlan(opportunity.opportunity_id, opportunity.opportunity_id, occurrence,
                self.channel, at, duration, segments, policy.selection_strategy, policy.timing_policy,
                trigger=opportunity.trigger, policy_revision=self.revision,
                transition_behavior=policy.transition_behavior, transition_seconds=policy.transition_seconds))
            shift += duration
            for part in segments:
                if part.event_type == 'advertisement':
                    self.counts[part.asset_id] = self.counts.get(part.asset_id,0)+1
        return tuple(plans), end+timedelta(seconds=shift)

    def plan_partial(self, asset_id, start, occurrence, limit, source_offset):
        """Fit an explicit carryover prefix and whole mid-show interruptions.

        After-show ads belong only to the final prefix. If content alone would
        finish but its ad cannot fit, reserve that ad's capacity and carry the
        remaining content into the next window. Never create a zero-content
        completion or silently drop a configured mid-show break.
        """
        remaining = float(self.media[asset_id].asset.duration_seconds)-source_offset
        budget = (limit-start).total_seconds()
        initial = self.snapshot()
        upper = min(remaining,budget)
        if remaining<=budget:
            try:
                _, full_end = self.plan(asset_id,start,occurrence,start+timedelta(days=366),source_offset=source_offset)
                upper = min(upper,budget-((full_end-start).total_seconds()-remaining))
            finally:
                self.restore(initial)
        low,high=1,int(upper*1000)
        best=None
        while low<=high:
            middle=(low+high)//2
            self.restore(initial)
            try:
                plans,end=self.plan(asset_id,start,occurrence,limit,source_offset=source_offset,
                                    content_seconds=middle/1000,include_after=False)
                best=(plans,end,middle/1000,self.snapshot())
                low=middle+1
            except ValueError:
                high=middle-1
        if best is None:
            self.restore(initial)
            raise ValueError('A complete configured ad interruption cannot fit this carryover bracket.')
        self.restore(best[3])
        return best[:3]
