# Portable setups — version 1

ChannelOS 0.0.3 can keep a complete active setup on an external drive or ordinary
folder. Open that setup on another computer and changes continue saving to the
drive. Opening does not import an independent per-PC copy.

## Copy and open

1. Open **Settings → Portable Setup**.
2. Choose the destination drive or folder. If your library is already on an
   external drive, choose that drive as the destination so its media can be
   reused in place. Choosing a smaller folder means media outside it must be
   copied into the portable setup.
3. Enable **Copy media outside the destination** when needed. A packaged build
   can also include its application folder. Generated thumbnails are optional;
   media sidecar artwork is included when its media is copied.
4. Choose **Review Copy** to see the channels, index counts, media bytes,
   unavailable files and source mappings. Choose **Copy Setup**. Media copying
   runs in the background and can be cancelled. The current session stays active
   while its captured snapshot is copied.
5. Choose **Open Copied Setup**. ChannelOS starts the selected setup and closes
   the previous session. Edits after this point save directly to the drive.

On the next PC, double-click `ChannelOS-App/ChannelOS.exe` if the app was included,
or use **Open Existing Setup** from Settings or the first-launch welcome screen.
Select the folder containing `ChannelOS.portable.json`. Recent setups are
shortcuts on each PC; an unavailable shortcut never creates an empty setup.

**Copy Setup** creates a new setup identity and keeps the source intact.
**Open Existing Setup** continues using the chosen setup in place. A destination
that already contains a setup is opened explicitly instead of overwritten.

## What travels

| Data | Behavior |
| --- | --- |
| Current channel YAML and Studio program groups | Included and resolved against the setup root |
| Library assets, locations, durations and hashes | Included; an existing library is reused without hashing/probing every video |
| Reusable ad collections, profiles and assignments | Included, including dynamic collection paths |
| Broadcast epochs, Viewer Clock and On Demand progress | Included with canonical asset identity unchanged |
| Committed ad plans, aired/watched ledgers, rotation and catch-up state | Included with stable plan/event identities |
| General display, controller, audio level and performance preferences | Shared on the drive |
| Audio output device ID | Stored on each PC per setup; defaults safely on another PC |
| Application runtime | Optional; copied into `ChannelOS-App` with its dependencies |
| Generated thumbnail cache | Optional and replaceable |
| Diagnostic logs | New logs are written to the active setup; old logs are not copied |

Copy captures metadata in one application turn after scans and Studio Auto Fill
finish. Playback and editing can continue during the subsequent media copy;
later edits remain in the original session until another copy is made. Media
already inside the destination is reused. Media copied from elsewhere is hashed
while copying and must match its indexed identity. Changed files need a source
rescan before retrying.

## Layout and paths

The selected folder is the setup root. Its required marker and data are:

- `ChannelOS.portable.json`: format `channelos-portable`, version `1`, UUID
  `setup_id`, origin `case_sensitive` flag, source roots with relative paths and
  stable sort ranks, creation time and index schema.
- `ChannelOS-Data/library.db`: canonical identity and drive-relative locations.
- `ChannelOS-Data/runtime.db`: broadcast/viewer state and ad planning/history.
- `ChannelOS-Data/ad_catalog.sqlite`: reusable ad authoring configuration.
- `ChannelOS-Data/channels/`: active channel definitions and Studio groups.
- `ChannelOS-Data/settings.json`: shared preferences.
- `ChannelOS-App/`: optional compatible native application bundle.

Existing media folders retain their locations relative to the chosen root.
External media copied by the workflow goes beneath
`Media/ChannelOS-<copy-id>/<source-folder>/` to avoid overwriting existing media.
Source names in that folder include an ordering prefix.

Stored media/source paths use `portable://Media/Shows/episode.mp4`, for example.
They are decoded relative to the current root, never the old drive letter or
mount point. Canonical SHA-256 asset IDs remain unchanged. Source sort ranks keep
default program ordering stable after relocation; declared episode order stays
intact too. Ad policy path signatures are normalized separately from program
schedule signatures so copying does not restart the Broadcast Clock.

The portable setup is self-contained. Adding a source outside its root is
rejected; copy the source onto the drive before adding it. Keep the marker, data
and referenced folders together when copying the setup with a file manager.
Moving only `ChannelOS-Data` separates it from its marker and is not supported.

## Continuity and recovery

Exit ChannelOS and safely eject the drive before moving it. An OS-owned exclusive
lock permits only one app writer per portable setup and releases after process
death. The lock file can remain on disk; its presence alone does not mean the
setup is locked.

If the active drive disappears or a different setup replaces its path, playback
stops, background work is cancelled and guarded writes fail. ChannelOS shows a
reconnect screen and does not silently switch to local state or recreate the
missing data directory. On return, database connections are reopened and saved
state is retained. In-memory viewing progress can be flushed after reconnection;
if the process also exits, progress since its last successful save may be lost.

Missing media retains its indexed identity and channel definitions. Portable
startup can use saved metadata to keep the lineup and clocks available without
forcing a full scan. Playback uses the existing temporary-unavailability and
recovery behavior until usable files return. A file deleted permanently still
needs the normal source rescan/index management workflow.

Copies are staged privately. The manifest is published last, after metadata and
media copies complete. A small journal and per-copy ownership markers let
**Open Existing Setup** finish a fully published interrupted copy, or discard
only that transaction's incomplete folders. Existing user files are kept.
Cancelling a copy keeps the current setup and media. A prior complete setup copy
remains the recovery option for corrupt source databases; damaged or newer data
is rejected before normal startup writes or migration.

## Compatibility and verification

Portable format 1 requires a compatible build supporting Library schema 3.
Older builds reject the index instead of treating portable references as local
paths. Channel schema and runtime schema validation remain in force. The first
ordinary local Library schema upgrade creates its usual `.bak` recovery copy.

The Windows package is Windows x64. Linux requires a compatible Linux native app
and media codecs; the Windows executable is not a Linux executable. Both builds
can use the shared relative setup format. Filesystem rules still apply: avoid
case-only filename distinctions and OS-reserved names for a drive shared between
Windows and Linux. A drive letter or Linux mount-point change does not require
editing channel YAML or rebuilding the index.

Automated acceptance covers relocation, unchanged-file index reuse, ad plan and
watch-history continuity, app bundle discovery, fresh-PC opening, missing media,
drive disconnect/reconnect, audio device separation, future-version rejection,
cancellation, changed-content refusal, real process-death copy recovery and the
Qt authoring workflow. Windows packaging also runs the suite and native VLC
playback smoke checks. A physical USB unplug across two PCs and a future native
Linux package remain hardware/release acceptance checks.

For source checkouts, `channelos-couch --portable-setup /path/to/setup --windowed`
uses the same selection, validation and lifetime lock as the packaged launcher.
