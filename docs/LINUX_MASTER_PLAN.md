# ChannelOS for Linux Master Plan

**Status:** Living architecture and implementation plan  
**Branch:** `ChannelOS-for-Linux`  
**Product direction:** Native, local-first ChannelOS for Linux desktops and living-room PCs  
**Source baseline:** ChannelOS `d9f8161`  

---

## 1. Purpose

This document defines what is required to make ChannelOS a genuine Linux
application without changing what ChannelOS is.

The Linux edition is not a server, web application, or thin client. It remains
the same offline, user-owned television system as the Windows edition:

- media remains on storage selected by the user;
- channels, schedules, clocks, Guide state, and settings remain local;
- ordinary viewing requires no account or internet connection;
- ChannelOS runs as a visible desktop or living-room application;
- Linux support must not weaken Windows support or fork the product model.

This branch is a platform proving ground. Portable fixes should return to the
shared ChannelOS build once validated rather than becoming Linux-only rewrites.

---

## 2. Definition of success

ChannelOS for Linux is complete enough to share when a nontechnical Linux user
can:

1. install or unpack ChannelOS without assembling a Python environment;
2. launch it from the desktop or Steam without opening a terminal;
3. select one or more local media folders;
4. scan a large library while the interface remains responsive;
5. create and edit channels through the normal ChannelOS interface;
6. open the Guide, tune channels, seek, pause, return to Live, and channel-surf;
7. use an ordinary gamepad without writing a mapping file;
8. restart ChannelOS and retain all channel clocks and state;
9. understand a missing dependency, disconnected drive, or unsupported display
   session from a visible error rather than a silent exit;
10. do all of the above offline after installation.

Launching the QML window once is not a completed Linux port. The playback,
native-window, controller, storage, packaging, licensing, and restart gates all
have to pass.

---

## 3. Current codebase audit

### 3.1 Already substantially portable

The following ChannelOS systems use ordinary Python, Qt, SQLite, YAML, or
provider-neutral contracts and should remain shared:

- media indexing and stable media identity;
- channel YAML parsing and resolution;
- deterministic channel runtimes;
- Broadcast and Viewer Clocks;
- Guide generation and UI-facing models;
- Library and On Demand state;
- Broadcaster and Channel Builder logic;
- QML screens and control intents;
- normalized `GamepadSnapshot` and `GamepadIntentMapper` behavior;
- SQLite schema/version safety;
- artwork discovery and caching;
- tests that do not assert Windows presentation details.

These systems should be ported by fixing their platform edges, not duplicated
under Linux-specific implementations.

### 3.2 Present but unproven on Linux

ChannelOS already contains useful Linux-shaped seams:

- Qt platform detection recognizes `xcb` as `x11`;
- `NativeVideoSurface` accepts `x11`;
- `LibVLCBackend.attach_video_surface()` calls `set_xwindow()`;
- PySide6, python-vlc, pathlib, SQLite, and PyYAML are cross-platform;
- keyboard control works independently of XInput;
- the controller mapper is separated from the Windows controller reader.

These are implementation hints, not proof. None has passed a Linux
real-machine playback gate in the current repository.

### 3.3 Currently Windows-specific

The following work must be replaced or generalized:

- `windows_app.py` owns packaged launch, data directories, first-run handling,
  logging, and visible startup errors;
- the default data path uses `%LOCALAPPDATA%` and an AppData fallback;
- controller discovery is XInput-only;
- bundled libVLC discovery only prepares Windows DLLs and `VLC_PLUGIN_PATH`;
- all packaging tools, specifications, audits, and package CI are Windows-only;
- hardware-decode validation is D3D11VA-specific;
- the current HUD/native-window behavior was validated against Windows DWM;
- documentation and error text frequently assume Windows paths and DLL names.

---

## 4. Supported Linux boundary

### 4.1 First supported architecture

