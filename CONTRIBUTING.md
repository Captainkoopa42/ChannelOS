# Contributing to ChannelOS

ChannelOS is pre-alpha. The most important contribution rule is to preserve the project's ownership contract while the implementation is still easy to change.

## Before changing architecture

Read:

1. `docs/MASTER_DESIGN.md`
2. `docs/ARCHITECTURE.md`
3. `docs/ROADMAP.md`
4. `docs/decisions/0001-local-first-portable-core.md`
5. `docs/decisions/0003-persistent-channel-clocks.md`
6. `docs/decisions/0004-distribution-and-appliance-neutrality.md`

Changes that make local playback dependent on a cloud account or distribution-platform entitlement, hide portable configuration in an undocumented format, make user media dependent on the ChannelOS database, or move authoritative scheduling logic into the UI conflict with the project direction.

## Current development focus

Phase 0 and Phase 1 are complete. The current milestone is `docs/GUIDE_AND_UI_BOUNDARY.md`.

The Guide/UI layer should consume stable runtime truth rather than reimplementing channel scheduling. In-process interfaces are acceptable initially, but keep the boundary clean enough to become local API/IPC later.

Steam/SteamOS is a first-class launch target, not a core dependency. New platform integration must not make standalone Windows/Linux or future appliance installs second-class.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

Keep modules small and testable. Prefer explicit deterministic behavior before adding automatic or intelligent scheduling.

For source-tree playback work, use the playback extra and a compatible development libVLC runtime. Finished packaging is expected to carry its compatible native playback runtime where licensing permits rather than requiring end users to configure VLC manually.

## Specs

Changes to the channel-definition format should update the corresponding specification and tests in the same change. Schema changes should be versioned rather than silently changing the meaning of an existing file.

## Release and licensing

ChannelOS is intended to become open source, but the repository does not yet contain a selected open-source license. Do not describe a build as an open-source release until the project owner has deliberately selected and added the license.

Public packaging work must also account for third-party runtime licenses and notices, including any bundled playback components.
