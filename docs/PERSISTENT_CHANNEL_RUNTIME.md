# Persistent Channel Runtime

**Status:** Phase 1 implementation candidate; automated reference-core tests passing  
**Phase:** 1 — Channel Runtime / Persistent Channels

## Purpose

Phase 0 proved that ChannelOS can index real user media and hand a selected asset to libVLC. Phase 1 changes the meaning of tuning a channel.

A channel is no longer "play the first file in this list." It owns an independently advancing schedule timeline.

> **The schedule belongs to the channel. The playhead belongs to the user.**

## Core invariant

ChannelOS does not keep every channel decoding in the background.

Instead, each channel has a persistent UTC schedule epoch. Given that epoch, the ordered timed media, and the current wall-clock instant, ChannelOS can calculate exactly what that channel would be broadcasting and how far into the current program it should be.

Example:

```text
Channel 007 epoch: 22:00:00

22:00:00–22:00:30  Clip A
22:00:30–22:01:15  Clip B
22:01:15–22:02:15  Clip C

Tune at 22:00:42
        ↓
Clip B
seek = 12 seconds
```

No hidden VLC instance had to play Channel 007 for those 42 seconds.

## Broadcast Clock

The current Phase 1 timeline is an indefinitely repeating deterministic sequential schedule.

For a schedule with total cycle duration `T`, ChannelOS computes:

```text
elapsed = wall_clock - schedule_epoch
cycle_position = elapsed mod T
```

The cumulative durations identify the active program and the in-program seek offset.

The math is defined both after and before the stored epoch, which keeps deterministic tests and future schedule inspection well behaved.

### Duration requirement

A Broadcast Clock cannot be correct without program durations.

Phase 1 therefore rejects scheduleable media whose indexed `duration_seconds` is missing or non-positive. The media can still exist in the library, but the persistent television runtime requires technical duration data.

The current intended path is to scan with the existing `ffprobe` adapter rather than inventing guessed durations.

## Persistent schedule identity

Each resolved channel gets a deterministic schedule signature derived from:

- channel number,
- programming mode,
- ordered stable media asset IDs,
- indexed media durations.

The local runtime SQLite database stores:

```text
channel number
schedule signature
schedule epoch
```

If ChannelOS restarts and the signature is unchanged, the original epoch survives. The channel therefore continues advancing across process restarts.

If the resolved programming inputs change, ChannelOS deliberately creates a new epoch rather than pretending the old timeline still maps cleanly onto different media.

This also provides the current missing-file recovery behavior: after a rescan marks a missing location offline, the resolved online media set changes, the schedule signature changes, and the channel re-anchors using the surviving media.

## Viewer Clock

The Broadcast Clock answers:

> What is Channel 007 broadcasting?

The Viewer Clock answers:

> Where is this viewer currently watching Channel 007's timeline?

A Viewer Clock stores:

```text
schedule_time_utc
observed_at_utc
running
```

When running, viewer schedule time advances with wall time. When paused or when the viewer leaves that channel, the personal playhead can freeze while the channel Broadcast Clock continues independently.

This creates the intended behaviors:

```text
LIVE
Viewer Clock == Broadcast Clock

PAUSE
Viewer Clock freezes
Broadcast Clock continues

PLAY
Viewer Clock resumes from its frozen point

SKIP_BACK / SKIP_FORWARD
Viewer Clock moves on the schedule timeline
Fast-forward is capped at LIVE

GO_LIVE
Viewer Clock snaps to Broadcast Clock
```

## Returning to a channel

Phase 1 implements all three intended return policies:

- `live` — return to what the channel is broadcasting now.
- `resume` — return to the saved Viewer Clock position.
- `ask` — expose that both choices exist instead of silently deciding.

Viewer continuity is stored per channel in the runtime database. The underlying media is never stored there.

## Multi-channel television state

`TelevisionRuntime` owns the active lineup by numeric channel identity and persists:

- current channel,
- previous channel,
- per-channel Viewer Clock continuity.

The channel list is numerically ordered, so Channel Up / Down wraps through the active lineup.

Previous Channel toggles between the last two tuned channels using the same runtime path as direct tuning.

## Control intents

The Phase 1 playback harness deliberately uses the vocabulary intended for future remotes and appliance clients:

```text
TUNE 007
CHANNEL_UP
CHANNEL_DOWN
PREVIOUS_CHANNEL
PAUSE
PLAY
SKIP_BACK 10
SKIP_FORWARD 30
GO_LIVE
STATUS
STOP
```

`TelevisionSession` converts these intents into ChannelOS runtime decisions first, then applies the selected media and seek offset through `PlaybackBackend`.

The decoder does not decide what Channel 007 means.

## CLI harnesses

Inspect a persistent channel without launching playback:

```bash
channelos broadcast channel-7.yaml --db .channelos/library.db --state-db .channelos/runtime.db
```

The output includes the selected asset, media ID, seek offset, program start/end, and persistent schedule epoch.

Run the current multi-channel playback harness:

```bash
channelos tv channel-7.yaml channel-12.yaml \
  --db .channelos/library.db \
  --state-db .channelos/runtime.db
```

This text console is still an engineering harness, not the final television UI.

## Automated validation

The Phase 1 branch currently tests:

- mid-program Broadcast Clock selection,
- cycle wraparound,
- pre-epoch timeline math,
- persistent epoch across restart,
- schedule re-anchoring when programming inputs change,
- rejection of missing duration data,
- Viewer Clock pause/play/seek/GO_LIVE,
- live versus resume behavior,
- explicit `ask` return behavior,
- Channel Up / Down and Previous Channel,
- two channels advancing independently while untuned,
- current/viewer continuity across runtime restart,
- fast-forward capped at LIVE,
- playback routing through a fake backend,
- CLI Broadcast Clock persistence,
- CLI television startup through the Phase 1 session,
- missing-file recovery after a real rescan marks an asset offline.

CI runs the reference core on Python 3.11, 3.12, and 3.13.

## Remaining Phase 1 work

The main unimplemented roadmap item is deterministic shuffle programming with repeat avoidance.

Before Phase 1 is merged, the preferred real-machine smoke test is:

1. ensure the selected real media has indexed durations,
2. define Channel 007 and Channel 012,
3. start the Phase 1 `tv` harness,
4. tune Channel 007 and note the program/offset,
5. switch to Channel 012,
6. wait long enough for Channel 007's Broadcast Clock to advance,
7. return to Channel 007 in `live` mode and verify it lands at the correct later point,
8. repeat with `resume`, pause, skip, and `GO_LIVE`.

Passing that test demonstrates the fundamental ChannelOS television behavior on a real decoder and real user media.
