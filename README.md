# ChannelOS

> **A personal broadcasting system for user-owned media.**
>
> Own the library. Own the schedule. Own the interface.

ChannelOS is an experimental, local-first media platform that turns media you own or legitimately control into a cable-style television experience: numbered channels, persistent programming, a guide, passive viewing, direct playback control, and remote-first operation.

The goal is not to build another streaming service or another thumbnail browser. The goal is to let a person **operate their own television network**.

## Project status

**Pre-alpha / Phase 0 — First Broadcast foundation**

The repository now contains the first executable media spine beneath the design: local scanning, stable content identity, a SQLite index that keeps media assets separate from paths, optional ffprobe technical probing, channel-to-index resolution, a backend-neutral playback contract, and a libVLC reference backend.

The next real-machine gate is an end-to-end VLC/libVLC smoke test with genuine user-owned media. After that, work moves to the Channel Runtime: generated timelines, Broadcast Clock, Viewer Clock, and `TUNE 007`.

The canonical description of the complete intended system — Live TV, Guide, Library/On Demand, profiles, metadata, playback architecture, remote controls, channel clocks, management UI, portability, and the long-term open hardware direction — is maintained in **[ChannelOS Master Design](docs/MASTER_DESIGN.md)**.

The current executable milestone and manual smoke-test path are documented in **[First Broadcast](docs/FIRST_BROADCAST.md)**.

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

The long-term experience is deliberately television-like: press `7`, and Channel 7 starts. Open the Guide if you care what is next. Browse the Library only when you actually want to choose.

## First Broadcast architecture

```text
user-owned files
      |
      v
filesystem scanner
      |
      +----> optional ffprobe technical data
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
PlaybackBackend
      |
      v
LibVLCBackend
```

The Phase 0 full-file SHA-256 identity is intentionally conservative. A path is a location, not the media identity. Moving unchanged content and rescanning resolves to the same `sha256:...` asset.

## Repository map

```text
ChannelOS/
├── README.md
├── pyproject.toml
├── docs/
│   ├── MASTER_DESIGN.md
│   ├── FIRST_BROADCAST.md
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
│   ├── scanner.py
│   └── tuner.py
└── tests/
    ├── test_library.py
    ├── test_loader.py
    ├── test_resolve.py
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

`ffprobe` is used when available for duration/container/stream information. Use `--no-probe` to skip it or `--require-probe` to make probe failure fatal.

For playback, install VLC/libVLC on the operating system and the optional Python binding:

```bash
python -m pip install -e ".[playback]"
```

Then point a channel YAML source at an indexed folder:

```bash
channelos resolve my-channel.yaml --db ".channelos\library.db"
channelos tune my-channel.yaml --db ".channelos\library.db" --dry-run
channelos tune my-channel.yaml --db ".channelos\library.db"
```

The temporary Phase 0 control console supports play, pause, mute/unmute, volume, seek, relative skip, playback rate, status, and quit. It is a test harness for the future remote/control boundary, not the intended final UI.

See [FIRST_BROADCAST.md](docs/FIRST_BROADCAST.md) for the full smoke test.

## Read first

1. **[Master Design — start here](docs/MASTER_DESIGN.md)**
2. **[First Broadcast — current executable milestone](docs/FIRST_BROADCAST.md)**
3. [Architecture](docs/ARCHITECTURE.md)
4. [Roadmap](docs/ROADMAP.md)
5. [Product vision](docs/VISION.md)
6. [Channel format specification](docs/specs/CHANNEL_FORMAT.md)
7. [ADR-0001: Local-first portable core](docs/decisions/0001-local-first-portable-core.md)
8. [ADR-0002: Media identity and playback](docs/decisions/0002-media-identity-and-playback.md)

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
