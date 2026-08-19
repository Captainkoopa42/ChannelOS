# ChannelOS Master Design

> **User-controlled television for user-owned media.**
>
> Own the library. Own the schedule. Own the interface.

**Status:** Living design / pre-alpha  
**Design version:** 0.3 — August 2026  
**Role:** Canonical product and system design reference

---

## 1. Purpose of this document

This document is the central design reference for ChannelOS.

The repository contains narrower documents for vision, architecture, roadmap, implementation decisions, current milestones, and file formats. This file exists to keep the whole idea visible in one place so contributors can answer a more important question than *“what code are we writing?”*:

> **What are we trying to build, what should it feel like, and what must never be lost as the implementation changes?**

When a lower-level implementation choice conflicts with the principles in this document, the implementation should change unless the design itself is deliberately revised.

ChannelOS is not defined by Python, YAML, VLC, Steam, SteamOS, a particular operating system, or a particular remote-control technology. Those are replaceable implementation and distribution choices.

ChannelOS is defined by its relationship with the user:

> **The software serves the user's media library. The library does not exist to serve the software.**

---

## 2. The core idea

ChannelOS is a local-first personal television system built around media the user owns or legitimately controls.

It combines two experiences that modern media systems often separate:

1. **Television:** turn it on, select a channel, and something is already playing.
2. **On demand:** browse the library, search, filter, choose a specific item, and control playback directly.

The user should never have to choose between the convenience of television and the control of a personal media library.

**One-sentence definition:**

> **ChannelOS is a user-owned cable network built from a user-owned media library.**

A shorter product phrase is:

> **User-controlled television.**

Traditional cable gives the broadcaster control over the schedule. Streaming gives the viewer control over selection but turns most viewing into active browsing. ChannelOS gives the user both roles.

> **The user is not merely the audience. The user is the broadcaster.**

ChannelOS is intended to become open-source software. The repository currently has not yet selected an open-source license, so that legal release step remains explicit rather than assumed.

---

## 3. Why ChannelOS exists

Digital distribution made media easier to access while making permanent ownership less central.

A modern customer may pay for access while remaining dependent on accounts, catalogs, license agreements, supported applications, authentication servers, changing terms, provider availability, and continued corporate interest in a particular title.

ChannelOS starts from a different premise:

> A media collection should behave more like a bookshelf than a temporary catalog rented from somebody else.

At the same time, local media software often replaces one problem with another. A folder tree or giant wall of thumbnails preserves ownership but loses the effortless quality of television.

Traditional television had a useful property:

> **You could just turn it on.**

ChannelOS preserves that passive experience without giving up user control.

A useful summary is:

- **Streaming can be excellent for access and discovery.**
- **Ownership is better for preservation.**
- **ChannelOS exists to make ownership effortless to watch.**

---

## 4. Constitutional principles

These principles are hard constraints unless the project deliberately changes its identity.

### 4.1 Ownership first

Media remains usable independently of ChannelOS.

ChannelOS may index, identify, schedule, annotate, remember, and present files. It must not require users to surrender those files into a proprietary media container.

Deleting ChannelOS must not delete or invalidate the user's collection.

### 4.2 Local first

Core functions should not require the internet:

- media indexing,
- channel generation,
- tuning,
- scheduling,
- Guide generation,
- playback,
- profiles,
- watch state,
- local metadata already stored by the system,
- export/import.

Online services may enhance the experience. They must not authorize the user's right to use the core system.

### 4.3 Open, portable state

Channel definitions, exports, metadata overrides, and other durable configuration should be documented and portable.

A user must be able to leave ChannelOS without losing the organizational work they put into it.

### 4.4 Couch first

Routine viewing must be comfortable from a couch with a remote or controller.

A mouse should not be required for normal television use.

### 4.5 Passive when desired, direct when desired

ChannelOS should never force the user into either pure television behavior or pure on-demand behavior.

The user can:

- press `7` and watch whatever Channel 7 is broadcasting,
- open the Guide,
- browse the Library,
- search for a specific movie,
- pause or rewind a channel,
- jump back to LIVE,
- or build and edit the channel itself.

### 4.6 No mandatory advertising

