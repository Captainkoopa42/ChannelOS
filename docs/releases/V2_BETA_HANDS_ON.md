# V2 Beta: 30-minute hands-on check

The automated suite (about 740 tests on Python 3.11, 3.12 and 3.13) covers
the scheduling, Guide, ads, Planner and storage logic. It cannot touch a real
decoder, display, controller, speaker or USB drive. This list covers only
those, plus the V2 features most likely to strand a real viewer.

The full routes in `WINDOWS_0.0.6_ACCEPTANCE.md` and
`WINDOWS_0.0.7_ACCEPTANCE.md` stay the reference. This is the short pass to
run on every beta build before sharing it.

**Before you start:** use the packaged ZIP, not the source tree. Copy your
real setup folder somewhere safe first. Have the log folder open
(Settings → General → Diagnostic logs). Note the build commit from
`PACKAGE-BOM.json`.

Mark each line ✅, ❌ (with what happened) or ➖ (skipped).

## 1. First launch (5 min)

| # | Do this | Expect |
|---|---|---|
| 1.1 | Unzip to a fresh folder on a PC with no Python, Qt or VLC installed. Run `ChannelOS.exe`. | Boot screen within a few seconds, then first-run setup. No missing-DLL errors. |
| 1.2 | Add a media folder, make one Sequential channel. | Channel airs right away with picture and sound. |
| 1.3 | Close and reopen. | Same channel, moved on in time. Boot sound plays and any button skips the boot screen. |
| 1.4 | Open a copy of your Beta 1 setup with this build. | Channels, positions and schedules intact; the upgrade notice appears once. |

## 2. Watching TV (5 min)

| # | Do this | Expect |
|---|---|---|
| 2.1 | Channel up/down, type a number, Previous Channel. | Only the chosen channel tunes, with no stale or delayed retune. |
| 2.2 | Pause 1 min, rewind, skip ahead past live, Go Live. | HUD shows behind/ahead correctly; Go Live lands on what's airing. |
| 2.3 | Let a program end. | Next program starts by itself. |
| 2.4 | Guide → pick another channel → watch. | Tunes the picked program. |
| 2.5 | F11 to windowed, maximize, restore, back to fullscreen while playing. | Video never goes black or freezes. |
| 2.6 | Play something On Demand, then back to TV. | TV picks up where its clock says; On Demand resumes later from Continue Watching. |

## 3. Hardware (8 min)

| # | Do this | Expect |
|---|---|---|
| 3.1 | Navigate every screen with a controller only, including a dialog and the on-screen keyboard. | Focus is always visible and never trapped. |
| 3.2 | Unplug the controller mid-use, wait 5 s, replug. | Works again without restarting. |
| 3.3 | Try one non-Xbox pad (PlayStation, Switch Pro or similar) if you have one. | Buttons match the drawing in Button Mapper. Note which pad you tried. |
| 3.4 | Alt-Tab into a game or browser, press controller buttons. | ChannelOS ignores them. |
| 3.5 | Switch speakers to headphones in Settings while a show plays. Restart. | Audio moves immediately and stays on the saved device. |
| 3.6 | Unplug the drive holding one channel's media. | That channel shows "Media unavailable"; others keep playing. Replug and rescan: it returns. |

## 4. Profiles and PIN (5 min)

| # | Do this | Expect |
|---|---|---|
| 4.1 | Set a PIN, give Kids one channel, switch to Kids. | Only that channel; volume capped; Settings asks for the PIN. |
| 4.2 | Enter a wrong PIN six times. | After the sixth: "Try again in 30 seconds". The right PIN also waits until the cooldown ends. |
| 4.3 | Right PIN after the cooldown. | Back to Home. |
| 4.4 | Switch to Lobby, close ChannelOS from the PIN pad, reopen. | Boots straight back into Lobby on its channel. |
| 4.5 | Close ChannelOS. Open `profiles.json`, change one character of `pinSalt` to `z`, save, reopen. | ChannelOS opens on Home, not stuck in Lobby. (Set the PIN again afterwards.) |

## 5. Building and moving (7 min)

| # | Do this | Expect |
|---|---|---|
| 5.1 | Studio: drag two shows onto tomorrow, Auto Fill the rest of the week, Apply. | Guide shows the same thing the Studio preview did. The channel airing now isn't interrupted. |
| 5.2 | Add an ad clip to a channel with ad breaks on. | Ads play at the breaks; Guide/HUD mark them. |
| 5.3 | Library → Add to Channel on one file. | Added without changing that channel's other settings. |
| 5.4 | Copy the whole setup to a USB drive. Open it on another PC or another drive letter. | Channels, schedules, profiles, themes and media paths all work. |
| 5.5 | Close ChannelOS. Open `settings.json` in Notepad, Save As with encoding "UTF-16 LE", reopen ChannelOS. | Opens normally with default settings instead of crashing. |

## If something fails

Write down the steps, what you expected, what happened, the build commit,
and attach `channelos.log` (and `channelos-crash.log` if there is one) from the log
folder. Each background failure now writes its full traceback to the log.
