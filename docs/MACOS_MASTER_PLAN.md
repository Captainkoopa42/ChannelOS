# ChannelOS for macOS Master Plan

**Status:** Shelved — awaiting macOS community contributors and physical Mac testing  
**Branch:** `ChannelOS-for-macOS`  
**Product direction:** Native, local-first ChannelOS for Mac desktops and living-room systems  
**Source baseline:** ChannelOS `d9f8161`  

> [!IMPORTANT]
> **This platform build is shelved.** The maintainer does not currently own Mac
> hardware, and ChannelOS will not pretend to support a platform that cannot be
> developed and tested on real machines. Work may resume when a Mac-owning
> community forms around ChannelOS and contributors are willing to help develop,
> package, and test the macOS edition alongside the maintainer. Until then, this
> branch and master plan preserve the intended architecture without representing
> an active release commitment.

---

## 1. Purpose

This document defines the work required to determine whether ChannelOS can
become a reliable macOS application and, if it can, how to ship it without
changing the product into something else.

The macOS edition remains:

- an offline-capable application for user-owned media;
- a ChannelOS interface, Guide, scheduler, and television runtime;
- locally authoritative for channels, clocks, settings, and state;
- usable without Jellyfin, Plex, a web server, or a cloud account;
- a sibling of the Windows and Linux editions, not an unrelated rewrite.

The existing code contains a macOS-shaped native-video path, but it has never
been validated on a Mac. This branch therefore begins as a feasibility branch.
It becomes a supported edition only after the real-machine gates pass.

---

## 2. Definition of success

ChannelOS for macOS is ready to share when a nontechnical Mac user can:

1. download a signed and notarized ChannelOS application;
2. open it through Finder without bypassing Gatekeeper or using Terminal;
3. choose media folders through the normal first-run interface;
4. index and browse a large local library without moving the media;
5. build channels and use the ChannelOS Guide normally;
6. play, seek, pause, return to Live, and channel-surf inside ChannelOS;
7. use a supported Bluetooth or wired controller;
8. restart the application and retain exact schedule and Viewer Clock state;
9. recover honestly from sleep, a disconnected drive, or an unavailable media
   file;
10. perform ordinary viewing without internet access after installation.

An unsigned development bundle that opens from Terminal is not a finished Mac
edition. Native video, Retina/full-screen presentation, controller input,
filesystem behavior, signing, notarization, and clean-machine launch must all be
proven.

---

## 3. Current codebase audit

### 3.1 Already substantially portable

The shared ChannelOS core should carry over without a macOS rewrite:

- media indexing and stable media identity;
- channel definitions and deterministic resolution;
- persistent channel runtimes;
- Broadcast and Viewer Clocks;
- Guide, Library, Broadcaster, and Channel Builder models;
- most QML presentation;
- keyboard control and normalized control intents;
- `GamepadSnapshot`, `GamepadIntentMapper`, and controller hot-plug state
  machine;
- SQLite databases, YAML, artwork, and ordinary pathlib-based file handling.

### 3.2 Present but unproven on macOS

The current code already:

- recognizes Qt's `cocoa` platform as `macos`;
- allows `NativeVideoSurface(platform="macos")`;
- passes the native handle to python-vlc `set_nsobject()`;
- builds the video target around a Qt `QWindow` hosted by a QML
  `WindowContainer`;
- uses PySide6 and PyInstaller versions that support macOS in principle.

This is a promising seam, not evidence that the handle is the correct `NSView`,
that video composites correctly, or that the frozen package can load and sign
libVLC.

### 3.3 Currently Windows-specific

- packaged launch, first run, data paths, logs, and visible crash handling live
  in `windows_app.py`;
- controller discovery is XInput-only;
- libVLC preparation searches for Windows DLLs;
- package scripts, PyInstaller specification, runtime audit, and CI are
  Windows-only;
- the HUD/native-child composition was designed around Windows DWM behavior;
- hardware decoding has only been verified through D3D11VA;
- the application icon is currently Windows `.ico`, not a Mac asset/catalog;
- no code-signing, hardened-runtime, notarization, bundle-identifier, or
  installer policy exists.

---

## 4. Initial macOS support boundary

### 4.1 Hardware architectures

Apple Silicon should be the first proof because it represents the current Mac
platform. Intel support remains desirable for existing user hardware.

The first packaging experiments should produce separate native builds:

