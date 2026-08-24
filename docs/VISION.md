# ChannelOS

> **A Personal Broadcasting System for User-Owned Media**
>
> Own the library. Own the schedule. Own the interface.

**Status:** Pre-alpha / Phase 2  
**Vision version:** 0.2 — August 2026

## The idea

ChannelOS is a local-first software layer that turns media a person legitimately owns or controls into a cable-style television experience: numbered channels, a Guide, scheduled programming, passive "just turn it on" viewing, and remote-first playback.

It is **not** a streaming service and **not** a media store. The user's library is the durable center of the system.

**One sentence:** ChannelOS is a user-owned cable network built from a user-owned media library.

## Why

Modern streaming optimized access but weakened ownership. A customer can pay for years and still lose a title because a license changes, a catalog is reorganized, an app is discontinued, an account is closed, or a provider changes its terms.

Streaming also made watching more active. Traditional television had a useful property: you could turn it on and join whatever was already playing. ChannelOS treats that passivity as a feature worth preserving.

**Thesis:** Streaming is excellent for access and discovery. Ownership is better for preservation. ChannelOS exists to make ownership as effortless to watch as streaming.

## Product principles

1. **Ownership first** — Media remains usable independently of ChannelOS.
2. **Local first** — Core playback, scheduling, Guide generation, and state work without cloud dependency.
3. **Open formats** — Channel definitions and exports are readable, documented, and portable.
4. **Couch first** — The primary interface is designed for a television and remote/controller.
5. **Passive by default** — A channel is immediately watchable without browsing.
6. **Control over automation** — Automatic programming is inspectable and overrideable.
7. **No mandatory advertising** — ChannelOS does not inject ads into a user's local media.
8. **No ownership theater** — Export means the user can actually leave with their configuration.
9. **Platform independence** — Distribution platforms may make ChannelOS convenient to obtain, but they do not authorize the user's local television.

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
    v
Media Index + Metadata
    |
    v
Programming Engine
    |
    v
Channel Runtime
  Broadcast Clock
  Viewer Clock
    |
    v
Guide / Television Service Boundary
  Now / Next
  horizon
  control intents
    |
    v
Player + Guide + Remote UI
```

Channel definitions should live in a documented, human-readable format. Runtime state—schedule epochs, current channel, viewer positions, watch history, and future cooldown state—should be stored separately.

## Programming engine

The programming engine is what makes ChannelOS a personal broadcaster instead of another media browser.

Current foundation:

- Sequential programming
- Deterministic shuffle
- Repeat-avoidance validation
- Persistent Broadcast Clock
- Persistent Viewer Clock

Later broadcaster capabilities:

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
- No distribution-platform entitlement is required for standalone/appliance local use.
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
- Traditional grid Guide
- Fast sleep/wake and resilient focus handling
- Controller/remote-first navigation

The default visual language should be a dark living-room palette: deep navy/charcoal surfaces, cool blue focus states, bright readable text, and a restrained LIVE indicator. The goal is to feel at home beside SteamOS while still looking unmistakably like ChannelOS rather than copying Steam.

### Management mode

Library import, channel creation, schedule editing, metadata correction, source configuration, and backup belong in a richer management interface. Complexity should live there—not in routine couch use.

## Architecture

```text
+------------------------------+
|        TV / Remote UI        |
| Live view | Guide | On-demand|
+--------------+---------------+
               | local service / API / IPC
+--------------v---------------+
| Guide + Television Boundary  |
| horizon | now/next | intents |
+--------------+---------------+
               |
+--------------v---------------+
|       Channel Runtime        |
| clocks | tune | continuity   |
+-------+--------------+-------+
        |              |
+-------v------+ +-----v-----------+
| Programming | | Playback Backend|
| Scheduler   | | libVLC / future |
+-------+------+ +-----+-----------+
        |              |
+-------v--------------v-----------+
|       Media Index / State        |
+--------------+-------------------+
               |
