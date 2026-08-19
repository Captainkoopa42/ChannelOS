# ChannelOS Architecture

**Status:** Draft 0.3  
**Phase:** 0 — First Broadcast foundation

## Architectural objective

ChannelOS should behave like a television system while remaining structurally subordinate to the user's media library.

The core architectural rule is simple:

> ChannelOS may index, schedule, remember, and present media. It must not become the only thing capable of interpreting or recovering that media.

The canonical product-level description of the intended system is maintained in [MASTER_DESIGN.md](MASTER_DESIGN.md).

The first executable vertical slice is documented in [FIRST_BROADCAST.md](FIRST_BROADCAST.md).

## System boundaries

```text
+---------------------------------------------------------+
|                    TV / Remote UI                      |
|            Live View | Guide | Library                 |
+---------------------------+-----------------------------+
                            |
                            | local API / IPC
                            v
+---------------------------------------------------------+
|                    Channel Runtime                     |
| tuning | broadcast/viewer clocks | now/next | handoff |
+---------------------+-------------------+---------------+
                      |                   |
                      v                   v
+---------------------------+   +-------------------------+
|    Programming Engine     |   |    Playback Adapter     |
| sequence | shuffle | time |   | libVLC / mpv / future  |
+-------------+-------------+   +------------+------------+
              |                              |
              +---------------+--------------+
                              v
+---------------------------------------------------------+
|                 Media Index / State                    |
| assets | locations | metadata | history | mappings     |
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

The Phase 0 model separates exact content identity from filesystem location:

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

### Index state

The reference core stores index state in SQLite.

The database is **not** the media library. It is a rebuildable map of media assets and their known locations.

Deleting the index may cost scan time and disposable runtime state. It must not affect the underlying media.

### Technical probing

Technical inspection is delegated to an `ffprobe` adapter when available. Duration, container, and stream data are useful inputs for scheduling and the future Guide.

A normal scan can still index media when ffprobe is unavailable. Strict probing can be requested for validation.

### Definitions

Channel definitions describe intent: channel number, name, source selectors, and programming behavior. They are human-readable and versioned.

Resolved media IDs do not belong inside the portable channel definition.

### Runtime state

Watch progress, current sequence position, repeat history, generated schedule, viewer offsets, profile state, and cache data belong in runtime state. Runtime state must never be required to recover the underlying media.

### Programming

The programming engine converts a channel definition plus indexed media plus runtime state into an ordered timeline. Its choices should be explainable.

Phase 0 only resolves eligible indexed media. Persistent sequence state and schedule generation come next.

### Channel clocks

A channel has a **Broadcast Clock** describing what it would be showing independently of the current viewer. A viewing session has a **Viewer Clock** describing where the user is currently watching within that timeline.

This is what will allow ChannelOS to feel like television while still supporting pause, rewind, fast-forward, resume, and a `GO_LIVE` command.

> **The schedule belongs to the channel. The playhead belongs to the user.**

Broadcast/Viewer clocks are the next major runtime subsystem after the First Broadcast media spine is proven on a real playback machine.

### Playback

ChannelOS delegates decoding to a mature player engine. ChannelOS owns selection, scheduling, handoff, tuning, playback intent, and viewer state; it does not own codec implementation.

Playback is accessed through a backend-neutral `PlaybackBackend` contract. The current contract includes:

- load
- play
- pause
- stop
- absolute seek
- current playback position
- volume
- mute
- playback rate

**libVLC is the first reference backend.** mpv or future engines may be supported behind the same interface.

The Python libVLC binding is optional so the library/index core can run without a playback installation.

### Control boundary

The Phase 0 tuner already routes commands through ChannelOS-owned playback intents rather than exposing VLC as the product UI.

The current text console is intentionally temporary. It proves the same boundary the future remote protocol will use:

```text
User intent
   |
   v
ChannelOS control/runtime
   |
   v
PlaybackBackend
   |
   v
libVLC
```

### UI

The TV UI is a client of the runtime. It should not contain the authoritative scheduling logic. That separation makes future desktop, appliance, phone-remote, and multi-TV clients possible.

## Current Phase 0 implementation

The reference implementation now contains:

```text
channel definition parser/validator
          |
          v
filesystem scanner ---> SHA-256 media identity
          |                       |
          v                       v
   SQLite media index <--- media locations
          |
          +---- optional ffprobe technical data
          |
          v
   channel source resolver
          |
          v
    primitive tuner
          |
          v
   PlaybackBackend
          |
          v
    LibVLCBackend
```

The code has automated tests for channel validation, scan caching, move-stable identity, source resolution, and playback-control routing through a fake backend.

A real-machine VLC/libVLC playback smoke test remains required before Phase 0 can be considered fully exited.

## Initial implementation choices

- **Language:** Python for the first reference core and test harness.
- **Definitions:** YAML, versioned with `schema_version`.
- **Index/state:** SQLite for the reference local index/runtime state.
- **Asset identity v1:** full-file SHA-256, independent of path.
- **Technical probing:** external ffprobe adapter when available.
- **Playback:** backend-neutral playback adapter; libVLC as the first reference backend.
- **Communication:** local-only process calls initially; local API/IPC once UI and runtime split.
- **Networking:** no internet requirement for core channel operation.

These are implementation choices, not ownership invariants. They can change without changing the project's identity.

## Trust boundaries

A future plugin/source system should assume extensions are untrusted until explicitly granted capability. Plugins should not silently receive unrestricted filesystem or network access.

## Phase 0 exit condition

Phase 0 is complete when ChannelOS can:

1. Load a documented channel definition.
2. Resolve at least one local media source.
3. Assign stable indexed identities to discovered files.
4. Recognize unchanged media after a path move/rescan.
5. Hand one selected indexed media item to a playback adapter.
6. Exercise basic user playback intents through the ChannelOS control boundary.
7. Preserve the distinction between portable definition, rebuildable index, user-owned media, and disposable runtime state.
8. Pass a real VLC/libVLC smoke test on a supported desktop machine.

Items 1–7 now exist in the reference implementation and automated tests. Item 8 is the immediate real-machine validation step.
