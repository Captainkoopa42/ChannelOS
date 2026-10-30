# ChannelOS broadcast advertising — implementation and acceptance

Updated October 30, 2026. This describes the ad feature on
`feature/ad-breaks-complete`, targeting `agent/broadcaster-channel-builder`.
The A–F letters below refer to the advertising roadmap, not the application's
older numbered development phases. Release validation is separate from feature
implementation: the checks below must pass on the commit being distributed.

## Phase A — runtime architecture

`ChannelRuntime` owns one broadcast timeline. `BroadcastSelection` retains the
original program occurrence, while its `BroadcastEvent` describes the selected
program, advertisement, filler or transition segment. `segment_id`, segment UTC
boundaries and source offset boundaries identify precise decoder work without
changing the parent program's identity. `events_between()` materializes that
same timeline for diagnostics and Studio.

Program schedule signatures and advertising signatures are independent. Ad
policy edits retain the channel epoch, viewer clock, started breaks and
history-bearing plans; unstarted future decisions can be invalidated.
Disabling ads preserves already committed historical timing and finishes an
active break. A changed sequential program schedule retires the old ad clock
while retaining completed history.

SQLite stores immutable plans, their policy/transition snapshots, source
locations, program clock mappings, catch-up checkpoints and separate airing and
viewer ledgers. Plans are committed before they can be exposed to playback.
Queries into the past reuse those decisions. Guide and viewer projections use
`project_at()` and cannot record future content as aired.

## Phase B — collections, profiles and portable channels

Studio manages collections over canonical Library asset IDs. Fixed collections
pin explicit assets. Dynamic collections retain indexed folder selectors and
exclusions as well as their applied asset snapshot. New indexed files become
eligible after the Library scan refreshes the runtime. Already committed plans
remain unchanged. Collection sources are excluded from program/filler pools,
including when the channel's normal source is a parent of the ad folder.

Reusable profiles provide strategy, triggers, duration, trim/expansion limits and
transition defaults. Assignments retain explicit channel overrides. Independent
placement assignments can use different collections and profiles for in-program
breaks, between-program breaks and slot/gap filling. Applied channels contain
effective policy snapshots; playback does not require Studio's catalog database.

Schema 0.4 advertising remains supported. Full portable snapshots use schema
0.5, which was already introduced on this branch. Versions 0.1–0.5 continue to
load; channels remain ad-disabled unless configured. Catalog migrations retain
older JSON-list collections and assignments without placement columns.

## Phase C — calendar and gap scheduling

Calendar gaps use committed ad plans. Between-program and fixed-slot placements
use the same selector as program interruptions. Strict Fit, Smoosh and legal
Expand budgets are resolved before a plan is published. Calendar filler is
clipped at the next protected fixed start. Sequential fixed slots reserve any
unfilled remainder with explicitly typed, timed filler, so the next show cannot
start early merely because no combination of ads fills the slot.

`slot_seconds` supports quarter-hour, half-hour, hour or custom slot sizes.
Content duration and broadcast duration remain distinct. Fixed calendar starts
are never silently shifted by advertising.

## Phase D — interruptions and resume

Explicit source-content breakpoints and interval triggers share opportunity
generation and deterministic overlap arbitration. Placement priority resolves
collisions. Sequential, deterministic shuffle and fixed-calendar programs all
produce program/ad/transition segments with exact content-resume mapping.
Persistent program clock rows eliminate iterative estimates of accumulated ad
time, including after long shutdowns. Watch from Beginning follows the program's
scheduled source start, including an explicitly configured content borrow.

## Phase E — selection, history and timing

Strategies include Best Fit, Largest, Smallest, Sequential, Least Played and
Complete Rotation. Best Fit uses exact subset fitting for up to fourteen assets
and a bounded deterministic fallback for larger pools. Individual ads do not
repeat within a selection. Complete Rotation orders eligible candidates by
rotation count, with stable ties and duration constraints; ads that cannot fit
a particular opportunity remain eligible for a later one.

