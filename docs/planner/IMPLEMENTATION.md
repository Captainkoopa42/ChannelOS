# Unified Broadcast Planner integration

Design baseline: `ChannelOS_Unified_Broadcast_Planner_Master_Plan_v0_3.md`
and `ChannelOS_Broadcast_Planner_Interactive_Demo_v0_4.html` (November 5, 2026).
Implementation starts from the verified Windows RC4 source
`54447f26c36f26cd63b8774abfc206e3380026fe`; its 551-test compatibility baseline
and performance work remain the release baseline.

The Planner is a third authoring path. Classic Builder and Manual Studio remain
valid. Portable definitions are the authoring authority; ChannelRuntime remains
the playout/Guide authority. The same deterministic planner compiler serves live
playout and read-only forecasts. Drafts never advance Broadcast/Viewer Clocks,
progression, ad viewing, or completion/cycle history.

## Implementation order

1. Typed groups, tracks, windows, calendar layers, suspensions, gates, profiles,
   original-airing records, stable occurrence identities, and version validation.
2. Pure bounded projection, fitting and source-offset handling, shared cursors,
   independent loops, first-pass milestones, safe cycle boundaries, DST rules.
3. Durable revision/cycle/completion records; actual-time reconciliation; reuse
   existing advertising plans and keep Viewer Clock operations independent.
4. Media-independent versioned profiles; pinned channel assignments; CSV/JSON
   historical imports; portable snapshots, channel archives, and rollback.
5. Integrated native Qt Planner, lazy calendar/forecast views, debounced worker
   previews, atomic Apply through the existing channel operation coordinator.
6. Whole-app regression, scale/cancellation, migration/portable recovery, and
   an independently labelled Windows test package. RC4 is not overwritten.

## Conservative policy defaults

- Strict fitting preserves full source media. Overrun and carryover are explicit.
- A media loop is independent from the channel cycle. First completion is sticky.
- Completion and date gates combine with AND; forced early/date-only behavior is
  explicit and identifies unfinished content.
- Active-cycle edits default to the next cycle. Historical occurrences and the
  current committed program/break structure remain protected.
- Missing historical items produce explained placeholders/blockers. A substitute
  is used only when explicitly mapped; era templates are labelled approximations.
- Ambiguous local times use the first fold by default; skipped local times move
  to the next valid instant. UTC bounds distinguish repeated local clock labels.
- Forecasts use deterministic declared choices; data-dependent uncertainty is
  labelled Estimated, while impossible or unknown conditions are explained.

## Completion gate for this feature

A multi-window 270-hour series, later-finishing second collection, scoped holiday
suspension, ALL/date gate, safe restart, Apply, and closed-app catch-up must agree
across Planner, Guide, live selection and persisted history. Independent loops,
Air Once & Done, two-channel profile isolation, ads/resume, DST and old channels
are required regression cases. A screen or forecast alone is not completion.
