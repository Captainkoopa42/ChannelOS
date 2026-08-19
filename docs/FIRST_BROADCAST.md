# First Broadcast Milestone

**Status:** Complete — real Windows/libVLC playback verified  
**Phase:** 0 — Foundation

> Historical milestone document. Phase 1 is also complete; the current development target is [GUIDE_AND_UI_BOUNDARY.md](GUIDE_AND_UI_BOUNDARY.md).

## Purpose

First Broadcast was the first complete vertical slice of ChannelOS:

```text
user-owned file
      ↓
filesystem scanner
      ↓
stable media asset + location index
      ↓
channel source resolution
      ↓
ChannelOS playback contract
      ↓
libVLC reference backend
      ↓
picture / sound
```

It deliberately did **not** attempt to implement the Guide, Broadcast Clock, profiles, poster library, or metadata matching. Those systems needed this spine underneath them.

## What Phase 0 established

The reference core could:

- recursively scan supported local video files without moving them,
- assign stable SHA-256 content IDs,
- keep media identity separate from filesystem location,
- recognize an unchanged file after it moves and is rescanned,
- cache unchanged path scans so every run does not re-hash every file,
- optionally use ffprobe for duration/container/stream metadata,
- resolve a schema `0.1` channel path source against the local index,
- expose a backend-neutral playback interface,
- use libVLC as the first playback backend,
- tune the first resolved item from a channel,
- route pause/play, mute, volume, seek/skip, playback rate, status, and stop through ChannelOS commands.

## Verified real-machine run

Phase 0 was closed with a real Windows smoke test rather than only mocks or dry runs:

- Python 3.11.9,
- 8/8 automated tests passed on the test machine,
- 184 genuine NVIDIA-recorded MP4 files were indexed from a real user media folder,
- a controlled Channel 07 definition resolved three exact indexed assets,
- `tune --dry-run` selected the expected first asset and stable SHA-256 media ID,
- the native VLC/libVLC runtime exposed libVLC 3.0.23 Vetinari successfully through `python-vlc`,
- `channelos tune` launched the selected Channel 07 asset and displayed genuine video through libVLC.

The user's media remained in place throughout the test. ChannelOS created and used only its rebuildable local index and channel definition.

## Development setup used for the milestone

Python 3.11+ is required.

Base development install:

```bash
python -m pip install -e ".[dev]"
```

For source-tree playback development:

```bash
python -m pip install -e ".[playback]"
```

At the time of the original milestone, a compatible native VLC/libVLC installation was used. The current architecture also supports bundled-style runtime discovery and a development override, and the finished product is intended to package its compatible playback runtime rather than making ordinary users configure VLC manually.

For technical media probing, install FFmpeg so `ffprobe` is available on `PATH`.

## First scan

```bash
channelos scan "D:\Media" --db ".channelos\library.db"
```

To index without ffprobe:

```bash
channelos scan "D:\Media" --db ".channelos\library.db" --no-probe
```

To require successful ffprobe inspection:

```bash
channelos scan "D:\Media" --db ".channelos\library.db" --require-probe
```

Inspect the indexed library:

```bash
channelos library --db ".channelos\library.db"
```

## Resolve a channel

Create or edit a channel definition whose source path is inside the indexed library:

```yaml
schema_version: "0.1"
channel: 7
name: Sci-Fi
sources:
  - path: D:\Media\Sci-Fi
programming:
  mode: sequential
presentation:
  number_width: 2
```

Resolve it without playback:

```bash
channelos resolve my-sci-fi.yaml --db ".channelos\library.db"
```

## Tune

First use the dry run:

```bash
channelos tune my-sci-fi.yaml --db ".channelos\library.db" --dry-run
```

Then, with a compatible playback runtime available:

```bash
channelos tune my-sci-fi.yaml --db ".channelos\library.db"
```

The Phase 0 console accepted:

```text
play
pause
mute
unmute
volume 80
seek 120
skip 30
skip -10
rate 2
rate 1
status
quit
```

This console was never intended to be the final remote UI. It proved that user intents passed through a ChannelOS-owned control boundary before reaching the decoder.

## The move test

This remains an important identity test:

1. Scan a media folder.
2. Note an item's `sha256:...` media ID.
3. Move that file to a different folder inside the scanned source.
4. Scan the source again.
5. Confirm the online path changes while the media asset ID remains the same.

If this fails, ChannelOS is treating file organization as ownership identity.

## What came immediately after

Phase 1 built the persistent Channel Runtime on top of this foundation:

- persistent channel state,
- generated timelines,
- Broadcast Clock,
- Viewer Clock,
- deterministic sequential and shuffle programming,
- `TUNE 007`,
- Channel Up/Down and Previous Channel,
- live/resume/ask return behavior,
- pause/seek and `GO_LIVE`,
- restart and missing-file recovery.

That milestone is complete and documented in [PERSISTENT_CHANNEL_RUNTIME.md](PERSISTENT_CHANNEL_RUNTIME.md).
