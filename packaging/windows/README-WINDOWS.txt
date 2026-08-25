ChannelOS Windows x64 alpha
===========================

START
-----
Keep the entire ChannelOS folder together. Double-click ChannelOS.exe.
ChannelOS does not require a separate Python, Qt, or VLC installation.

On a fresh ChannelOS data directory, the first launch asks you to choose one
folder containing media you own. ChannelOS indexes those files in place and
creates an initial sequential channel so the television can start without
PowerShell, hand-written YAML, or a pre-existing database. Your media files are
not moved, renamed, or copied into ChannelOS.

Large folders can take time on their first scan because ChannelOS establishes
stable media identity and inspects each file for scheduling information. If you
cancel the folder chooser, no channel is created; double-click ChannelOS.exe
again whenever you want to retry setup.

DISPLAY MODE
------------
ChannelOS is fullscreen by default for couch/TV use. Settings > Display Mode can
switch between Fullscreen and Windowed mode, and the choice is saved locally.
F11 is the quick keyboard toggle. The --windowed command-line flag remains an
explicit development/startup override.

USER DATA AND LOGS
------------------
ChannelOS stores its normal writable data in:

    %LOCALAPPDATA%\ChannelOS

This includes library.db, runtime.db, settings.json, managed channel definitions,
artwork cache data, and logs. Set CHANNELOS_DATA_DIR before launch only when you
deliberately want another data directory, such as a clean test environment.

REPLACEABLE THIRD-PARTY LIBRARIES
---------------------------------
The Qt/PySide6 runtime is visible beneath _internal\PySide6. The LGPL-only
libVLC runtime is visible beneath runtime\vlc. They are dynamically loaded
sidecars, not hidden inside a one-file executable.

See licenses\DISTRIBUTION.md, licenses\REPLACING-LGPL-LIBRARIES.md, the
included license texts, and PACKAGE-BOM.json for the exact build inventory and
replacement/compliance information.

ChannelOS is free and open-source software under MPL-2.0.
Copyright (c) 2026 William Robert Adams.
