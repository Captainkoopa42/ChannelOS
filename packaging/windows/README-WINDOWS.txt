ChannelOS Windows x64 alpha
===========================

START
-----
Keep the entire ChannelOS folder together. Double-click ChannelOS.exe.
ChannelOS does not require a separate Python, Qt, or VLC installation.

On a fresh ChannelOS data directory, choose New Library or Open Existing Setup.
New Library asks for one folder containing media you own, indexes it in place and
creates an initial sequential channel so the television can start without
PowerShell, hand-written YAML, or a pre-existing database. Your media files are
not moved, renamed, or copied into ChannelOS.

Large folders can take time on their first scan because ChannelOS establishes
stable media identity and inspects each file for scheduling information. If you
cancel the folder chooser, no channel is created; double-click ChannelOS.exe
again whenever you want to retry setup.

PORTABLE SETUP
--------------
Open Settings > Portable Setup > Copy to Drive / Folder. Choose the drive itself
if your media is already on it. ChannelOS reuses the saved index and leaves
existing media in place. Enable "Copy media outside the destination" if videos
also need to be brought from this PC. The packaged app can be included too.

Choose Review Copy, Copy Setup, then Open Copied Setup. Once opened, that drive
is the active save location. Channel edits, watch progress and ad history save
there, so they are already present on the next computer.

On another PC, double-click ChannelOS-App\ChannelOS.exe on the drive, or choose
Open Existing Setup from a compatible ChannelOS install. Select the folder
containing ChannelOS.portable.json. No full library scan is required. Keep that
marker, ChannelOS-Data and the referenced media folders together when moving
the setup. Audio output device selection stays on each computer.

Exit ChannelOS and safely eject the drive before moving it. If it disconnects
during use, playback stops and writes are blocked until the same setup returns.
An interrupted copy can be recovered with Open Existing Setup. A setup can be
open in only one ChannelOS process at a time. Windows and Linux need their own
compatible native application builds; this download is for Windows x64.

WATCHING AHEAD
--------------
Skip Forward can move past Live into upcoming local programs. The TV badge and
Home show whether you are ahead of Live, behind Live, or Live. Go Live returns to
the current broadcast from either side and resumes playing. Pause and seeking
change your viewing position while the channel's broadcast schedule keeps
running. Continue Watching preserves that position across restarts.

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
An active portable setup instead stores shared data and logs in ChannelOS-Data
on the selected drive. Recent-setup shortcuts and audio device IDs stay local.

For troubleshooting, send these files from the logs folder:

    channelos.log
    channelos-crash.log

channelos.log rotates automatically and keeps the three previous files as
channelos.log.1 through channelos.log.3. It records startup details, Qt/QML
warnings, Library and Studio background work, playback failures, and Python
exceptions. channelos-crash.log is a smaller last-resort trace for fatal native
or Python crashes and keeps two previous files. Routine entries do not list the
contents of your media library, although an error emitted by a decoder or the
operating system can include the path of the file involved.

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
