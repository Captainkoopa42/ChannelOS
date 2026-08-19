# ChannelOS Architecture

**Status:** Draft 0.4  
**Phase:** 1 — Persistent Channel Runtime

## Architectural objective

ChannelOS should behave like a television system while remaining structurally subordinate to the user's media library.

The core architectural rule is simple:

> ChannelOS may index, schedule, remember, and present media. It must not become the only thing capable of interpreting or recovering that media.

The canonical product-level description is [MASTER_DESIGN.md](MASTER_DESIGN.md). Phase 0 is documented in [FIRST_BROADCAST.md](FIRST_BROADCAST.md). The current executable runtime is documented in [PERSISTENT_CHANNEL_RUNTIME.md](PERSISTENT_CHANNEL_RUNTIME.md).

## System boundaries

```text
+---------------------------------------------------------+
|                    TV / Remote UI                      |
|            Live View | Guide | Library                 |
+---------------------------+-----------------------------+
                            |
                            | local control intents / API
                            v
+---------------------------------------------------------+
|                 Television Runtime                     |
| TUNE | channel +/- | previous | GO_LIVE | continuity  |
+---------------------------+-----------------------------+
                            |
                            v
+---------------------------------------------------------+
|                  Channel Runtime                       |
| numeric identity | schedule epoch | Broadcast Clock    |
| Viewer Clock | generated timeline | restart state      |
+---------------------+-------------------+---------------+
                      |                   |
                      v                   v
+---------------------------+   +-------------------------+
|    Programming Engine     |   |    Playback Adapter     |
| sequence | future shuffle |   | libVLC / mpv / future  |
+-------------+-------------+   +------------+------------+
              |                              |
              +---------------+--------------+
                              v
+---------------------------------------------------------+
|                 Media Index / State                    |
| assets | locations | technical metadata | mappings     |
+---------------------------+-----------------------------+
                            |
                            v
+---------------------------------------------------------+
|                    Source Adapters                     |
|        local filesystem | NAS | removable media        |
+---------------------------------------------------------+
```

## Separation of concerns

### Media

The media layer is owned by the user and exists independently of ChannelOS. ChannelOS references files where the user keeps them rather than importing media into an application-controlled container.

### Media asset vs. media location

A media item must not be identified only by its current path.

The reference model separates exact content identity from filesystem location:

```text
MediaAsset
  asset_id = sha256:<content digest>
  technical data
       |
       +-- MediaLocation: D:\Media\Movie.mkv
       +-- MediaLocation: NAS:\Backup\Movie.mkv
```

This means an unchanged file can move without becoming a new conceptual asset. Exact duplicate files can also be represented as one asset with multiple locations.

The initial full-file SHA-256 strategy is deliberately conservative. It is more expensive than a partial fingerprint but gives the project a simple, testable identity invariant before optimization.

See [ADR-0002](decisions/0002-media-identity-and-playback.md).

### Media index state

The reference core stores media-index state in SQLite.

The database is **not** the media library. It is a rebuildable map of media assets and known locations.

Deleting the index may cost scan time. It must not affect the underlying media.

### Technical probing

Technical inspection is delegated through a `MediaProbe` boundary, with ffprobe as the current adapter. Duration, container, and stream data are inputs to scheduling and the future Guide.

A basic library scan may still index media without ffprobe. A persistent Broadcast Clock, however, refuses media whose duration is unknown or non-positive. ChannelOS does not guess schedule durations.

### Portable definitions

Channel definitions describe durable user intent: channel number, name, source selectors, and programming behavior. They are human-readable and versioned.

Resolved media IDs, wall-clock epochs, current tune state, and viewer positions do not belong inside the portable channel definition.

### Runtime state

Runtime state is local operational state rather than media ownership.

The Phase 1 reference runtime uses a separate SQLite database for:

```text
schedule epoch by channel number
schedule signature
current channel
previous channel
per-channel Viewer Clock continuity
```

This state can be deleted without deleting media. Future Export My Television work must make relevant continuity state portable without making this database itself authoritative.

## Programming and timeline generation

The programming layer converts a resolved channel into a timed schedule.

Phase 1 currently implements deterministic repeating sequential programming. The total cycle duration is the sum of indexed media durations.

```text
Program A = 30s
Program B = 45s
Program C = 60s
cycle = 135s
```

A schedule epoch anchors that cycle to UTC wall time.

Shuffle with repeat avoidance is the remaining Phase 1 programming item. Time-of-day blocks, weighted rotations, marathons, feature slots, and seasonal rules remain later broadcaster-tool work.

## Broadcast Clock

The Broadcast Clock is authoritative channel time.

For a wall-clock instant `t`:

```text
elapsed = t - epoch
cycle_position = elapsed mod cycle_duration
```

Cumulative program durations map `cycle_position` to:

- the media asset that should currently be airing,
- its schedule start/end,
- the exact in-program seek offset.

This is why an untuned channel keeps advancing without a background decoder.

Example:

```text
22:00:00–22:00:30  A
22:00:30–22:01:15  B

Tune at 22:00:42
        ↓
B @ 12 seconds
```

The decoder did not create those 42 seconds. The channel schedule did.

See [ADR-0003](decisions/0003-persistent-channel-clocks.md).

## Schedule signatures and restart recovery

A persistent channel schedule is fingerprinted from the inputs that define its current timeline:

- channel number,
- programming mode,
- ordered stable asset IDs,
- indexed durations.

If the signature is unchanged after ChannelOS restarts, the original epoch is reused and the Broadcast Clock continues naturally.