ChannelOS does not inject advertising into local user-owned media.

Users may intentionally program trailers, bumpers, station IDs, home videos, public-service material, music, or their own commercial-like breaks if they want them. The system should not impose them.

### 4.7 Explainable automation

When ChannelOS selects content automatically, the user should be able to understand why.

```text
Channel 7
→ weekday prime-time block
→ science-fiction rotation
→ Stargate SG-1
→ next unplayed episode
```

Automation should serve the broadcaster, not become an invisible authority.

### 4.8 Replaceable components

Playback engines, metadata providers, source adapters, remotes, user interfaces, and distribution channels should be replaceable behind stable ChannelOS interfaces.

The project should avoid becoming dependent on one vendor, one cloud API, one player engine, or one storefront when a clean abstraction can prevent that dependency.

### 4.9 Distribution is not entitlement

A platform may install, update, launch, or help users discover ChannelOS. It must not become the authority that decides whether the user's standalone or appliance installation may play local media.

This principle is especially important because Steam is the preferred primary public launch target.

---

## 5. Product forms and deployment

ChannelOS should be one television system that can inhabit several kinds of host.

```text
ChannelOS Core
   ├── Desktop / PC application
   │      Windows / Linux
   │      ordinary installable program
   │
   ├── Steam / SteamOS application
   │      preferred public launch/discovery target
   │      living-room/controller-first
   │
   └── Dedicated appliance
          minimal host OS
          boots directly into ChannelOS
          HDMI + remote/controller
```

### 5.1 Desktop application

The ordinary software form should install and run like a normal application on supported Windows and Linux systems.

A user can point it at local disks, removable storage, or network shares and use ChannelOS without turning the entire computer into an appliance.

### 5.2 Steam and SteamOS

Steam is the preferred **primary public launch and discovery target**, subject to Valve accepting the application and the project satisfying release requirements.

If ChannelOS is distributed on Steam, the intended listing is free to users.

SteamOS and Steam Machine-class living-room PCs are especially attractive reference hosts because the ChannelOS product is already designed around:

- a television,
- controller/remote-style input,
- fullscreen launching,
- local PC storage,
- PC-class hardware decoding,
- an application library that can be launched from the couch.

But the architectural rule is explicit:

> **Steam may be where many users get ChannelOS. Steam must never be what makes ChannelOS theirs.**

A Steam account, Steam client, or Steam entitlement check must not be required for standalone or appliance local playback.

### 5.3 Dedicated appliance

The same core should eventually be capable of turning a supported small PC into a dedicated ChannelOS receiver.

ChannelOS does **not** need a custom kernel to do this. A minimal existing Linux base can provide drivers, filesystems, networking, GPU/video support, USB, Bluetooth, and HDMI, then boot directly into ChannelOS.

```text
POWER
  ↓
minimal host OS
  ↓
ChannelOS runtime/service
  ↓
full-screen ChannelOS UI
  ↓
TV
```

From the couch, the underlying general-purpose OS should disappear.

The system is the product. The box is one possible host.

See [ADR-0004](decisions/0004-distribution-and-appliance-neutrality.md).

---

## 6. The four user-facing modes

ChannelOS has four major user experiences. They are different views over the same library and runtime.

### 6.1 Live TV

Live TV is the passive mode.

Turn on ChannelOS and a channel is already playing. Enter a number or use Channel Up/Down to tune.

Core controls:

- digits `0–9`,
- Channel Up / Down,
- Previous Channel,
- Volume Up / Down,
- Mute,
- Play / Pause,
- Rewind,
- Fast Forward,
- Skip Back / Skip Forward,
- LIVE,
- Guide,
- Info,
- Home,
- Back.

The goal is not to mimic old television limitations. The goal is to preserve television's simplicity while giving the owner better control.

### 6.2 Guide

The Guide is a traditional electronic program guide generated from the user's own channels.

```text
              8:00          8:30          9:00          9:30
──────────────────────────────────────────────────────────────────
  2  Comedy   Futurama      Futurama      Simpsons       Simpsons
  4  Movies   Jurassic Park ────────────────────────────→
  7  Sci-Fi   Stargate SG-1 ───────→ Star Trek TNG ─────────────→
  9  Docs     Planet Earth ─────────────→ Cosmos ────────────────→
 12  Trek     DS9 ──────────→ Voyager ─────────→ Enterprise ─────→
```

