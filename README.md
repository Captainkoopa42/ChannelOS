> [!IMPORTANT]
> **The macOS edition is currently shelved.** The maintainer does not own Mac
> hardware, so active development will wait until a Mac-owning community is
> willing to help develop and test the platform alongside him. The preserved
> architecture and restart conditions are recorded in
> [the macOS Master Plan](docs/MACOS_MASTER_PLAN.md).

# ChannelOS

> **A personal broadcasting system for user-owned media.**
>
> Own the library. Own the schedule. Own the interface.

ChannelOS is a local-first personal television system that turns media you own or legitimately control into a cable-style experience: numbered channels, persistent programming, a Guide, passive viewing, direct playback control, and remote-first operation.

The goal is not to build another streaming service or another thumbnail browser. The goal is to let a person **operate their own television network**.

## Project status

**Working local alpha / Phase 3 active / Phase 4 first slice functional**

Phase 0, Phase 1, and Phase 2 are complete. The active couch implementation now exercises the real ChannelOS television path on Windows rather than only a console or visual-shell proof.

Real-machine validation currently includes:

- persistent Channel 007 and 012 schedules,
- authoritative multi-channel Guide navigation,
- embedded video and audio inside the ChannelOS Qt couch UI,
- D3D11VA hardware decoding through libVLC,
- automatic scheduled program rollover,
- Broadcast Clock / Viewer Clock lag and `GO_LIVE`,
- pause, rewind, skip-forward, and channel switching,
- readable short-form Guide aggregation without modifying schedule truth,
- a real Library view backed by the canonical SQLite media index,
- local Add Media Folder,
- independent On Demand playback over the same indexed media,
- end-of-file replay/rewind recovery,
- return from On Demand to television without destroying channel clock state.

Optional native Xbox-compatible controller input is implemented and validated
on Windows with an 8BitDo Ultimate controller in Xbox/XInput mode, including
hot-plug behavior and settings-driven control hints. Steam Input can expose
other controllers through its normal gamepad/XInput emulation path; native
SteamOS validation remains a separate gate.

The key runtime rule remains:

> **The schedule belongs to the channel. The playhead belongs to the user.**

The implementation is now close enough to the original design that progress is tracked explicitly against it rather than by replacing it. See **[Implementation Status](docs/IMPLEMENTATION_STATUS.md)** for the current design-fidelity audit, completion estimates, and delivery calibration.

The canonical complete product direction remains **[ChannelOS Master Design](docs/MASTER_DESIGN.md)**. The active television UI is documented in **[Couch UI](docs/COUCH_UI.md)**, and the phase sequence remains in **[Roadmap](docs/ROADMAP.md)**.

## Core promise

ChannelOS must never become the thing standing between a person and their media.

- Media remains ordinary user-controlled files.
- Core local playback must not require a cloud account.
- Channel definitions are human-readable and portable.
- Runtime/index state is kept separate from media.
- Export must become real migration, not an ecosystem trap.
- ChannelOS does not inject advertising into local media playback.
- A distribution platform must never become an entitlement requirement for local use.

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

## Architecture

```text
user-owned files
      |
      v
Media Library / Index
      |
      v
Programming + Channel Runtime
  schedule epoch
  Broadcast Clock
  Viewer Clock
  sequential / deterministic shuffle
      |
      v
Guide / Television Service Boundary
  schedule horizon
  Now / Next
  Guide rows
  explain-why
  control intents
      |
      +--------------------+
      |                    |
      v                    v
TV / Couch UI        Management / future clients
      |
      v
TelevisionSession
      |
      v
PlaybackBackend
      |
      v
LibVLCBackend
```

The UI is a client of ChannelOS state. It must not become the place where authoritative scheduling logic lives.

The Phase 0 full-file SHA-256 identity is intentionally conservative. A path is a location, not the media identity. Moving unchanged content and rescanning resolves to the same `sha256:...` asset.

Runtime state is deliberately separate from the media index. Schedule epochs, current/previous channel, and Viewer Clock continuity can be discarded or exported without changing the media itself.

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

## Deployment and launch direction

ChannelOS is one system intended to support several deployment forms:

```text
ChannelOS Core
   ├── Desktop application
   │      Windows / Linux
   ├── Steam / SteamOS distribution
   │      primary public living-room launch target
   └── Dedicated appliance
          boot directly into ChannelOS
          HDMI + remote/controller
```

**Steam is intended to be a primary launch and discovery channel, not a dependency.** If ChannelOS is accepted for Steam distribution, the intended public listing is free to users. Steam/SteamOS is attractive because it already solves living-room installation, updating, controller access, and launching on PC-class hardware.

ChannelOS must remain independently installable. Standalone Windows/Linux packages, source distribution, and future bootable appliance images remain first-class paths. A Steam account or Steam client must never be required to authorize ordinary local playback in a standalone or appliance installation.

