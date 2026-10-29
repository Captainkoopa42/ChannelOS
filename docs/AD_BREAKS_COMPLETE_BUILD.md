# Advertisement Breaks — Complete Build Plan

This document defines the complete advertisement system built on top of the alpha implementation. It is an implementation contract, not a claim that every listed capability is already shipped.

## Non-negotiable runtime invariants

1. `ChannelRuntime` remains the sole authority for what is airing at a broadcast timestamp. The Guide is a read-only projection of that timeline.
2. Ads remain a separate media scope in the canonical Library. Adding an ad source must never add those assets to ordinary program or filler pools.
3. Broadcast time is independent of viewer tune time. Tuning, seeking, pausing, or restarting a viewer must not move the channel schedule.
4. An ad break is a scheduled interruption of a program occurrence. The interrupted program's original start/end and content offset remain recoverable; after the break, playback resumes at the exact content position implied by the broadcast clock.
5. Break plans are deterministic and immutable once committed for an airing opportunity. A restart or a second viewer must not produce a different ad sequence for the same opportunity.
6. A schedule edit may invalidate future plans, but must not silently rewrite an already-airing break.
7. All timing arithmetic uses timezone-aware UTC instants and bounded durations. No policy may silently overrun a hard scheduled boundary.

## Accepted product decisions

- Per-channel scheduling priority.
- Both explicitly configured breakpoints and automatic interval triggers.
- Per-channel Expand policy.
- Per-profile default ad-selection strategy.
- One shared broadcast timeline, with Guide/HUD as projections of runtime state.

## Complete feature set

### Scheduling
- Fixed calendar-gap insertion (alpha).
- Configured breakpoints within program occurrences.
- Automatic interval breaks.
- Break opportunities identify channel, program occurrence, trigger type, scheduled timestamp, and priority.
- Overlapping opportunities are resolved deterministically using per-channel priority and stable tie-breaking.

### Collections and profiles
- Reusable ad collections referencing canonical Library asset IDs.
- Reusable break profiles defining default strategy, trigger defaults, transition defaults, and timing policy defaults.
- Per-channel profile assignment and explicit per-channel overrides.
- Channel definitions remain portable; profile/collection persistence must have stable IDs and validation.

### Selection and rotation
- Best Fit, Largest, Smallest, Sequential, Least Played, and Complete Rotation.
- Persistent play history keyed by stable asset ID and committed airing plan.
- Deterministic tie-breaking and a clear behavior for unavailable/offline assets.
- A committed plan is shared by all viewers and survives application restarts.

### Timing policies
- Strict Fit: only complete ads that fit.
- Smoosh: allow configured trimming to fit a bounded opportunity, with minimum-duration and trim-limit validation.
- Expand: per-channel policy may borrow within configured limits from the following content boundary; it must never silently move a fixed calendar start.
- If no legal plan exists, use the channel's configured fallback (filler or leave-gap) rather than breaking timeline invariants.

### Playback and presentation
- Mid-program ad insertion and exact content resumption.
- Configurable fade/transition behavior with safe defaults and no accidental overlap in the authoritative clock.
- Guide rows expose break markers while preserving the parent program occurrence.
- Now/Next identifies an active advertisement as an ad break and retains the interrupted program context.
- Playback HUD shows an ad-break indicator and, where available, break progress.

## Architecture

- **BreakOpportunityScheduler**: derives explicit and interval opportunities from program occurrences and channel/profile policy.
- **AdSelectionEngine**: selects assets from collections using strategy and history.
- **BreakPlanStore**: persists immutable plans, plan segments, and play history in SQLite with schema migrations and transactional commits.
- **ChannelRuntime**: resolves the authoritative event at a broadcast instant, including program, ad, and filler segments.
- **TelevisionSession**: executes the selected segment and transitions without changing the broadcast clock.
- **GuideService**: projects parent program occurrences and their break markers from runtime state; it does not schedule ads.
- **Channel Studio**: edits collections, profiles, breakpoints, intervals, priority, policies, and previews validated plans.

## Delivery phases

1. **Timeline and persistence foundation** — introduce typed break policy/trigger/profile/collection definitions, stable occurrence IDs, SQLite migrations, immutable plan storage, and backwards-compatible schema migration.
2. **Opportunity scheduling and playback** — configured and interval triggers, priority arbitration, mid-program insertion, and exact resume.
3. **Selection and history** — all strategies, durable history, collection/profile assignment, deterministic multi-viewer/restart behavior.
4. **Timing and transitions** — Smoosh/Expand rules, bounded timing validation, and fade/transition execution.
5. **Studio, Guide, HUD, and release hardening** — complete editing UI, Guide markers, Now/Next/HUD states, migration tests, restart tests, and Windows packaging.

## Required verification

- Legacy schema 0.1–0.4 channels load unchanged and remain ad-disabled unless configured.
- Same broadcast timestamp yields the same committed segment for every viewer and after restart.
- Mid-program breaks resume the interrupted content at the exact expected source offset.
- Configured and interval triggers are deterministic and priority arbitration is stable.
- History commits exactly once per aired segment, including crash/restart boundaries.
- Smoosh respects minimum-duration and trim limits; Expand respects channel policy and never shifts a fixed calendar start.
- Guide output is a faithful projection of runtime segments and never mutates plans.
- Offline/missing assets and invalid profiles fail validation safely.
- Existing runtime, Guide, Studio, and Windows build tests remain green.
