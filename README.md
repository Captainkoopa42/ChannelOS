# ChannelOS

> **A personal broadcasting system for user-owned media.**
>
> Own the library. Own the schedule. Own the interface.

ChannelOS is an experimental, local-first media platform that turns media you own or legitimately control into a cable-style television experience: numbered channels, persistent programming, a guide, passive viewing, and remote-first playback.

The goal is not to build another streaming service or another thumbnail browser. The goal is to let a person **operate their own television network**.

## Project status

**Pre-alpha / Phase 0 — Skeleton**

This repository currently defines the product philosophy, the first portable channel format, and a small reference implementation that can load and validate channel definitions.

The canonical description of the complete intended system — Live TV, Guide, Library/On Demand, profiles, metadata, playback architecture, remote controls, channel clocks, management UI, portability, and the long-term open hardware direction — is maintained in **[ChannelOS Master Design](docs/MASTER_DESIGN.md)**.

## Core promise

ChannelOS must never become the thing standing between a person and their media.

- Media remains ordinary user-controlled files.
- Core local playback must not require a cloud account.
- Channel definitions are human-readable and portable.
- Runtime state is kept separate from media.
- Export must be real migration, not an ecosystem trap.
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

The long-term experience is deliberately television-like: press `7`, and Channel 7 starts. Open the guide if you care what is next. Browse the library only when you actually want to choose.

## Repository map

```text
ChannelOS/
├── README.md
├── pyproject.toml
├── docs/
│   ├── MASTER_DESIGN.md
│   ├── VISION.md
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   ├── ChannelOS_Product_Vision.docx
│   ├── decisions/
│   │   └── 0001-local-first-portable-core.md
│   └── specs/
│       └── CHANNEL_FORMAT.md
├── examples/
│   └── channels/
│       └── sci-fi.yaml
├── src/channelos/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── loader.py
│   └── models.py
└── tests/
    └── test_loader.py
```

## Try the Phase 0 prototype

Requires Python 3.11+.

```bash
python -m pip install -e .[dev]
channelos validate examples/channels/sci-fi.yaml
channelos show examples/channels/sci-fi.yaml
pytest
```

The current prototype deliberately does very little: it proves that a documented channel file can be parsed, validated, and represented without hiding the user's configuration inside a proprietary database.

## Read first

1. **[Master Design — start here](docs/MASTER_DESIGN.md)**
2. [Product vision](docs/VISION.md)
3. [Architecture](docs/ARCHITECTURE.md)
4. [Roadmap](docs/ROADMAP.md)
5. [Channel format specification](docs/specs/CHANNEL_FORMAT.md)
6. [ADR-0001: Local-first portable core](docs/decisions/0001-local-first-portable-core.md)

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
