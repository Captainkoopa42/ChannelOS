# ChannelOS Control-Intent Boundary

**Status:** Native Windows couch-controller adapter implemented; real-machine
controller validation pending

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

## Native Windows controller support

The couch launcher now discovers and hot-plugs Xbox-compatible controllers
through the XInput API already supplied by Windows. No controller package,
driver, Steamworks SDK, native DLL, or new Python dependency is bundled by this
feature.

ChannelOS polls the active controller at approximately 60 Hz. When no
controller is present, discovery backs off to one check every 1.5 seconds so
idle systems do not continuously scan empty controller slots. The most recently
active XInput slot is checked first. A newly connected controller is primed
with its current state: buttons or sticks already held during connection must
be released before they can trigger an action.

Only the first available XInput controller controls the couch UI in this slice.
Disconnecting it does not interrupt playback or keyboard control. The optional
adapter can be disabled for diagnosis before launch:

```powershell
$env:CHANNELOS_DISABLE_CONTROLLER = "1"
```

Remove that environment variable, or set it to `0`, to enable discovery again.

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
| Left / Right trigger | `SKIP_BACK / SKIP_FORWARD` | Seek by the configured distance |
| Left-stick click | `GO_LIVE` | Return the Viewer Clock to live |
| Right-stick click | `PREVIOUS_CHANNEL` | Return to the previous channel |
| Right stick up / down | `VOLUME_UP / VOLUME_DOWN` | Adjust volume with held repeat |

Navigation sticks use press/release hysteresis and a deliberate held-repeat
delay. This avoids drift near the deadzone while retaining responsive shelf and
Guide browsing. D-pad and stick input that request the same direction in one
sample are de-duplicated.

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
- Escape/Backspace/consumer Back -> `BACK`,
- digits -> `DIGIT 0` through `DIGIT 9`,
- `G` or a consumer Guide key -> `GUIDE`,
- `H` -> `HOME`,
- `I` or a consumer Info key -> `INFO`,
- `S` or a consumer Settings key -> `SETTINGS`,
- `+`, `-`, `M`, and multimedia volume keys -> volume intents,
- multimedia play/pause keys -> explicit transport intents,
- consumer Channel Up/Down keys -> channel intents,
- `L` -> `GO_LIVE`,
- `P` -> `PREVIOUS_CHANNEL`.

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
- user-editable bindings or controller glyph switching,
- vibration/rumble,
- an on-screen text keyboard,
- the future local phone/web remote transport,
- an external IPC/control-intent protocol.

The next gate is real hardware on Windows, including connect-at-start,
hot-plug, unplug/replug, Library/Guide navigation, playback controls, and a
Steam Input-emulated controller. After that passes, the Windows slice can merge
without making SteamOS claims it has not earned.
