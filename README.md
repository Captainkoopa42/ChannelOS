# ChannelOS

> **A personal broadcasting system for user-owned media.**
>
> Own the library. Own the schedule. Own the interface.

ChannelOS is an experimental, local-first media platform that turns media you own or legitimately control into a cable-style television experience: numbered channels, persistent programming, a guide, passive viewing, direct playback control, and remote-first operation.

The goal is not to build another streaming service or another thumbnail browser. The goal is to let a person **operate their own television network**.

## Project status

**Pre-alpha / Phase 1 — Persistent Channel Runtime**

Phase 0 is complete: the reference core has indexed genuine user media on Windows, resolved a real Channel 07, and displayed the selected asset through VLC/libVLC.

The current Phase 1 branch adds the first actual television runtime: persistent numeric channels, deterministic generated timelines, independently advancing Broadcast Clocks, per-channel Viewer Clocks, restart continuity, missing-file recovery, live/resume/ask return behavior, `TUNE 007`, Channel Up/Down, Previous Channel, pause/seek, and `GO_LIVE`.

The key runtime rule is:

> **The schedule belongs to the channel. The playhead belongs to the user.**

A channel does **not** need a hidden player decoding in the background. Given its persistent schedule epoch, indexed media durations, and wall-clock time, ChannelOS calculates what that channel would currently be airing and the exact seek offset into that program.

The canonical complete product direction is maintained in **[ChannelOS Master Design](docs/MASTER_DESIGN.md)**. The current executable runtime milestone is **[Persistent Channel Runtime](docs/PERSISTENT_CHANNEL_RUNTIME.md)**.

## Core promise

ChannelOS must never become the thing standing between a person and their media.

- Media remains ordinary user-controlled files.
- Core local playback must not require a cloud account.
- Channel definitions are human-readable and portable.
- Runtime/index state is kept separate from media.
- Export must become real migration, not an ecosystem trap.
- ChannelOS does not inject advertising into local media playback.

If ChannelOS disappears, the library survives.

## What a channel is

A ChannelOS channel is **not a folder**. It is a programmable view over media sources with an identity, channel number, selection rules, scheduling rules, and continuity state.

```yaml
schema_version: "0.1"
channel: 7
name: Sci-Fi
sources:
  - path: /media/TV/Stargate SG-1
  - path: /media/TV/Star Trek - The Next Generation
programming:
  mode: sequential
  preserve_episode_order: true
```

The intended experience is deliberately television-like: press `7`, and Channel 7 starts at whatever point its schedule has reached. Open the Guide if you care what is next. Browse the Library only when you actually want to choose.

## Current architecture

```text
user-owned files
      |
      v
filesystem scanner
      |
      +----> optional ffprobe technical durations
      |
      v
MediaAsset (stable SHA-256 content ID)
      |
      +---- MediaLocation(s)
      |
      v
SQLite media index
      |
      v
channel source resolver
      |
      v
Persistent Channel Runtime
  schedule signature
  schedule epoch
  Broadcast Clock
  Viewer Clock
  current / previous channel
      |
      v
TelevisionSession
  TUNE 007
  CHANNEL_UP / DOWN
  PREVIOUS_CHANNEL
  PAUSE / PLAY / SKIP / GO_LIVE
      |
      v
PlaybackBackend
      |
      v
LibVLCBackend
```

The Phase 0 full-file SHA-256 identity is intentionally conservative. A path is a location, not the media identity. Moving unchanged content and rescanning resolves to the same `sha256:...` asset.

The Phase 1 runtime state is also deliberately separate from the media index. Schedule epochs, current/previous channel, and Viewer Clock continuity can be discarded or exported without changing the media itself.

## Virtual television instead of background decoding

Suppose Channel 007 begins at 10:00:00 and contains three timed programs:

```text
10:00:00–10:00:30  Program A
10:00:30–10:01:15  Program B
10:01:15–10:02:15  Program C
```

