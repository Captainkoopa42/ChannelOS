# ChannelOS Master Design

> **User-controlled television for user-owned media.**
>
> Own the library. Own the schedule. Own the interface.

**Status:** Living design / pre-alpha  
**Design version:** 0.2 — August 2026  
**Role:** Canonical product and system design reference

---

## 1. Purpose of this document

This document is the central design reference for ChannelOS.

The repository contains narrower documents for vision, architecture, roadmap, implementation decisions, and file formats. This file exists to keep the whole idea visible in one place so contributors can answer a more important question than *“what code are we writing?”*:

> **What are we trying to build, what should it feel like, and what must never be lost as the implementation changes?**

When a lower-level implementation choice conflicts with the principles in this document, the implementation should change unless the design itself is deliberately revised.

ChannelOS is not defined by Python, YAML, VLC, a particular operating system, or a particular remote-control technology. Those are replaceable implementation choices.

ChannelOS is defined by its relationship with the user:

> **The software serves the user's media library. The library does not exist to serve the software.**

---

## 2. The core idea

ChannelOS is a local-first, open-source personal television system built around media the user owns or legitimately controls.

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

These principles should be treated as hard constraints unless the project deliberately changes its identity.

### 4.1 Ownership first

Media remains usable independently of ChannelOS.

ChannelOS may index, identify, schedule, annotate, remember, and present files. It must not require users to surrender those files into a proprietary media container.

Deleting ChannelOS must not delete or invalidate the user's collection.

### 4.2 Local first

Core functions should not require the internet:

- media indexing
- channel generation
- tuning
- scheduling
- guide generation
- playback
- profiles
- watch state
- local metadata already stored by the system
- export/import

Online services may enhance the experience. They must not authorize the user's right to use the core system.

### 4.3 Open, portable state

Channel definitions, exports, metadata overrides, and other durable configuration should be documented and portable.

A user must be able to leave ChannelOS without losing the organizational work they put into ChannelOS.

### 4.4 Couch first

Routine viewing must be comfortable from a couch with a remote.

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

Users may intentionally program trailers, bumpers, station IDs, home videos, public-service material, music, or even their own commercial-like breaks if they want them. The system should not impose them.

### 4.7 Explainable automation

When ChannelOS selects content automatically, the user should be able to understand why.

Example:

```text
Channel 7
→ weekday prime-time block
→ science-fiction rotation
→ Stargate SG-1
→ next unplayed episode
```

Automation should serve the broadcaster, not become an invisible authority.

### 4.8 Replaceable components

Playback engines, metadata providers, source adapters, remotes, and user interfaces should be replaceable behind stable ChannelOS interfaces.

The project should avoid becoming dependent on one vendor, one cloud API, or one media engine when a clean abstraction can prevent that dependency.

---

## 5. The four user-facing modes

ChannelOS has four major user experiences. They are different views over the same library and runtime.

### 5.1 Live TV

Live TV is the passive mode.

Turn on ChannelOS and a channel is already playing. Enter a number or use Channel Up/Down to tune.

Core controls:

- digits `0–9`
- Channel Up / Down
- Previous Channel
- Volume Up / Down
- Mute
- Play / Pause
- Rewind
- Fast Forward
- Skip Back / Skip Forward
- LIVE
- Guide
- Info
- Home
- Back

The goal is not to mimic old television limitations. The goal is to preserve television's simplicity while giving the owner better control.

### 5.2 Guide

The Guide is a traditional electronic program guide generated from the user's own channels.

Example:

```text
              8:00          8:30          9:00          9:30
──────────────────────────────────────────────────────────────────
  2  Comedy   Futurama      Futurama      Simpsons       Simpsons
  4  Movies   Jurassic Park ────────────────────────────→
  7  Sci-Fi   Stargate SG-1 ───────→ Star Trek TNG ─────────────→
  9  Docs     Planet Earth ─────────────→ Cosmos ────────────────→
 12  Trek     DS9 ──────────→ Voyager ─────────→ Enterprise ─────→
```

