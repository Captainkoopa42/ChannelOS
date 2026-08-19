# ChannelOS Roadmap

This roadmap is intentionally behavior-first. ChannelOS does not need to support every codec, service, or device before it proves that personally owned media can feel like television again.

The canonical product direction is [MASTER_DESIGN.md](MASTER_DESIGN.md). Phase 0 and Phase 1 are complete. The current milestone is [GUIDE_AND_UI_BOUNDARY.md](GUIDE_AND_UI_BOUNDARY.md).

## Phase 0 — Foundation / First Broadcast

**Goal:** Establish the constitutional boundaries and prove the first complete owned-file-to-playback path.

- [x] Product vision
- [x] Master design
- [x] Repository structure
- [x] Versioned channel-definition format
- [x] Reference parser and validator
- [x] Example channel
- [x] Initial architecture decision record
- [x] Filesystem media scanner
- [x] Stable media identity model (`sha256:<content>` in v1)
- [x] Media asset vs. media location separation
- [x] SQLite local index
- [x] Unchanged-file scan cache
- [x] Move/relink identity test
- [x] Optional ffprobe technical metadata adapter
- [x] Backend-neutral playback adapter interface
- [x] libVLC reference backend implementation
- [x] Indexed channel source resolver
- [x] Primitive `resolve` and `tune --dry-run` commands
- [x] Phase 0 playback-control console through the ChannelOS abstraction
- [x] Automated control-routing test with a fake playback backend
- [x] Real Windows libVLC smoke test with genuine media playback

**Exit:** Passed. A real machine can scan owned media, preserve stable identity independently of path, resolve a validated channel against that index, launch the selected file through libVLC, and accept ChannelOS-owned playback commands without exposing VLC as the product interface.

**Verified:** Windows desktop, Python 3.11.9, VLC/libVLC 3.0.23 Vetinari. The real-machine run indexed 184 NVIDIA-recorded MP4 files, resolved three exact assets into Channel 07, selected the expected stable SHA-256 media ID, and displayed genuine video through the ChannelOS → libVLC path.

## Phase 1 — Channel Runtime / Persistent Channels

**Goal:** Turn the indexed/playable media spine into independently advancing television channels.

- [x] Persistent numeric channel identity
- [x] Sequential programming state
- [x] Shuffle programming with repeat avoidance
- [x] Generated channel timeline
- [x] Broadcast Clock
- [x] Viewer Clock
- [x] Per-channel continuity state
- [x] Restart recovery
- [x] Missing-file recovery
- [x] `TUNE 007`
- [x] Channel Up / Down
- [x] Previous Channel
- [x] Return behavior: live / resume / ask
- [x] `GO_LIVE`
- [x] Windows bundled/development libVLC runtime discovery path

**Automated exit behavior:** Passed. The reference-core suite covers independent untuned advancement, persistent clocks, viewer continuity, deterministic sequential/shuffle schedules, repeat-window validation, playback routing, restart behavior, and recovery paths.

**Real-machine gate:** Passed on Windows with genuine indexed media through libVLC. Channels 007 and 012 advanced independently while untuned; switching, Previous Channel, pause/resume, Viewer Clock lag, and `GO_LIVE` behaved correctly. Channel 012 was then changed from sequential to shuffle and real playback opened the deterministic shuffled schedule rather than the source order.

**Exit:** Passed and merged to `main`.

## Phase 2 — Guide / UI-facing plumbing

**Goal:** Make generated timelines visible and navigable through a stable television-facing data boundary before building the polished couch shell.

- [ ] Explicit Guide / television service boundary
- [ ] Schedule horizon generation
- [ ] Now / Next model
- [ ] Program durations from indexed technical data
- [ ] Traditional grid-guide data model
- [ ] Schedule regeneration rules
- [ ] Explain-why trace for programmed items
- [ ] Tune from Guide through ChannelOS control intents
- [ ] Watch from Beginning where the owned media permits it
- [ ] Multi-channel Guide/runtime agreement tests
- [ ] Real-media Guide-to-playback smoke test

**Architectural rule:** The Guide and future UI consume runtime truth; they do not independently invent channel schedules.

**Exit:** A client can request a believable Guide horizon, display Now/Next, tune a current program, start an eligible scheduled program from its beginning, and explain why each item was scheduled using the same truth that drives playback.

## Phase 3 — Appliance UX / Control Surface

**Goal:** Make the computer disappear during ordinary viewing while preserving direct control.

- [ ] Full-screen live view
- [ ] Remote/controller input abstraction
- [ ] Open ChannelOS control-intent protocol
- [ ] Numeric direct tuning
- [ ] Channel up/down
- [ ] Previous channel
- [ ] Volume / mute integration
- [ ] Play / pause
- [ ] Rewind / fast-forward / skip
- [ ] LIVE button behavior
- [ ] Minimal Now/Next overlay
- [ ] Guide UI
- [ ] Home / Back / Info navigation
- [ ] Large, television-readable focus states and targets
- [ ] Default dark navy/charcoal + cool-blue ChannelOS visual language
- [ ] SteamOS/controller compatibility as a first-class couch target
- [ ] Autostart and crash recovery
- [ ] Packaged playback runtime so ordinary users do not configure libVLC manually

