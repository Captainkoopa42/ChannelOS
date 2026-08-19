# Guide and UI Boundary

**Status:** Phase 2 design target  
**Phase:** 2 — Guide

## Purpose

Phase 1 proved that ChannelOS can maintain real persistent television channels. Phase 2 turns that runtime into stable television-facing data that a Guide and later couch UI can consume without duplicating scheduling logic inside presentation code.

The architectural rule is:

> **The runtime decides television state. The UI presents and controls it.**

The next work is therefore both Guide work and plumbing work.

## Boundary

```text
Media Index
    |
    v
Programming Engine
    |
    v
Channel Runtime
    |  Broadcast Clock / Viewer Clock
    v
Guide + Television Service Boundary
    |  schedule horizon
    |  Now / Next
    |  channel rows
    |  program detail
    |  explain-why
    |  control intents
    v
TV UI / desktop UI / SteamOS UI / future clients
```

The Guide must not calculate authoritative channel schedules independently from the Channel Runtime. Given the same channel definition, persistent epoch, programming policy, and time, the Guide and a direct tune must agree about what is airing.

## Phase 2 read models

The exact Python types may evolve, but the UI-facing boundary should be able to express at least:

### GuideProgram

```text
channel_number
stable media identity
program title / display label
start_utc
end_utc
duration
current-state flags
programming explanation / trace
```

### NowNext

```text
channel_number
now
next
viewer_lag where relevant
```

### GuideChannelRow

```text
channel identity
channel number
channel name
ordered programs covering requested horizon
```

### GuideHorizon

A deterministic time range such as:

```text
start_utc
end_utc
rows[]
```

The horizon should be generated from schedule truth, not from decoder history.

## Required behavior

Phase 2 should implement:

- schedule horizon generation for a requested time range,
- Now / Next for every active channel,
- traditional grid-guide data suitable for a couch UI,
- program durations derived from indexed technical data,
- deterministic regeneration when programming inputs change,
- explain-why traces for automatically selected programs,
- tune from Guide using the same ChannelOS control path as `TUNE 007`,
- Watch from Beginning when the owned media and reconstructed schedule permit it,
- coherent representation of past, current, and future scheduled programs.

## Current engineering harness

The first Guide projection can be inspected without launching a decoder:

```bash
channelos guide channel-7.yaml channel-12.yaml \
  --db .channelos/library.db \
  --state-db .channelos/runtime.db \
  --hours 2
```

The command prints the requested schedule horizon plus current Now/Next state for each channel. `--from` accepts an explicit timezone-aware ISO-8601 horizon start, and `--why` exposes the deterministic scheduling trace for every scheduled occurrence.

This command is an engineering visibility tool, not the final Guide UI. Its purpose is to prove that a UI-facing client can consume the same persistent schedule truth that playback uses.

## Control path

A Guide selection must not directly manipulate libVLC.

```text
Guide selection
      |
      v
ChannelOS intent / service call
      |
      v
TelevisionRuntime / Viewer Clock decision
      |
      v
TelevisionSession
      |
      v
PlaybackBackend
```

Examples:

```text
TUNE channel=7
WATCH_FROM_BEGINNING channel=7 program=<stable scheduled program>
GO_LIVE channel=7
```

The exact public control protocol can be finalized in Phase 3, but Phase 2 data types should not make that future separation difficult.

## API / IPC posture

The first implementation may remain in-process for speed and testability. The architectural boundary should nevertheless be explicit enough that it can later become a local API or IPC service without moving scheduling logic into the UI.

This is important because the same core should eventually serve:

- the desktop application,
- the fullscreen couch interface,
- Steam / SteamOS launches,
- a dedicated ChannelOS appliance,
- a local management web UI,
- a phone/tablet remote,
- household multi-TV clients.

## UI scope in Phase 2

Phase 2 may include a basic Guide view or engineering visualization to prove the data path. The polished appliance interface belongs mainly to Phase 3.

The intended visual direction is dark and television-first: deep navy/charcoal surfaces, cool blue focus states, bright legible text, large remote-friendly targets, and a restrained LIVE indicator. It should feel natural when launched from SteamOS while remaining visibly ChannelOS rather than copying Steam's interface.

## Tests

Automated tests should verify at least:

- a Guide horizon agrees exactly with `broadcast_at()` at overlapping instants,
- channel rows are ordered by numeric channel identity,
- sequential and deterministic-shuffle channels produce stable horizons,
- Now/Next crosses program boundaries correctly,
- horizons work across cycle wraparound,
- schedule changes invalidate/regenerate affected Guide data coherently,
- tune-from-Guide routes through the ChannelOS runtime rather than the playback backend directly,
- Watch from Beginning selects offset zero for the intended scheduled program where supported,
- explain-why output is deterministic and tied to the scheduling decision.

## Exit gate

Phase 2 is complete when a user-facing client can request a believable Guide horizon for multiple real channels, display Now/Next, tune a current program, start an owned scheduled program from its beginning where allowed, and show why a scheduled item was selected — with all answers coming from the same runtime truth that drives playback.

The real-machine gate should use the existing genuine indexed media library and verify that selecting a Guide program launches the same asset and offset the Guide predicted.
