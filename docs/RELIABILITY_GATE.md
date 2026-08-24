# Reliability Foundation and Windows Gate

**Status:** Implemented on `agent/reliability-foundation`; automated and Windows validation required before merge.

This slice hardens existing ChannelOS behavior for a large real-world Library. It intentionally adds no new product mode.

## Implemented boundaries

- Home **Add Media** and Library Manager scans share the same Qt worker, progress state, cancellation token, and single-flight gate.
- Hashing and technical probing do not run on the Qt GUI thread.
- Cancellation never reconciles incomplete scan membership. The last successful index remains visible and the source is marked `cancelled`.
- Local Library and Runtime SQLite databases use WAL and a finite 5-second busy timeout.
- UNC, `//`, and `file:` network-looking database paths avoid WAL and use the rollback journal.
- A database from a newer ChannelOS schema fails closed before schema writes.
- An older existing schema receives one consistent `<database>.bak` snapshot before upgrade work begins. Existing backups are never overwritten.
- Channel resolution queries only the indexed source roots named by that channel.
- Broadcaster source choices use a distinct-root query rather than loading all media rows.
- current/previous tuning state is committed in one SQLite transaction.
- Artwork results are published as one settled batch and patch card URLs without rebuilding the complete Library snapshot for each thumbnail.
- The headless QML CI gate now includes Settings.

## Explicitly not included

- controller/SDL/Steam Input support,
- Windows installer or bundled libVLC runtime,
- integer-millisecond clock migration,
- one-player playback refactor,
- fingerprint acceleration,
- metadata title normalization or folder exclusions,
- Library to Channel workflow or Channel Studio.

## Automated exit

The pull request must pass the reference-core suite on Python 3.11, 3.12, and 3.13 and the complete headless couch-QML job.

## Windows real-machine exit

Use a media folder whose first scan takes at least ten seconds.

1. Start **Add Media** from Home. Confirm Home/Guide continues painting and navigation remains responsive.
2. Cancel while a large file is hashing. Confirm the progress window reports cancellation and the prior Library contents remain present.
3. Start the scan again and let it finish. Confirm counts and Library cards refresh.
4. During a Home scan, try a rescan from **Manage Sources**. Confirm ChannelOS clearly refuses the second scan.
5. Exercise tune, pause, Previous Channel, On Demand, and return to live television.
6. Close and relaunch ChannelOS. Confirm the same Library, current/previous tuning state, and Broadcast/Viewer Clock behavior return.
7. Save the PowerShell output with the tested commit ID. Benign libVLC/D3D11 thumbnail messages are not a failure unless playback or UI behavior is affected.

Only after this gate passes should the reliability branch merge to `main`. The next planned product slice is **Info**, followed by the controller adapter and then Windows packaging.