The Guide should support television-like navigation while taking advantage of the fact that the media is locally available.

Possible behavior:

- select a currently airing program → **Tune**
- select a future program → **Info / Reminder / Schedule options**
- select a past program still present in the library → **Watch from beginning**
- press Info → display why it was scheduled

This means ChannelOS can feel like cable while being more forgiving than cable.

### 5.3 Library / On Demand

The Library is the active selection mode.

Users should be able to browse their collection as a rich media shelf rather than a folder tree.

Top-level examples:

- Movies
- Television
- Documentaries
- Animation
- Home Video
- Music / Audio where supported
- Collections
- Genres
- Tags
- Favorites
- Continue Watching
- Recently Added

A title page might show:

```text
Alien
1979 • Sci-Fi • Horror • 1h 57m

[poster]      [backdrop]

PLAY
ADD TO CHANNEL
MORE INFO

Director
Cast
Genres
Description
Audio / subtitle information
```

A series page might expose:

```text
Star Trek: Deep Space Nine
7 Seasons • 176 Episodes

CONTINUE
SEASONS
EPISODES
ADD SERIES TO CHANNEL
MORE INFO
```

The Library and the channel system must operate on the same canonical media index. They should never become separate collections that drift apart.

### 5.4 Management / Broadcaster mode

Television viewing should be remote-simple. Media administration does not have to be.

ChannelOS should eventually provide a richer management interface, ideally reachable from a desktop or phone browser on the local network.

Management tasks include:

- add files or folders
- add network locations
- add removable storage
- detect supported discs
- review unmatched media
- correct metadata
- select posters or artwork
- create genres and tags
- create channels
- edit channel numbers
- build schedules and programming blocks
- create profiles
- manage parental/household restrictions if enabled
- backup/export the system

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

## 6. The fundamental channel model

A channel is **not a folder** and **not merely a playlist**.

A channel is a programmable broadcast identity over one or more media sources.

It has at least:

- channel number
- name
- optional branding/artwork
- eligible source selectors
- scheduling rules
- programming rules
- continuity state
- generated timeline
- Now / Next state
- optional profile-specific behavior

Example:

```yaml
schema_version: "0.1"
channel: 7
name: Sci-Fi
sources:
  genres:
    - Sci-Fi
  collections:
    - Stargate SG-1
    - Star Trek: The Next Generation
    - The Expanse
programming:
  mode: weighted_rotation
  preserve_episode_order: true
  avoid_repeat_days: 14
```

Another channel could be defined almost entirely from user tags:

```yaml
channel: 31
name: Late Night Horror
sources:
  tags:
    - horror
    - late-night
programming:
  start_after: "21:00"
  mode: shuffle_no_repeat
```

When new media receives the `late-night` tag, it can automatically become eligible for Channel 31.

This makes organization and broadcasting parts of one system.

---

## 7. Broadcast time and viewer time

This is one of ChannelOS's foundational concepts.

Each channel has a **Broadcast Clock**: what the channel would be showing at a given time whether or not anyone is currently watching it.

Each viewer session has a **Viewer Clock**: where the person is currently watching within that channel's timeline.

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

Resume and the viewer remains five minutes behind.

Fast-forward can reduce that gap until the viewer reaches LIVE.

Rewind can move through earlier parts of the current program and, where the schedule is reconstructable, earlier scheduled programs.

The key design rule is:

> **The schedule belongs to the channel. The playhead belongs to the user.**

That resolves the apparent tension between authentic television behavior and direct ownership control.

### Returning to a channel

Profiles or channels may support different return behaviors:

- `live` — return to the channel's current broadcast point
- `resume` — return to the viewer position previously left behind
- `ask` — offer both when meaningful

The system should not assume one philosophy is correct for every household.

---

## 8. Programming engine

The programming engine converts channel definitions, indexed media, schedule rules, and runtime state into a deterministic or explainable timeline.

Initial programming capabilities should include:

