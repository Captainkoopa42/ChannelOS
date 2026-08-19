# ChannelOS Couch UI

**Status:** Phase 3 implementation target  
**Phase:** 3 — Couch Interface

## Product rule

> **The runtime decides television state. The UI presents and controls it.**

The couch interface must remain a client of the existing Guide and television runtime. It must not recreate scheduling logic, infer a second Broadcast Clock, or manipulate libVLC directly.

## Approved visual direction

The first ChannelOS couch interface is intentionally television-first rather than streaming-app-first.

### Startup / Home

Startup uses a classic cable-TV split composition:

- dark navy / charcoal ChannelOS shell,
- navigation and identity on the left,
- large television preview area on the upper right,
- quick-action cards across the lower area,
- Channel 001 as the first-start default when no previous channel exists,
- an unassigned / unpopulated channel presents deliberate classic television static rather than an error panel.

Later playback plumbing should let the preview show the last tuned channel when viewer state exists. Static remains the default visual identity for an intentionally unassigned channel.

### Guide

The actual Guide is a full-screen modern cable grid, not the startup split layout.

- channels are vertical,
- time runs horizontally,
- program blocks are sized from authoritative schedule start/end times,
- the current Broadcast Clock has a visible time marker,
- the selected program drives the information header,
- a television preview region occupies the upper-right portion of the Guide,
- focus is a bright cool-blue state suitable for keyboard, controller, or remote navigation,
- LIVE is restrained red,
- the Guide remains dense and readable from couch distance.

The interaction model is deliberately familiar: Up/Down changes channel rows, Left/Right moves through scheduled programs, Enter/OK selects, Guide returns to the Guide / current time, and Back returns toward the previous screen.

### Live television and overlays

Live television is full-screen video. Information appears as temporary overlays rather than permanently shrinking playback. Channel / program overlays include channel number and identity, title, current/next information, LIVE state, schedule progress, and relevant transport state.

### Library / On Demand

Library is a separate owned-media browsing mode using the same ChannelOS visual language. It is not the product's default identity; live television and the Guide remain central.

## Visual tokens

The initial implementation should stay close to:

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

These are implementation anchors, not a requirement that every surface use exactly one literal color value forever.

## First implementation slice

The first real UI slice proves the presentation boundary before video embedding is added:

1. optional `PySide6` UI dependency and packaged QML assets,
2. `channelos-couch` launcher,
3. QML-friendly Guide projection produced from `GuideService`,
4. approved startup / static Channel 001 composition,
5. full-screen Guide generated from real ChannelOS schedule rows,
6. keyboard / D-pad-style focus navigation,
7. periodic Guide refresh from the same authoritative runtime.

The next plumbing slice adds control actions and an embedded playback surface:

```text
QML selection
    -> Qt/Python adapter
    -> GuideController / TelevisionSession
    -> TelevisionRuntime
    -> PlaybackBackend
    -> libVLC embedded video surface
```

## First real-machine gate

The first couch UI gate is successful when a Windows development machine can:

- launch the new interface from the existing Channel 007 and 012 definitions,
- show the approved startup screen,
- open the Guide,
- display real Guide rows for both channels,
- navigate them with the keyboard,
- keep the Guide in agreement with the Broadcast Clock as it refreshes.

Playback inside the Qt surface is the following gate, not a reason to duplicate or bypass the runtime during this visual-shell proof.