The Guide should support television-like navigation while taking advantage of local ownership:

- select a currently airing program → **Tune**,
- select a future program → **Info / future schedule actions**,
- select an eligible past/current owned program → **Watch from Beginning**,
- press Info → display why it was scheduled.

The Guide is a view over schedule truth. It must not invent a second scheduling system.

### 6.3 Library / On Demand

The Library is the active selection mode.

Users should be able to browse their collection as a rich media shelf rather than a folder tree.

Top-level examples:

- Movies,
- Television,
- Documentaries,
- Animation,
- Home Video,
- Music / Audio where supported,
- Collections,
- Genres,
- Tags,
- Favorites,
- Continue Watching,
- Recently Added.

A title page might show:

```text
Alien
1979 • Sci-Fi • Horror • 1h 57m

[poster]      [backdrop]

PLAY
ADD TO CHANNEL
MORE INFO
```

The Library and channel system must operate on the same canonical media index. They should never become separate collections that drift apart.

### 6.4 Management / Broadcaster mode

Television viewing should be remote-simple. Media administration does not have to be.

Management tasks include:

- add files/folders/network locations/removable storage,
- review unmatched media,
- correct metadata,
- select artwork,
- create genres/tags/collections,
- create and number channels,
- build schedules and programming blocks,
- create profiles,
- manage household restrictions if enabled,
- backup/export the system.

A useful long-term pattern is:

```text
ChannelOS appliance / receiver
        │
        ├── TV interface: watch
        │
        └── local web interface: manage
```

The television remains simple while deep control remains available.

---

## 7. The fundamental channel model

A channel is **not a folder** and **not merely a playlist**.

A channel is a programmable broadcast identity over one or more media sources.

It has at least:

- channel number,
- name,
- optional branding/artwork,
- eligible source selectors,
- scheduling rules,
- programming rules,
- continuity state,
- generated timeline,
- Now / Next state,
- optional profile-specific behavior.

Current schema `0.1` deliberately supports a smaller subset than the long-term model. Future source selectors and programming modes must be added through explicit versioned schema changes rather than silently changing existing definitions.

Example of current-style intent:

```yaml
schema_version: "0.1"
channel: 7
name: Sci-Fi
sources:
  - path: /media/TV/Sci-Fi
programming:
  mode: shuffle
  preserve_episode_order: false
  avoid_repeat_days: 0
presentation:
  number_width: 3
```

Longer-term channel sources may come from genres, tags, collections, series, paths, or combinations of them.

---

## 8. Broadcast time and viewer time

This is one of ChannelOS's foundational concepts and is already implemented in Phase 1.

Each channel has a **Broadcast Clock**: what the channel would be showing at a given time whether or not anyone is currently watching it.

Each viewer has a **Viewer Clock**: where that person is currently watching within the channel's timeline.

Normally:

```text
Broadcast:  21:47:12
Viewer:     21:47:12
State:      LIVE
```

Pause for five minutes:

```text
Broadcast:  21:52:12
Viewer:     21:47:12
Offset:     -00:05:00
```

Resume and the viewer remains five minutes behind. Fast-forward can reduce that gap until LIVE. Rewind can move through reconstructable earlier schedule time.

The key design rule is:

> **The schedule belongs to the channel. The playhead belongs to the user.**

### Returning to a channel

ChannelOS supports three explicit return policies:

- `live` — return to the channel's current broadcast point,
- `resume` — return to the viewer position previously left behind,
- `ask` — expose both choices when meaningful.

See [ADR-0003](decisions/0003-persistent-channel-clocks.md).

---

## 9. Programming engine

The programming engine converts channel definitions, indexed media, schedule rules, and runtime state into a deterministic or explainable timeline.

Phase 1 has implemented and validated:

- deterministic sequential programming,
- deterministic shuffle derived from stable asset identity,
- all eligible shuffle items before cycle repetition,
- strict `avoid_repeat_days` feasibility validation.