+--------------v-------------------+
|          Source Adapters         |
+----------------------------------+
```

Implementation posture:

- Delegate decoding to a proven player engine.
- SQLite is sufficient for early single-household state.
- Keep channel definitions human-readable.
- Keep the UI outside authoritative scheduling logic.
- Target Windows/Linux generally, with SteamOS as a first-class living-room target.
- Keep APIs local-only by default.
- Use a minimal existing OS for future appliance images rather than building a custom kernel.

## Deployment forms

ChannelOS should be the same television system in several forms:

```text
ChannelOS Core
   ├── Desktop / PC application
   ├── Steam / SteamOS application
   └── Dedicated appliance image
```

### Steam as the primary public launch target

Steam is the preferred public launch/discovery platform, subject to Valve accepting the application and the project satisfying release requirements. If listed there, the intended application is free to users.

SteamOS and Steam Machine-class living-room PCs are especially attractive because ChannelOS is already designed around fullscreen television use, controller/remote input, local storage, and PC-class video playback.

But **ChannelOS is not a Steam-only system**. Steam is a distribution and launch surface, not an ownership or authorization layer. Standalone Windows/Linux packages, source distribution, and future appliance images remain first-class.

## Playback packaging

Development may use system libVLC or an explicit development runtime path. A finished package should include the compatible native playback runtime it requires where licensing permits, so ordinary users are not asked to configure VLC manually.

Playback remains backend-neutral even when libVLC is the first bundled implementation.

## MVP

The MVP proves **television behavior**, not universal media compatibility.

1. Scan local media folders.
2. Create channels manually from supported sources.
3. Assign numbers and names.
4. Support sequential and deterministic shuffle programming.
5. Remember Broadcast/Viewer continuity across restarts.
6. Tune instantly from keyboard, controller, or remote intent.
7. Play through a proven playback backend.
8. Show Now / Next and a basic Guide.
9. Run full-screen and recover cleanly from missing files or player errors.
10. Export/import configuration without moving media.

**MVP success test:** Give a person a folder containing several shows, define five channels, hand them a remote, and let them forget there is a computer underneath.

## Current development position

Phase 0 — Foundation: **complete**.  
Phase 1 — Persistent Channels: **complete**.  
Phase 2 — Guide / UI-facing plumbing: **current**.

The detailed phase ordering lives in [ROADMAP.md](ROADMAP.md) so the canonical vision does not maintain a second competing roadmap.

## Hard-to-reverse design decisions

- Media never becomes hostage to the application database.
- Core local playback never requires ChannelOS cloud authentication.
- Distribution platforms never become core entitlement authorities.
- Channel exports stay documented and portable.
- No mandatory telemetry.
- No platform-injected ads into local playback.
- Plugins do not silently receive unrestricted filesystem/network access.
- Automatic programming stays inspectable.
- Routine TV operation never requires a pointing device.
- The UI consumes runtime truth rather than owning schedule truth.

## What makes it different

ChannelOS overlaps with Plex/Jellyfin-style libraries, DVRs, playlists, launchers, and streaming interfaces, but its center is different:

> The product is not **browse your media beautifully**.  
> The product is **operate your own television network**.

The user is not merely the audience. **The user is the broadcaster.**

## Long-term direction

- Multiple household profiles
- Household-wide broadcasting to several televisions
- Local phone/tablet remote and Guide
- Optional metadata providers
- Seasonal and time-aware programming
- Station branding, bumpers, IDs, and presentation packages
- Local explainable smart scheduling
- Live tuner/capture integration where lawful
- Music-radio and ambient channels
- Dedicated mini-PC/appliance images
- SteamOS / Steam Machine-class living-room deployment
- Open physical remote

## Open-source release requirement

ChannelOS source is licensed under the Mozilla Public License 2.0. Packaged
public releases remain gated on an exact third-party dependency bill of
materials and verification against `docs/DISTRIBUTION.md`.

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

ChannelOS exists because convenience and ownership should not be opposites. It takes the simplicity of television—the remote, the channel, the Guide, the ability to simply turn something on—and rebuilds it on top of media the viewer controls.

**The user is not the audience of ChannelOS. The user is the broadcaster.**