The first packaged target should be 64-bit x86 Linux. ARM64 is valuable for
small living-room systems, but it adds another native Python, Qt, libVLC, and
packaging matrix and should follow the first reliable x86_64 package.

### 4.2 First supported display path

The first native-video target is:

```text
Qt xcb platform -> X11/XWayland window -> libVLC set_xwindow()
```

ChannelOS currently rejects Qt's `wayland` platform because it has no native
Wayland video-surface implementation. The first package may deliberately launch
through `xcb` when XWayland is available, but it must report that choice and
fail clearly when the required display path is unavailable.

Native Wayland is a later milestone. The project must not describe XWayland as
native Wayland support.

### 4.3 Distribution baseline

The build must be produced on Linux; PyInstaller output is platform-specific.
The oldest supported distribution/glibc baseline must be selected through a
package-compatibility experiment rather than assumed from the developer's
machine.

Initial real-machine coverage should include:

- one mainstream desktop distribution using X11;
- one Wayland-default distribution running ChannelOS through XWayland;
- one SteamOS living-room machine or equivalent Steam Deck/Steam Machine class
  system;
- Intel, AMD, and NVIDIA graphics coverage as hardware becomes available.

---

## 5. Target platform architecture

### 5.1 Shared desktop launcher

The Windows launcher should be decomposed into a shared desktop application
layer plus small platform policies:

```text
desktop_app.py
  |- common first-run flow
  |- common argument defaults
  |- common logging and crash boundary
  |- common ChannelOS startup
  |
  `- platform policy
       |- data/state/cache locations
       |- visible error reporting
       |- native runtime preparation
       `- launch integration
```

Linux should add a small `linux_app.py` entry point rather than copy the entire
Windows launcher.

### 5.2 Linux data locations

ChannelOS should follow the XDG Base Directory rules:

| Data | Preferred location |
|---|---|
| databases, channel definitions, durable application data | `$XDG_DATA_HOME/channelos` or `~/.local/share/channelos` |
| logs and other persistent diagnostic state | `$XDG_STATE_HOME/channelos` or `~/.local/state/channelos` |
| regenerable artwork and metadata cache | `$XDG_CACHE_HOME/channelos` or `~/.cache/channelos` |
| settings separated from durable data, when implemented | `$XDG_CONFIG_HOME/channelos` or `~/.config/channelos` |

`CHANNELOS_DATA_DIR` remains the explicit portable/testing override. When it is
set, ChannelOS may keep all writable state beneath that selected root so a user
can intentionally maintain a self-contained installation.

Migration must be transactional and must never silently abandon an existing
database or channel directory.

### 5.3 Visible failures

Linux startup must not depend on a terminal. Before the main QML engine is
available, failures may use a minimal Qt message dialog. After startup, errors
belong in the ChannelOS interface and durable log.

The application must show the log location and a plain-language cause for:

- unavailable libVLC;
- unsupported display platform;
- unreadable database or channel directory;
- missing/disconnected media source;
- package corruption;
- first-run cancellation or failure.

---

## 6. Playback and native video

### 6.1 libVLC discovery

Linux runtime preparation should support, in order:

1. an audited ChannelOS-owned sidecar runtime in the package;
2. `CHANNELOS_VLC_DIR` for development and controlled replacement;
3. a compatible system libVLC for source-tree development;
4. a visible failure with installation guidance.

Discovery must identify the actual shared library and plugin directory used.
Error text must refer to Linux `.so` libraries rather than Windows DLLs.

### 6.2 X11 attachment gate

The existing `QWindow`/`WindowContainer` surface must be exercised with genuine
video. The gate must verify:

- `QGuiApplication.platformName()` is `xcb`;
- `winId()` produces a valid X11 window identifier;
- `set_xwindow()` attaches before playback;
- audio and video both appear in the ChannelOS window;
- the surface survives Guide/Home transitions, maximize, restore, and
  full-screen changes;
- overlays do not hide or detach the native video child;
- playback survives monitor changes and common fractional scaling settings.

