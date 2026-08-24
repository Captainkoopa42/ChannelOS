# ChannelOS Control-Intent Boundary

**Status:** First transport-neutral couch input slice implemented

ChannelOS does not attach television behavior directly to a particular
keyboard, controller, USB remote, transport, or storefront.

The current path is:

```text
physical input
    -> device/transport adapter
    -> ControlCommand(ControlIntent, optional value)
    -> couch intent router
    -> ChannelOS controller/runtime behavior for the active screen
```

The canonical Python vocabulary lives in `src/channelos/control.py`. The Qt
keyboard adapter and screen-aware router currently live in
`src/channelos/couch_qt.py`.

## Why the split matters

`UP` means moving the Home selection on Home, moving between Guide rows in the
Guide, and changing channel while watching Live TV. The physical device should
not contain those rules. It reports `UP`; ChannelOS interprets it using current
application state.

The same is true for `SELECT`, `BACK`, `PLAY_PAUSE`, `CHANNEL_UP`, `GUIDE`,
`HOME`, and the rest of the control vocabulary.

## Current inputs

The first adapter preserves all existing keyboard behavior and additionally
recognizes Qt multimedia/consumer keys when the operating system exposes them:

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

Steam Input or controller software can already map a controller to these
keyboard/media inputs without putting ChannelOS behavior into the mapping.

## Current boundary and honest limitations

This slice implements the shared intent model, Qt keyboard/media/consumer-key
adapter, and screen-aware dispatch. It does **not** yet claim:

- native SDL/XInput controller discovery,
- analog-stick or trigger handling,
- user-editable bindings,
- controller hot-plug UI,
- SteamOS/controller real-machine validation,
- the future local phone/web remote transport,
- an external IPC/control-intent protocol.

Those adapters should create the same `ControlCommand` objects and call the same
router. They must not duplicate channel, Guide, On Demand, or navigation rules.

## Behavioral rules

- Device adapters translate physical signals only.
- Screen-specific meaning belongs to the ChannelOS router.
- Runtime television actions still pass through the existing controller/runtime
  boundaries.
- Text-entry and management overlays may retain local focus handling so normal
  typing is not stolen by global single-letter shortcuts.
- Explicit `PLAY` and `PAUSE` are idempotent; `PLAY_PAUSE` toggles.
- Opening Home or Guide from On Demand first checkpoints/stops the On Demand
  session so persistent resume state remains truthful.
- Unknown physical inputs are ignored instead of guessed.

## Next input work

1. Wire every Home destination to a real surface using these intents.
2. Add Settings and persistent binding/preferences storage.
3. Choose a native gamepad adapter boundary without making it authoritative.
4. Validate Xbox/Steam-style controller behavior on Windows and SteamOS.
5. Expose the same intent vocabulary through a local, permission-aware IPC
   boundary for future phone and physical remotes.
