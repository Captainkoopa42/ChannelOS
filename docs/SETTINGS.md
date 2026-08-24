# ChannelOS Settings

**Status:** First persistent couch-settings slice implemented; Windows validation pending

ChannelOS Settings is intentionally small. The first slice exposes preferences
that already correspond to real couch behavior instead of filling the screen
with future placeholders.

## Current preferences

| Preference | Default | Choices / behavior |
| --- | ---: | --- |
| Volume | 100% | 0-100% in 5% steps |
| Muted | Off | On / Off |
| Skip Back | 10 seconds | 5, 10, 15, or 30 seconds |
| Skip Forward | 30 seconds | 15, 30, 60, or 90 seconds |

Volume and mute changes apply to the active Live TV or On Demand session and
become the next-launch defaults. Skip choices apply to both television and On
Demand transport intents.

The Settings screen supports mouse, keyboard, D-pad, and future adapters that
emit the same ChannelOS control intents:

```text
Up / Down       Select a setting
Left / Right    Change the selected setting
Enter           Advance/toggle, or confirm Reset Defaults
Escape / H      Return Home
S               Open Settings outside an active text editor
```

## Persistence and safety

Preferences are stored locally at:

```text
.channelos/settings.json
```

The file is separate from both `library.db` and `runtime.db`. Changing or
resetting preferences does not edit the media index, watch history, Viewer
Clocks, Broadcast Clocks, or channel definitions.

Writes use a temporary file followed by an atomic replacement. A missing,
damaged, or invalid file falls back to the conservative defaults listed above.
Reset Defaults rewrites only this settings file.

## Deliberate limits

This is not yet a complete configuration center. Controller bindings, themes,
accessibility options, playback-runtime selection, profiles, server/remote
permissions, and startup/crash-recovery controls remain later work. They should
be added only when the corresponding behavior is real.
