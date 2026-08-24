# Third-party notices

ChannelOS is developed using open-source software created and maintained by
other people and projects. Their work remains governed by their respective
licenses; the Mozilla Public License 2.0 applied to ChannelOS does not replace
or alter those licenses.

## Status of this document

This file is a **development dependency inventory**, not the frozen bill of
materials for a packaged ChannelOS release. The source repository does not
currently bundle a native libVLC or FFmpeg runtime. A release package must be
audited from the exact files it contains and must update or accompany this
inventory with versions, hashes, license texts, source locations, build
configuration, and any required installation information.

See [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) for the distribution policy
and release gate.

## Direct Python dependencies

| Project | Declared requirement | ChannelOS use | Declared license | Project/license information |
|---|---|---|---|---|
| PyYAML | `>=6.0,<7` | Required YAML parsing | MIT | <https://pypi.org/project/PyYAML/> |
| python-vlc | `>=3.0.0` | Optional Python binding for playback | LGPL-2.1-or-later for the generated module | <https://pypi.org/project/python-vlc/> |
| PySide6 / Qt for Python | `>=6.8,<7` | Optional Qt Quick couch interface | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only, or a commercial Qt license | <https://pypi.org/project/PySide6/> |
| pytest | `>=8,<9` | Development and test dependency; not required at runtime | MIT | <https://pypi.org/project/pytest/> |
| PyInstaller | `>=6.22,<7` | Windows one-folder packaging tool | GPL-2.0-only with the PyInstaller bootloader exception; some files Apache-2.0 | <https://pyinstaller.org/en/stable/license.html> |

ChannelOS intends to use PySide6 under its LGPLv3 option and limits itself to
Qt modules available under compatible LGPL terms. Adding a GPL-only Qt module
requires a new distribution and compatibility review.

Python package installers may resolve additional transitive dependencies. Each
transitive dependency remains subject to its own license. Exact packaged
versions and files will be recorded in the release bill of materials.

PyInstaller's documented bootloader exception permits generated application
bundles to be shipped under the application's license subject to the licenses
of the bundled dependencies. ChannelOS still records the exact build-tool
version and copies license material found in the build environment into the
portable package for transparency.

## External native tools and runtimes

### libVLC

ChannelOS can use libVLC through python-vlc, but python-vlc does not contain the
native playback runtime. During source development, a compatible system libVLC
or an explicit `CHANNELOS_VLC_DIR` may be used.

No native libVLC runtime is bundled in this source repository. VLC plugin
licenses vary. A future ChannelOS package must use an audited LGPL-only libVLC
runtime and plugin set unless the complete application's licensing and
distribution plan is deliberately changed and reviewed.

- libVLC engine relicensing announcement: <https://images.videolan.org/press/lgpl-libvlc.html>
- LGPL-only Windows native package: <https://www.nuget.org/packages/VideoLAN.LibVLC.Windows/>
- Separately published GPL plugin package, which ChannelOS must not copy into
  an LGPL-only runtime: <https://www.nuget.org/packages/VideoLAN.LibVLC.Windows.GPL/>

### FFmpeg and ffprobe

ChannelOS can invoke a system-provided `ffprobe` for technical media metadata
and a system-provided `ffmpeg` for optional thumbnail generation. Neither is a
declared Python dependency or bundled in this source repository.

FFmpeg is LGPL-2.1-or-later by default, but enabling GPL components changes the
license of the resulting build. A future bundled build must be selected and
audited by its exact configuration and contents.

- FFmpeg license and compliance guidance: <https://ffmpeg.org/legal.html>

## No endorsement

Project names and links are provided for attribution and license compliance.
They do not imply that their authors or maintainers endorse ChannelOS.
