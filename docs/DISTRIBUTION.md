# ChannelOS distribution and dependency policy

**Status:** Active development policy

**ChannelOS license:** Mozilla Public License 2.0

**Copyright:** Copyright (c) 2026 William Robert Adams

This document defines the rules for turning the ChannelOS source tree into a
redistributable application. It is a technical compliance policy, not legal
advice and not a substitute for reviewing the exact contents of a release.

## 1. Core rule

ChannelOS source files are distributed under the Mozilla Public License 2.0
unless a file clearly states another license. Third-party components retain
their own licenses. Building a Larger Work does not relicense Qt, libVLC,
FFmpeg, Python dependencies, or other third-party material as MPL-2.0.

Every release must preserve these properties:

- ChannelOS remains independently installable and usable without Steam or any
  other distribution-platform entitlement.
- User-owned local playback does not require a cloud account.
- Dynamically linked LGPL components remain replaceable by the user.
- Required license texts, notices, corresponding-source information, and
  installation/relinking information travel with the release.
- The exact files in the release, not a package name or assumption, determine its
  third-party license obligations.

## 2. Source distributions

A ChannelOS source distribution must include at least:

- `LICENSE.md`,
- `THIRD_PARTY_NOTICES.md`,
- `ACKNOWLEDGMENTS.md`, and
- this distribution policy.

The corresponding ChannelOS source must remain available under MPL-2.0. Files
incorporated from another project must preserve their original notices and be
identified separately.

## 3. Native Windows libVLC policy

Development may continue to use a compatible system installation or the
`CHANNELOS_VLC_DIR` override. Those are development conveniences, not the
finished installation design.

For a packaged Windows build:

1. Place `libvlc.dll`, `libvlccore.dll`, and the audited LGPL `plugins/` tree in
   a replaceable sidecar location such as `runtime/vlc/`.
2. Use the native file tree from the LGPL-only
   `VideoLAN.LibVLC.Windows` artifact as an audited input. It is a source of
   native runtime files for ChannelOS packaging, **not a .NET dependency**;
   ChannelOS must not add a `dotnet` package reference.
3. Do not include the `VideoLAN.LibVLC.Windows.GPL` companion package in an
   LGPL-only ChannelOS distribution.
4. Do not create the runtime by copying `C:\Program Files\VideoLAN\VLC` or any
   other ordinary VLC application installation. Those installations can
   contain GPL plugins that are absent from the LGPL-only package.
5. Record the precise package version, download location, hashes, native DLL
   list, and complete plugin directory listing in the release bill of
   materials.

If ChannelOS later requires a missing GPL plugin, distribution must stop until
the complete licensing consequence is reviewed deliberately.

## 4. Qt / PySide6 policy

ChannelOS intends to use Qt for Python under the LGPLv3 option.

A packaged build must:

- use dynamically linked, user-replaceable Qt libraries;
- avoid GPL-only Qt modules unless the entire distribution is reviewed for that
  change;
- include the applicable LGPL text and prominent Qt/PySide6 notice;
- provide the corresponding Qt source, or a compliant written offer and clear
  retrieval instructions, for the exact binaries distributed;
- permit reverse engineering for the purpose of debugging modifications to the
  LGPL libraries; and
- provide sufficient installation information for a recipient to run the
  application with a compatible replacement/relinked LGPL library.

Do not use a one-file packaging layout that makes the Qt or libVLC libraries
effectively unreplaceable. Prefer an application executable plus visible
sidecar runtime files. The final directory and installer layout will be decided
and tested during the packaging milestone.

## 5. FFmpeg / ffprobe policy

The source build currently treats `ffmpeg` and `ffprobe` as optional external
executables. ChannelOS must continue to degrade cleanly when they are absent.

If a release bundles FFmpeg tools:

- use a verified LGPL build configured without `--enable-gpl` and
  `--enable-nonfree`;
- prefer a shared/dynamically linked build whose libraries remain replaceable;
- do not bundle an unverified system executable or a GPL build merely because
  it is convenient;
- record the exact build identifier, configuration, source, hashes, DLLs, and
  external libraries in the release bill of materials; and
- satisfy FFmpeg's notice, corresponding-source, and reverse-engineering
  requirements.

## 6. Frozen release bill of materials

Before publishing an installer, portable archive, Steam build, or appliance
image, create a bill of materials for the exact release candidate. For every
bundled third-party component, record:

- project and component name;
- exact version and source URL;
- cryptographic hash of each downloaded artifact;
- effective SPDX license expression;
- copied file and plugin inventory;
- whether the component was modified;
- build flags and build identifier where applicable;
- corresponding-source location or written-offer instructions;
- required license/notice files; and
- replacement, relinking, or installation instructions required by its
  license.

The release is blocked if a file has unknown origin or license, if a GPL-only
component has entered the intended LGPL-sidecar runtime unnoticed, or if the
recipient cannot exercise the replacement rights required by an LGPL
component.

## 7. Installer contents and verification

The final installer or portable archive must expose, in an ordinary readable
location:

- the ChannelOS MPL-2.0 license;
- third-party notices and applicable dependency license texts;
- acknowledgments;
- corresponding-source and relinking/replacement instructions; and
- the release bill of materials or a durable link to the exact matching copy.

Packaging CI should inventory and hash the staged runtime, compare it with the
approved bill of materials, and fail if unexpected native files or plugins are
present. A clean Windows machine must then verify installation, launch,
playback, replacement-friendly sidecar discovery, upgrade, and uninstall.

## 8. Current Windows packaging foundation

The development packaging lane produces a portable Windows x64 folder and ZIP,
not an installer and not a one-file executable. Its inputs and controls are:

- Python 3.12 and the versions frozen in
  `packaging/windows/requirements-build.txt`;
- PyInstaller one-folder mode, with Qt/PySide6 beneath the visible `_internal/`
  sidecar tree;
- `VideoLAN.LibVLC.Windows` 3.0.23.1, pinned by URL and SHA-256 in
  `packaging/windows/runtime-lock.json`;
- extraction of only `libvlc.dll`, `libvlccore.dll`, and `plugins/` from the
  audited x64 native tree;
- a full package file inventory and SHA-256 values in `PACKAGE-BOM.json`; and
- CI validation that rejects unexpected files, import libraries, hash changes,
  incomplete notices, or a GPL companion package.

`tools/windows/build-package.ps1` is the supported local build entry point.
The `windows-package` GitHub Actions workflow performs the same build on
Windows and uploads the audited ZIP for testing.

The portable build is a packaging preview. First-run setup, installer creation,
upgrade, and uninstall remain separate gates. Until first-run setup exists, the
packaged launcher reports a clear diagnostic when no indexed channel exists.
