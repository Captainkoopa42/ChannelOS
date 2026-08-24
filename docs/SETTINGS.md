# ChannelOS Settings

**Status:** Expanded Settings and performance profiles implemented; Windows
validation pending on the feature branch

ChannelOS stores couch preferences in a small local JSON file. Settings do not
edit the media index, watch history, channel definitions, or television clocks.

## Performance profiles

The profile selector provides safe starting points. These are machine-performance
profiles, not household viewer profiles and not a light-color theme.

| Profile | Generated thumbnails | Cache limit | Generate during playback | Motion |
| --- | --- | ---: | --- | --- |
| Standard | On | Unlimited | On | Normal |
| Lightweight | Off | 256 MB | Off | Reduced |
| Custom | User choices | User choice | User choice | User choice |

Standard deliberately preserves ChannelOS behavior from before performance
profiles existed. Existing `settings.json` files therefore load as Standard.

Lightweight reduces optional presentation work for less powerful machines. It
does **not** lower video quality, alter schedules, change playback accuracy, or
remove media. Local sidecar images and already cached thumbnails still display.
When neither is available, the existing format-card fallback remains visible.

Changing an individual performance control switches the label to Custom. The
available generated-art cache limits are Unlimited, 128 MB, 256 MB, 512 MB,
1 GB, and 2 GB. Applying a smaller limit removes the oldest generated
thumbnails until the cache fits.

## Couch and playback preferences

| Preference | Default | Choices / behavior |
| --- | ---: | --- |
| Volume | 100% | 0-100% in 5% steps |
| Muted | Off | On / Off |
| Skip Back | 10 seconds | 5, 10, 15, or 30 seconds |
| Skip Forward | 30 seconds | 15, 30, 60, or 90 seconds |

Volume and mute changes apply to the active Live TV or On Demand session and
become the next-launch defaults. Skip choices apply to both television and On
Demand control intents.

## Generated artwork safety

The Settings screen reports generated-thumbnail count and size. **Clear
Generated Artwork** deletes only JPEG files created by ChannelOS in its artwork
cache. It never deletes:

- original media,
- exact-title sidecar images,
- `poster`, `cover`, `folder`, `fanart`, `thumb`, or `thumbnail` sidecars,
- Library database records,
- channel or runtime state.

A cache clear invalidates an in-progress thumbnail result so an old FFmpeg job
cannot restore the file after the clear completes.

## Navigation

```text
Up / Down       Select a setting; the list scrolls to keep it visible
Left / Right    Change the selected setting
Enter           Advance/toggle, clear generated art, or reset defaults
Escape / H      Return Home
S               Open Settings outside an active text editor
```

The same control-intent boundary supports mouse, keyboard, D-pad, and future
native controller adapters.

## Persistence

Preferences are stored locally at:

```text
.channelos/settings.json
```

Writes use a temporary file followed by atomic replacement. A missing, damaged,
or invalid file falls back safely to Standard defaults. Reset Defaults rewrites
only this settings file and reapplies Standard mode.

## Deliberate limits

Native controller bindings, a light-color theme, playback-runtime selection,
server/remote permissions, and startup/crash-recovery controls remain later
work. Household viewer profiles are a separate roadmap feature.