### 6.3 Hardware decoding

Hardware acceleration is an optimization, not a prerequisite for schedule
correctness. Linux validation must record:

- decoder and video-output path selected by libVLC;
- CPU/GPU load and dropped frames;
- VA-API or vendor-specific acceleration when available;
- clean software-decoding fallback;
- SDR behavior first, with HDR/color-management claims deferred until measured.

The package must not force one GPU vendor's decoder path globally.

### 6.4 Audio

Default-system audio is sufficient for the first port gate. The requested
ChannelOS audio-output selector should be implemented later through the shared
playback abstraction so Windows, Linux, and macOS receive one product feature
rather than three incompatible settings.

---

## 7. Controller and couch input

The existing `ControllerBackend` protocol and normalized mapper are the correct
boundary. Linux needs a native reader that emits the same `ControllerReading`
records as XInput.

The first engineering spike should compare:

- an SDL gamepad backend shared with macOS;
- a Linux-specific backend only if the shared route cannot meet packaging,
  licensing, hot-plug, or mapping requirements;
- Steam Input keyboard/controller mapping as a fallback, not the only native
  controller story.

The chosen backend must not require the ordinary user to run ChannelOS as root
or manually edit `/dev/input` permissions.

Hardware gates should include:

- Xbox-compatible USB and Bluetooth modes;
- the user's 8BitDo controller family in at least one wired/dongle mode and one
  Bluetooth mode;
- a PlayStation-style controller when available;
- connect at startup, connect after startup, disconnect, reconnect, sleep, and
  resume;
- no ghost button event when a held controller first connects;
- correct A/B or Cross/Circle semantics as presented by ChannelOS;
- keyboard and controller mixed input without focus loss.

---

## 8. Filesystems and media sources

Linux validation must cover differences hidden by the current Windows machine:

- case-sensitive paths and filenames;
- Unicode and long paths;
- symbolic links and symlink loops;
- mounted internal drives and removable USB storage;
- disconnected and remounted media roots;
- read-only media libraries;
- network-mounted media as a source without placing ChannelOS's SQLite database
  on an unsafe network filesystem;
- duplicate-looking paths that resolve to different case-sensitive files;
- permissions changing after a library was indexed.

ChannelOS must never move, rename, or delete user media as part of scanning or
platform migration.

---

## 9. Packaging and installation

### 9.1 First package

The first shareable artifact should be an audited one-folder Linux package plus
a portable archive. It should preserve visible, replaceable Qt and libVLC
components rather than hide them in a one-file executable.

The branch should add:

```text
packaging/linux/
tools/linux/
.github/workflows/linux-package.yml
```

The package must be built and audited on a Linux runner and include:

- ChannelOS executable and QML resources;
- required PySide6/Qt plugins, including the selected xcb platform support;
- python-vlc binding;
- either an audited libVLC runtime or explicit compatible system dependency;
- icon, desktop entry, and launch metadata;
- license texts, notices, replacement instructions, and frozen bill of
  materials;
- a visible README describing supported display and runtime requirements.

### 9.2 Later package formats

AppImage or another portable desktop bundle may be evaluated after the basic
folder package works. Flatpak is valuable but should be a later lane because a
personal-media application needs carefully designed file-picker, portal, and
persistent library permissions. The first Linux proof should not be blocked by
sandbox policy work.

### 9.3 LGPL and dependency policy

The Windows distribution policy still applies in spirit:

- dynamically linked LGPL components remain replaceable;
- only audited libVLC/libVLCcore and plugin files are shipped;
- GPL-only VLC plugins are not included accidentally;
- exact package sources, versions, hashes, libraries, and plugins are recorded;
- relinking/replacement instructions are tested against the shipped layout;
- FFmpeg remains optional unless an audited compliant build is deliberately
  added.

---

## 10. CI and automated testing

The Linux branch should add a Linux job immediately, before feature coding.

### Headless tests

