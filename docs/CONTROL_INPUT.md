# ChannelOS Control-Intent Boundary

**Status:** SDL2 and XInput controller backends, remappable buttons and keys, and
an on-screen keyboard implemented; real-machine validation per controller family
pending

ChannelOS does not attach television behavior directly to a keyboard,
controller, USB remote, transport, or storefront.

The current path is:

```text
physical input
    -> device/transport adapter
    -> ControlCommand(ControlIntent, optional value)
    -> couch intent router
    -> ChannelOS controller/runtime behavior for the active screen
```

The canonical vocabulary lives in `src/channelos/control.py`. Keyboard and
consumer-key translation lives in `src/channelos/couch_qt.py`; normalized
gamepad translation and the dependency-free Windows XInput backend live in
`src/channelos/controller_input.py`. Both feed the same screen-aware router.

## Why the split matters

`UP` means moving the Home selection on Home, moving between Guide rows in the
Guide, and changing channel while watching Live TV. A device adapter reports
`UP`; ChannelOS decides what it means from the current application state.

The same rule applies to `SELECT`, `BACK`, `PLAY_PAUSE`, `CHANNEL_UP`, `GUIDE`,
`HOME`, and every other command. Controller support therefore does not create a
second set of television rules.

## Controller backends

ChannelOS reads controllers through **SDL2** (PySDL2 plus SDL2.dll on Windows)
when it is available, and falls back to the Windows **XInput** API otherwise.
SDL's community controller database maps hundreds of pads to one *positional*
layout: Xbox, PlayStation (DualShock and DualSense), Switch Pro and Joy-Con
pairs, Steam Deck, GameCube and N64 adapters, 8BitDo and other retro pads, and
generic USB gamepads. Buttons are read by position, never by the letter printed
on them, so Nintendo's A (the east button) is "east" like Xbox's B. One binding
table therefore fits every brand.

`CHANNELOS_CONTROLLER_BACKEND=xinput` forces the XInput path for diagnosis.
If SDL can't load, controllers still work through XInput (Xbox-compatible pads).

ChannelOS polls the active controller at approximately 60 Hz. When no
controller is present, discovery backs off to one check every 1.5 seconds so
idle systems do not continuously scan empty controller slots. The most recently
active XInput slot is checked first. A newly connected controller is primed
with its current state: buttons or sticks already held during connection must
be released before they can trigger an action.

Polling and dispatch are focus-aware. While ChannelOS is not the active
application, the Qt bridge suspends XInput reads and forgets held-input state.
On focus return it primes a fresh controller sample before dispatch resumes, so
using the same controller in a game or another application cannot also move the
ChannelOS interface in the background.

Only the first available controller controls the couch UI.
Disconnecting it does not interrupt playback or keyboard control. The optional
adapter can be disabled for diagnosis before launch:

```powershell
$env:CHANNELOS_DISABLE_CONTROLLER = "1"
```

Remove that environment variable, or set it to `0`, to enable discovery again.
The normal user-facing **Controller Input** switch in Settings persists the same
choice without requiring an environment variable. Keyboard and mouse controls
remain available when the switch is off.

## Default gamepad layout

| Controller control | ChannelOS intent | Ordinary meaning |
| --- | --- | --- |
| D-pad or left stick | `UP / DOWN / LEFT / RIGHT` | Navigate the active screen |
| A / South | `SELECT` | Open, select, or play/pause in video |
| B / East | `BACK` | Close the current layer or go back |
| X / West | `PLAY_PAUSE` | Play or pause Live / On Demand |
| Y / North | `INFO` | Open or close contextual Info |
| View / Back | `GUIDE` | Open the Guide |
| Menu / Start | `HOME` | Open Home |
| Left / Right bumper | `CHANNEL_DOWN / CHANNEL_UP` | Change live channel |
| Left / Right trigger | `SKIP_BACK / SKIP_FORWARD` | Seek by the configured distance; one day back / ahead in the Guide |
| Left-stick click | `GO_LIVE` | Return the Viewer Clock to live |
| Right-stick click | `PREVIOUS_CHANNEL` | Return to the previous channel |
| Right stick up / down | `VOLUME_UP / VOLUME_DOWN` | Adjust volume with held repeat |

Navigation sticks use press/release hysteresis and a deliberate held-repeat
delay. This avoids drift near the deadzone while retaining responsive shelf and
Guide browsing. D-pad and stick input that request the same direction in one
sample are de-duplicated.

The Live and On Demand HUD legends switch to controller names while a gamepad
is connected. Their trigger labels read the current persisted Skip Back and
Skip Forward values (for example, `LT -15s` and `RT +60s`) instead of showing
the defaults after the viewer changes Settings. Disconnecting the controller
restores the keyboard legend with the same live values.

The content-first Library receives controller navigation through its own shelf
overlay, so the D-pad/left stick browse shelves and cards rather than the old
flat-list model. The existing Channel Builder can be browsed and opened with a
controller; text editing still deliberately belongs to keyboard/mouse (or a
future on-screen keyboard).