Longer-term programming capabilities include:

- weighted rotation,
- time-of-day blocks,
- weekday/weekend rules,
- morning / afternoon / prime-time / late-night identities,
- marathons,
- movie feature slots,
- seasonal programming,
- specials,
- user-selected trailers,
- bumpers,
- station IDs,
- intermissions,
- music or atmosphere blocks.

The programming engine should operate without actually decoding every channel.

If a household has 100 channels, ChannelOS should not require 100 simultaneously playing videos. It only needs schedule state describing what each channel *would* be broadcasting.

```text
Channel 7 schedule:
21:29:00 — 22:18:00  The Expanse

Tune time:
21:47:00

Resolved playback:
The Expanse episode X
seek to 00:18:00
```

Only the tuned media needs to be decoded.

---

## 10. Guide and UI-facing service boundary

Phase 2 introduces the next important architectural boundary.

The UI should not reach into runtime internals or recalculate channel schedules. Instead, ChannelOS should expose television-facing read models and control intents.

```text
Channel Runtime
      ↓
Guide / Television Service Boundary
      ├── schedule horizon
      ├── Now / Next
      ├── Guide channel rows
      ├── program detail
      ├── explain-why trace
      └── control intents
      ↓
UI clients
```

The boundary should support at least:

- Guide horizons over a requested time range,
- Now / Next per channel,
- numeric channel identity and names,
- program start/end/duration,
- stable references to scheduled owned media,
- LIVE/viewer state where relevant,
- explain-why traces,
- tune from Guide,
- Watch from Beginning where schedule reconstruction and owned media permit it.

The first implementation may remain in-process. It should still be explicit enough to become a local API or IPC service later.

That allows the same core to drive:

- desktop UI,
- fullscreen couch UI,
- Steam/SteamOS launch,
- dedicated appliance UI,
- local management web UI,
- phone/tablet remote,
- multi-TV household clients.

See [GUIDE_AND_UI_BOUNDARY.md](GUIDE_AND_UI_BOUNDARY.md).

---

## 11. Media library and index

The media library is the durable center of ChannelOS.

ChannelOS indexes media rather than absorbing it.

The source files remain where the user chooses:

```text
D:\Media\Movies\
D:\Media\Television\
/media/documentaries/
NAS:/FamilyVideo/
```

The index may record:

- stable ChannelOS media ID,
- current path/location(s),
- file identity/fingerprint information,
- media type,
- title/year/runtime,
- series/season/episode,
- genres/tags/collections,
- cast/creator data,
- description/artwork,
- audio/subtitle tracks,
- technical media information,
- metadata source and user overrides,
- availability state.

Runtime databases can be disposable. The user's media cannot be.

### Stable identity

Paths change. Drives get renamed. NAS mounts move.

The Phase 0 reference core identifies exact file content with a full-file SHA-256 ID and stores filesystem location separately.

A user should be able to move a library and relink it without rebuilding every channel from scratch.

---

## 12. Import, metadata, tags, and collections

Adding media should be easy enough for ordinary household use.

The TV interface may expose simple Add Media actions while the management interface provides deeper workflows.

ChannelOS should never silently rewrite or reorganize the user's files unless the user explicitly requests such a tool.

Metadata should make a personal library pleasant to browse without becoming another dependency trap.

Potential provider boundary:

```text
MetadataProvider
    ├── Online provider plugin
    ├── Local sidecar metadata
    ├── Embedded metadata
    └── Manual entry
```

Users should be able to override titles, artwork, descriptions, genres, tags, numbering, collections, and match identity.

Genres are broad classification. Tags are personal concepts. Collections are explicit groups. Channels are programmable broadcast views that can eventually select from all of them without duplicating media files.

> Losing access to a metadata website should not turn a carefully organized local library back into meaningless filenames.

---

## 13. Profiles and household state

The media library belongs to the ChannelOS installation or household, while profiles primarily own viewing state and preferences.

A profile may contain:

- watch history,
- Continue Watching state,
- favorites,
- viewer clock offsets,
- return-to-channel behavior,
- language/subtitle preferences,
- personal channels,
- UI preferences,
- content visibility rules where configured.