- `arm64` on Apple Silicon;
- `x86_64` on Intel, if the required Python, PySide6, python-vlc, and libVLC
  inputs remain available and supportable.

A `universal2` bundle should follow only after both native builds pass. A
universal PyInstaller target still requires universal-compatible Python and
every collected native dependency; selecting the flag alone cannot make
single-architecture libVLC plugins universal.

### 4.2 OS-version baseline

The minimum macOS version must be selected from the intersection of:

- the PySide6/Qt support matrix;
- the Python build used for packaging;
- PyInstaller bootloader support;
- libVLC and plugin support;
- ChannelOS real-machine availability.

The plan must not promise an OS version before a clean-machine package runs on
it. Each release records the tested macOS, hardware architecture, Python, Qt,
PyInstaller, and libVLC versions.

### 4.3 Distribution lane

The first public Mac edition should use direct distribution outside the Mac App
Store:

```text
ChannelOS.app -> Developer ID signing -> notarization -> stapled distributable
```

The Mac App Store and App Sandbox add file-access and entitlement constraints
that are not necessary to prove a local personal-media application. They are
not first-release targets.

---

## 5. Target platform architecture

### 5.1 Shared desktop launcher

macOS should use the same shared desktop launch boundary proposed for Linux:

```text
desktop_app.py
  |- first-run orchestration
  |- common arguments and startup
  |- logging and crash boundary
  |- ChannelOS runtime launch
  |
  `- macOS platform policy
       |- data/state/cache locations
       |- visible startup errors
       |- native runtime preparation
       |- Finder/application-bundle behavior
       `- package diagnostics
```

A thin `macos_app.py` entry point should provide policy, not duplicate the
Windows application.

### 5.2 macOS data locations

The ordinary user locations should be:

| Data | Preferred location |
|---|---|
| databases, channel files, and durable state | `~/Library/Application Support/ChannelOS` |
| logs | `~/Library/Logs/ChannelOS` |
| regenerable artwork/metadata cache | `~/Library/Caches/ChannelOS` |

`CHANNELOS_DATA_DIR` remains the explicit portable/testing override. Tests must
verify that no Windows AppData directory is accidentally created on macOS.

If the directory layout changes after an experimental build, migration must be
transactional and preserve the previous databases and channel files until the
new launch succeeds.

### 5.3 Finder and visible failures

ChannelOS must launch correctly when Finder supplies no terminal, working
directory, or developer environment. All bundled resources must be found
relative to the application bundle or packaged Python resources.

Before QML is available, startup failures may use a minimal Qt alert. After
startup, ChannelOS owns the error surface. Every failure should point to the Mac
log directory without asking the viewer to discover Console.app internals.

---

## 6. Playback and native Cocoa presentation

### 6.1 The first feasibility gate

Before packaging work expands, an actual Mac must prove that:

1. Qt reports the `cocoa` platform;
2. the hosted `QWindow` is realized and returns a nonzero `winId()`;
3. the handle passed to `set_nsobject()` is accepted as the required native
   Cocoa video target;
4. genuine local video and audio render inside the intended ChannelOS geometry;
5. seek and program transitions work at ChannelOS-selected offsets;
6. closing or changing screens does not orphan the libVLC video output.

If the `QWindow` handle is not a reliable `NSView` target, the repair belongs in
a small macOS presentation adapter. It must not force a scheduler or QML
rewrite.

### 6.2 libVLC discovery and bundle layout

Development may use a compatible system-installed libVLC or
`CHANNELOS_VLC_DIR`. A distributable application must carry an audited native
runtime in a conventional `.app` layout, with libraries/frameworks, plugins,
and resources placed where the loader and signing tools can validate them.

Runtime preparation must:

- locate the exact bundled `.dylib`/framework and plugin directory;
- configure python-vlc before its first import;
- report the actual runtime version and path;
- reject incompatible architecture combinations;
- avoid copying an ordinary VLC application bundle without auditing its plugins
  and licenses;
- never depend on `/Applications/VLC.app` for an ordinary ChannelOS user.

### 6.3 Window composition and Retina behavior

The Windows-tested overlay solution cannot be assumed correct on Cocoa. Real
tests must cover:

- QML over/around the native video child;
- Guide and Home transitions during playback;
- full-screen entry and exit;
- macOS Spaces and Mission Control;
- Retina scaling and movement between displays with different scale factors;
- menu bar/Dock interaction;
- maximize/zoom and ordinary resizes;
- sleep, wake, lock, and display reconnection;
- focus returning to ChannelOS after native dialogs.

### 6.4 Hardware decoding and media quality

The first port must play correctly with software decoding. VideoToolbox or
other hardware acceleration should then be measured rather than assumed.

Record:

- selected decoder and video output;
- CPU/GPU load and dropped frames;
- tune-to-first-frame latency;
- Apple Silicon versus Intel behavior;
- SDR playback first;
- HDR, color management, 10-bit output, and tone mapping only after controlled
  visual and technical tests.

### 6.5 Audio

The system default output is acceptable for the initial Mac feasibility gate.
The user-requested audio-output selector should later be implemented through
the shared playback contract so it behaves consistently across all desktop
editions.

---

## 7. Controller and couch input

macOS has no XInput backend. The existing normalized controller boundary allows
two credible experiments:

1. Apple's Game Controller framework through a small maintained Python/native
   bridge;
2. the same SDL gamepad backend considered for Linux.

The decision should be based on:

- controller coverage;
- Bluetooth, USB, and hot-plug behavior;
- stable button naming and axis normalization;
- package size and native-library complexity;
- license compatibility;
- Apple Silicon and Intel support;
- interaction with code signing and hardened runtime;
- ability to keep the existing mapper and tests unchanged.

Real hardware gates should include Xbox, PlayStation-style, and available 8BitDo
controllers, including Bluetooth mode. Steam Input can remain an optional
distribution aid but must not be required for a standalone Mac application.

---

## 8. Filesystem and media permissions

The first directly distributed build should not enable App Sandbox. It still
must handle modern macOS file access honestly.

Validation must cover:

- media selected through the Qt native folder picker;
- removable and external drives;
- disconnected and remounted volumes;
- files under user-controlled Movies and home folders;
- case-insensitive and case-sensitive APFS volumes;
- Unicode, long paths, aliases, and symbolic links;
- media on network shares;
- permissions revoked or changed after indexing;
- no deletion, movement, or renaming of user media;
- no assumption that the Finder launch working directory contains application
  resources.

If a future sandboxed/App Store lane is explored, security-scoped access and
persistent bookmarks require their own design and migration plan. They should
not be partially introduced into the first direct-distribution build.

---

## 9. Packaging, signing, and notarization

### 9.1 Application bundle

The branch should add:

```text
packaging/macos/
tools/macos/
.github/workflows/macos-package.yml
```

PyInstaller can create a windowed `.app` bundle, but the generated layout must
be audited for ChannelOS QML, Qt plugins, python-vlc, libVLC libraries/plugins,
icons, metadata, and licenses. The first package remains a one-folder app
bundle, not a self-extracting one-file design.

The bundle needs a stable identifier chosen before signing. It also needs a Mac
`.icns` asset derived from the ChannelOS artwork without replacing the source
brand asset.

### 9.2 Signing order

Every nested executable library or framework must be compatible with the final
architecture and signing identity. The release workflow must:

1. assemble the audited `.app`;
2. sign nested native code and the outer bundle correctly;
3. enable hardened runtime as required for notarization;
4. verify the signature deeply and strictly;
5. archive the application using a method that preserves bundle metadata;
6. submit it with Apple's current notarization tooling;
7. wait for acceptance and retain the notarization log;
8. staple the ticket where applicable;
9. validate the final downloaded artifact through Gatekeeper on a clean Mac.

Entitlements must be minimal and evidence-based. The project must not add broad
runtime, library-validation, or debugging exceptions merely to make an
incorrect bundle launch.

### 9.3 Developer and public artifacts

Two package classes are useful:

- an ad-hoc-signed internal artifact for automated and local development tests;
- a Developer ID-signed and notarized artifact for ordinary external users.

Only the second should be described as the shareable Mac release.

### 9.4 LGPL and replacement rights

Qt and libVLC remain separately licensed native components. The Mac package
must:

- inventory every native binary and VLC plugin;
- include required licenses, notices, exact sources, versions, and hashes;
- keep dynamically linked components in an identifiable bundle location;
- document how a user can replace/relink compatible LGPL components;
- explain the re-signing step required after a user modifies the `.app` bundle;
- avoid GPL-only VLC plugins unless the entire distribution decision is
  deliberately revisited;