- sequential episode order
- shuffled playback
- shuffle with repeat avoidance
- weighted rotation
- time-of-day blocks
- weekday/weekend rules
- morning / afternoon / prime-time / late-night identities
- marathons
- movie feature slots
- seasonal programming
- specials
- user-selected trailers
- bumpers
- station IDs
- intermissions
- music or atmosphere blocks

Longer term, ChannelOS may support smarter local scheduling, but a user should always be able to inspect and override it.

The programming engine should operate without actually decoding every channel.

If a household has 100 channels, ChannelOS should not require 100 simultaneously playing videos. It only needs a timeline describing what each channel *would* be broadcasting.

When the user tunes Channel 7 at 21:47, the runtime resolves:

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

## 9. Media library and index

The media library is the durable center of ChannelOS.

ChannelOS should index media rather than absorb it.

The source files remain where the user chooses:

```text
D:\Media\Movies\
D:\Media\Television\
/media/documentaries/
NAS:/FamilyVideo/
```

The index may record:

- stable ChannelOS media ID
- current path
- file identity/fingerprint information
- media type
- title
- original title where useful
- year
- runtime
- series
- season
- episode
- episode title
- genres
- user tags
- collections
- cast
- director/creator
- description
- poster
- backdrop
- audio tracks
- subtitle tracks
- technical media information
- metadata source
- user overrides
- availability state

Runtime databases can be disposable. The user's media cannot be.

### Stable identity

Paths change. Drives get renamed. NAS mounts move.

The media index should therefore grow toward stable media identity rather than treating the current path as the media's identity.

A user should be able to move a library and relink it without rebuilding every channel from scratch.

---

## 10. Import and file discovery

Adding media should be easy enough for ordinary household use.

The TV interface may expose a simple **Add Media** entry, while the management interface provides the full workflow.

Possible inputs:

```text
ADD MEDIA

Select Files
Select Folder
Add Network Location
Add Removable Drive
Add Disc
```

A folder import should recursively discover supported files without moving them.

Example:

```text
D:\Media\
    Movies\
        Alien (1979).mkv
    Television\
        Futurama\
            Season 03\
                S03E01.mkv
        Star Trek Deep Space Nine\
            Season 04\
                S04E11.mkv
```

ChannelOS should attempt to identify these items and then present uncertain matches for review.

The ideal experience resembles the best parts of older desktop media libraries: insert or point to something, and the system tries to make the collection visually understandable with titles, covers, descriptions, and grouping.

It should never silently rewrite or reorganize the user's files unless the user explicitly requests such a tool.

---

## 11. Metadata and artwork

Metadata should make a personal library pleasant to browse without becoming another dependency trap.

ChannelOS should support a provider abstraction:

```text
MetadataProvider
    ├── Online provider plugin A
    ├── Online provider plugin B
    ├── Local sidecar metadata
    ├── Embedded metadata
    └── Manual entry
```

Provider availability should not determine whether the library remains usable.

Once metadata is retrieved or entered, ChannelOS should cache durable information locally where licensing and provider terms permit.

Users should be able to override:

- title
- poster
- backdrop
- description
- genres
- tags
- season/episode numbering
- collection membership
- match identity

### Portable metadata

ChannelOS should eventually support exporting metadata alongside media mappings, potentially through portable sidecars or an export package.

The exact format is still a design decision, but the principle is fixed:

> Losing access to a metadata website should not turn a carefully organized local library back into meaningless filenames.

---

## 12. Genres, tags, collections, and channels

ChannelOS should distinguish several organizational concepts.

### Genres

Broad classification such as:

- Action
- Animation
- Comedy
- Crime
- Documentary
- Drama
- Fantasy
- Horror
- Science Fiction
- Thriller
- Western

Metadata providers may suggest genres, but the user can edit them.

### User tags

Personal concepts that may not exist in standard metadata:

- Comfort TV
- Late Night
- Creature Feature
- Background
- Family Favorite
- Rainy Day
- Holiday
- Childhood

