# ChannelOS Household Server (Jellyfin edition)

> **One server in the house. The same cable lineup in every room.**

**Status:** Design map. Nothing here is built yet.  
**Document version:** 0.1, November 7, 2026  
**Branch:** `ChannelOS-for-Jellyfin`  
**Builds on:** [JELLYFIN_BACKEND_MASTER_PLAN.md](JELLYFIN_BACKEND_MASTER_PLAN.md) (inbound
Jellyfin source) and [PORTABLE_SETUP.md](PORTABLE_SETUP.md) (setups that travel)  
**Depends on V2 work:** viewing profiles (Home, Kids, Daycare, Lobby) and themes
from `feature/v2-live-video-audit-themes`

---

## 1. The idea

A ChannelOS household runs on one Jellyfin server, which the user either sets up
from inside ChannelOS or already has. The server:

1. **Airs and streams its media.** Channels can schedule anything on the server.
   If a program isn't on the device watching, it streams from the server.
2. **Checks whether a file is the same.** Before streaming, ChannelOS checks
   whether the device already has the exact same file. If it does, it plays the
   local copy, saving server load and bandwidth.
3. **Carries the whole ChannelOS setup.** Channels, Studio, ads, themes, settings
   and viewing profiles are saved as a *setup* on the server. Every connected
   device can pull it down, push changes back, or export and import it as a
   file, in either direction.

The Jellyfin edition is the paid Patreon build: the maintained server
integration, the companion plugin and setup sync. The local-only ChannelOS stays
complete without it (master plan §3.2).

---

## 2. The map

```text
                        ┌───────────────────────────────────────────┐
                        │            Household server               │
                        │                                           │
  media folders ───────►│  Jellyfin  (library, metadata, streaming) │
                        │     │                                     │
                        │     └─ ChannelOS Companion plugin         │
                        │          • content-hash index             │
                        │          • setup storage (versions)       │
                        │          • compatibility info             │
                        └───────────────▲───────────────────────────┘
                                        │ HTTPS / LAN
          ┌─────────────────────────────┼─────────────────────────────┐
          │                             │                             │
 ┌────────┴────────┐          ┌─────────┴───────┐           ┌─────────┴───────┐
 │ ChannelOS (PC)  │          │ ChannelOS (Deck)│           │ ChannelOS (TV / │
 │ local media too │          │ no local media  │           │ Android)        │
 └─────────────────┘          └─────────────────┘           └─────────────────┘
   each device:  Guide + Broadcast Clock + playback resolver + setup sync
```

What lives where:

| Thing | Owner | Why |
| --- | --- | --- |
| What airs when (Guide, Broadcast Clock) | ChannelOS | ChannelOS is the television (master plan §3.1) |
| The media, metadata, network delivery and transcoding | Jellyfin | It is already good at this |
| "Is this the same file?" (content hashes) | Companion plugin | Jellyfin's API does not publish file hashes |
| Setups (channels, profiles, themes…) | Companion plugin storage, plus files | So every device can share one lineup |
| Login tokens | Each device's credential store | Never in a setup or an export (master plan §3.5) |
| Where each device is watching | Each device | Different rooms watch different things |

---

## 3. The four parts

### 3.1 Host the server

There are two ways in, both from **Settings → Server**, or from the Guide's
"Add a server" row when nothing is connected:

- **Set one up for me (guided).** ChannelOS detects whether Jellyfin is
  installed. If it isn't, it explains what will happen and downloads the
  official installer, but only after the user says yes. It then runs that
  installer, asks which folders to share, and installs the Companion plugin
  through Jellyfin's plugin repository.
- **I already have one.** Server discovery on the LAN (Jellyfin answers
  broadcast discovery), or type an address, then sign in with Quick Connect or a
  username and password.

Rules carried from master plan §2.3: nothing is installed, elevated or
reconfigured silently. Every step is shown and confirmed, and ChannelOS never
takes ownership of a server the user already runs. A remote server that goes
offline is shown as offline, and local channels keep playing.