If the resolved inputs change, ChannelOS creates a new epoch. This avoids silently projecting an old timeline onto a different schedule.

The same mechanism currently handles missing files. A rescan marks a disappeared media location offline, resolution removes it, the signature changes, and the channel re-anchors using surviving online media.

## Viewer Clock

The Broadcast Clock answers what the channel is broadcasting. The Viewer Clock answers where this viewer is personally watching that schedule.

A Viewer Clock stores a schedule timestamp, the wall-clock instant at which that position was observed, and whether the playhead is running.

```text
LIVE
Viewer Clock == Broadcast Clock

PAUSE
Viewer Clock freezes
Broadcast Clock continues

PLAY
Viewer Clock advances again from its frozen schedule point

SKIP / REWIND
Viewer Clock moves on the channel timeline

GO_LIVE
Viewer Clock := Broadcast Clock
```

Fast-forward is capped at LIVE; ChannelOS does not let a viewer seek into programming that the channel has not reached yet.

> **The schedule belongs to the channel. The playhead belongs to the user.**

## Returning to channels

Per-channel continuity enables three explicit policies:

- `live` — tune to current Broadcast Clock,
- `resume` — tune to saved Viewer Clock,
- `ask` — surface the choice instead of silently making it.

When a viewer leaves a channel, its saved Viewer Clock may freeze while the Broadcast Clock continues mathematically.

## TelevisionRuntime

`TelevisionRuntime` is the Phase 1 multi-channel state layer.

It owns:

- the active lineup keyed by numeric channel identity,
- current channel,
- previous channel,
- channel-up/down ordering,
- per-channel continuity decisions.

It does **not** decode media.

The current control vocabulary includes:

```text
TUNE 007
CHANNEL_UP
CHANNEL_DOWN
PREVIOUS_CHANNEL
PAUSE
PLAY
SKIP_BACK
SKIP_FORWARD
GO_LIVE
STATUS
```

This vocabulary is intentionally aligned with the future open ChannelOS remote/control-intent protocol.

## Playback

ChannelOS delegates decoding to mature player engines.

Playback is accessed through a backend-neutral `PlaybackBackend` contract:

- load
- play
- pause
- stop
- absolute seek
- current playback position
- volume
- mute
- playback rate

**libVLC is the first reference backend.** Alternative backends may later sit behind the same contract.

The runtime decides channel/media/time first. `TelevisionSession` then translates the resulting selection into backend load/play/seek operations.

```text
TUNE 007
   |
   v
TelevisionRuntime
   |
   +--> Channel 007 Broadcast Clock
   |       -> asset + seek offset
   v
TelevisionSession
   |
   v
PlaybackBackend
   |
   v
libVLC
```

The decoder never decides what Channel 007 means.

## UI boundary

The TV UI is a client of the runtime. It must not contain authoritative scheduling logic.

That separation allows the same runtime to support:

- desktop software,
- couch-first TV UI,
- dedicated open appliance,
- phone/tablet remote,
- future household multi-TV clients.

## Current reference implementation

```text
channel YAML
    |
    v
parser / validator
    |
    v
filesystem scanner ---> SHA-256 asset identity
    |                         |
    +--> optional ffprobe     v
    |                   SQLite media index
    |                         |
    +-------------------------+
              |
              v
       source resolver
              |
              v
       ChannelRuntime
       schedule signature
       persistent epoch
       Broadcast Clock
              |
              v
       TelevisionRuntime
       Viewer Clock
       current / previous
              |
              v
       TelevisionSession
              |
              v
       PlaybackBackend
              |
              v
        LibVLCBackend
```

Automated tests cover Phase 0 media behavior plus Phase 1 clock mathematics, restart persistence, missing-file recovery, two-channel independent advancement, live/resume/ask behavior, previous-channel toggling, GO_LIVE, backend routing, and the Phase 1 CLI harness.

The current CI matrix runs the reference core on Python 3.11, 3.12, and 3.13.

## Current implementation choices

- **Language:** Python for the reference core/test harness.
- **Definitions:** YAML with `schema_version`.
- **Media index:** SQLite.
- **Runtime state:** separate SQLite database.
- **Asset identity v1:** full-file SHA-256, independent of path.
- **Technical probing:** `MediaProbe`; ffprobe first.
- **Playback:** backend-neutral; libVLC first.
- **Channel time:** UTC persistent schedule epochs.
- **Communication:** in-process calls initially; local API/IPC when UI/runtime split.
- **Networking:** no internet requirement for core operation.

These are implementation choices, not ownership invariants. They can change without changing the project's identity.

## Trust boundaries

A future plugin/source system should assume extensions are untrusted until explicitly granted capability. Plugins should not silently receive unrestricted filesystem or network access.

## Phase 1 exit condition

Phase 1 is complete when ChannelOS can:

1. maintain stable numeric channel identities,
2. generate a timed schedule from indexed media,
3. calculate the correct current program/offset without background decoding,
4. preserve schedule time across process restart,
5. maintain an independent Viewer Clock,
6. pause/seek and return to LIVE without stopping Broadcast Clock,
7. tune directly, channel up/down, and previous-channel,
8. preserve or discard channel continuity according to live/resume/ask policy,
9. recover coherently when an indexed media location disappears,
10. pass the two-channel independent-advancement test,
11. run the same behavior against genuine timed media through the real playback backend.

Items 1–10 are implemented and covered by automated reference-core tests. Item 11 is the real-machine Phase 1 gate. Deterministic shuffle/repeat-avoidance remains an additional roadmap item before Phase 1 is considered feature-complete.
