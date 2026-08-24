# ADR-0004: Steam-first distribution without platform lock-in

**Status:** Accepted as product direction  
**Date:** 2026-08-19

## Context

ChannelOS is intended to become both an ordinary installable application and software capable of turning a small PC into a dedicated television appliance.

The project also needs a realistic public launch path. Steam and SteamOS are unusually well aligned with ChannelOS's couch-first goals: PC-class hardware, living-room launch behavior, controller input, application installation, and updates are already familiar to the target audience.

At the same time, making Steam authoritative for ChannelOS would conflict with the local-first ownership contract. ChannelOS must remain useful if Steam is absent, unavailable, or simply unwanted by the user.

## Decision

### Primary launch target

Steam is the preferred primary public launch/discovery channel, subject to Valve accepting the application for distribution and the project satisfying all release and licensing requirements.

If distributed through Steam, the intended ChannelOS listing is free to users.

SteamOS and Steam Machine-class living-room PCs are first-class reference targets for couch deployment.

### Steam is distribution, not architecture

ChannelOS will not require Steam for its core runtime, media index, scheduling, Guide generation, playback, profiles, or export/import.

A standalone installation must not require a Steam account, Steam entitlement check, or Steam client to authorize ordinary local use.

The core architecture remains:

```text
ChannelOS Core
    |
    +-- standalone Windows/Linux application
    +-- Steam / SteamOS package
    `-- dedicated appliance image
```

The same user-owned media, channel definitions, runtime model, and control intents should survive across these deployment forms.

### Dedicated appliance mode

ChannelOS does not need a custom kernel to behave as a dedicated device.

A future appliance image may use a minimal Linux base for drivers, filesystems, networking, GPU/video support, USB, Bluetooth, and HDMI, then boot directly into the ChannelOS full-screen shell.

Conceptually:

```text
power on
   |
minimal host OS
   |
ChannelOS service/runtime
   |
full-screen ChannelOS UI
```

The user should not need to interact with a desktop during ordinary appliance use.

### Playback runtime packaging

Development builds may use a compatible system libVLC or an explicit development override.

Finished application packages should include the compatible native playback runtime they require where licensing permits, rather than requiring ordinary users to find or install VLC into a particular path. The `PlaybackBackend` abstraction remains the architectural boundary.

Third-party runtime licenses and notices must be reviewed before public packaging.

### Visual integration

The default couch interface may use a dark navy/charcoal and cool-blue visual family that feels natural when launched from SteamOS. ChannelOS must retain its own branding, focus language, and identity rather than reproducing Steam's interface or marks.

Visual styling is themeable presentation, not a platform dependency.

### Open-source release gate

ChannelOS source is licensed under the Mozilla Public License 2.0. Public
packaging remains gated on the frozen dependency bill of materials,
third-party notice/source obligations, and the verification rules in
`docs/DISTRIBUTION.md`.

## Consequences

### Positive

- ChannelOS gains a strong living-room-oriented launch target without designing around a locked console platform.
- Steam can provide discovery, installation, updates, and controller-friendly launching while ChannelOS retains ownership of its actual television behavior.
- Standalone and appliance users are not second-class users.
- SteamOS compatibility naturally pressures the UI toward couch-first input and fullscreen reliability.
- The same software core can move from desktop testing to a dedicated box without a platform rewrite.

### Costs

- Packaging must be tested independently on Steam/SteamOS and standalone Windows/Linux paths.
- The project must maintain a clean separation between optional platform integration and core functionality.
- Public release requires explicit license selection and dependency compliance work.
- Appliance images add host-OS integration, update, recovery, and hardware-compatibility work later in the roadmap.

## Rejected alternatives

### Make ChannelOS Steam-only

Rejected because platform entitlement would become a dependency and contradict local-first portability.

### Build a custom operating-system kernel

Rejected because ChannelOS's product value is the television system, not reimplementing general-purpose hardware support. A minimal existing OS can provide the substrate for appliance mode.

### Require users to install VLC separately forever

Rejected as a finished-product experience. System libVLC remains useful for development, but packaged releases should own their compatible runtime dependencies.

## Invariant

> **Steam may be where many users get ChannelOS. Steam must never be what makes ChannelOS theirs.**