ChannelOS may support both household channels shared by everyone and personal channels belonging to one profile without duplicating underlying media.

---

## 14. Playback architecture and packaging

ChannelOS should not waste years re-solving media decoding.

Playback belongs behind a backend-neutral adapter.

```text
Channel Runtime
      │
      ▼
PlaybackBackend
      │
      ├── LibVLCBackend   ← first reference backend
      ├── future mpv backend
      └── future backends
```

ChannelOS owns:

- what should play,
- when it should play,
- where playback should begin,
- channel switching,
- viewer time,
- volume/mute/pause/seek intent,
- Guide state,
- continuity.

The playback backend owns:

- decoding,
- codecs/containers,
- hardware acceleration,
- audio output,
- subtitles,
- seeking implementation,
- rendering.

> **VLC does media playback. ChannelOS does television.**

### Development playback runtime

`python-vlc` is a control binding; it does not itself contain the native libVLC runtime.

Development builds may use:

- a bundled-style `runtime/vlc` directory,
- `CHANNELOS_VLC_DIR` as an explicit source/development override,
- compatible system runtime discovery where supported.

### Finished product packaging

Ordinary users should not be asked to install VLC into a particular path or configure DLL search behavior.

A finished package should include the compatible native playback runtime it requires where licensing permits:

```text
ChannelOS/
    application executable
    runtime/
        vlc/
            libVLC runtime
            plugins/
```

The backend-neutral boundary remains unchanged.

Third-party runtime license compliance and notices are release requirements, not optional cleanup.

---

## 15. Control model and remote protocol

The physical remote, gamepad, keyboard layer, or phone remote should not contain ChannelOS business logic.

They should emit a small open set of user intents.

```text
POWER

DIGIT 0 ... DIGIT 9
TUNE 007
CHANNEL_UP
CHANNEL_DOWN
PREVIOUS_CHANNEL

VOLUME_UP
VOLUME_DOWN
MUTE

PLAY
PAUSE
PLAY_PAUSE
REWIND
FAST_FORWARD
SKIP_BACK
SKIP_FORWARD
GO_LIVE

GUIDE
INFO
HOME
BACK

UP
DOWN
LEFT
RIGHT
SELECT
```

The ChannelOS service/runtime interprets those intents.

This allows the same control model to be driven by keyboard, gamepad, USB remote, Steam Input/controller mappings, local web remote, phone, development console, or future purpose-built hardware.

The software should not care whether the signal arrived over USB, infrared, Bluetooth, RF, or another transport once translated into ChannelOS intents.

---

## 16. Couch UI and visual direction

The ChannelOS television UI should be designed for distance, not for a desktop monitor.

Priorities:

- high contrast,
- large readable type,
- obvious selected/focused element,
- large controller/remote-friendly targets,
- shallow common navigation,
- no mandatory pointer,
- fast return to Live TV,
- minimal obstruction of currently playing media.

### Default visual family

The default ChannelOS theme should use a Steam-adjacent dark/cool living-room palette:

- deep navy or charcoal background,
- slightly lighter blue-black panels,
- cool blue focus/selection accents,
- bright soft-white primary text,
- blue-gray secondary text,
- restrained red for LIVE,
- amber for warnings where useful.

The goal is **continuity of environment**, especially when launched from SteamOS, not imitation.

ChannelOS must retain its own wordmark, iconography, layout, and focus language. It should not reproduce Steam trademarks or visually masquerade as the Steam interface.

Themes can come later. Accessibility and television readability outrank stylistic purity.

---

## 17. Complete system architecture