- test the documented replacement path before release.

Apple code signing does not erase LGPL obligations; replacement instructions
must account for both.

---

## 10. CI and automated testing

macOS tests and packages must be built on macOS runners. PyInstaller is not a
cross-compiler for a Windows or Linux host.

### Automated matrix

- shared pure Python suite;
- database, resolver, clocks, Guide, Library, and channel tests;
- macOS data-path and Finder-style argument tests;
- controller mapper tests with fake readings;
- QML construction/navigation where the runner display allows it;
- bundle-content and Mach-O architecture audit;
- license/BOM audit;
- ad-hoc signature verification for CI artifacts;
- rejection of accidental Windows DLL/AppData assumptions.

### Limits of CI

A cloud Mac runner cannot establish living-room quality. It does not replace a
physical Mac for native libVLC video, hardware decoding, Bluetooth controllers,
Retina/multi-display behavior, sleep/wake, external storage, Gatekeeper download
provenance, or long viewing sessions.

---

## 11. Implementation phases

### Phase 0 — Prove or disprove the native-video seam

Deliverables:

- this master plan;
- macOS CI for existing portable tests;
- a source-tree diagnostic reporting architecture, macOS/Qt version, Cocoa
  platform, libVLC version/path, and native handle;
- genuine local video attached through `set_nsobject()` on a physical Mac;
- no package claim yet.

Exit gate:

> A physical Mac displays genuine video inside ChannelOS, seeks to a specified
> offset, and exits cleanly without an orphan native player window.

If this fails, document the exact Cocoa surface mismatch before further port
work.

### Phase 1 — Shared launcher and Mac state

Deliverables:

- common desktop launcher extraction;
- `macos_app.py` policy/entry point;
- Application Support, Logs, and Caches directories;
- Finder-safe resource discovery;
- first-run UI and visible startup errors;
- migration/path/log tests.

Exit gate:

> ChannelOS launches from Finder in a development bundle, creates state only in
> the expected Mac locations, and completes setup without Terminal.

### Phase 2 — Playback, presentation, and controller

Deliverables:

- reliable Cocoa video surface;
- Guide/Home/HUD/full-screen/Retina validation;
- software decode plus measured VideoToolbox behavior;
- selected macOS controller backend;
- Bluetooth and hot-plug validation;
- sleep/wake and external-display recovery.

Exit gate:

> A physical Mac can operate ChannelOS from a supported controller and tune to
> the exact program/offset predicted by the Guide across a full program
> transition.

### Phase 3 — Native architecture packages

Deliverables:

- reproducible Apple Silicon `.app` builder;
- Intel builder if dependency support is viable;
- audited Qt/libVLC bundle layout;
- package BOM, notices, replacement guide, icon, and metadata;
- CI artifacts with architecture/signature checks.

Exit gate:

> A clean Mac with no Python or VLC development environment opens the internal
> application bundle and plays indexed media.

### Phase 4 — Developer ID distribution

Deliverables:

- stable bundle identifier;
- hardened-runtime configuration;
- minimal entitlements justified by tests;
- Developer ID signing;
- current notarization submission and stapling;
- clean downloaded-artifact Gatekeeper validation;
- documented release procedure that keeps credentials out of the repository.

Exit gate:

> A nontechnical user downloads the public artifact, opens it normally through
> Finder, completes ChannelOS setup, and watches a channel without bypassing a
> macOS security control.

### Phase 5 — Compatibility and polish

Deliverables:

- supported macOS-version matrix;
- Apple Silicon/Intel decision or universal2 artifact after both native lanes
  pass;
- external drives, network shares, multiple displays, Retina scaling, and long
  sessions;
- performance budgets and tune latency;
- audio-output selection through the shared playback feature;
- optional Steam distribution validation without making Steam mandatory.

Exit gate:

> All real-machine gates below pass on each architecture and OS version claimed
> by the release.

---

## 12. Real-machine acceptance gates

1. Launch a downloaded signed/notarized build through Finder.
2. Complete first run without Terminal or an installed Python environment.
3. Index at least 900 mixed media files without UI lockup or media mutation.
4. Restart and reproduce the same channels, schedules, and Broadcast Clock.
5. Tune at a non-zero offset and compare playback against the Guide.
6. Cross a program boundary without losing the native video surface.
7. Open and close Guide, Home, Library, Settings, and Broadcaster during
   playback.