Rotation is channel-local and uses earlier committed reservations. It therefore
does not depend on whether the Guide was opened first or another channel was
watched. Completed aired counts are written only when a real broadcast-time
observation reaches the segment end. Restart catch-up generates missing
sequential/shuffle occurrences and calendar gaps in chronological order. Work is
bounded to 10,000 occurrences per catch-up request, with a durable checkpoint.

Viewer history is independent. It records verified decoder progress, merges
unique source-coverage ranges across rewind/restart, retains partial completion,
and records a full viewing only after sufficient coverage. Seeking across an ad
cannot count as watching it. Diagnostics expose aired counts, watched counts,
last airing/viewing and viewer completion rate.

Smoosh respects minimum duration and maximum trim. Expand is explicitly bounded:

| Source / priority | Behavior |
| --- | --- |
| `schedule_shift`, sequential/shuffle | Delay following programming within the extra-time allowance, preserving content. |
| `available_slot_time`, calendar | Consume available slack without moving the next fixed start. |
| `current_program`, advertising priority | Borrow only the permitted tail of the current program, with a persisted content cut. Calendar boundaries remain protected. |
| `next_event`, advertising priority, sequential/shuffle | Borrow only permitted leading content from the next program, with a persisted source-start cut. |
| `next_event` or `schedule_shift`, calendar | Use the permitted calendar slack; a protected fixed event is never borrowed or moved. |
| Fixed priority | Do not expand past the requested break budget. |

Borrowing content requires the explicit **Prioritize ads** setting. The default
preserves program content. Fixed-slot boundaries stay protected under every
priority.

## Phase F — broadcast presentation, playback and recovery

Guide rows preserve parent shows and expose compact amber break markers,
including within short-form visual groups. Now/Next recognizes an active break
and its returning program. The Live HUD exposes the ad indicator, parent title,
break boundaries and remaining time.

Studio offers ordinary controls for profiles, placement assignments, transition
duration, fixed slots, scheduling priority and expansion source. Advanced JSON
overrides are optional. Preview resolves an isolated full event timeline and
returns segment/source boundaries and diagnostics without writing live history.

Playback implements:

- **Cut**: load/seek the authoritative next segment.
- **Fade through black**: apply independent video brightness and audio gain
  envelopes within scheduled media time. User volume and mute remain independent.
- **Hold last frame**: reserve a typed transition event in the plan, seek the
  preceding ad's last frame, and hold it without moving the viewer or broadcast
  clocks. Transition time is fitted together with media time.

Fade through black uses the existing single decoder; this is not an overlapping
two-decoder crossfade. Profiles identify the actual supported behavior.

Pause, rewind, Go Live and channel changes keep their existing clock semantics.
A failed ad decoder can recover at the following authoritative program boundary.
Offline ad sources do not prevent the channel's program runtime from opening;
Studio validation still reports missing/offline references. Failed viewer
playback never counts as verified consumption.

## Verification and distribution gates

`tests/test_ad_broadcast_integration.py` exercises complete workflows rather than
only individual helpers: Guide/look-ahead parity, long offline recovery,
channel-local rotation, placement snapshots, dynamic membership, protected
calendar boundaries, content borrowing, fixed-slot fallback, ad disabling,
partial viewing/rewind, decoder failure, schema compatibility and schedule edits.
The existing runtime, Guide, Studio, playback and migration suites remain part of
the required run. `test_channel_studio_qml_runtime.py` also drives the actual ad
settings and placement controls and checks cancellation/restoration.

Required checks for each release candidate:

1. Full pytest suite on Python 3.11, 3.12 and 3.13.
2. Headless Couch/QML loading and interaction tests.
3. Windows locked-environment tests, portable package build and package audit.
4. `tools/windows/smoke_ad_playback.py`: native Qt HWND with the bundled libVLC,
   generated AVI fixtures, real cut/fade/hold playback, transitions, native video
   output and preservation of audio controls. CI requests GDI video output and software decoding; physical audio output is
   checked separately from retained volume/mute intent.
5. Publish the Windows artifact only after the preceding Windows gates pass.

The automated native check does not replace validation of D3D11 hardware decode,
fullscreen/window transitions and physical audio output on the user's own PC.
Those remain real-machine release checks; do not report them as performed by a
headless or software-output runner.
