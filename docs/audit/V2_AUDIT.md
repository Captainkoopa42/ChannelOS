# ChannelOS V2 audit

A top-down review before the Windows V2 release. The codebase has about 25,900
lines of Python and 14,400 lines of QML/JS.

## Method

- Ran static analysis with ruff over pyflakes, bugbear, pylint errors and
  warnings, performance and security rules.
- Profiled the expensive paths: ad catch-up, Guide projection, startup imports.
- Captured QML warnings while visiting every couch screen, the Studio Planner
  tab and each Planner dialog.
- Checked dynamic SQL, SQLite connection settings and test-process stability.
- Ran the full suite on Python 3.12 and 3.13, the versions CI and Windows use.

## Fixed in this pass

| Area | Finding | Change |
| --- | --- | --- |
| Performance | WAL databases synced to disk on every commit. Ad catch-up makes about three commits per program, so fsync was ~40% of catch-up time. | Every WAL connection now uses `synchronous=NORMAL`, which SQLite documents as corruption-safe in WAL. A power cut can lose only the newest commits, and plans are deterministic and re-derived. Catch-up for one day of a dense ad channel went from 1.54 s to 0.75 s; NTFS fsync is slower than Linux, so the Windows gain should be larger. |
| Performance | Catch-up computed and discarded a SHA-256 occurrence id per program. | Removed. |
| Performance (earlier on this branch) | Ad rotation counting was quadratic. | Now incremental with a versioned cache: 11.6 s → 1.7 s at +2 days. |
| Stability | A Studio layout test segfaulted on Python 3.12 (Windows and Linux) after other QML tests, which blocked the Windows build. | The test now measures controls in QML instead of wrapping every item from Python, and teardown order is fixed in the ad-settings test. |
| Stability | The Planner embedded in Studio built a second, unused ad editor. | It is only created when the Planner runs standalone. |
| Hygiene | 19 unused imports and 3 unused variables. | Removed. ruff's pyflakes rules now pass cleanly. |

## Checked and fine

- **Dynamic SQL.** Every one of the 23 `f"..."` SQL statements uses code
  constants or `?` placeholders. None uses user input.
- **Loop closures.** The 7 bugbear B023 findings call the closure within the
  same iteration (a sort key, `attempt()`), so none is a real bug.
- **QML warnings.** None while switching every couch screen, every Planner
  tab, or opening each Planner dialog.
- **Startup.** Importing the whole app takes about 125 ms before Qt.
  PySide, libVLC and the Planner load lazily.
- **Background work.** Planner forecasts, channel mutations, library scans and
  artwork all run on worker threads. Results are tagged with a generation or
  token, so stale results are dropped.

## Recommendations (not changed)

1. **Batch ad catch-up commits.** Even with NORMAL sync, about 10,700 commits
   for three days still cost about 0.9 s. Committing per catch-up step instead
   of per program would remove most of that. It changes when plans become
   visible to other connections, so it needs its own change and tests.
2. **Blind `except Exception` (47 sites).** Most guard optional platform
   features (VLC events, controller polling, artwork). Log at debug level where
   they currently pass silently, so field logs can explain odd behaviour.
3. **Settings screen rows are index-based in both QML and Python.**
   `SETTINGS_FIRST_ACTION` and `SETTINGS_ROW_COUNT` in `couch_qt.py` now mirror
   `SettingsScreen.qml`. A keyed row model shared by both would remove the
   duplication.
4. **Release tag.** `release-candidate.yml` publishes the fixed tag
   `v0.0.7-rc.1`, which already exists, so later pushes cannot publish. Move it
   to the V2 version before tagging the release.