### 3.2 Air and stream server media

- Channels can include server items. In schedules they are referenced as
  `jellyfin:<server-uuid>:<item-id>` until they are matched (master plan §7.3).
- The Guide shows them like any other program. A small marker says the program
  comes from the server.
- When the server can't serve a program, its row says so in plain words and the
  schedule stays truthful (master plan §9.4).

### 3.3 Is it the same file? (local first)

Each time a program starts, the resolver picks the cheapest source that is
*proven* to be the same media:

| Order | Source | Evidence needed | Server cost |
| --- | --- | --- | --- |
| 1 | Local file | Same content hash (SHA-256) as the server item | None |
| 2 | Local file | User confirmed the match once ("Same video") | None |
| 3 | Server, direct play | Device can decode the file as-is | Bandwidth only |
| 4 | Server, direct stream | Container needs remuxing only | Light |
| 5 | Server, transcode | Last resort, e.g. a weak device or slow network | Heavy |

How the hashes meet:

- ChannelOS already stores a SHA-256 for every local file.
- The Companion plugin hashes server files in the background at low priority. It
  caches each hash by path, size and modified time, so files are only hashed
  again when they change. It serves the hashes as `item-id → sha256`.
- A device downloads the hash index once, then fetches only the changes, and
  matches it against its own library. Matched items get both locations under
  one asset (master plan §7.4). Playback then prefers local automatically.
- **Probable matches** (same TMDB/TVDB ID, matching runtime and file size, but no
  hash yet) are *suggested* in the Library manager. They are never merged
  automatically. Title-only matches are never used (master plan §3.4).
- **Without the plugin**, the server still streams. Matching falls back to
  suggestions only, so the plugin is what makes the bandwidth savings automatic.

What it saves: a household PC that keeps local copies of the server's shows
streams nothing for them. A Steam Deck on the couch with no local media streams
everything, using direct play.

### 3.4 The setup travels (sync, import, export)

A **setup** is the ChannelOS part of a household, without the media itself:

| In a setup | Notes |
| --- | --- |
| Channel definitions, Studio program groups, Planner blocks | Media referenced by asset identity (hash or server ID), never by a device path |
| Ad collections, profiles and assignments | Same identity rule |
| Broadcast epochs | So channel 7 shows the same program at the same moment in every room |
| Themes, including wallpaper images | Images go in the setup archive |
| Viewing profiles (Kids, Daycare, Lobby) and the PIN hash | The salted PIN hash travels; the PIN itself never does |
| General settings | Per-device items are left out (audio device, display mode, window size) |
| **Not included** | Login tokens, viewer and On Demand positions, logs, thumbnail cache |

Moving it around:

- **Push / pull.** A device saves its setup to the server as a new version.
  Other devices see "A newer setup is available" and choose when to apply it.
  Applying never interrupts a program that is playing.
- **Named setups.** One server can hold several, such as *Living Room*, *Kids'
  Room* and *Lobby*. Each device chooses which one it follows.
- **Conflicts.** If two devices change the same setup, both are kept as
  separate versions and the user picks one. Nothing is merged silently. Older
  versions can be restored.
- **Export / import.** A setup can be saved as a `.channelos-setup` file (a zip
  with a manifest and version) and imported anywhere: from file to server, from
  server to file, or from one server to another. This works offline and without
  the Jellyfin edition, and reuses the Portable Setup copy code and identity
  rules.
- **On a new device,** importing a setup resolves each program through §3.3:
  local copy if matched, otherwise server, otherwise shown honestly as
  unavailable.

Who can change what: any signed-in Jellyfin user can pull setups shared with
them. Only Jellyfin administrators can push a household setup. A device
running a locked profile (Kids, Daycare, Lobby) can pull updates, but can't
push or edit without the PIN.

---

## 4. Components

