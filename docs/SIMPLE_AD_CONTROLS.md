# Simple ad controls — 0.0.5

Studio keeps its existing calendar, timeline and draft/apply workflow. The left
panel now has Media Bin and Ad Bin tabs. The Ad Bin shows selected indexed source
folders, their counts and expandable clip lists. Search stays within those
sources. Checkboxes exclude individual clips; canonical duplicates appear once.
Ads remain separate from program and normal filler pools, even when ads are off.

Classic New/Edit uses the same ad editor and Ad Bin. Editing an existing Classic
channel now round-trips its ad settings instead of dropping them.

## Ad Breaks

New ad setups start with one complete ad after every planned show. Ads remain
off until enabled. The selected clip's actual duration determines the break;
there is no 120-second budget in this mode.

- Sequential follows the visible source order and natural clip order.
- Shuffle uses a saved bag. Every eligible clip appears once per cycle, with no
  immediate repeat at a cycle boundary when at least two clips are available.
- Each channel has its own durable rotation. Actual watching and seeking do not
  consume extra queue entries. Restart and portable moves preserve reservations.
- Preview works in temporary state. Auto Fill reads a snapshot of existing
  rotation state and chooses exact clips in the detached draft. It does not
  advance the live queue.

Timed scheduling reveals two mutually exclusive choices and an interval selector
with 15 minutes, 30 minutes, one hour, or custom seconds/minutes/hours.

### Timed Ad Breaks

Use wall-clock marks plus an ad after each show. Pause the program for a whole
clip, then resume at its exact content position. Clock marks during an ad do not
create another ad. If a clock mark is within 30 seconds of the end of the show's
remaining content, defer it to the show ending and play one break there.

### Aligned Show Starts

Shows start on the selected clock grid. A long show spans multiple slots and
finishes normally. At least the first full queued ad must fit before the next
show; choose the next grid boundary that allows it. More whole ads fill that
window in queue order. If the next queued clip cannot fit, keep it for the next
break and use channel filler for the remainder. Filler and ads do not trigger ads.
Classic channels use filler until their first aligned show start.

Auto Fill stores exact ad reservations in the calendar blocks, so reopened
playback uses the same clips and times. Existing fixed starts remain protected;
invalid packed schedules are rejected before saving. Use Clear Range and Auto
Fill to rebuild an already filled range for a new timing policy.

## Advanced Ad Settings

The toolbar's Ad Catalog entry becomes Advanced Ad Settings. Its tabs are:

1. Break rules: explicit points, content intervals, fixed slots and placements.
2. Timing & fitting: duration, priority, Strict Fit/Smoosh/Expand, borrowing and
   schedule policy, with labels and units.
3. Playback: selection strategy and Cut/Fade/Hold transitions.
4. Profiles: saved collections, profiles and assignments, all IDs and technical
   configuration, with collapsible detail sections and named load selectors.

Opening Advanced changes no policy. Applying edited advanced rules activates
Custom settings; the simple popup shows that status and offers an explicit
Use simple settings action. Existing advanced channels retain their settings.
Placement-managed bins show their effective clips and direct edits to Profiles.

## Configuration and compatibility

Schema 0.6 adds `setup_mode`, `play_order`, `clock_interval_seconds` and
`clock_offset_seconds`, plus optional calendar `ad_plan` snapshots. Legacy
0.1–0.5 definitions remain supported. Their default ad policy signatures stay
unchanged. Channels without ads retain their earlier schema where possible.
New configurations need a build supporting schema 0.6.

Clock marks use the channel's saved UTC offset. Common 15/30/60-minute grids
continue to fall on the usual local clock marks. Portable copies normalize
snapshot policy revisions and media paths while retaining selected clips and
rotation state. The portable setup format and Library index format are unchanged.

Verification covers exact whole-clip selection, rotation/restart, wall-clock
resume positions, aligned starts, protected calendar boundaries, Qt map and
snapshot round-trips, Studio Auto Fill/Preview/Apply, dialog cancellation,
advanced profile controls, and portable copy/relocation.
