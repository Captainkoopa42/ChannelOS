# Replacing LGPL libraries in ChannelOS for Windows

This portable ChannelOS build keeps the LGPL libraries visible and dynamically
loaded. You may inspect, modify, rebuild, and replace them for your own use.
Back up the original folder before changing it; ABI-incompatible replacements
will prevent the application from starting.

## libVLC

The native runtime is in `runtime/vlc/`. It contains `libvlc.dll`,
`libvlccore.dll`, and the `plugins/` tree copied from the exact LGPL-only
`VideoLAN.LibVLC.Windows` artifact recorded in `PACKAGE-BOM.json`.

To test a compatible replacement, close ChannelOS, replace that entire runtime
tree as one unit, and restart ChannelOS. Do not mix plugin trees from unrelated
versions. In a source checkout, `CHANNELOS_VLC_DIR` can point to a separate
compatible runtime without changing the packaged copy.

Corresponding libVLC source for the packaged version is linked from
`PACKAGE-BOM.json`. VideoLAN's build instructions apply to modified builds.

## Qt for Python / PySide6

PySide6, Shiboken, Qt DLLs, and Qt plugins are visible beneath
`_internal/PySide6/` and related `_internal/` entries. ChannelOS selects the
LGPLv3 option for the Qt modules it uses.

The exact wheel versions are recorded in `PACKAGE-BOM.json`. Official Qt for
Python 6.11.2 source is available from:

<https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/>

Qt 6.11.2 module source archives are available from:

<https://download.qt.io/archive/qt/6.11/6.11.2/submodules/>

To test a compatible replacement, reproduce the one-folder build using the
MPL-licensed ChannelOS source and `packaging/windows/requirements-build.txt`,
or replace the matching DLL/plugin set in `_internal/PySide6/` with an
ABI-compatible build. Keep each Qt build and its plugins together.

Nothing in ChannelOS prohibits reverse engineering for the purpose of debugging
your modifications to these LGPL libraries. These instructions describe the
development preview; every release candidate still requires a clean-machine
replacement test.
