# ChannelOS implementation status

**Candidate:** 0.0.6 for Windows x64, November 2, 2026.

The candidate contains Broadcaster/Studio, complete advertising, portable setups,
watch-ahead playback, simple ad controls, and the release-audit repairs. Its source
lineage includes every commit from the builder through `feature/simple-ad-controls`.
The repair and release branches retain that lineage; no feature branch is dropped.

## Implemented and covered by automated regressions

- Library additions preserve the complete saved channel and calendar.
- Numeric input cancels on navigation and alternative tuning, including direct QML navigation.
- A missing source excludes unavailable playback while Home, Guide, Library and Broadcaster remain accessible.
- Source removal checks program files/subfolders, calendar/filler IDs, ad sources,
  placements and assigned collections. Original media remains untouched.
- Deleted stations have archived clocks/plans/history and fresh active state on number reuse.
  A recovery journal completes or rolls back interrupted deletion.
- Profile defaults, channel overrides and placement overrides resolve in that order.
  Assignments stay in the draft; Use Profile Defaults restores inheritance.
- Calendar swaps, moves, deletion and insertion reconcile reservations in chronological
  order. Fixed starts remain protected, active/viewed reservations remain immutable,
  and abandoned future plans never enter the airing ledger.
- Temporary partial lineups use clocks belonging to their own resolved schedule,
  preserving the original persisted channel epoch and saved viewer state.
- Studio wraps its toolbar at supported smaller window sizes, keeping all seven
  week days and ad actions visible. Ad dialogs have stable viewport sizing.

Channel schemas 0.1–0.6 remain supported. Runtime schema 3 adds archive and calendar
ownership state and scopes program clocks; an existing schema-2 database is backed
up before migration. Older builds must not open the migrated database.

## Validation and publication

The exact candidate commit is recorded in `PACKAGE-BOM.json` and the GitHub Actions
run. The release workflow gates publication on Python 3.11/3.12/3.13, QML, locked
Windows packaging, native VLC transition playback and packaged portable relocation.
The public candidate includes its checksum and source revision.

Physical Windows speaker/headphone switching, controller hot-plug and a real USB
move remain device acceptance checks. Automated results do not replace them. Use
[the acceptance route](releases/WINDOWS_0.0.6_ACCEPTANCE.md) and record results against
the downloaded ZIP's checksum. This is a prerelease candidate, not a claim of
completed physical acceptance.

See [release notes](releases/v0.0.6-rc.1.md), [architecture](ARCHITECTURE.md), and the
[historical August status](history/IMPLEMENTATION_STATUS_2026-08-24.md).