| Component | Language / licence | Responsibility |
| --- | --- | --- |
| `jellyfin_client.py` | Python, MPL-2.0 | REST client, auth, discovery (master plan §23) |
| Catalog + resolver | Python, MPL-2.0 | Asset identities, local/server locations, the §3.3 order |
| `setup_sync.py` | Python, MPL-2.0 | Build, apply, version and diff setups; `.channelos-setup` files |
| Server setup wizard | QML + Python, MPL-2.0 | §3.1 guided hosting and sign-in |
| **ChannelOS Companion** | C# Jellyfin plugin, GPL-3.0, separate repository | Hash index, setup storage, info endpoint |
| Outbound Live TV (existing `jellyfin.py`) | Python, MPL-2.0 | Optional extra: publish ChannelOS channels to other Jellyfin apps (master plan §22) |

The plugin talks to ChannelOS only over HTTP, so the GPL plugin and the MPL app
stay separate works. Both keep their source-access obligations.

### Companion plugin endpoints (draft)

```text
GET  /ChannelOS/Info                 → plugin version, API version, hashing progress
GET  /ChannelOS/Hashes?since=<cursor> → [{itemId, mediaSourceId, sha256, size}], next cursor
GET  /ChannelOS/Setups               → [{setupId, name, version, updatedAt, updatedBy}]
GET  /ChannelOS/Setups/{id}?version=  → setup archive
PUT  /ChannelOS/Setups/{id}           → new version (admin only; If-Match on version)
```

The setup archive is stored as plugin data on the server. It is included in the
server's normal backups but kept separate from Jellyfin's own database.

---

## 5. The Jellyfin edition (Patreon)

| Free ChannelOS | Jellyfin edition |
| --- | --- |
| Full local television: channels, Guide, Studio, Planner, ads, themes, profiles, boot video | Everything in free |
| Portable Setup and `.channelos-setup` export/import | Server media in channels and On Demand |
|  | Automatic local-first matching (with Companion) |
|  | Setup sync, named setups and versions across devices |
|  | Guided server setup and the Companion plugin |
|  | Maintained compatibility with new Jellyfin releases |

What patrons pay for is upkeep: Jellyfin's API changes and the plugin needs
rebuilding for new server versions. Source rights for the MPL and GPL parts are
preserved.

---

## 6. Build order

These steps follow the master plan's Phases 0–5.

| Step | Delivers | Done when |
| --- | --- | --- |
| H0 | Master plan Phases 0–3 (client, catalog cache, Library, On Demand) | Server media plays On Demand inside ChannelOS |
| H1 | `.channelos-setup` export/import (local only, free) | A setup exported on one PC imports on another PC and resolves media by hash |
| H2 | Companion plugin hash index plus the resolver order (§3.3) | A matched program plays locally with zero server traffic; an unmatched one direct-plays |
| H3 | Master plan Phase 4 (server-backed channels) | A server-only channel airs the exact program and offset the Guide predicts |
| H4 | Setup sync: push, pull, versions, named setups | Two devices follow *Living Room*; an edit on one appears on the other after one confirmation |
| H5 | Guided server setup (§3.1) | A user with no Jellyfin gets a working server and a synced setup without opening a terminal |
| H6 | Polish: shared household lineup, offline handling, optional outbound Live TV | Same channel shows the same moment in two rooms |

H1 is useful by itself, and it is the free building block for everything after it.

---

## 7. Open questions

1. Should the Companion plugin hash *every* file, or only files that appear in a
   ChannelOS channel or setup? The second option is faster on large servers.
2. How big can setups get with theme wallpapers? Should images be capped or
   compressed on push?
3. Should Kids and Lobby devices auto-apply new setup versions overnight?
4. Should a device that follows a setup be able to keep local-only channels on
   top of it, such as a bedroom-only channel?
5. How should the plugin be distributed: through a custom Jellyfin plugin
   repository URL for patrons, or as a manual install?
6. Which minimum Jellyfin version should be supported? The master plan reviewed
   10.11.11.
