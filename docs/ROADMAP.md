# ChannelOS Roadmap

This roadmap is intentionally behavior-first. ChannelOS does not need to support every codec, service, or device before it proves that personally owned media can feel like television again.

## Phase 0 — Skeleton

**Goal:** Establish the constitutional boundaries and a testable core.

- [x] Product vision
- [x] Repository structure
- [x] Versioned channel-definition format
- [x] Reference parser and validator
- [x] Example channel
- [x] Initial architecture decision record
- [ ] Filesystem media scanner
- [ ] Stable media identity model
- [ ] Playback adapter interface
- [ ] mpv proof of concept

**Exit:** A media file can be indexed by stable identity and launched through a playback adapter from a validated channel definition.

## Phase 1 — Persistent Channels

**Goal:** Make a channel behave like something a viewer can return to.

- [ ] Numeric channel identity
- [ ] Sequential programming
- [ ] Shuffle programming with repeat avoidance
- [ ] Per-channel continuity state
- [ ] Restart recovery
- [ ] Missing-file recovery
- [ ] Tune / channel-up / channel-down commands

**Exit:** Channel 12 remains recognizably Channel 12 across application restarts.

## Phase 2 — Guide

**Goal:** Generate a coherent timeline instead of selecting one item at a time.

- [ ] Schedule horizon generation
- [ ] Now / Next model
- [ ] Program durations
- [ ] Traditional grid guide data model
- [ ] Schedule regeneration rules
- [ ] Explain-why trace for programmed items

**Exit:** A user can see a believable day of programming and understand why each item was scheduled.

## Phase 3 — Appliance UX

**Goal:** Make the computer disappear during normal viewing.

- [ ] Full-screen live view
- [ ] Remote input abstraction
- [ ] Numeric direct tuning
- [ ] Channel up/down
- [ ] Previous channel
- [ ] Minimal Now/Next overlay
- [ ] Guide UI
- [ ] Autostart and crash recovery

**Exit:** A keyboard and mouse are optional for ordinary viewing.

## Phase 4 — Programmer

**Goal:** Give channels identity.

- [ ] Time-of-day blocks
- [ ] Weighted rotations
- [ ] Marathons
- [ ] Feature/movie slots
- [ ] Seasonal rules
- [ ] User-owned bumpers and station IDs
- [ ] Intermissions

**Exit:** Two channels using overlapping media can still feel distinctly programmed.

## Phase 5 — Export My Television

**Goal:** Prove ownership extends to configuration and history.

- [ ] Full configuration export
- [ ] Library remapping on import
- [ ] Schedule definitions
- [ ] Metadata overrides
- [ ] Watch state
- [ ] Channel continuity
- [ ] Machine-to-machine migration test

**Exit:** A fresh ChannelOS install can reconstruct the recognizable television from an export and restored media.

## Phase 6 — Ecosystem

**Goal:** Extend ChannelOS without turning the core into a platform monopoly.

- [ ] Source adapter SDK
- [ ] Capability-limited plugins
- [ ] Optional metadata providers
- [ ] Multiple TVs on a household network
- [ ] Phone/tablet remote
- [ ] Music-radio and ambient channels
- [ ] Dedicated appliance image experiments

## Explicitly not on the early roadmap

- DRM circumvention
- Streaming-service scraping
- Mandatory cloud accounts
- Advertising injection
- Custom codec development
- AI scheduling before deterministic scheduling is solid

AI may eventually assist programming, but it should arrive only after ChannelOS has a transparent deterministic scheduler to compare against.
