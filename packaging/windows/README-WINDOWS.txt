ChannelOS Windows x64 preview
=============================

START
-----
Keep the entire ChannelOS folder together. Double-click ChannelOS.exe.
ChannelOS does not require a separate Python, Qt, or VLC installation.

This preview still requires at least one indexed channel. If no channel exists,
ChannelOS shows an error and writes a diagnostic log instead of silently failing.
The first-run channel/setup experience is a later product milestone.

USER DATA AND LOGS
------------------
ChannelOS stores its normal writable data in:

    %LOCALAPPDATA%\ChannelOS

This includes library.db, runtime.db, managed channel definitions, and logs.
Set CHANNELOS_DATA_DIR before launch only when you deliberately want another
data directory.

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
