# ADR-0003 — Persistent Channel Clocks and Virtual Broadcast Time

**Status:** Accepted for Phase 1  
**Date:** 2026-08-19

## Context

ChannelOS must make many personal channels feel like independently running television stations without decoding every channel simultaneously.

Keeping one hidden player alive per channel would waste CPU/GPU resources, complicate restart recovery, and incorrectly make the decoder responsible for channel time.

ChannelOS also needs pause, rewind, fast-forward, resume, and `GO_LIVE` without changing the underlying channel schedule.

## Decision

ChannelOS separates two clocks.

### Broadcast Clock

Each persistent channel stores a UTC schedule epoch. The programming timeline plus elapsed wall-clock time determines what the channel would currently be broadcasting.

For repeating deterministic Phase 1 schedules:

```text
elapsed = now - epoch
cycle_position = elapsed mod total_cycle_duration
```

The program containing `cycle_position` is selected and the offset inside that program becomes the decoder seek position.

Untuned channels therefore advance virtually; they do not require background decoding.

### Viewer Clock

Each channel may also have a personal Viewer Clock containing a schedule timestamp, the wall-clock instant at which it was observed, and whether it is running.

When LIVE, Viewer Clock and Broadcast Clock coincide. Pause freezes only Viewer Clock. Rewind/skip move Viewer Clock. `GO_LIVE` sets Viewer Clock back to current Broadcast Clock.

### Persistence

Runtime state is stored separately from the media index. The Phase 1 reference implementation uses a local SQLite runtime database for:

- schedule epoch by numeric channel,
- schedule signature,
- current channel,
- previous channel,
- per-channel Viewer Clock continuity.

This database does not own or contain the media.

### Schedule signatures

The Phase 1 schedule signature includes the channel number, programming mode, stable asset IDs, and technical durations.

If the signature is unchanged after restart, the original epoch survives.

If programming inputs change — including a previously indexed location disappearing after a rescan — ChannelOS re-anchors the schedule instead of applying the old epoch to a different sequence. Saved Viewer Clock continuity for that channel is discarded because it no longer identifies the same schedule.

### Duration authority

Persistent scheduling requires positive indexed media durations. ChannelOS will reject a schedule that lacks them rather than guessing.

The current reference technical-data path is the `MediaProbe` boundary with ffprobe as the first implementation.

### Playback ownership

The runtime chooses:

```text
channel
media asset
schedule timestamp
seek offset
```

Only then does `TelevisionSession` ask `PlaybackBackend` to load/play/seek. The decoder never decides what a channel means or where its schedule should be.

## Consequences

### Positive

- dozens or hundreds of channels can advance while only the tuned channel consumes decoder resources,
- channel state survives process restart,
- pause and rewind do not stop the channel's Broadcast Clock,
- direct tuning can land in the middle of the correct program,
- the same runtime can later drive a Guide, desktop UI, appliance UI, phone remote, or alternative playback backend,
- missing media can be handled as a schedule-input change rather than a decoder failure,
- the architecture preserves the rule: **the schedule belongs to the channel; the playhead belongs to the user.**

### Costs

- correct technical durations become mandatory for persistent scheduling,
- schedule edits need explicit re-anchoring semantics,
- clock drift between the authoritative Viewer Clock and a real decoder will eventually need synchronization policy,
- Phase 1 sequential schedules are deliberately simpler than future time blocks, marathons, weighted rotations, and Guide horizons.

## Rejected alternatives

### Keep every channel playing invisibly

Rejected because it wastes resources, scales poorly, and makes decoder process lifetime part of schedule truth.

### Use playback position as the Broadcast Clock

Rejected because untuned channels would stop advancing and restarts would lose television time.

### Guess durations when metadata is missing

Rejected because accumulated timing error would make Guide data and direct tuning dishonest.

### Put runtime state into portable channel YAML

Rejected because portable programming intent and machine/viewer continuity are different classes of data.