**Exit:** A keyboard and mouse are optional for ordinary viewing, while pause/seek/volume controls remain under the viewer's command. The same couch UI works as a normal desktop application and as a Steam/SteamOS-launched application.

## Phase 4 — Library / On Demand

**Goal:** Make the owned collection as pleasant to deliberately browse as the channels are to passively watch.

- [ ] Movie / television / season / episode model
- [ ] Poster/backdrop library UI
- [ ] Search
- [ ] Genres
- [ ] User tags
- [ ] Collections
- [ ] Continue Watching
- [ ] Recently Added
- [ ] Favorites
- [ ] Add to Channel
- [ ] Local Add Media / folder-selection workflow

**Exit:** The same canonical media index supports both television channels and deliberate on-demand selection without duplicate libraries.

## Phase 5 — Metadata and Broadcaster Tools

**Goal:** Make the library understandable and the channels programmable without making metadata providers authoritative.

- [ ] Metadata provider abstraction
- [ ] File/title matching workflow
- [ ] Artwork caching
- [ ] Manual correction
- [ ] Metadata overrides
- [ ] Portable metadata strategy
- [ ] Time-of-day blocks
- [ ] Weighted rotations
- [ ] Marathons
- [ ] Feature/movie slots
- [ ] Seasonal rules
- [ ] User-owned bumpers and station IDs
- [ ] Intermissions

**Exit:** A user can organize the shelf and program recognizable stations while retaining local control over the resulting metadata and rules.

## Phase 6 — Profiles

**Goal:** Separate household ownership from individual viewer state.

- [ ] Profile selection
- [ ] Per-profile watch history
- [ ] Continue Watching state
- [ ] Favorites
- [ ] Viewer Clock state
- [ ] Language/subtitle preferences
- [ ] Personal channels
- [ ] Optional library/channel visibility rules

## Phase 7 — Export My Television

**Goal:** Prove ownership extends to configuration, metadata work, profiles, and history.

- [ ] Full configuration export
- [ ] Library remapping on import
- [ ] Schedule definitions
- [ ] Metadata overrides
- [ ] Watch state
- [ ] Channel continuity
- [ ] Profiles
- [ ] Machine-to-machine migration test

**Exit:** A fresh ChannelOS install can reconstruct the recognizable television from an export and restored/relinked media.

## Phase 8 — Ecosystem / Multi-device

**Goal:** Extend ChannelOS without turning the core into a platform monopoly.

- [ ] Source adapter SDK
- [ ] Capability-limited plugins
- [ ] Optional metadata providers
- [ ] Multiple TVs on a household network
- [ ] Phone/tablet remote
- [ ] Local management web UI
- [ ] Music-radio and ambient channels
- [ ] Alternative playback backend(s)

## Phase 9 — Open appliance and remote

**Goal:** Prove the software can become a user-owned television appliance without requiring a custom kernel or proprietary receiver.

- [ ] Dedicated minimal-Linux appliance image experiments
- [ ] Steam Machine / SteamOS living-room PC validation as a reference host class
- [ ] Reference receiver hardware exploration
- [ ] Boot directly into ChannelOS full-screen shell
- [ ] Open remote design
- [ ] RF / BLE / IR transport evaluation
- [ ] HDMI-focused boot/wake experience
- [ ] Hardware consumes the same open ChannelOS control intents as software remotes

**Exit:** Flash/install ChannelOS onto supported PC-class hardware, connect it to a television, power it on, and reach the couch UI without interacting with a general-purpose desktop.

## Distribution and release strategy

Steam is the preferred **primary public launch/discovery target**, subject to platform approval and release requirements. The intended Steam listing is free to users.

That does **not** make ChannelOS a Steam-only product. The same core must remain distributable as:

- standalone Windows application,
- standalone Linux application,
- source/build distribution,
- Steam / SteamOS application,
- future dedicated appliance image.

Steam may provide installation, updates, discovery, controller-friendly launching, and an excellent living-room host environment. It must not become an authorization dependency for local media playback or the only route to obtain/use ChannelOS.

Before public distribution, including Steam:

- [ ] Select and add the intended open-source license
- [ ] Audit third-party runtime licenses/notices
- [ ] Verify packaged libVLC distribution compliance
- [ ] Produce repeatable Windows/Linux packages
- [ ] Validate SteamOS couch/controller behavior
- [ ] Verify a standalone install works without Steam present

See [ADR-0004](decisions/0004-distribution-and-appliance-neutrality.md).

## Explicitly not on the early roadmap

- DRM circumvention
- Streaming-service scraping
- Mandatory cloud accounts
- Advertising injection
- Custom codec development
- Custom operating-system kernel development
- AI scheduling before deterministic scheduling is solid

AI may eventually assist programming, but it should arrive only after ChannelOS has a transparent deterministic scheduler to compare against.
