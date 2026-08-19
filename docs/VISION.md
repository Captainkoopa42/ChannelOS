# ChannelOS

> **A Personal Broadcasting System for User-Owned Media**
>
> Own the library. Own the schedule. Own the interface.

**Status:** Concept / pre-alpha  
**Vision version:** 0.1 — August 2026

## The idea

ChannelOS is a local-first software layer that turns media a person legitimately owns or controls into a cable-style television experience: numbered channels, a guide, scheduled programming, passive "just turn it on" viewing, and remote-first playback.

It is **not** a streaming service and **not** a media store. The user's library is the durable center of the system.

**One sentence:** ChannelOS is a user-owned cable network built from a user-owned media library.

## Why

Modern streaming optimized access but weakened ownership. A customer can pay for years and still lose a title because a license changes, a catalog is reorganized, an app is discontinued, an account is closed, or a provider changes its terms.

Streaming also made watching more active. Traditional television had a useful property: you could turn it on and join whatever was already playing. ChannelOS treats that passivity as a feature worth preserving.

**Thesis:** Streaming is excellent for access and discovery. Ownership is better for preservation. ChannelOS exists to make ownership as effortless to watch as streaming.

## Product principles

1. **Ownership first** — Media remains usable independently of ChannelOS.
2. **Local first** — Core playback, scheduling, guide generation, and state work without cloud dependency.
3. **Open formats** — Channel definitions and exports are readable, documented, and portable.
4. **Couch first** — The primary interface is designed for a television and remote.
5. **Passive by default** — A channel is immediately watchable without browsing.
6. **Control over automation** — Automatic programming is inspectable and overrideable.
7. **No mandatory advertising** — ChannelOS does not inject ads into a user's local media.
8. **No ownership theater** — Export means the user can actually leave with their configuration.

## What it feels like

Sit down. Turn on the TV. ChannelOS is already full-screen.

- Press `12` — Channel 12 begins immediately.
- Channel up/down moves through your personal networks.
- Open Guide — see what is on now and what is next.
- Press Info — see the real media item, source, progress, and the programming rule that selected it.
- Open Library — browse on demand when you actually want to choose something specific.

Example lineup:

| Ch | Name | Idea |
|---:|---|---|
| 02 | Local News & Home Video | Family recordings and saved clips |
| 04 | Cartoons | Animated blocks with time-of-day rules |
| 07 | Sci-Fi | Rotating science-fiction programming |
| 12 | Star Trek | Ordered or mixed-series blocks |
| 18 | Documentaries | Nature, science, history |
| 23 | Comfort TV | Low-attention favorites and reruns |
| 27 | Movies | Features placed at sensible start times |
| 31 | Night Shift | Late-night classics and atmosphere |

## Fundamental model

A **channel is not a folder**. It is a programmable view over one or more media sources. It has identity, selection rules, schedule rules, continuity state, and display metadata.

```text
Library / Storage
    |
    +-- Movies
    +-- Television
    +-- Music / Audio
    +-- Home Video
    +-- Other user-controlled media
            |
            v
      Media Index + Metadata
            |
            v
      Programming Engine
       +-- rules
       +-- schedule
       +-- shuffle / sequence
       +-- continuity
       +-- block generation
            |
            v
      Channel Runtime
       +-- Channel 07
       +-- Channel 12
       +-- Channel 27
            |
            v
      Player + Guide + Remote UI
```

### Example channel definition

```yaml
channel: 12
name: Star Trek
sources:
  - collection: Star Trek TNG
  - collection: Star Trek DS9
  - collection: Star Trek VOY
programming:
  mode: mixed_blocks
  preserve_episode_order: true
  avoid_repeat_days: 14
prime_time:
  start: "20:00"
  rule: two_part_and_feature_events
ads:
  platform_injected: false
```

Channel definitions should live in a documented, human-readable format. Runtime state—watch history, current sequence position, repeat cooldowns, and playback progress—should be stored separately.

## Programming engine

The programming engine is what makes ChannelOS a personal broadcaster instead of another media browser.

Initial modes:

- Sequential episode order
- Shuffle with repeat avoidance
- Weighted rotation
- Time blocks: morning / afternoon / prime time / late night
- Marathons
- Movie feature slots
- User-selected intermissions, bumpers, trailers, station IDs, or music
- Seasonal programming

When ChannelOS chooses something automatically, it should be able to answer **why**: e.g. `Channel 7 -> weekday prime time -> Stargate rotation -> next unplayed episode`.

## The ownership contract

These are constitutional constraints for the project:

- No proprietary media container is required.
- No ChannelOS account is required for local playback.
- No remote server check is required to authorize the core application.
- Deleting the ChannelOS database must not delete the user's media.
- A full export contains channel definitions, schedules, metadata overrides, watch state, settings, and library mappings.
- Export formats are documented enough for another program to read.
- Optional cloud features may enhance the local system but never authorize it.
- ChannelOS does not inject advertising into a user's local library.

### Export My Television

A user should be able to install ChannelOS on another machine, point it at the same or restored media folders, import a configuration export, and recover the recognizable structure of their television: lineup, schedules, preferences, and continuity.

## Content sources

ChannelOS should use source adapters.

**Primary:**
- Local filesystem
- NAS / network shares
- Removable storage

**Possible:**
- Disc-backed workflows where lawful and technically supported
- Public-domain / openly licensed media
- Provider-authorized online integrations through documented APIs