- all pure Python tests;
- database, resolver, runtime, Guide, Library, and channel tests;
- platform-path tests with explicit XDG environments;
- controller normalization tests using fake backend readings;
- package manifest and licensing audits;
- rejection of accidental Windows path/DLL assumptions.

### QML tests

QML tests may run through a virtual X server for construction, signals, and
navigation. A virtual display does not prove native libVLC playback, GPU
decoding, controller hardware, or living-room presentation.

### Regression rule

Every portable change must keep the shared Windows-independent suite green.
Linux success is not permission to scatter `if sys.platform` checks throughout
the scheduler or UI.

---

## 11. Implementation phases

### Phase 0 — Establish the Linux truth

Deliverables:

- this master plan;
- Linux CI for the existing non-hardware test suite;
- a portability audit recorded in implementation status;
- no packaging or feature claims yet.

Exit gate:

> The current shared test suite runs on Linux, and every failure is classified
> as a real portability issue, missing display dependency, or invalid
> Windows-only test.

### Phase 1 — Shared launcher and XDG state

Deliverables:

- shared desktop launch boundary;
- Linux platform policy and entry point;
- XDG data/state/cache paths with `CHANNELOS_DATA_DIR` override;
- first-run UI and visible failure dialog;
- tests for paths, migration safety, and log creation.

Exit gate:

> A source-tree launch creates state only in the expected Linux locations and
> can complete first run without a terminal-dependent workflow.

### Phase 2 — Genuine Linux playback and input

Deliverables:

- Linux libVLC discovery and diagnostics;
- xcb/X11 native video attachment;
- real media playback, seek, pause, transition, and Broadcast Clock validation;
- native controller backend selected and implemented;
- software decode plus measured hardware-decode behavior.

Exit gate:

> On a real Linux desktop, ChannelOS tunes a channel at the exact predicted
> offset and can be operated from the tested controller without a terminal.

### Phase 3 — Audited Linux package

Deliverables:

- one-folder package builder;
- locked native/runtime inputs;
- dependency and plugin audit;
- package bill of materials;
- desktop entry, icon, visible README, and replacement instructions;
- CI-produced artifact.

Exit gate:

> A clean supported Linux machine launches the downloaded artifact, completes
> setup, indexes media, and plays a channel without Python, pip, or an external
> development checkout.

### Phase 4 — Desktop compatibility and resilience

Deliverables:

- X11 and XWayland coverage;
- Intel/AMD/NVIDIA observations;
- external drive and permissions recovery;
- sleep/wake and monitor-change recovery;
- large-library responsiveness measurement;
- accessibility/focus and full-screen checks.

Exit gate:

> All real-machine gates below pass with diagnostics showing the selected
> display, decoder, controller, and runtime paths.

### Phase 5 — SteamOS and broader Linux distribution

Deliverables:

- Steam launch and Steam Input validation;
- couch-mode behavior on SteamOS;
- package/runtime decision for Steam;
- AppImage/Flatpak evaluation;
- native Wayland research after the xcb product path is reliable;
- ARM64 feasibility after x86_64 is stable.

Exit gate:

> ChannelOS can be installed, launched, configured, and watched from a
> SteamOS-style living-room system without requiring a desktop keyboard during
> ordinary use.

---

## 12. Real-machine acceptance gates

1. Launch from an application menu with no terminal attached.
2. Complete first-run folder selection and generate writable state.
3. Index at least 900 mixed media files without UI lockup or data loss.
4. Restart and reproduce the same channel schedules and Broadcast Clock.
5. Tune at a non-zero program offset and compare playback to Guide prediction.
6. Cross a program boundary without losing the Viewer Clock or video surface.
7. Open Guide/Home/Library repeatedly during playback.
8. Maximize, restore, enter full screen, change monitor, and return.
9. Pause, seek, skip, return to Live, change channels, and use Previous Channel.
10. Connect, disconnect, and reconnect a controller during runtime.
11. Suspend and resume the machine during browsing and playback.
12. Disconnect and reconnect an indexed external media drive.
13. Run once under native X11 and once under XWayland.
14. Record CPU, memory, GPU/video-decode, dropped-frame, scan-time, and
    tune-to-first-frame measurements.