SteamOS and Steam Machine-class living-room PCs are therefore high-priority reference hosts, but ChannelOS is **not a Steam-only system**.

## Product packaging

During development, ChannelOS may use a system-installed libVLC or the `CHANNELOS_VLC_DIR` development override.

A finished packaged application should carry the compatible native playback runtime it needs rather than asking ordinary users to discover DLLs or install VLC in a particular location. The backend boundary remains unchanged:

```text
Channel Runtime -> PlaybackBackend -> LibVLCBackend -> packaged libVLC
```

Any bundled third-party runtime must be distributed in compliance with its license.

The active packaging foundation builds an audited Windows x64 portable folder
and ZIP with visible, replaceable Qt and libVLC sidecars. It pins the LGPL-only
VideoLAN runtime by version and hash and emits a complete `PACKAGE-BOM.json`.
See **[Distribution policy](docs/DISTRIBUTION.md)** for the exact boundary. The
Windows package is still a preview until it passes the real-machine package
gate; first-run setup and an installer follow afterward.

## Visual direction

The default couch UI should use a dark, cool living-room palette: deep navy/charcoal surfaces, cool blue focus and selection states, bright readable text, and a restrained LIVE indicator. This intentionally feels at home when launched from SteamOS while remaining visually distinct ChannelOS branding rather than a copy of Steam's interface.

Themes may be added later. Accessibility, television readability, and unmistakable focus states matter more than decorative fidelity to any platform.

## Development quick start

Requires Python 3.11+.

```bash
python -m pip install -e ".[dev]"
channelos validate examples/channels/sci-fi.yaml
pytest
```

On Windows, the couch UI automatically discovers an Xbox-compatible XInput
controller; no extra Python package is required. Steam Input can expose other
supported controllers through its normal gamepad/XInput emulation. Keyboard
controls remain available, and controller discovery can be disabled for
diagnosis with `CHANNELOS_DISABLE_CONTROLLER=1`. See
**[Controller input](docs/CONTROL_INPUT.md)** for the complete layout and honest
platform limits.

Scan a real local folder without moving its files:

```bash
channelos scan "D:\Media" --db ".channelos\library.db"
channelos library --db ".channelos\library.db"
```

Persistent scheduling requires real durations. `ffprobe` is used when available for duration/container/stream information. Use `--require-probe` when preparing a media set for the Broadcast Clock.

For source-tree playback development:

```bash
python -m pip install -e ".[playback]"
```

The development runtime can use a compatible system libVLC, a bundled `runtime/vlc` layout, or `CHANNELOS_VLC_DIR` where supported. The eventual user-facing package should hide this setup.

Inspect one persistent channel without launching a decoder:

```bash
channelos broadcast my-channel.yaml \
  --db ".channelos/library.db" \
  --state-db ".channelos/runtime.db"
```

Run the current multi-channel engineering harness:

```bash
channelos tv channel-7.yaml channel-12.yaml \
  --db ".channelos/library.db" \
  --state-db ".channelos/runtime.db"
```

The console accepts the control-intent vocabulary that future UI and remotes will use:

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
2. **[Implementation Status — current reality](docs/IMPLEMENTATION_STATUS.md)**
3. [Persistent Channel Runtime — completed Phase 1](docs/PERSISTENT_CHANNEL_RUNTIME.md)
4. [First Broadcast — completed Phase 0](docs/FIRST_BROADCAST.md)
5. [Architecture](docs/ARCHITECTURE.md)
6. [Roadmap](docs/ROADMAP.md)
7. [Product vision](docs/VISION.md)
8. [Channel format specification](docs/specs/CHANNEL_FORMAT.md)
9. [ADR-0001: Local-first portable core](docs/decisions/0001-local-first-portable-core.md)
10. [ADR-0002: Media identity and playback](docs/decisions/0002-media-identity-and-playback.md)
11. [ADR-0003: Persistent channel clocks](docs/decisions/0003-persistent-channel-clocks.md)
12. [ADR-0004: Distribution and appliance neutrality](docs/decisions/0004-distribution-and-appliance-neutrality.md)

## North Star

Every major feature should answer five questions:

1. Does this increase the user's control over their media?
2. Does it still work if ChannelOS loses internet access?
3. Can the user understand what the system did?
4. Can the user export or migrate the result?
5. Does it make television easier to use from a couch?

## License

ChannelOS is open-source software licensed under the [Mozilla Public License
2.0](LICENSE.md). Copyright (c) 2026 William Robert Adams.

Third-party components keep their own licenses. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the current development
inventory, [`ACKNOWLEDGMENTS.md`](ACKNOWLEDGMENTS.md) for thanks, and
[`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) for the rules and remaining audit
required before publishing a packaged release.

---

**The user is not the audience of ChannelOS. The user is the broadcaster.**