```text
                        USER
                         │
              Remote / TV / Web Client
                         │
                         ▼
+-------------------------------------------------------------+
|                Guide / Television Service                  |
| horizon | now/next | tune | controls | explain-why        |
+-----------------------------+-------------------------------+
                              │
                              ▼
+-------------------------------------------------------------+
|                    Television Runtime                       |
| broadcast clocks | viewer clocks | tuning | continuity     |
+------------------+--------------------------+---------------+
                   │                          │
                   ▼                          ▼
+--------------------------+       +--------------------------+
|   Programming Engine     |       |     Playback Adapter     |
| sequence | shuffle       |       | libVLC / future         |
| future blocks/weighting  |       +--------------------------+
+------------+-------------+
             │
             ▼
+-------------------------------------------------------------+
|                 Media Library / Index                       |
| stable IDs | metadata | genres | tags | collections         |
| technical info | availability | user overrides             |
+-----------------------------+-------------------------------+
                              │
                              ▼
+-------------------------------------------------------------+
|                       Source Adapters                       |
| local files | NAS | removable storage | supported future   |
+-------------------------------------------------------------+

Optional local services:
Metadata Providers
Profile Store
Artwork Cache
Export / Import
Local Management Web UI
Remote Receiver Service
```

The authoritative scheduling logic lives below the UI.

The playback backend does not decide what Channel 007 means.

The distribution platform does not decide whether the user's local media may play.

---

## 18. Export My Television

Portability should become a first-class feature rather than an emergency feature.

A full export should eventually preserve:

- channel definitions and lineup,
- schedules/programming rules,
- tags and collections,
- metadata overrides,
- artwork references or portable artwork where allowed,
- library mappings,
- profiles,
- watch state,
- viewer preferences,
- application settings.

The user should be able to:

1. install ChannelOS on another machine,
2. restore or reconnect the media library,
3. import the export,
4. relink moved storage where necessary,
5. recover a recognizable version of their television system.

This migration should work across deployment forms where platform capabilities allow it: desktop to desktop, Steam install to standalone install, or desktop to dedicated appliance.

> **If ChannelOS disappears, the library survives. If a machine disappears, the television can be rebuilt.**

---

## 19. Plugin, privacy, and network posture

ChannelOS should grow through explicit interfaces rather than hard-coding every service into the core.

Potential extension points include:

- PlaybackBackend,
- MetadataProvider,
- MediaSourceAdapter,
- ArtworkProvider,
- RemoteTransport,
- Guide/notification integration,
- authorized online source integrations.

Plugins should be treated as untrusted until granted capabilities. They should not silently receive unrestricted filesystem or network access.

The core system should work without telemetry, a mandatory ChannelOS account, a mandatory remote server, or a mandatory storefront entitlement.

Networking should be explicit and understandable:

- local NAS access,
- local remote/control traffic,
- local management UI,
- explicitly enabled metadata lookups,
- explicitly installed provider integrations.

A household should be able to run a useful ChannelOS installation entirely within its local network after software and desired metadata are installed.

---

## 20. What ChannelOS is not

ChannelOS is not intended to be:

- another subscription streaming service,
- a proprietary media store,
- a DRM-circumvention project,
- a streaming-service scraper,
- an ad-removal system for third-party protected streams,
- a custom video codec project,
- a custom general-purpose OS kernel project,
- a replacement for mature playback engines,
- a cloud account required to play local files,
- a Steam-only application,
- a platform that hides user configuration in an unreadable proprietary format.

Its job is narrower and more interesting:

> **Turn a user's own media collection into a television system they control.**

---

## 21. Current implementation status

### Phase 0 — Foundation

**Complete.**

The reference core can index genuine local media, preserve stable identity independently of path, resolve channel sources, and display real video through the ChannelOS → libVLC path.

### Phase 1 — Persistent channels

**Complete and merged to `main`.**

Implemented and validated:

- persistent numeric channel identities,
- deterministic sequential programming,
- deterministic shuffle with repeat-window validation,
- generated repeating timelines,
- Broadcast Clock,
- Viewer Clock,
- restart persistence,
- missing-file recovery,
- direct tune, Channel Up/Down, Previous Channel,
- live/resume/ask behavior,
- pause/play/seek/`GO_LIVE`,
- real Windows libVLC playback,
- Windows runtime discovery for bundled/development libVLC layouts.

The final local Windows suite passed 37 tests and the final Phase 1 GitHub Actions run passed before merge.

### Phase 2 — Guide / UI-facing plumbing

**Current.**

The next job is to expose the already-working television engine as stable Guide and UI-facing data:

- schedule horizon generation,
- Now / Next,
- Guide rows,
- schedule regeneration rules,
- explain-why traces,
- tune from Guide,
- Watch from Beginning,
- real-media Guide-to-playback validation.

