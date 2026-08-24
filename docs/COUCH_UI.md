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
- classic television static for an unassigned channel,
- Current Channel as the authoritative Home television state when one is tuned.

Home resolves its television presentation in this order:

1. the persisted/current tuned channel and its Viewer Clock,
2. real Channel 001 at the Broadcast Clock when no channel is currently tuned,
3. a presentation-only `001 ChannelOS / UNASSIGNED / NO PROGRAMMING` static slot.

The reserved 001 state is not a fake `ChannelRuntime`: it has no media identity,
Viewer Clock, or generated schedule. The Guide projects the same unassigned 001
slot only when no real Channel 001 exists, and Enter on that row explains how
to assign it instead of attempting a runtime tune. A real Channel 001 always
replaces the synthetic slot.

The Guide keeps **selection** separate from **tuning**. Opening the Guide anchors
the cursor on the current tuned channel when possible, while a `WATCHING`
indicator remains on that row even if the user browses elsewhere. Merely opening
Home or Guide never retunes television state.

`Continue Watching` is now a real television intent rather than a placeholder.
Its resolution order is current persisted Viewer Clock, previous channel with
saved continuity, then real Channel 001 live. If none exists, Home remains on
the presentation-only unassigned 001 static state and does not manufacture a
runtime channel. Resuming a paused Viewer Clock starts it from the exact saved
schedule position; opening Home itself still never advances or retunes state.

On application startup, after the Qt window and native video child have become
visible, ChannelOS starts that same continuation/default resolution once so the
Home television picture is already running on boot. This is a startup action,
not a Home-navigation side effect: returning to Home later still does not
retune the television.

When a television decoder is already active, Home and Guide reuse the **same**
native libVLC `QWindow` as a bounded picture-in-guide/picture-in-home surface.
ChannelOS does not create a second decoder, duplicate the video window, retune
the channel, or manually reparent the native HWND. The Guide keeps the direct
root-coordinate geometry already validated on Windows. Home uses the same
approach but derives its root position from the stable split-layout dimensions
instead of repeatedly mapping nested item coordinates. Returning to Live expands
that same surface back to the root. Guide browsing therefore keeps the tuned
channel running while selection/program metadata can move independently.

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

The main Live information layer is transient: tuning or transport/channel input
shows the lower-third and clock, and ten seconds without another qualifying Live
interaction hides them again. Repeated Live interaction restarts the timer.
Compact volume/mute and numeric-channel-entry overlays keep their own shorter
timers.

The libVLC target remains a native child window. The Windows-safe HUD presentation deliberately avoids a second full-screen transparent native child above it. Small bounded overlays use native child windows where appropriate, while the translucent lower-third is a bounded transient top-level window so Windows can alpha-compose it without obscuring the video during maximize/restore.

The couch launcher is fullscreen by default via Qt `showFullScreen()`; `--windowed`
is the explicit development override. On Windows this is the borderless
fullscreen presentation path rather than an exclusive decoder-owned fullscreen
mode.

### Library / On Demand

Library reads the canonical ChannelOS media index and now has an explicit source-management foundation.

It can add, rescan, cancel scans, remove a source from the index without touching the files, search/sort indexed media, and launch On Demand playback by stable asset identity.

The product-facing Library is now content-first. It presents a persistent
navigation rail, a prominent selected-title banner, horizontal shelves over the
real indexed collection, search, source-derived groupings, and duration-based
long/short-form groupings. Until local artwork exists, deterministic branded
media cards keep every indexed file browsable without pretending that external
metadata has already been matched.

The shelves use an accordion presentation so only one collection needs to be
open at a time. A viewer can select compact shelf headers with Up/Down, expand
with Enter or Right, collapse from the first card with Left, and toggle a shelf
with the mouse. File-backed cards display a concise format such as MP4 or MKV
instead of exposing the decoder's raw container list, and long source names are
elided within their shelf header.

The former three-pane Library remains available as the secondary **Manage
Sources** surface. Adding, rescanning, and removing indexed roots therefore
stays powerful without making storage administration the first thing a viewer
sees. Continue Watching, Recently Added, and semantic movie/television shelves
remain intentionally absent until ChannelOS stores the facts required to label
them truthfully.

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
- complete artwork-backed content-first Library visual pass — the real shelf
  layout and secondary source manager are in place; artwork remains,
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
