# ChannelOS Architecture

**Status:** Draft 0.5  
**Current phase:** 2 — Guide / UI-facing plumbing

## Architectural objective

ChannelOS should behave like a television system while remaining structurally subordinate to the user's media library.

The core architectural rule is simple:

> ChannelOS may index, schedule, remember, and present media. It must not become the only thing capable of interpreting or recovering that media.

The canonical product-level description is [MASTER_DESIGN.md](MASTER_DESIGN.md). Phase 0 is documented in [FIRST_BROADCAST.md](FIRST_BROADCAST.md). Phase 1 is documented in [PERSISTENT_CHANNEL_RUNTIME.md](PERSISTENT_CHANNEL_RUNTIME.md). The current milestone is [GUIDE_AND_UI_BOUNDARY.md](GUIDE_AND_UI_BOUNDARY.md).

## System boundaries

```text
+---------------------------------------------------------+
|                    TV / Remote UI                      |
|            Live View | Guide | Library                 |
+---------------------------+-----------------------------+
                            |
                            | local service / API / IPC
                            v
+---------------------------------------------------------+
|             Guide / Television Boundary                |
| horizon | Now/Next | detail | explain-why | intents    |
+---------------------------+-----------------------------+
                            |
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
| sequence | shuffle        |   | libVLC / future        |
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

The authoritative scheduling logic belongs below the UI boundary. The interface can request television state and issue user intents; it must not independently decide what a channel is airing.

## Separation of concerns

### Media

The media layer is owned by the user and exists independently of ChannelOS. ChannelOS references files where the user keeps them rather than importing media into an application-controlled container.

### Media asset vs. media location

A media item must not be identified only by its current path.

```text
MediaAsset
  asset_id = sha256:<content digest>
  technical data
       |
       +-- MediaLocation: D:\Media\Movie.mkv
       +-- MediaLocation: NAS:\Backup\Movie.mkv
```

The reference model separates exact content identity from filesystem location. An unchanged file can move without becoming a new conceptual asset, and exact duplicates can be represented as one asset with multiple locations.

The initial full-file SHA-256 strategy is deliberately conservative. It is more expensive than a partial fingerprint but gives the project a simple, testable identity invariant before optimization.

See [ADR-0002](decisions/0002-media-identity-and-playback.md).

### Media index state

The reference core stores media-index state in SQLite.

The database is **not** the media library. It is a rebuildable map of media assets and known locations.

Deleting the index may cost scan time. It must not affect the underlying media.

### Technical probing

Technical inspection is delegated through a `MediaProbe` boundary, with ffprobe as the current adapter. Duration, container, and stream data are inputs to scheduling and the Guide.

A basic library scan may still index media without ffprobe. A persistent Broadcast Clock refuses scheduleable media whose duration is unknown or non-positive. ChannelOS does not guess schedule durations.

### Portable definitions

Channel definitions describe durable user intent: channel number, name, source selectors, and programming behavior. They are human-readable and versioned.

Resolved media IDs, wall-clock epochs, current tune state, and viewer positions do not belong inside the portable channel definition.

### Runtime state

Runtime state is local operational state rather than media ownership.

The reference runtime uses a separate SQLite database for:

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

Phase 1 implements two deterministic repeating policies:

- sequential programming in resolved source order,
- deterministic shuffle derived from stable asset identities.

Every eligible shuffle item appears once before the cycle repeats. `avoid_repeat_days` is treated as a guarantee: if the eligible media duration cannot satisfy the requested window, the runtime rejects the configuration rather than silently weakening it.

For either policy, indexed positive durations form a repeating timed cycle anchored to a persistent UTC schedule epoch.

Time-of-day blocks, weighted rotations, marathons, feature slots, and seasonal rules remain later broadcaster-tool work.

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

See [ADR-0003](decisions/0003-persistent-channel-clocks.md).

## Schedule signatures and restart recovery

A persistent channel schedule is fingerprinted from the inputs that define its current timeline:

- channel number,
- programming policy,
- stable asset IDs,
- indexed durations.

Sequential schedules preserve effective source order. Shuffle schedules derive their order from stable identities so path movement does not silently mutate the shuffled schedule.

If the signature is unchanged after restart, the original epoch is reused and the Broadcast Clock continues naturally.

If the programming inputs change, ChannelOS creates a new epoch. This avoids projecting an old timeline onto a different schedule.

The same mechanism handles missing files. A rescan marks a disappeared location offline, resolution changes the eligible media set, the signature changes, and the channel re-anchors using surviving online media.

## Viewer Clock

The Broadcast Clock answers what the channel is broadcasting. The Viewer Clock answers where the viewer is personally watching that schedule.

```text
LIVE
Viewer Clock == Broadcast Clock

PAUSE
Viewer Clock freezes
Broadcast Clock continues

PLAY
Viewer Clock advances again from its frozen point

SKIP / REWIND
Viewer Clock moves on the channel timeline

GO_LIVE
Viewer Clock := Broadcast Clock
```

Fast-forward is capped at LIVE.

> **The schedule belongs to the channel. The playhead belongs to the user.**

## On Demand watch state

Direct Library playback owns a third, deliberately separate clock: the On
Demand playhead. It is keyed by stable media asset ID and viewer ID in the local
runtime database. It never changes a channel epoch, Broadcast Clock, schedule,
or per-channel Viewer Clock.

```text
on_demand_watch(viewer_id, asset_id)
    -> position, duration, completion, last watched time