The polished couch shell follows this plumbing rather than reaching directly into runtime internals.

See [GUIDE_AND_UI_BOUNDARY.md](GUIDE_AND_UI_BOUNDARY.md).

---

## 22. Roadmap discipline

The detailed implementation phase ordering lives in [ROADMAP.md](ROADMAP.md).

The Master Design deliberately does **not** duplicate a second numbered roadmap. Doing so caused the earlier design document and executable roadmap to drift apart as implementation accelerated.

This document owns product identity and architectural invariants. `ROADMAP.md` owns milestone sequencing and completion state.

---

## 23. First complete product test

A meaningful product test is not “does a window open?”

It is:

1. Give ChannelOS a folder containing several movies and television series.
2. Let it identify/index them without taking ownership of the files.
3. Define several channels.
4. Generate persistent schedules.
5. Start ChannelOS full-screen.
6. Press `7`.
7. See the correct program at the correct broadcast offset.
8. Pause.
9. Wait.
10. Resume behind LIVE.
11. Fast-forward until LIVE.
12. Open the Guide.
13. Tune Channel 12 from the Guide.
14. Open Library.
15. Deliberately choose a movie.
16. Return to Live TV.
17. Shut ChannelOS down and restart it without losing channel time.
18. Export the configuration.
19. Restore/relink it on another supported installation.

If that experience works coherently, ChannelOS is no longer merely a media-player wrapper. It is a personal television system.

A public living-room launch test adds:

20. Install/launch ChannelOS through Steam or SteamOS.
21. Complete ordinary couch use with a controller/remote and no mouse.
22. Verify the same media/configuration can also be used by a standalone build without Steam present.

---

## 24. Release and legal gates

Before a public release, especially a Steam launch, ChannelOS must deliberately complete:

- selection and addition of an appropriate open-source software license,
- third-party dependency/license review,
- bundled libVLC license/notice compliance,
- repeatable Windows and Linux packaging,
- SteamOS/controller validation,
- standalone no-Steam validation,
- privacy/network behavior review,
- clear user-facing handling of media sources and permissions.

The project should not call itself legally open source merely because the source is visible. The intended license must actually be selected and published.

---

## 25. Design questions every feature must pass

Before adding a major feature, ask:

1. Does this increase or reduce the user's control over their media?
2. Does the core behavior still work without internet access?
3. Can the user understand what the system did?
4. Can the user override it?
5. Can the result be exported or migrated?
6. Does it preserve ordinary access to the underlying media?
7. Does it make routine television use easier from a couch?
8. Does it avoid unnecessary reinvention of mature technology?
9. Does it work with both passive viewing and direct selection?
10. Are we building for the user's library, or accidentally building another ecosystem trap?
11. Would the feature still make sense outside Steam or any other distribution platform?

A feature that fails several of these questions should be reconsidered.

---

## 26. Product language

Several phrases capture the project clearly and should remain useful touchstones:

> **User-controlled television.**

> **The schedule belongs to the channel. The playhead belongs to the user.**

> **VLC does media playback. ChannelOS does television.**

> **If ChannelOS disappears, the library survives.**

> **The user is not the audience of ChannelOS. The user is the broadcaster.**

> **Steam may be where many users get ChannelOS. Steam must never be what makes ChannelOS theirs.**

---

## 27. North Star

ChannelOS should eventually feel less like launching software and more like owning an appliance that happens to be open, programmable, and under the household's control.

A person should be able to spend an evening without browsing a catalog at all:

```text
POWER
7
```

and simply watch television.

Five minutes later, that same person should be able to decide they want something specific:

```text
HOME
LIBRARY
MOVIES
ALIEN
PLAY
```

Neither mode is secondary.

On a desktop, ChannelOS should be an ordinary program. On SteamOS, it should feel like a natural living-room application. On a dedicated receiver, it should be able to become the entire visible boot experience.

Those are different hosts for the same user-owned television system.

Modern media taught people to expect convenience. Local ownership provides durability. ChannelOS should refuse the assumption that users must sacrifice one to have the other.

**Own the library. Own the schedule. Own the interface.**