15. Confirm the package contains no unrecorded native library or VLC plugin.
16. Confirm an ordinary user can find the log after an intentional startup
    failure.

---

## 13. Explicit non-goals for the first Linux release

- rewriting ChannelOS as a web application;
- turning Linux ChannelOS into a server daemon;
- requiring Jellyfin, Plex, Steam, or an online account;
- claiming native Wayland before a real Wayland video path exists;
- supporting every Linux distribution from one untested package;
- ARM64 before the x86_64 package is reliable;
- Flatpak sandboxing before local media permissions are designed and tested;
- custom Linux distribution or appliance image before the desktop application
  is stable;
- changing ChannelOS schedule truth or channel formats for the operating system;
- merging Linux and Jellyfin work before each boundary is independently proven.

---

## 14. Immediate engineering slice

The safest first implementation is:

1. add Linux CI for the existing test suite;
2. extract shared launch behavior from `windows_app.py` without changing Windows
   behavior;
3. add typed desktop data/state/cache paths and XDG tests;
4. add a Linux source-tree entry point and visible startup errors;
5. report Qt platform name, libVLC version/path, and video target in diagnostics;
6. run a genuine MP4 through the existing xcb `set_xwindow()` path;
7. stop and repair native-window behavior before attempting packaging.

This proves the smallest useful statement:

```text
The real ChannelOS core can launch and play real media on Linux.
```

---

## 15. Open decisions

1. oldest supported Linux/glibc baseline;
2. bundled versus system libVLC for the first package;
3. SDL or another backend for native Linux/macOS gamepad input;
4. exact package format after the portable folder proof;
5. whether the first package always selects xcb or detects and explains the
   Wayland/XWayland choice;
6. hardware-decode expectations by GPU vendor;
7. approach for a future native Wayland video surface;
8. Steam runtime/native Linux package relationship;
9. ARM64 priority after x86_64;
10. how shared platform fixes return to the offline build branch without making
    the edition branches drift.

---

## 16. Reference baseline

ChannelOS references:

- `docs/ARCHITECTURE.md`
- `docs/CONTROL_INPUT.md`
- `docs/DISTRIBUTION.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/MASTER_DESIGN.md`
- `docs/ROADMAP.md`
- `src/channelos/controller_input.py`
- `src/channelos/couch_qt.py`
- `src/channelos/playback.py`
- `src/channelos/windows_app.py`
- `packaging/windows/`

External primary references reviewed:

- [Qt for Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html)
- [Qt for Linux deployment](https://doc.qt.io/qt-6/linux-deployment.html)
- [Wayland and Qt](https://doc.qt.io/qt-6/wayland-and-qt.html)
- [Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)
- [Qt for Python and PyInstaller](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html)
- [PyInstaller operating model](https://pyinstaller.org/en/stable/operating-mode.html)
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)
- [SDL gamepad API](https://wiki.libsdl.org/SDL3/CategoryGamepad)
- [python-vlc MediaPlayer API](https://python-vlc.readthedocs.io/en/latest/api/vlc/MediaPlayer.html)
- [Flatpak desktop integration and portals](https://docs.flatpak.org/en/latest/desktop-integration.html)
- [Steam Deck and Steam Machine compatibility review](https://partner.steamgames.com/doc/steamdeck/compat)

Version-sensitive behavior must be rechecked when ChannelOS changes its Python,
PySide6, PyInstaller, or libVLC support range.

---

## 17. Final platform statement

```text
Linux changes how ChannelOS reaches the screen, controller, filesystem,
and package manager.

It does not change who owns the media.
It does not change who owns the schedule.
It does not change what ChannelOS is.
```
