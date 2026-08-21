# ChannelOS Couch UI

**Status:** Working local alpha
**Phase:** 3 — Couch Interface
**Real-machine gate:** Passed for the current Windows implementation

## Product rule

> **The runtime decides television state. The UI presents and controls it.**

The couch interface remains a client of the Guide and television runtime.

It does not recreate scheduling logic, invent a second Broadcast Clock, or use libVLC as the product's state authority.

## Current implementation

The current Qt Quick / PySide6 couch application now includes:

- ChannelOS startup/home presentation,
- deliberate Channel 001 unassigned/static state,
- real multi-channel Guide,
- keyboard/D-pad-style navigation,
- authoritative selected-program detail,
- current Broadcast Clock marker,
- adaptive short-form Guide presentation,
- native embedded libVLC video,
- embedded audio,
- hardware-decoded Windows playback,
- live channel/program HUD,
- Now / Next,
- LIVE / behind-live presentation,
- pause/resume,
- rewind and skip forward,
- channel Up / Down,
- numeric direct tuning,
- Previous Channel,
- volume/mute controls,
- return to LIVE,
- automatic scheduled program rollover,
- real Library browser,
- explicit media-source management,
- responsive/cancellable source scans,
- independent On Demand playback,
- On Demand pause/seek,
- end-of-file replay/rewind recovery,
- stable maximize/restore behavior during native Windows playback.

## Approved visual direction

The interface remains television-first rather than streaming-app-first.

### Startup / Home

Startup uses the classic cable-TV split composition:

- dark navy / charcoal ChannelOS shell,
- navigation and identity on the left,
- television preview region on the upper right,
- quick-action cards across the lower area,
- Channel 001 as the intentional first-start default,
- classic television static for an unassigned channel.

### Guide

The Guide is a full-screen modern cable grid:

- channels vertical,
- time horizontal,
- program blocks derived from authoritative start/end times,
- current Broadcast Clock marker,
- selected-program header,
- cool-blue focus state,
- restrained red LIVE state,
- couch-readable density.

Very short captures are grouped only in the **visual projection**.

The underlying Guide still retains and selects exact scheduled occurrences.

### Live television

Live television is full-screen native video.

The television HUD presents:

- channel number/name,
- title,
- LIVE or behind-live state,
- schedule progress,
- Now / Next,
- transport state,
- clock,
- transient volume/mute and numeric-channel entry.

The libVLC target remains a native child window. The Windows-safe HUD presentation deliberately avoids a second full-screen transparent native child above it. Small bounded overlays use native child windows where appropriate, while the translucent lower-third is a bounded transient top-level window so Windows can alpha-compose it without obscuring the video during maximize/restore.

### Library / On Demand

Library reads the canonical ChannelOS media index and now has an explicit source-management foundation.

It can add, rescan, cancel scans, remove a source from the index without touching the files, search/sort indexed media, and launch On Demand playback by stable asset identity.

The present three-pane management-oriented Library is an infrastructure step, not the final product-facing visual target. The intended consumer surface remains content-first: navigation rail, artwork/thumbnail shelves, Continue Watching, categories, and prominent media presentation with source/storage management moved into a secondary surface.

On Demand uses a playback session separate from television scheduling.

This preserves the conceptual boundary:

```text
Library selection
      |
      v
On Demand playhead

Channel schedule
      |
      v
Broadcast / Viewer Clock
```

Both use the same owned-media index and the same ChannelOS presentation surface, but one does not rewrite the state of the other.

## Real-machine validation

The Windows development machine has validated:

- Channel 007 sequential scheduling,
- Channel 012 deterministic shuffle scheduling,
- Guide-to-live playback,
- embedded video and audio,
- D3D11VA GPU decoding,
- automatic short-program rollover,
- Viewer Clock lag after pause,
- `GO_LIVE`,
- channel switching,
- numeric direct tuning,
- Previous Channel,
- volume/mute,
- real indexed Library browsing,
- source preflight and large responsive rescans,
- cooperative scan cancellation without corrupting the previous successful index,
- On Demand play/pause/seek,
- On Demand natural-EOF recovery,
- return from On Demand to live television,
- maximize/restore during active native video with the bounded translucent HUD architecture.

## Remaining Phase 3 / first-release UI work

Major remaining couch/release work includes:

- richer Info behavior,
- controller/remote abstraction,
- Settings,
- content-first Library visual pass,
- artwork/video-thumbnail pipeline,
- Continue Watching integration,
- Library -> Add to Channel authoring flow,
- normal-user playback-runtime packaging,
- SteamOS/controller validation,
- autostart/crash recovery,
- clean-machine release testing.

## Visual tokens

```text
Background       #050c15
Panel            #081625
Raised panel     #0d2035
Soft panel       #10283f
Dividers         #1a3550
Primary text     #f4f7fb
Secondary text   #9fb0c2
Accent           #1a91ff
Bright focus     #42adff
LIVE             #ff4a4a
```

These remain implementation anchors rather than immutable theme requirements.

## Architectural result

The original presentation boundary has survived implementation:

```text
QML presentation
    -> Qt/Python adapter
    -> Guide / On Demand control layer
    -> authoritative ChannelOS runtime or media selection
    -> PlaybackBackend
    -> libVLC
    -> native video surface
```

VLC performs media playback.

ChannelOS performs television.