Tags are particularly useful because they can drive channels.

### Collections

Explicit groups such as:

- Star Trek
- Alien franchise
- Christmas Movies
- Nature Documentaries

### Channels

Programmable broadcast views that select from genres, tags, collections, series, paths, or combinations of them.

The same media can belong to multiple genres, tags, collections, and channels without duplication of the actual media file.

---

## 13. Profiles and household state

The media library belongs to the ChannelOS installation or household, while profiles primarily own viewing state and preferences.

A profile may contain:

- watch history
- Continue Watching state
- favorites
- ratings/reactions
- viewer clock offsets
- return-to-channel behavior
- language/subtitle preferences
- preferred audio behavior
- personal channels
- channel weighting preferences
- UI preferences
- content visibility rules where configured

Conceptually:

```text
HOUSEHOLD LIBRARY
        │
        ├── Profile A
        │     history
        │     favorites
        │     viewer state
        │     personal channels
        │
        ├── Profile B
        │     history
        │     favorites
        │     viewer state
        │
        └── Kids
              allowed library
              allowed channels
              viewer state
```

ChannelOS may support both:

- **Household channels** shared by everyone
- **Personal channels** belonging to one profile

The architecture should allow this without duplicating the underlying media.

---

## 14. Playback architecture

ChannelOS should not waste years re-solving media decoding.

Playback belongs behind a backend-neutral adapter.

```text
Channel Runtime
      │
      ▼
Playback Adapter API
      │
      ├── LibVLC backend   ← first reference backend
      ├── mpv backend      ← possible alternative
      └── future backends
```

**libVLC is the preferred first reference backend.**

ChannelOS owns:

- what should play
- when it should play
- where playback should begin
- channel switching
- viewer time
- volume intent
- mute state
- pause/play state
- seek commands
- guide state
- continuity

The playback backend owns the low-level work:

- decoding
- codecs
- containers
- hardware acceleration
- audio output
- subtitles
- seeking implementation
- rendering

This separation preserves the project's purpose.

> **VLC can do media playback. ChannelOS does television.**

---

## 15. Control model and remote protocol

The eventual physical remote should not contain ChannelOS business logic.

It should emit a small, open set of user intents.

A conceptual protocol:

```text
POWER

DIGIT 0
DIGIT 1
...
DIGIT 9
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

The runtime interprets these intents.

This means the same control model can initially be driven by:

- keyboard
- gamepad
- USB remote
- web remote
- phone
- development console

and later by a purpose-built open-source ChannelOS remote.

The software should not care whether the signal arrived over USB, infrared, Bluetooth, RF, or another transport once it has been translated into ChannelOS control intents.

---

## 16. Long-term open-source remote and receiver

The long-term hardware vision is a user-owned television appliance.

Conceptually:

```text
OPEN-SOURCE REMOTE
        │
   RF / BLE / IR
        │
        ▼
CHANNELOS RECEIVER / APPLIANCE
        │
        ├── Channel Runtime
        ├── Guide
        ├── Library
        ├── Profiles
        ├── Local management API
        └── libVLC playback backend
        │
       HDMI
        │
        ▼
        TV
```

Possible hardware capabilities:

- HDMI output
- USB storage
- Ethernet
- Wi-Fi
- NAS access
- local RF/BLE/IR receiver
- optional removable storage

The ideal appliance experience is intentionally boring:

1. Turn it on.
2. ChannelOS appears.
3. Press a channel number.
4. Watch television.

No visible desktop should be required in appliance mode.

No mouse cursor should be required for routine viewing.

The hardware is a long-term target, not a prerequisite for proving the software architecture.

---

## 17. Top-level TV interface

A future home screen may combine passive and active media without turning into an advertisement wall.

Example:

```text
┌──────────────────────────────────────────────────────────┐
│                       ChannelOS                          │
│                                                          │
│  LIVE TV                                                 │
│  Continue Channel 7 — Sci-Fi                             │
│                                                          │
│  CONTINUE WATCHING                                       │
│  Alien    DS9 S04E11    Futurama S03E02                  │
│                                                          │
│  ON DEMAND                                               │
│  Movies   Television   Documentaries   Home Video        │
│                                                          │
│  GENRES                                                  │
│  Sci-Fi   Comedy   Horror   Action                       │
│                                                          │
│  CHANNELS                                                │
│  2 Comedy   7 Sci-Fi   12 Trek   31 Late Night          │
└──────────────────────────────────────────────────────────┘
```

The interface should prioritize the user's content rather than paid placements, platform promotions, or mandatory recommendations.

---

## 18. System architecture

The complete conceptual architecture is:

```text
                        USER
                         │
              Remote / TV / Web Client
                         │
                         ▼
