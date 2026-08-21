# ChannelOS Implementation Status

**Snapshot:** August 20, 2026  
**Status:** Working local alpha  
**Active implementation:** Phase 3 couch experience with the first functional Phase 4 Library / On Demand slice  
**Canonical product definition:** [MASTER_DESIGN.md](MASTER_DESIGN.md)

This document records implementation progress against the original ChannelOS design.

It does **not** redefine the product in order to match the implementation.

The Master Design remains the yardstick.

---

## Executive assessment

ChannelOS has moved beyond a proof-of-concept core.

A real Windows machine can now:

- index ordinary user-owned media without taking ownership of the files,
- preserve stable media identity independently of file path,
- run persistent numbered television channels,
- advance channels while they are not being watched,
- maintain separate Broadcast and Viewer Clocks,
- generate a traditional multi-channel Guide,
- tune Guide selections through the authoritative runtime,
- display embedded video and audio inside the ChannelOS couch UI,
- use hardware video decoding through libVLC / D3D11VA,
- automatically roll from one scheduled program into the next,
- pause, resume, rewind, skip forward, change channels, and return LIVE,
- visually aggregate very short scheduled clips without altering schedule truth,
- browse the real indexed media library,
- add media folders from inside the Library,
- play indexed media through an independent On Demand session,
- pause and seek On Demand media,
- recover correctly when replaying or rewinding after natural end-of-file,
- return from On Demand to live television while preserving television clock state.

This is now a working local television system rather than only an architectural prototype.

---

## Completion uses two different denominators

Earlier estimates blurred together a focused first release and the complete long-range design.

Those are not the same target.

### Focused desktop / couch v1

Estimated completion:

**approximately 60-65%**

This means the experience required for a credible local Windows/Linux television application:

- media ownership/indexing,
- persistent channels,
- Guide,
- live playback,
- television controls,
- Library / On Demand,
- minimum broadcaster/channel management,
- normal-user packaging,
- controller/remote polish,
- settings and release hardening.

### Full Master Design

Estimated completion:

**approximately 35-40%**

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

These later systems are real parts of the design but should not be confused with the amount of work remaining before ChannelOS becomes useful.

### Fidelity to the original idea

Estimated fidelity of the implemented system:

**approximately 90-95%**

This is a design-audit estimate, not a mathematical quality score.

The important result is that implementation progress has not required changing the fundamental identity of ChannelOS.

---

## Original idea vs. current implementation

| Original design requirement | Current state | Fidelity |
| --- | --- | --- |
| User-owned files remain ordinary files | Implemented | Very high |
| Local-first core | Implemented for current core | Very high |
| One canonical media index | Implemented | Very high |
| Numbered persistent television channels | Implemented | Very high |
| Channels advance while untuned | Implemented | Very high |
| Broadcast Clock | Implemented | Very high |
| Viewer Clock | Implemented | Very high |
| LIVE / behind-live behavior | Implemented and real-machine tested | Very high |
| Traditional television Guide | Implemented and real-machine tested | Very high |
| Guide derives from runtime truth | Implemented | Very high |
| Live television is passive by default | Implemented | High |
| Library is separate active-selection mode | Implemented first functional slice | High |
| Library and channels share one media index | Implemented | Very high |
| On Demand does not contaminate channel scheduling | Implemented with separate playback session | Very high |
| Couch-first presentation | Working keyboard/D-pad implementation | High |
| User is broadcaster | Runtime exists; management UI still incomplete | Partial |
| Rich metadata/artwork | Not yet | Low |
| Advanced scheduling/programming tools | Not yet | Low |
| Profiles | Not yet | None |
| Export/import | Not yet | None |
| Multi-device household | Not yet | None |
| SteamOS validation | Not yet | Low |
| Dedicated appliance | Future phase | None |

---

## Four-mode audit

The Master Design defines four major user-facing modes.

### 1. Live TV

**Status: substantially functional**

Implemented:

- real embedded video and audio,
- persistent channels,
- automatic scheduled program rollover,
- channel Up / Down,
- pause / resume,
- rewind and skip forward,
- LIVE return,
- Viewer Clock lag,
- temporary channel/program HUD,
- Now / Next,
- schedule progress,
- hardware-decoded real-media validation.

Still needed:

- numeric direct-tuning UI,
- Previous Channel couch binding,
- volume/mute couch controls,
- fuller Info behavior,
- controller/remote abstraction,
- startup/resume polish.

Estimated mode completion:

**85-90% of the first-release viewing experience.**

### 2. Guide

**Status: substantially functional**

Implemented:

- authoritative multi-channel schedule horizon,
- Now / Next,
- exact program durations,
- stable schedule occurrence IDs,
- explain-why data,
- current Broadcast Clock marker,
- selected-program detail,
- tune current program,
- Watch from Beginning runtime path,
- adaptive short-form visual aggregation,
- real-machine Guide-to-playback validation.

The Guide model remains exact even when the presentation groups many very short programs into readable visual blocks.

Estimated mode completion:

**90-95% of the first-release Guide experience.**

### 3. Library / On Demand

**Status: functional first slice**

Implemented:

- real indexed media list,
- real file names,
- real duration and file-size data,
- real source location,
- Add Media Folder workflow,
- dedicated On Demand playback session,
- play/pause,
- rewind/skip,
- end-of-file replay recovery,
- return to Library,
- successful handoff back to live television.

Still needed:

- normalized media/container labels,
- title/media-type model,
- Movies / Television / seasons / episodes,
- search,
- sorting/filtering,
- artwork,
- metadata,
- collections,
- favorites,
- Continue Watching,
- Recently Added,
- Add to Channel.

Estimated mode completion:

**45-55% of the intended Library experience**, despite the core playback path already working.

### 4. Broadcaster / Management

**Status: runtime foundation exists; product UI largely unbuilt**

Already underneath the UI:

- versioned channel definitions,
- numeric channel identity,
- sequential programming,
- deterministic shuffle,
- repeat avoidance,
- source resolution,
- generated schedule timelines,
- explainable scheduling primitives.

Still needed in the product interface:

- channel creation/editing,
- source selection,
- Add to Channel,
- channel numbering,
- programming-block editor,
- weighted rotations,
- time-of-day schedules,
- marathons,
- feature slots,
- seasonal rules,
- bumpers/station IDs,
- metadata correction,
- backup/export controls.

Estimated mode completion:

**20-30%**, because the engine foundation exists but broadcaster-facing tooling does not.

---

## Architectural decisions that strengthened rather than changed the idea

### Qt Quick / PySide6

The original design intentionally did not make the product dependent on one UI technology.

Qt Quick is therefore an implementation choice, not a product-definition change.

### libVLC embedded playback

ChannelOS still owns television state and control.

libVLC remains a replaceable decoder/playback backend.

The successful native WindowContainer integration therefore follows the original abstraction rather than exposing VLC as the product.

### Short-form Guide aggregation

Short captures created a presentation problem in a multi-hour Guide.

The solution deliberately preserved every exact scheduled occurrence and grouped only their visual presentation.

Schedule truth was not changed to make the UI easier.

### Separate On Demand session

On Demand playback uses the same canonical media index but does not insert a selected Library asset into the television schedule.

This is especially close to the original Master Design:

- television remains television,
- On Demand remains direct selection,
- both operate on the same owned library.

### Decoder suspension during On Demand

When On Demand temporarily owns the video presentation surface, ChannelOS may stop the live decoder.

It does **not** stop the channel's Broadcast Clock.

Returning to television therefore correctly reveals that the Viewer Clock may now be behind LIVE.

This behavior is a direct consequence of the original Broadcast Clock / Viewer Clock design.

---

## Important remaining first-release work

The largest remaining first-release work is no longer proving that ChannelOS can behave like television.

The remaining work is increasingly productization:

1. Library metadata/title cleanup, search, sorting, and media organization.
2. Minimum viable Broadcaster / Channel Management UI.
3. Numeric tuning, Previous Channel, volume/mute, and controller abstraction.
4. Settings and source management.
5. Continue Watching / resume integration.
6. Packaging libVLC so ordinary users do not configure a runtime directory.
7. Windows installer / repeatable package.
8. Linux and SteamOS validation.
9. License and third-party notice review.
10. Crash recovery and ordinary-user hardening.

---

## Delivery calibration

These are planning ranges, not promises.

The previous blanket **3-6 month** estimate was too coarse for the focused v1 because it treated later ecosystem/appliance work as though it were required before ChannelOS became useful.

Observed development has also moved materially faster than that estimate assumed.

### Working local alpha

**Achieved now.**

The system already performs the core ChannelOS loop with real media.

### Focused desktop/couch beta

At the current observed development and test cadence:

**roughly 2-4 weeks** is a reasonable planning range.

This assumes scope remains focused on the first-release experience rather than pulling later roadmap phases forward.

### Shareable packaged Windows beta

A more cautious range is:

**roughly 3-6 weeks.**

Packaging, licensing, controller behavior, clean-machine testing, migration, failure recovery, and installer behavior can take disproportionately longer than feature coding.

### Steam / SteamOS-quality release candidate

A reasonable current planning range is:

**roughly 6-10 weeks**, subject to packaging quality, SteamOS behavior, release requirements, and platform acceptance.

### Full long-range Master Design

The original multi-device, profiles, export, ecosystem, and dedicated-appliance roadmap remains a project measured in **months**, not days.

A **3-6+ month** range can still be reasonable for that broad target.

It should no longer be presented as the wait before ChannelOS itself becomes a usable product.

---

## Current product identity

The implementation still supports the original one-sentence definition:

> **ChannelOS is a user-owned cable network built from a user-owned media library.**

And the current implementation has made the second statement increasingly literal:

> **The user is not merely the audience. The user is the broadcaster.**

The remaining major gap is no longer whether ChannelOS can operate the television.

It is giving the broadcaster the complete set of tools to program it.