If you tune at 10:00:42, ChannelOS calculates:

```text
Program B
seek = 12 seconds
```

Channel 007 did not have to consume CPU/GPU resources for those 42 seconds. Its schedule advanced mathematically.

That is the mechanism that lets many personal channels behave like live television while only the tuned channel is actually decoded.

## Repository map

```text
ChannelOS/
├── README.md
├── pyproject.toml
├── docs/
│   ├── MASTER_DESIGN.md
│   ├── FIRST_BROADCAST.md
│   ├── PERSISTENT_CHANNEL_RUNTIME.md
│   ├── VISION.md
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── ChannelOS_Product_Vision.docx
│   ├── decisions/
│   │   ├── 0001-local-first-portable-core.md
│   │   └── 0002-media-identity-and-playback.md
│   └── specs/
│       └── CHANNEL_FORMAT.md
├── examples/
│   └── channels/
│       └── sci-fi.yaml
├── src/channelos/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── library.py
│   ├── loader.py
│   ├── models.py
│   ├── playback.py
│   ├── probe.py
│   ├── resolve.py
│   ├── runtime.py
│   ├── scanner.py
│   ├── television.py
│   └── tuner.py
└── tests/
    ├── test_cli_runtime.py
    ├── test_library.py
    ├── test_loader.py
    ├── test_resolve.py
    ├── test_runtime.py
    ├── test_runtime_recovery.py
    ├── test_television.py
    └── test_tuner.py
```

## Try the reference core

Requires Python 3.11+.

Development/tests:

```bash
python -m pip install -e ".[dev]"
channelos validate examples/channels/sci-fi.yaml
pytest
```

Scan a real local folder without moving its files:

```bash
channelos scan "D:\Media" --db ".channelos\library.db"
channelos library --db ".channelos\library.db"
```

Persistent scheduling requires real durations. `ffprobe` is used when available for duration/container/stream information. Use `--require-probe` when preparing a media set for the Phase 1 Broadcast Clock.

Inspect what one persistent channel is broadcasting without launching a decoder:

```bash
channelos broadcast my-channel.yaml \
  --db ".channelos\library.db" \
  --state-db ".channelos\runtime.db"
```

For playback, install VLC/libVLC on the operating system and the optional Python binding:

```bash
python -m pip install -e ".[playback]"
```

Run the current multi-channel television harness:

```bash
channelos tv channel-7.yaml channel-12.yaml \
  --db ".channelos\library.db" \
  --state-db ".channelos\runtime.db"
```

The Phase 1 console accepts the future control-intent vocabulary:

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
QUIT
```

This remains an engineering harness. The finished product is intended to hide the computer behind a couch-first television interface or an open dedicated appliance.

## Read first

1. **[Master Design — start here](docs/MASTER_DESIGN.md)**
2. **[Persistent Channel Runtime — current executable milestone](docs/PERSISTENT_CHANNEL_RUNTIME.md)**
3. [First Broadcast — completed Phase 0](docs/FIRST_BROADCAST.md)
4. [Architecture](docs/ARCHITECTURE.md)
5. [Roadmap](docs/ROADMAP.md)
6. [Product vision](docs/VISION.md)
7. [Channel format specification](docs/specs/CHANNEL_FORMAT.md)
8. [ADR-0001: Local-first portable core](docs/decisions/0001-local-first-portable-core.md)
9. [ADR-0002: Media identity and playback](docs/decisions/0002-media-identity-and-playback.md)

## North Star

Every major feature should answer five questions:

1. Does this increase the user's control over their media?
2. Does it still work if ChannelOS loses internet access?
3. Can the user understand what the system did?
4. Can the user export or migrate the result?
5. Does it make television easier to use from a couch?

## License

No open-source license has been selected yet. Until one is deliberately chosen and added, normal copyright restrictions apply.

---

**The user is not the audience of ChannelOS. The user is the broadcaster.**