```

The first implementation uses the explicit `default` viewer while preserving
the storage boundary needed for later profiles.

## Returning to channels

Per-channel continuity enables three explicit policies:

- `live` — tune to current Broadcast Clock,
- `resume` — tune to saved Viewer Clock,
- `ask` — surface the choice instead of silently making it.

When a viewer leaves a channel, its saved Viewer Clock may freeze while the Broadcast Clock continues mathematically.

## TelevisionRuntime

`TelevisionRuntime` owns the active lineup by numeric channel identity and persists:

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

## Phase 2 Guide / television service boundary

The next architectural boundary sits between the runtime and presentation layers.

It should expose stable read models for:

- Guide schedule horizons,
- Now / Next,
- per-channel rows,
- program start/end times,
- current/previous/live state,
- explain-why traces,
- program detail needed for Guide navigation.

It should also accept high-level user intents such as tune, Watch from Beginning, and `GO_LIVE` without allowing the UI to talk directly to libVLC.

The first implementation may remain in-process. The boundary should still be explicit enough to become local API/IPC later without moving scheduling logic into the UI.

See [GUIDE_AND_UI_BOUNDARY.md](GUIDE_AND_UI_BOUNDARY.md).

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

### Development runtime discovery

During source development on Windows, ChannelOS can discover a compatible native libVLC through:

1. a bundled-style `runtime/vlc` layout,
2. the `CHANNELOS_VLC_DIR` development override,
3. compatible system discovery/fallback where supported.

`python-vlc` is the control binding; it is not the native playback runtime itself.

### Product packaging

A finished ChannelOS package should include the compatible native playback runtime it requires where licensing permits. Ordinary users should not need to install VLC into a particular path or configure environment variables.

The product packaging target is therefore conceptually:

```text
ChannelOS/
    ChannelOS executable / application
    runtime/
        vlc/
            native libVLC runtime
            plugins/
```

This packaging detail does not change the backend abstraction. Third-party licenses/notices must be reviewed before public distribution.

## UI boundary

The TV UI is a client of the Guide/television service boundary. It must not contain authoritative scheduling logic.

That separation allows the same runtime to support:

- desktop software,
- couch-first TV UI,
- Steam / SteamOS launch,
- dedicated open appliance,
- local management UI,
- phone/tablet remote,
- future household multi-TV clients.

The default couch visual language is intended to use dark navy/charcoal surfaces, cool blue focus/selection states, bright readable text, and a restrained LIVE indicator. It should feel natural in a SteamOS living-room environment while remaining distinct ChannelOS branding.

## Deployment profiles

ChannelOS is one core system with multiple hosts.

```text
ChannelOS Core
   ├── Desktop mode
   │      Windows / Linux
   │
   ├── Steam / SteamOS mode
   │      primary public living-room launch target
   │
   └── Appliance mode
          minimal host OS
          boots directly into ChannelOS
          HDMI + remote/controller
```

Steam/SteamOS is a **distribution and launch target, not an architectural dependency**. Standalone installations and appliance images must remain capable of ordinary local playback without Steam entitlement or account checks.

A future dedicated appliance does not require ChannelOS to implement a custom kernel. A minimal Linux base can provide drivers, filesystems, GPU/video support, networking, USB, Bluetooth, and HDMI, then launch ChannelOS directly.

See [ADR-0004](decisions/0004-distribution-and-appliance-neutrality.md).

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

Phase 1 is complete and merged. The full local Windows reference suite passed 37 tests after deterministic shuffle was added, and the corresponding GitHub Actions run passed. Real playback validation covered independent channel clocks, switching, pause/resume lag, `GO_LIVE`, Windows libVLC loading, and deterministic shuffle using genuine indexed media.

## Current implementation choices

- **Language:** Python for the reference core/test harness.
- **Definitions:** YAML with `schema_version`.
- **Media index:** SQLite.
- **Runtime state:** separate SQLite database.
- **Asset identity v1:** full-file SHA-256, independent of path.
- **Technical probing:** `MediaProbe`; ffprobe first.
- **Playback:** backend-neutral; libVLC first.
- **Channel time:** UTC persistent schedule epochs.
- **Programming:** deterministic sequential and shuffle in Phase 1.
- **Communication:** in-process calls initially; explicit local service/API/IPC boundary as UI develops.
- **Networking:** no internet requirement for core operation.
- **Deployment:** Windows/Linux core, SteamOS first-class living-room target, dedicated appliance later.

These are implementation choices, not ownership invariants. They can change without changing the project's identity.

## Trust boundaries

A future plugin/source system should assume extensions are untrusted until explicitly granted capability. Plugins should not silently receive unrestricted filesystem or network access.

Distribution platforms are also outside the ownership boundary: they may install or update ChannelOS, but they must not become the authority that decides whether standalone/appliance local media can play.

## Completed Phase 1 gate

Phase 1 has passed the required behaviors:

1. stable numeric channel identities,
2. deterministic sequential and shuffle schedules,
3. current program/offset calculation without background decoding,
4. schedule persistence across process restart,
5. independent Viewer Clock,
6. pause/seek/return-to-LIVE behavior,
7. direct tuning, channel up/down, and previous-channel,
8. live/resume/ask continuity policy,
9. coherent missing-file recovery,
10. two-channel independent advancement,
11. genuine media playback through the real libVLC backend,
12. deterministic shuffle over genuine indexed media.

The architectural focus now moves to Phase 2: projecting this runtime truth into a Guide and stable UI-facing service boundary.
