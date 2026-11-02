# Advertisement Breaks — Development Guide (v0.5)

This document replaces the original calendar-only alpha instructions. The
advertising feature is **opt-in** and uses the same canonical Library index as
ordinary television programming, but commercial assets are resolved in their
own pool. The currently active development branch is
`feature/ad-breaks-complete`; this is not yet a release claim.

## Try the ad system

1. Start ChannelOS with an indexed Library. Add your ad folder through Library
   and scan it so every commercial has a stable asset ID and duration.
2. Open **Channel Studio**. Use **Ad Catalog** to save a fixed collection of
   canonical asset IDs, or a dynamic collection of indexed source folders.
   Optionally exclude asset IDs.
3. Save a **Break Profile** with timing and selection defaults. The catalog
   supports `best_fit`, `largest`, `smallest`, `sequential`,
   `least_played`, and `complete_rotation` selection.
4. Assign the collection and profile to the current channel. An assignment
   remains authoring data until you **Apply** the Studio channel.
5. In **Ad Breaks**, enable advertising, supply sources or asset IDs, and
   configure breakpoints, intervals, duration, and timing policy. Existing
   reusable catalog assignments provide the effective settings on apply.
6. Use **Preview Ad Schedule** to inspect sample events. Applying the Studio
   draft writes a portable v0.5 channel YAML containing the effective policy
   and canonical asset IDs. Channel playback does not need the Studio catalog.
7. Tune the channel during a break: the authoritative runtime computes the
   advertisement and the correct media offset, then resumes normal content.
   The Live HUD shows an AD badge.

For fixed calendar channels, ads fill *bounded gaps between programs*. They
cannot delay the next fixed UTC calendar block. For sequential channels, ads
can be triggered by program-content breakpoints and intervals. Runtime plans
are saved in SQLite and recovered on restart. Older schema 0.1–0.4 definitions
remain readable.

## Policies and diagnostics

- **Strict Fit** schedules only ads that fully fit a break.
- **Smoosh** permits trimming only within configured limits.
- **Expand** can extend sequential breaks within its explicit budget; calendar
  expansion is disabled at protected fixed starts.
- Completed scheduled airings and verified viewer ad completions use *separate*
  ledgers. Tuning into an ad or skipping over it does not count as a completed
  viewing.
- **Ad Catalog → Current Channel Diagnostics** reports committed plans, aired
  segments, watched segments, and last logical airing.

## Known release blockers

This is still in-progress development. See
[AD_BREAKS_COMPLETE_BUILD.md](AD_BREAKS_COMPLETE_BUILD.md) for the complete
design contract and verification requirements. Remaining features include
runtime execution of fade/hold transitions, full offline catch-up planning,
richer per-placement profile selection, protected schedule-expansion policies,
and end-to-end native decoder/controller validation. Do not label Phases A–E
fully shipped until all verification gates pass.
