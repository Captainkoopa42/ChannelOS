# ChannelOS Settings

**Status:** Expanded Settings, performance profiles, and selectable libVLC audio
output implemented; Windows device-switch validation pending on the feature branch

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
| Audio Output | System Default | Any destination currently exposed by libVLC, such as speakers or headphones |
| Volume | 100% | 0-100% in 5% steps |
| Muted | Off | On / Off |
| Skip Back | 10 seconds | 5, 10, 15, or 30 seconds |
| Skip Forward | 30 seconds | 15, 30, 60, or 90 seconds |
| Controller Input | On | On / Off; input is always suspended while another application has focus |

Audio Output, volume, and mute changes apply to both Live TV and On Demand and
become the next-launch defaults. A choice is remembered even when that decoder
has not been created yet. System Default deliberately returns routing to the
operating system. Before the first media load, ChannelOS validates a saved
destination against the outputs currently exposed by libVLC. A disconnected
device falls back to System Default and that safe choice is persisted.
Skip choices apply to both television and On Demand control intents.

Controller Input is a persistent master switch for ChannelOS gamepad polling.
When enabled, controller commands are accepted only while ChannelOS is the
active application. Losing focus clears held-button state; returning to
ChannelOS primes the current state so a button held in another application
cannot trigger a delayed action. Keyboard and mouse input remain available when
controller input is off, including for turning it back on.

## Truthful presentation

The persisted Settings snapshot is the source for both behavior and visible
values. The Settings rows update immediately, the volume/mute HUD mirrors the
effective audio state, Library performance behavior follows the active profile,
and the Live/On Demand control legend shows the configured skip distances.

When a controller is connected those playback hints use the controller labels
(`LT`, `RT`, bumpers, stick clicks, and face buttons). Without a controller they
use the equivalent keyboard labels. The displayed skip distances come from the
same values used by the actual seek command, so changing 10 seconds to 15
seconds cannot leave a stale `-10s` label behind.

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

The same control-intent boundary supports mouse, keyboard, D-pad, and the
optional native Windows XInput controller adapter.

## Persistence

Preferences are stored locally at:

```text
.channelos/settings.json
```

Writes use a temporary file followed by atomic replacement. Existing alpha
settings files without an audio-device field migrate to System Default. A
missing, damaged, or invalid file falls back safely to Standard defaults. Reset
Defaults rewrites only this settings file, reapplies Standard mode, and restores
System Default audio routing.

## Deliberate limits

User-editable controller bindings, a light-color theme, audio-channel mapping,
playback-runtime selection, server/remote permissions, and startup/crash-recovery
controls remain later work. Household viewer profiles are a separate roadmap
feature.

## Release candidate validation

Settings remain separate from channel/ad policy. In 0.0.6, leaving playback for
Settings cancels pending numeric tuning. An unavailable lineup can still reach
Library, Broadcaster and Settings. Physical speaker/headphone and controller
checks are recorded separately in [Windows acceptance](releases/WINDOWS_0.0.6_ACCEPTANCE.md).


## Tabs

Settings has three tabs, chosen in the sidebar or with Page Up / Page Down,
the controller shoulder buttons or triggers (they wrap around):

- **General**: display mode, performance profile, reduced motion, controller
  input, skip distances, artwork generation and cache, diagnostic logs, reset.
- **Video & Audio**: audio output, volume, mute, and every picture setting.
- **Extras**: theme, Theme Builder, and Portable Setup & Backup.

Rows are keyed by name in `SettingsScreen.qml`, which also owns keyboard and
controller navigation for this screen.

## Video

Picture settings apply to Live TV, On Demand and the Home preview, and save with
the other preferences.

| Setting | Choices | Notes |
| --- | --- | --- |
| Aspect Ratio | Auto, 16:9, 4:3, 21:9, 2.35:1, 1.85:1, 16:10, 5:4, 1:1 | Auto uses each video's own shape; force one for mislabeled recordings |
| Picture Fit | Fit, Fill, Stretch | Fit letterboxes, Fill crops edges to the screen's shape, Stretch distorts to fill |
| Overscan Trim | Off, 2, 4, 6, 8 % | Trims every edge, for VHS and broadcast captures |
| Deinterlace | Auto, Off, Yadif, Yadif 2x, Bob, Blend, Linear | From the next program |
| Hardware Decoding | Auto (GPU), Off (CPU) | From the next program; turn off for driver artifacts |
| Brightness / Contrast / Color Saturation | 50-150 % | Stack with channel fades |

Fill and Stretch follow the video window's size. Crops wait until the decoder
reports the source size, then apply without restarting the program. Unknown or
hand-edited values fall back to the defaults.

## Theme and Theme Builder

`Theme` switches the whole interface look: ChannelOS, ChromeSpace, and any
theme you build.

**Theme Builder** (Settings → Theme Builder) creates your own themes:

- **Colors.** Twelve roles: background, panels, buttons and cards, borders,
  text, secondary text, accent, highlight and focus, selection, live and
  alerts, success, and warning. Each has a color picker (hue, color and light
  sliders plus a swatch board) or a hex field. Every screen derives from these
  roles, so a light or dark set of roles both work. Text on accent fills and on
  selections automatically switches to whichever color reads best.
- **Wallpaper.** Choose any PNG, JPEG, WebP, BMP or GIF. It is copied into the
  setup's `themes/images` folder, so it travels with a portable drive. Fit it
  as fill, fit, tile or center, and set image opacity. Panel opacity (40–100 %)
  lets the wallpaper show through the panels, MySpace-style.
- **Live preview.** The whole app shows the draft while you edit. Closing
  without saving puts your current theme back.
- **Save** keeps the theme; **Save & Use** also switches to it. Built-in themes
  are never changed: editing one saves your own copy. Deleting the theme in use
  returns to ChannelOS.

On-screen displays drawn over video keep the dark broadcast style in every
theme, so they stay readable on any picture.

## Startup

Settings → Extras controls what you see while ChannelOS starts.

- **Boot Video**: *TV Static* (the first-boot default), *My Video*, or *Off*.
  The video plays on every launch while the setup opens behind it, so it never
  adds waiting time. Any key, click or tap skips it. If the setup is ready first,
  the video still plays to its end (or until skipped); if the video ends first,
  the loading style takes over. Videos are capped at two minutes on screen.
- **My Boot Video**: choose any video VLC plays (MP4, MKV, WebM, MOV, ...; up to
  500 MB). It is copied into the setup's `boot` folder, so it travels with a
  portable drive. A missing or unplayable file falls back to TV Static.
- **Boot Video Sound**: play it with or without sound.
- **Loading Style**: *Classic* (wordmark and progress line), *Fill Bar* (a
  full-width bar along the bottom with a percentage), or *Dancing TV* (the app
  icon hops to a beat, its antennas spring, the power light blinks, and the
  guide rows on its screen light up as startup progresses). Reduced Motion
  shows the fill bar instead of the dancing TV.
- **Preview Startup** runs the chosen style through a full boot without
  restarting.

Progress is real: opening the setup, then the first channel, then the rest of
the lineup. The loading screen stays up in the main window until the first
channel is ready, then fades into Home.
