# Channel continuity (Beta 2)

A quick channel (Sequential or Shuffle) never restarts unless you ask it to.
Adding, removing or re-probing media, closing ChannelOS, a missing drive or a
clock correction does not interrupt what is on air, lose your place, or
rewrite the Guide's past.

Calendar and Planner channels already kept their clocks and are unchanged.

## Why this exists

Beta 1 (`4b5bb89`) stored one start time (`epoch_utc`) and a fingerprint of
the channel's inputs. A change to the fingerprint reset the epoch to *now* and
deleted the viewer position. GPT reproduced this against the released code:

| Change | Beta 1 |
|---|---|
| Unchanged rescan | clock survives |
| Append an episode (sequential or shuffle) | channel restarts, viewer position deleted |
| A duration re-probed 0.1 s different | same restart |
| Probe changed but files are cache hits | clock survives (probe not run) |

The running app used transient runtimes after a scan, so the reset only
appeared at the next startup, far from its cause. Keeping the old epoch alone
does not help: a longer cycle changes the modulo result and moves every
position. Hence revisions.

## The model

Each quick channel has a log of **schedule revisions**
(`channel_revisions` in the runtime database). A revision freezes:

- the lineup it plays: asset order **and durations**;
- when it takes effect (`effective_utc`);
- a virtual epoch, so the existing cycle arithmetic works unchanged within it;
- the content signature it was made from, and why it exists.

"What is on at T" uses the revision active at T. Past revisions are never
rewritten. `RevisionTimeline` (in `channel_revisions.py`) keeps
`SequentialTimeline`'s interface, so ads, the Guide and the viewer clock use
it without change. The channel's clock identity (`runtime.signature`, used in
ad occurrence IDs) stays the same across revisions, so committed ad breaks keep
their identity.

## When a change takes effect

A change is detected when a channel opens persistently and its content
signature (settings plus eligible media, durations rounded to 10 ms) differs
from the latest revision. The background recovery worker that runs after a
rescan opens quick channels persistently whenever all their media is
reachable, so a normal rescan queues the change straight away. ChannelOS then
stores a **pending revision**:

- **Boundary:** the end of the program airing now. Nothing on air is
  interrupted.
- **Sequential order is kept:** the new revision starts at the episode after
  the one that just aired, in the new order. Adding episode 11 while 3 airs
  gives 4 next; 11 airs after 10. A missing episode added later waits for its
  place in the next pass. If the program that just aired was removed, the
  channel continues with the next remaining one from the old order.
- **Shuffle:** everything not yet aired in this pass plays first (the rest of
  the pass, then new media), then what already aired. Nothing repeats early.
- **Several changes before the boundary** replace the pending revision's
  lineup and keep its boundary.
- **It is stored at once.** Closing before the boundary and reopening after it
  gives the same schedule as staying open.
- **What aired stays aired.** Each channel keeps a high-water mark of how far
  its schedule has been seen (`channel_revision_horizon`): every persistent
  open, and live airing crossing a revision boundary, advances it. A revision
  that took effect before that mark is never treated as pending again, even
  if the PC clock is set back, and new boundaries are placed after it.

With ad breaks, boundaries are on the program-content clock, the same clock
the sequential ad engine already uses.

## Durations and missing media

- Durations are frozen per revision. Probe noise under 10 ms is not a change.
  A real correction becomes a pending revision like any other change.
- A file shorter than its slot leaves the remainder dark until the next
  program; a longer one is cut when the next program starts. Either way the
  schedule doesn't move.
- **Missing media keeps its slot.** A transient runtime (a file missing)
  plays the saved revisions and never writes scheduling state, including ad
  plans: it plays breaks already committed and plans none. A program whose
  file can't be read becomes an `unavailable` selection: the player stops and
  Live shows *"Program unavailable"*, then the channel carries on at the next
  program.
- **A whole source unplugged:** the channel has no runtime and shows
  *"MEDIA UNAVAILABLE – Reconnect"* in the Guide, as in Beta 1. Nothing is
  written, so when the drive returns the channel resumes exactly where the
  schedule says, with no time compressed.
- **Removing media** from the channel is a change applied at the next
  boundary. Until then a scheduled program whose file is still readable keeps
  playing; only an unreadable one becomes unavailable.

## Restarting is explicit

**Channel editor → Restart From Beginning…** (confirmed) calls
`RuntimeStore.restart_channel`. It is the only way a quick channel starts over:
it clears that channel's clock, revisions and viewer position, and the next
open starts it now. The editor also shows a pending change: *"Changes take
effect after Orbit Station – S01E04 (3:24 PM)."* The time is wall-clock
time. On channels with ad breaks it is shown as *"about"*, because breaks not
planned yet can only push it later; the change stays pending until it really
takes effect.

## Upgrading from Beta 1

On the first Beta 2 open of each quick channel, with no revisions yet:

| Saved clock | Result |
|---|---|
| None | New channel: revision 0 starts now. |
| Signature matches the current lineup | **Carried over exactly:** revision 0 uses the original epoch; viewer and Guide history unchanged. |
| Signature differs, clock written by Beta 1 | **Restarted honestly:** the old epoch, signature and viewer row are kept in `channel_migrations`; revision 0 starts now; the Guide shows *"Schedule history unavailable"* for earlier time, and Home shows a one-time notice. |
| Signature differs, clock written by Beta 2 (e.g. a Calendar channel switched to Sequential) | Starts now, no notice. |

Beta 1's viewer record has no asset, so a restarted channel can't be placed
"where you left off"; we don't pretend. From Beta 2 the viewer position also
saves its asset ID and revision, so future migrations never need to guess.
Channels that already reset under Beta 1 can't be recovered.

The first time a database runs Beta 2, ChannelOS records exactly which clocks
existed (`channel_beta1_clocks`). A clock is a Beta 1 clock only while it is
still that same clock, a rule that a PC clock set back can't fool. A
migration's clock, revision, migration record and viewer cleanup are written
in **one transaction**: if ChannelOS is interrupted, nothing changed and the
next start makes the same decision.

Authoring snapshots and their rollback (`runtime_snapshot.py`), channel
delete/restore and Restart all include the revision tables.

## Clock changes

Revision boundaries are UTC. Daylight saving changes only what is displayed.
A PC clock correction may legitimately move Live (the arithmetic uses the new
"now"), but it never resets the epoch, duplicates a revision or loses viewer
state, and a pending revision activates once, at its stored boundary.

## Tests

`tests/test_channel_revisions.py` covers GPT's Beta 1 scenarios with the
continuity expectations, plus:

- closed across the boundary vs. staying open;
- a paused viewer across activation;
- repeated edits and unchanged rescans;
- shuffle pass order;
- missing media in a transient runtime (no time compressed, nothing written);
- clock corrections;
- both migration paths, with the Guide label and notice;
- explicit restart, delete/restore, the saved viewer asset and revision;
- the editor's pending-change and restart controls.

GPT's audit of `72d908b` found eight issues. Each has a regression test
(`test_audit1`…`test_audit8`); seven fail on `72d908b`. Finding 3 (a whole
source unplugged) was resolved by keeping and proving the existing
"Reconnect" behaviour rather than inventing slots for an absent drive.

`test_runtime`, `test_runtime_recovery` and `test_ad_broadcast_integration`
were updated where they asserted Beta 1's restart.