+-------------------------------------------------------------+
|                    ChannelOS Control Layer                  |
| tune | volume | mute | play/pause | seek | guide | profile |
+-----------------------------+-------------------------------+
                              │
                              ▼
+-------------------------------------------------------------+
|                     Channel Runtime                         |
| broadcast clocks | viewer clocks | tuning | now/next       |
| continuity | active profile | session state                 |
+------------------+--------------------------+---------------+
                   │                          │
                   ▼                          ▼
+--------------------------+       +--------------------------+
|   Programming Engine     |       |     Playback Adapter     |
| schedules | blocks       |       | libVLC / mpv / future    |
| sequence | shuffle       |       +--------------------------+
| weighting | marathons    |
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
| local files | NAS | removable storage | supported discs    |
+-------------------------------------------------------------+

Optional local services:

Metadata Providers
Profile Store
Artwork Cache
Export / Import
Local Management Web UI
Remote Receiver Service
```

The authoritative scheduling logic should live in the runtime, not inside the TV UI.

That allows multiple clients to share the same household system later.

---

## 19. Export My Television

Portability should become a first-class feature rather than an emergency feature.

A full export should eventually be capable of preserving:

- channel definitions
- channel lineup
- schedules
- programming rules
- tags
- collections
- metadata overrides
- artwork references or portable artwork where allowed
- library mappings
- profiles
- watch state
- viewer preferences
- application settings

The user should be able to:

1. install ChannelOS on another machine,
2. restore or reconnect the media library,
3. import the export,
4. relink moved storage where necessary,
5. recover a recognizable version of their television system.

> **If ChannelOS disappears, the library survives. If a machine disappears, the television can be rebuilt.**

---

## 20. Plugin and extension philosophy

ChannelOS should grow through explicit interfaces rather than hard-coding every service into the core.

Potential extension points:

- PlaybackBackend
- MetadataProvider
- MediaSourceAdapter
- ArtworkProvider
- RemoteTransport
- Guide/notification integration
- Authorized online source integrations

Plugins should be treated as untrusted until granted capabilities.

They should not silently receive unrestricted access to the filesystem or network.

A plugin system must not undermine the ownership and privacy guarantees of the local core.

---

## 21. Privacy and network posture

The core system should work without telemetry.

No mandatory account should be required for local playback.

No mandatory remote server should be required to validate the user's installation.

Networking should be explicit and understandable:

- local NAS access
- local remote/control traffic
- local management UI
- explicitly enabled metadata lookups
- explicitly installed provider integrations

A household should be able to run a useful ChannelOS installation entirely within its local network after metadata and software are installed.

---

## 22. What ChannelOS is not

ChannelOS is not intended to be:

- another subscription streaming service
- a proprietary media store
- a DRM-circumvention project
- a streaming-service scraper
- an ad-removal system for third-party protected streams
- a custom video codec project
- a replacement for mature playback engines
- a cloud account required to play local files
- a platform that hides user configuration in an unreadable proprietary format

Its job is narrower and more interesting:

> **Turn a user's own media collection into a television system they control.**

---

## 23. Development strategy

The project should prove the defining behavior before chasing polish.

### Phase 0 — Foundation

Already underway:

- repository structure
- documented ownership philosophy
- portable channel definition format
- parser/validator
- architecture boundaries

### Phase 1 — Library + playback

Build:

- local media scanner
- stable media IDs
- basic metadata fields
- playback adapter interface
- libVLC reference backend
- direct play by media ID

Exit test:

> Point ChannelOS at several owned video files, index them without moving them, select one by stable ID, and play it through the playback adapter.

### Phase 2 — Real channels

Build:

- generated channel timelines
- Broadcast Clock
- Viewer Clock
- tune by number
- Channel Up/Down
- sequential scheduling
- shuffle scheduling
- return-to-channel behavior
- LIVE behavior

Exit test:

> Define Channels 7 and 12. Tune 7, switch to 12, wait, return to 7, and arrive at the correct point in Channel 7's independently advancing schedule.

### Phase 3 — Transport controls

Build:

- volume
- mute
- pause/play
- rewind
- fast-forward
- skip
- GO_LIVE
- Info overlay

Exit test:

> ChannelOS feels like television until the viewer wants control, then behaves like owned media.

### Phase 4 — Guide

Build:

- Now / Next
- full grid guide
- future schedule generation
- past-program reconstruction where possible
- tune from Guide
- Watch from Beginning

### Phase 5 — Library / On Demand

Build:

- poster-based browsing
- movies / shows / seasons / episodes
- search
- genres
- tags
- collections
- Continue Watching
- Add to Channel

### Phase 6 — Metadata management

Build:

- provider abstraction
- matching workflow
- artwork caching
- manual correction
- portable metadata strategy

### Phase 7 — Profiles

Build:

- profile selection
- per-profile history
- favorites
- viewer state
- personal channels
- optional library/channel visibility rules

### Phase 8 — Appliance TV UX

Build:

- fullscreen shell
- remote-only navigation
- resilient boot/wake behavior
- local management UI
- receiver abstraction

Exit test:

> Hand someone a remote and let them forget a computer is underneath the television.

### Phase 9 — Portability and ecosystem

Build:

- Export My Television
- import/relink workflow
- plugin SDK
- alternative playback backends
- remote transports
- metadata providers

### Phase 10 — Open hardware

Explore:

- reference receiver/appliance
- open remote design
- RF/BLE/IR choices
- enclosure and board options
- appliance images

Hardware should consume the same open control protocol developed during the software phases.

---

## 24. The first complete product test

A meaningful early product test is not “does a window open?”

It is:

1. Give ChannelOS a folder containing several movies and television series.
2. Let it identify/index them without taking ownership of the files.
3. Define several channels.
4. Generate a schedule.
5. Start ChannelOS full-screen.
6. Press `7`.
7. See the correct program at the correct broadcast offset.
8. Press Pause.
9. Wait.
10. Resume behind LIVE.
11. Fast-forward until LIVE.
12. Open the Guide.
13. Tune Channel 12.
14. Open Library.
15. Deliberately choose a movie.
16. Return to Live TV.
17. Export the configuration.

If that experience works coherently, ChannelOS is no longer merely a media-player wrapper. It is a personal television system.

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

A feature that fails several of these questions should be reconsidered.

---

## 26. Product language

Several phrases capture the project clearly and should remain useful touchstones:

> **User-controlled television.**

> **The schedule belongs to the channel. The playhead belongs to the user.**

> **VLC does media playback. ChannelOS does television.**

> **If ChannelOS disappears, the library survives.**

> **The user is not the audience of ChannelOS. The user is the broadcaster.**

---

## 27. North Star

ChannelOS should eventually feel less like launching software and more like owning an appliance that happens to be open, programmable, and completely under the household's control.

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

The purpose of ChannelOS is to put both forms of watching on top of a library the user controls permanently.

Modern media taught people to expect convenience. Local ownership provides durability. ChannelOS should refuse the assumption that users must sacrifice one to have the other.

**Own the library. Own the schedule. Own the interface.**