8. Enter/leave full screen and use macOS Spaces/Mission Control.
9. Move the application between Retina and nonmatching-scale displays when
   hardware is available.
10. Pause, seek, skip, return to Live, change channels, and use Previous
    Channel.
11. Connect, disconnect, and reconnect a Bluetooth controller.
12. Sleep and wake during browsing and during playback.
13. Disconnect and reconnect an indexed external drive.
14. Confirm Finder launch, paths, and logs with no developer shell environment.
15. Record CPU, memory, hardware decode, dropped frames, scan time, and
    tune-to-first-frame.
16. Verify app architecture, nested signatures, hardened runtime, notarization,
    stapling, and Gatekeeper assessment.
17. Confirm every bundled native library and VLC plugin appears in the frozen
    bill of materials.
18. Repeat all claimed gates independently on Apple Silicon and Intel if both
    are advertised.

---

## 13. Explicit non-goals for the first Mac release

- Mac App Store submission;
- App Sandbox or security-scoped bookmark architecture;
- iPhone, iPad, Apple TV, or visionOS editions;
- universal2 before both native architectures are proven;
- requiring `/Applications/VLC.app` on the user's machine;
- unsigned public distribution or instructions to bypass Gatekeeper;
- replacing ChannelOS with a web interface;
- requiring Jellyfin, Plex, Steam, or an online account;
- promising HDR/color accuracy before controlled testing;
- changing ChannelOS schedule truth, channel files, or product identity for
  macOS;
- allowing Mac-only fixes to permanently fork the portable core.

---

## 14. Immediate engineering slice

The first Mac work should remain deliberately small:

1. add a macOS CI job for the existing portable suite;
2. add platform diagnostics without modifying schedule or QML behavior;
3. install the development dependencies on a physical Apple Silicon Mac;
4. launch the current source tree through Qt Cocoa;
5. attach the existing `QWindow.winId()` using `set_nsobject()`;
6. play one genuine MP4 and seek to a chosen offset;
7. exercise Guide/Home transitions and close the application;
8. record whether the surface is valid, embedded, stable, and correctly scaled;
9. only then extract the shared launcher and begin packaging.

This answers the most important unknown before expensive signing and packaging
work:

```text
Can the real ChannelOS television surface behave correctly on Cocoa?
```

---

## 15. Open decisions

1. minimum supported macOS version;
2. Apple Silicon-only first release versus parallel Intel support;
3. separate native packages versus later universal2;
4. bundled libVLC source and exact plugin audit path;
5. Cocoa `QWindow`/`NSView` integration if the current handle is insufficient;
6. Apple Game Controller framework versus a shared SDL backend;
7. stable bundle identifier;
8. exact icon/bundle metadata;
9. entitlements, if any, actually required by PySide6 and bundled libVLC under
   hardened runtime;
10. ZIP, DMG, or another final transport after notarized `.app` validation;
11. replacement/re-signing instructions for user-modified LGPL libraries;
12. how validated portable work returns to the offline build branch without
    platform branches drifting.

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

- [Qt for macOS](https://doc.qt.io/qt-6/macos.html)
- [Qt for macOS deployment](https://doc.qt.io/qt-6/macos-deployment.html)
- [Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)
- [Qt for Python and PyInstaller](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html)
- [PyInstaller macOS options](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller macOS bundle specification](https://pyinstaller.org/en/stable/spec-files.html)
- [Apple Developer ID distribution](https://developer.apple.com/developer-id/)
- [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [Apple hardened runtime](https://developer.apple.com/documentation/security/hardened-runtime)
- [Apple Game Controller framework](https://developer.apple.com/documentation/gamecontroller)
- [Apple macOS Library directories](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/MacOSXDirectories/MacOSXDirectories.html)
- [python-vlc MediaPlayer API](https://python-vlc.readthedocs.io/en/latest/api/vlc/MediaPlayer.html)

Version-sensitive behavior must be rechecked when ChannelOS changes its Python,
PySide6, PyInstaller, libVLC, signing, or supported macOS range.

---

## 17. Final platform statement

```text
macOS changes how ChannelOS reaches Cocoa, controllers, folders,
application bundles, and Gatekeeper.

It does not change who owns the media.
It does not change who owns the schedule.
It does not change what ChannelOS is.
```