**Out of scope:**
- Building the project around DRM circumvention
- Scraping streaming services to remove ads or bypass access controls

## User interface

### Television mode

- Full-screen at launch/boot
- Numeric channel entry
- Channel up/down and previous channel
- Minimal Now/Next overlay
- Traditional grid guide
- Fast sleep/wake and resilient focus handling

### Management mode

Library import, channel creation, schedule editing, metadata correction, source configuration, and backup belong in a richer management interface. Complexity should live there—not in routine couch use.

## Architecture

```text
+------------------------------+
|        TV / Remote UI        |
| Live view | Guide | On-demand|
+--------------+---------------+
               | local API / IPC
+--------------v---------------+
|       Channel Runtime        |
| Tune | continuity | handoff  |
+-------+--------------+-------+
        |              |
+-------v------+ +-----v-----------+
| Programming | | Playback Engine |
| Scheduler   | | mpv/VLC/etc.    |
+-------+------+ +-----+-----------+
        |              |
+-------v--------------v-----------+
|       Media Index / State        |
| metadata | history | mappings    |
+--------------+-------------------+
               |
+--------------v-------------------+
|          Source Adapters         |
| local | NAS | removable | future |
+----------------------------------+
```

Implementation posture:

- Delegate decoding to a proven player engine first.
- SQLite is sufficient for early single-household state.
- Keep channel definitions human-readable.
- Target Linux/Windows before dedicated appliance builds.
- Keep APIs local-only by default.

## MVP

The MVP proves **television behavior**, not universal media compatibility.

1. Scan local media folders.
2. Create channels manually from folders, series, or playlists.
3. Assign numbers and names.
4. Support sequential and shuffle programming.
5. Remember per-channel continuity across restarts.
6. Tune instantly from keyboard or remote input.
7. Play through a proven external playback engine.
8. Show a basic Now / Next guide.
9. Run full-screen and recover cleanly from missing files or player errors.
10. Export/import configuration without moving media.

**MVP success test:** Give a person a folder containing several shows, define five channels, hand them a remote, and let them forget there is a computer underneath.

## Not MVP

- Streaming-service scraping or ad removal
- Cloud accounts
- Remote telemetry
- AI scheduling
- Complex household permissions
- Mobile apps
- Custom codecs
- Custom OS images

## Development phases

| Phase | Focus | Exit condition |
|---|---|---|
| 0 — Skeleton | Repo, config format, scanner, player POC | A media file can be indexed and played by stable ID |
| 1 — Channels | Numbers, sequence/shuffle, state | Channel 12 behaves like a persistent channel |
| 2 — Guide | Schedule generation, Now/Next, grid | A coherent day of programming exists |
| 3 — Appliance UX | Remote, autostart, fullscreen resilience | Keyboard/mouse optional for viewing |
| 4 — Programmer | Time blocks, weighting, marathons | Channels develop recognizable identities |
| 5 — Portability | Backup/export/import | Export My Television works end to end |
| 6 — Ecosystem | Plugin/source adapter SDK | Extensions do not require core modification |

## Proposed repository layout

```text
channelos/
|-- README.md
|-- LICENSE
|-- docs/
|   |-- VISION.md
|   |-- ARCHITECTURE.md
|   |-- CHANNEL_FORMAT.md
|   |-- UX_PRINCIPLES.md
|   `-- ROADMAP.md
|-- channelos-core/
|   |-- library/
|   |-- scheduler/
|   |-- runtime/
|   |-- state/
|   `-- sources/
|-- channelos-ui/
|   |-- live/
|   |-- guide/
|   `-- settings/
|-- channelos-player/
|-- examples/
|   `-- channels/
|-- tests/
`-- tools/
```

## Hard-to-reverse design decisions

- Media never becomes hostage to the application database.
- Core local playback never requires ChannelOS cloud authentication.
- Channel exports stay documented and portable.
- No mandatory telemetry.
- No platform-injected ads into local playback.
- Plugins do not silently receive unrestricted filesystem/network access.
- Automatic programming stays inspectable.
- Routine TV operation never requires a pointing device.

## What makes it different

ChannelOS overlaps with Plex/Jellyfin-style libraries, DVRs, playlists, launchers, and streaming interfaces, but its center is different:

> The product is not **browse your media beautifully**.  
> The product is **operate your own television network**.

The user is not merely the audience. **The user is the broadcaster.**

## Long-term direction

- Multiple household profiles
- Household-wide broadcasting to several televisions
- Local phone/tablet remote and guide
- Optional metadata providers
- Seasonal and time-aware programming
- Station branding, bumpers, IDs, and presentation packages
- Local explainable smart scheduling
- Live tuner/capture integration where lawful
- Music-radio and ambient channels
- Dedicated mini-PC/appliance images

## Project North Star

Every major feature should be tested against five questions:

1. Does this increase or reduce the user's control over their media?
2. Does it still work if ChannelOS loses internet access?
3. Can the user understand what the system did?
4. Can the user export or migrate the result?
5. Does this make television easier to watch from a couch?

If a feature fails several of those questions, it may belong in another product.

## Initial manifesto

We bought the movie. We saved the episode. We recorded the moment. We built the library. The software should serve that library—not redefine whether we are allowed to have one.

ChannelOS exists because convenience and ownership should not be opposites. It takes the simplicity of television—the remote, the channel, the guide, the ability to simply turn something on—and rebuilds it on top of media the viewer controls.

**The user is not the audience of ChannelOS. The user is the broadcaster.**
