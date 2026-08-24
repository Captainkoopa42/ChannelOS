# WIP — Home boot video presentation

Branch: `agent/library-content-first`

## Why this checkpoint exists

The merged television-aware Home/Guide work is stable when a channel has already been entered, but the Home live preview still has a Windows-native startup presentation issue when ChannelOS launches directly into Home.

This WIP checkpoint intentionally preserves the investigation on a non-main branch before the content-first Library work begins.

## Confirmed working

- ChannelOS launches to Home.
- The remembered/current television state is restored.
- Home metadata correctly shows the remembered channel and Viewer Clock.
- Guide live preview positioning works.
- Home live preview positioning works after television playback has already been established.
- libVLC uses the existing single native video surface.
- D3D11VA hardware decoding is active on the tested Windows machine.
- The full automated test suite was green before this checkpoint.
- Local `test-channel-*.yaml` files remain untracked and are not part of this branch.

## Current bug

On a fresh application launch, before entering Live, the Home preview does not reliably paint the actual video.

Observed progression:

1. Initial startup behavior: Home preview remained blank even though remembered channel metadata was correct.
2. After making the Home native `WindowContainer` visible from remembered/default television state before startup playback, the preview stopped being blank but could display stale desktop/backbuffer contents instead of the decoded movie.
3. libVLC logs still showed D3D11VA decoding, so television state and decoder startup were occurring; the unresolved problem is native Windows presentation timing/realization at application boot.

## Current hypothesis

The embedded native `QWindow`/`WindowContainer` exists and is visible, but startup playback may still begin before Windows/Qt has fully realized the native child for D3D11 presentation.

The fixed 500 ms delay was useful as an isolation step, but it still guessed when the native child was ready. The current branch now uses a bounded readiness gate instead:

1. show the QML host window,
2. wait for the host and embedded video window to be visible, exposed, and non-zero in size,
3. require that state to remain stable across three checks,
4. only then request the native handle, attach libVLC, and start Home playback,
5. make one diagnosed fallback attempt after five seconds rather than waiting forever.

The PowerShell output carries `[ChannelOS Home video]` messages so the exact startup state can be reported from the Windows test machine.

## First Windows readiness-gate test

The first real-machine run still showed stale desktop/backbuffer contents and no
`[ChannelOS Home video]` diagnostics. That combination exposed the actual
integration gap: `channelos.couch` launches `broadcaster_qt.run_qt()`, while the
startup experiment had only been installed in the narrower
`couch_qt.run_qt()` path.

The active Broadcaster-integrated launcher attached the native surface before
showing the host window and never called `startHomePlayback()` at application
startup. The readiness implementation is now a shared helper invoked by both Qt
launch paths, and a regression test follows the real `channelos.couch` import to
verify that the active launcher retains the gate.

This is a presentation/startup timing experiment, not a redesign of the television runtime.

## Architecture that must remain intact

- One authoritative television runtime.
- Broadcast Clock belongs to the channel.
- Viewer Clock belongs to the viewer.
- One persistent native libVLC playback surface.
- No second decoder for Home or Guide previews.
- No manual HWND reparenting workaround.
- Home navigation itself must not retune television.
- Unassigned Channel 001 remains presentation-only and must not become a fake runtime channel.

## Separate warning

The recurring QML warning:

`BroadcasterScreen.qml:763:41: Unable to assign [undefined] to QString`

is being tracked separately. It is not believed to be the cause of the Home boot video presentation issue.

## Next work after this bug

Once Home boot video presentation is stable:

1. Content-first Library / On Demand visual pass.
2. Artwork / thumbnail pipeline.
3. Persistent On Demand resume / Continue Watching.
4. Finish remaining Home features.
5. Settings last.