## Steam Input compatibility

Steam Input's legacy/gamepad emulation can present supported controllers to a
Windows application as an Xbox/XInput controller. That means a PlayStation,
Nintendo, Steam, or other Steam-supported controller can use the native
ChannelOS layout when Steam is configured to emit normal gamepad/XInput input.
ChannelOS does not require a Steam account, Steam entitlement, or Steamworks
integration to run.

This is compatibility through the stable device boundary, not a claim that the
full Steam Input API is integrated. Official action sets, per-controller glyphs,
Steam-published configurations, and direct Steam Input API support can be
considered later if ChannelOS receives an application ID and those features add
real value. The standalone build must continue to work without Steam.

On SteamOS/Linux, Steam's legacy keyboard mapping can already target the
existing keyboard bindings. Native Linux gamepad discovery and real-machine
SteamOS validation remain explicit follow-up work; this Windows XInput slice
does not pretend they are finished.

## Keyboard and media-key adapter

Existing keyboard behavior remains available:

- arrow keys -> `UP`, `DOWN`, `LEFT`, `RIGHT`,
- Enter/Return/Space -> `SELECT`,
- Escape/consumer Back -> `BACK` (Backspace only edits text, so typing never leaves a screen),
- digits -> `DIGIT 0` through `DIGIT 9`,
- `G` or a consumer Guide key -> `GUIDE` (inside the Guide: back to now),
- Home -> `GUIDE_NOW`,
- Page Up / Page Down and media rewind / fast-forward -> `REWIND` / `FAST_FORWARD`
  (3 hours in the Guide),
- `,` / `.` -> `SKIP_BACK` / `SKIP_FORWARD` (one day in the Guide),
- `H` -> `HOME`,
- `I` or a consumer Info key -> `INFO`,
- `S` or a consumer Settings key -> `SETTINGS`,
- `+`, `-`, `M`, and multimedia volume keys -> volume intents,
- multimedia play/pause keys -> explicit transport intents,
- consumer Channel Up/Down keys -> channel intents,
- `L` -> `GO_LIVE`,
- `P` -> `PREVIOUS_CHANNEL`.

## Remapping, layouts and couch typing

**Settings → Controller** holds the controls (see [SETTINGS.md](SETTINGS.md)):

- **Button Mapper:** draws the controller family and lets every button, both
  triggers, the stick clicks, the right-stick directions, paddles and the
  touchpad do any action. *Find a Button* jumps to whatever you press. While
  the mapper is open the controller navigates with the default layout, and the
  left stick always navigates everywhere, so a remap can never strand anyone.
- **Controller Layout:** Automatic picks the drawing from SDL's controller type
  and name (`controller_layouts.detect_family`); any family can be chosen
  instead. Families: Xbox, PlayStation, Nintendo Switch, GameCube, N64, SNES,
  NES, Genesis/Mega Drive, Dreamcast, Atari joystick, Steam Deck/Controller and
  Generic.
- **Keyboard Mapper:** give any key any action. Esc is always Back and 0–9
  always tune channels. Media keys are listed too.
- **Dedicated Controller Mode:** selecting a text box (Select on a focused box,
  or a click) opens the on-screen keyboard. It types into that box without
  taking focus, so a real keyboard keeps working. A types, X deletes, Y adds a
  space, LB/RB move the cursor, and Back or Done closes it.

Bindings are saved in `settings.json` as changes from the defaults
(`controller_bindings`, `key_bindings`), so a portable setup keeps them.

Backspace is not Back: it only edits text, so typing can never leave a screen.

## Behavioral rules

- Device adapters translate physical signals only.
- Screen-specific meaning belongs to the ChannelOS router.
- Runtime television actions pass through the existing controller/runtime
  boundaries.
- Text-entry and management overlays may retain local focus handling so normal
  typing is not stolen by global single-letter shortcuts.
- Explicit `PLAY` and `PAUSE` are idempotent; `PLAY_PAUSE` toggles.
- Opening Home or Guide from On Demand first checkpoints/stops the On Demand
  session so persistent resume state remains truthful.
- Unknown physical inputs are ignored rather than guessed.
- Controller failure is optional and isolated: it must never prevent keyboard
  launch or media playback.

## Honest limitations and next input work

This slice does not yet claim:

- Windows real-machine validation with Xbox and Steam-emulated controllers,
- native Linux/SteamOS gamepad discovery,
- multiple simultaneous couch controllers,
- vibration/rumble,
- the future local phone/web remote transport,
- an external IPC/control-intent protocol.

The next gate is real hardware on Windows, including connect-at-start,
hot-plug, unplug/replug, Library/Guide navigation, playback controls, and a
Steam Input-emulated controller. After that passes, the Windows slice can merge
without making SteamOS claims it has not earned.
