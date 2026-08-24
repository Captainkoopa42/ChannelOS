# ChannelOS Implementation Status

**Snapshot:** August 24, 2026
**Status:** Working local alpha  
**Active implementation:** First-release couch and controller experience
**Canonical product definition:** [MASTER_DESIGN.md](MASTER_DESIGN.md)

This document records implementation progress against the original ChannelOS design.

It does **not** redefine the product in order to match the implementation.

The Master Design remains the yardstick.

---

## Executive assessment

ChannelOS is now a functioning local television system with real media, persistent channel state, a real Guide, embedded native video, an independent On Demand path, a usable Broadcaster, and first-class media-source lifecycle management.

A real Windows machine can now:

- index ordinary user-owned media without taking ownership of the files,
- preserve stable media identity independently of file path,
- track explicit media sources and source status,
- preflight, rescan, cancel, and safely remove sources from the index,
- run persistent numbered television channels,
- advance channels while they are not being watched,
- maintain separate Broadcast and Viewer Clocks,
- generate a traditional multi-channel Guide,
- tune Guide selections through the authoritative runtime,
- display embedded video and audio inside the ChannelOS couch UI,
- use hardware video decoding through libVLC / D3D11VA,
- maximize and restore the Windows UI during active playback without losing video,
- automatically roll from one scheduled program into the next,
- pause, resume, rewind, skip forward, change channels, tune numerically, use Previous Channel, control volume/mute, and return LIVE,
- browse/search/sort the real indexed media library,
- play indexed media through an independent On Demand session,
- pause and seek On Demand media,
- recover correctly when replaying or rewinding after natural end-of-file,
- persist meaningful On Demand playheads and resume them from Continue Watching,
- return from On Demand to live television while preserving television clock state,
- create and edit portable channel definitions through the Broadcaster,
- reload created/edited channels immediately into runtime and Guide state.

Home now wires every visible destination, makes the lower quick-action row
controller/mouse accessible, and provides persistent volume, mute, and
seek-distance preferences. Settings includes Standard, Lightweight, and Custom
machine-performance profiles, generated-art cache controls, and reduced motion;
these controls have passed Windows real-machine validation and are merged.

The [Reliability Gate](RELIABILITY_GATE.md) is implemented, Windows validated,
and merged: shared background/cancellable media scanning, SQLite concurrency and
version guards, source-scoped resolution, atomic tuning persistence, and batched
artwork updates now form the normal foundation.

The largest remaining first-release work is now product experience and release hardening rather than proving the television model.

---

## Completion uses two different denominators

### Focused desktop / couch v1

Estimated completion:

**approximately 84-86%**

This is the focused first-release experience: local ownership/indexing, persistent channels, Guide, live playback, television controls, Library / On Demand, minimum broadcaster/channel management, normal-user packaging, controller/remote polish, settings, and release hardening.

### Full Master Design

Estimated completion:

**approximately 40-45%**

The complete design also includes substantial later systems:

- rich metadata,
- advanced broadcaster programming,
- profiles,
- export/import,
- multi-device household operation,
- phone/tablet remote,
- local management web UI,
- plugin/source ecosystem,
- SteamOS validation,
- dedicated appliance experiments,
- open physical remote work.

### Fidelity to the original idea

Estimated fidelity of the implemented architecture:

**approximately 90-95%**

This is a design-audit estimate, not a mathematical quality score. Implementation has not required changing the fundamental identity of ChannelOS.

---

## Original idea vs. current implementation

