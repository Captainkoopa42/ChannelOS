# ADR-0002: Stable media identity, indexed locations, and backend-neutral playback

**Status:** Accepted for the Phase 0 reference implementation  
**Date:** 2026-08-18

## Context

ChannelOS cannot build persistent channels, guide schedules, profiles, watch state, or portable metadata if a media item is identified only by its current filesystem path. Paths change when users rename folders, replace drives, or reorganize a library.

ChannelOS also should not become a codec project. Mature playback engines already solve media decoding, rendering, audio, subtitles, seeking, and hardware acceleration.

## Decision

### Media asset identity

The Phase 0 reference index identifies exact file content with a full-file SHA-256 digest.

The stable asset ID is:

```text
sha256:<hex digest>
```

The content identity is stored separately from one or more filesystem locations.

```text
MediaAsset
    asset_id
    content_sha256
    size
    duration / technical probe data
        |
        +-- MediaLocation A
        +-- MediaLocation B
```

Moving an unchanged file therefore creates or activates a new location while resolving to the same media asset.

The user's path is never the canonical media identity.

### Index storage

The first implementation uses SQLite for disposable runtime/index state. SQLite references user files; it does not import, move, rename, or own them.

A scan marks previously known locations for that scanned source offline, rediscovers current files, and reactivates or creates locations as appropriate.

Unchanged files at unchanged paths reuse cached size/mtime information and do not need to be re-hashed on every scan.

### Technical probing

ChannelOS uses an optional `ffprobe` adapter to retrieve machine-readable media duration/container/stream information.

A normal scan can still index a file when ffprobe is absent or a particular file cannot be probed. Strict probing is available when validation is required.

### Playback

ChannelOS defines its own `PlaybackBackend` interface. Core runtime code talks to that interface rather than directly to VLC.

The first reference implementation is `LibVLCBackend`, using the Python libVLC binding when installed.

The boundary includes:

- load
- play
- pause
- stop
- absolute seek
- current position
- volume
- mute
- playback rate

Future mpv or other playback engines may implement the same ChannelOS contract.

## Consequences

### Positive

- Moving an unchanged file does not create a new conceptual media asset.
- Exact duplicate files naturally collapse to one asset with multiple locations.
- Paths remain user-controlled and replaceable.
- The library/index can be rebuilt without touching the media.
- Playback implementation can change without rewriting channel logic.
- The first tuner can exercise pause, seek, rate, volume, and mute through ChannelOS-owned commands.

### Costs and limitations

- Full-file SHA-256 is intentionally conservative and may be slow on a first scan of large libraries.
- A file moved to a new path may need to be hashed again before ChannelOS recognizes it as the same asset.
- A byte-for-byte modified/re-encoded file is a different Phase 0 asset even if it represents the same movie or episode. Higher-level title/episode identity belongs to the later metadata model.
- `python-vlc` is only a binding; a usable native VLC/libVLC installation is also required on the machine doing playback.
- `ffprobe` is an external tool and is not bundled with ChannelOS.

These are acceptable Phase 0 tradeoffs because they establish clean identity and playback boundaries without making the index proprietary or entangling ChannelOS with one decoder.

## Invariant

> **The media asset is not its path, and ChannelOS playback logic is not its decoder.**