| Original design requirement | Current state | Fidelity |
| --- | --- | --- |
| User-owned files remain ordinary files | Implemented | Very high |
| Local-first core | Implemented for current core | Very high |
| One canonical media index | Implemented | Very high |
| Explicit source lifecycle without taking file ownership | Implemented and real-machine tested | Very high |
| Numbered persistent television channels | Implemented | Very high |
| Channels advance while untuned | Implemented | Very high |
| Broadcast Clock | Implemented | Very high |
| Viewer Clock | Implemented | Very high |
| LIVE / behind-live behavior | Implemented and real-machine tested | Very high |
| Traditional television Guide | Implemented and real-machine tested | Very high |
| Guide derives from runtime truth | Implemented | Very high |
| Live television is passive by default | Implemented | High |
| Library is separate active-selection mode | Content-first shelves, local artwork, management surface, and durable Continue Watching implemented | High |
| Library and channels share one media index | Implemented | Very high |
| On Demand does not contaminate channel scheduling | Implemented with separate playback session | Very high |
| Couch-first presentation | Working keyboard/D-pad implementation | High |
| Functional Home destinations | Implemented and real-machine tested | High |
| Persistent Settings | Basic controls and performance/cache profiles merged and Windows validated | High |
| User is broadcaster | Safe Channel Builder MVP implemented | High |
| Rich metadata/artwork | Not yet | Low |
| Advanced scheduling/programming tools | Foundation only | Partial |
| Profiles | Not yet | None |
| Export/import | Not yet | None |
| Multi-device household | Not yet | None |
| SteamOS validation | Not yet | Low |
| Dedicated appliance | Future phase | None |

---

## Four-mode audit

### 1. Live TV

**Status: substantially functional**

Implemented:

- real embedded video and audio,
- persistent channels,
- automatic scheduled program rollover,
- channel Up / Down,
- numeric direct tuning,
- Previous Channel,
- volume/mute,
- functional Home menu and lower quick-action navigation,
- persistent volume, mute, and skip-distance Settings,
- Standard/Lightweight/Custom performance settings with safe generated-art
  cache controls,
- transport-neutral couch control intents with keyboard, multimedia-key, and
  consumer-remote-key translation,
- pause / resume,
- rewind and skip forward,
- LIVE return,
- Viewer Clock lag,
- channel/program HUD,
- Now / Next,
- schedule progress,
- D3D11VA hardware-decoded real-media validation,
- stable maximize/restore using a bounded translucent HUD architecture.
- contextual Info drawers for Home, Guide, Library, Live, and On Demand.

Still needed:

- native controller/Steam Input adapter and real-machine validation,
- startup/resume polish,
- release hardening.

Estimated mode completion:

**90-95% of the first-release viewing experience.**

### 2. Guide

**Status: substantially functional**

Implemented:

- authoritative multi-channel schedule horizon,
- Now / Next,
- exact program durations,
- stable schedule occurrence IDs,
- current Broadcast Clock marker,
- selected-program detail,
- tune current program,
- Watch from Beginning runtime path,
- adaptive short-form visual aggregation,
- real-machine Guide-to-playback validation.

Estimated mode completion:

**90-95% of the first-release Guide experience.**

### 3. Library / On Demand

**Status: backend/source-management foundation strong; consumer surface functional and expanding**

Implemented:

- canonical indexed media,
- first-class `media_sources`,
- source status/counts/scan timestamps/errors,
- preflight with no persistence side effect,
- worker-thread hashing/probing,
- cooperative cancellation including large-file hashing,
- successful-only membership reconciliation,
- safe index-only source removal,
- shared-asset preservation,
- source/channel dependency protection,
- search and sort,
- content-first navigation with expandable horizontal shelves,
- local sidecar artwork and lazy video-thumbnail caching with a no-image fallback,
- stable-asset On Demand launch,
- On Demand play/pause/seek,
- durable playhead checkpoints and restart-safe resume,
- truthful Continue Watching shelf with progress and completion handling,
- natural-EOF recovery,
- successful handoff back to live television.

Still needed for the intended consumer Library:

- richer selected-title artwork/backdrop presentation,
- Recently Added/categories,
- richer title/media-type model,
- Movies / Television / seasons / episodes,
- metadata,
- collections/favorites,
- Library -> Add to Channel,
- richer filtering and organization.

Estimated completion:

- **Library backend/source lifecycle: 85-90%**
- **consumer Library experience: 65-70%**

### 4. Broadcaster / Management

**Status: safe Channel Builder MVP implemented**

Implemented:

- Broadcaster Home with channel/current/next state,
- create/edit channel flow,
- display number and width,
- sequential/shuffle modes,
- preserve-order option,
- repeat window,
- source selection,
- real resolver/runtime preview,
- duplicate number/file overwrite prevention,
- explicit Edit path with identity lock,
- `.bak` backup before updates,
- atomic replace,
- portable Channel Definition 0.1 YAML in `channels/`,
- immediate Guide/runtime/numeric-tuning reload,
- external/LLM authoring documentation.

Still needed:

- Library -> Add to Channel,
- programming-block editor,
- weighted rotations,
- time-of-day schedules,
- marathons/feature slots,
- seasonal rules,
- bumpers/station IDs,
- richer metadata correction,
- backup/export controls.

Estimated mode completion:

**80-85% of the minimum first-release Broadcaster, with advanced programming intentionally later.**

---

## Architectural decisions validated by implementation

### Qt Quick / PySide6

Qt Quick remains an implementation choice rather than a product-definition dependency.

### libVLC embedded playback

ChannelOS owns television state and control. libVLC remains a replaceable playback backend.

### Windows native video + bounded HUD composition

The libVLC target is a native child window. A second full-screen transparent native child above it proved unsafe across Windows maximize/restore transitions: the video could remain active while presentation was obscured.

The validated architecture keeps the native video surface unchanged, uses small bounded native overlays where appropriate, and renders the translucent lower-third as a bounded transient top-level window. This preserves the old HUD appearance while allowing Windows to alpha-compose it without covering the entire video surface.

No decoder restart or HWND-rebind recovery loop is required for maximize/restore.

### Separate On Demand session

On Demand playback uses the same canonical media index but does not insert a Library asset into television scheduling. Television remains television; On Demand remains direct selection.

On Demand resume state is persisted by stable asset ID and the current default
viewer ID. It is deliberately stored separately from both Broadcast Clock and
Viewer Clock state. Five-second checkpoints plus pause, seek, stop, and shutdown
saves make resume robust without turning the 250 ms presentation refresh into
constant database writes. The schema is ready for later per-profile rows; no
profile experience is claimed yet.

### Decoder suspension during On Demand

When On Demand temporarily owns the presentation surface, ChannelOS may stop the live decoder without stopping the channel's Broadcast Clock. Returning to television can therefore correctly reveal Viewer Clock lag.

---

## Important remaining first-release work

1. Native controller/Steam Input adapter and real-machine validation.
2. Normal-user libVLC/runtime packaging.
3. Windows installer / repeatable package.
4. Linux and SteamOS validation.
5. Frozen packaged-dependency bill of materials and compliance verification
   under `docs/DISTRIBUTION.md` (the MPL-2.0 source license and development
   notices are complete).
6. Crash recovery, clean-machine testing, and ordinary-user hardening.

Library -> Add to Channel remains defined by the Channel Studio concept and is
intentionally queued behind the current input and packaging work so its
authoring behavior can be designed deliberately.

---

## Delivery calibration

These remain planning ranges, not promises.

### Working local alpha

**Achieved.**

### Focused desktop/couch beta

At the current observed development and test cadence:

**roughly 2-4 weeks** remains a reasonable planning range if scope stays focused.

### Shareable packaged Windows beta

**roughly 3-6 weeks** remains a reasonable planning range.

Packaging, licensing, controller behavior, clean-machine testing, migration, failure recovery, and installer behavior can take disproportionately longer than feature coding.

### Steam / SteamOS-quality release candidate

**roughly 6-10 weeks**, subject to packaging quality, SteamOS behavior, release requirements, and platform acceptance.

### Full long-range Master Design

The multi-device, profiles, export, ecosystem, and dedicated-appliance roadmap remains a project measured in **months**, not days. A **3-6+ month** range can still be reasonable for that broad target.

---

## Current product identity

The implementation still supports the original one-sentence definition:

> **ChannelOS is a user-owned cable network built from a user-owned media library.**

And the second statement is now literal in the running product:

> **The user is not merely the audience. The user is the broadcaster.**

The largest visible feature gap before a focused beta remains
Library-to-channel authoring. Packaging, input polish, and release hardening
remain the larger delivery risks.
