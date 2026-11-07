# ChannelOS 0.0.7 Windows acceptance route

This is a test route, not a claim that physical-device checks have passed.
Record the Windows version, controller/audio devices, package commit and ZIP
SHA-256, result and relevant log path. Use a copied setup and keep its backup.

Run the existing `WINDOWS_0.0.6_ACCEPTANCE.md` regression route as well.

| Check | Expected result | Device result |
|---|---|---|
| Cold boot | Home appears without loading the Planner or scanning media again | Pending |
| Planner entry | Studio → Planner tab loads indexed collections in a worker; planner channels open on that tab; keyboard text remains text | Pending |
| Calendar conversion | Adding the first planner rule to a calendar channel asks first; Keep Calendar leaves the draft unchanged; Studio blocks stay fixed after Apply | Pending |
| Shared progression | Add the same collection 2–5 times; windows share one cursor | Pending |
| Reruns | Add an independent rerun; its progress does not consume the primary track | Pending |
| Loop vs cycle | Loop a shorter collection while another finishes; first-pass completion remains earned | Pending |
| Brackets | Try 15/30/45/60/custom; strict never cuts or speeds a program | Pending |
| Carryover and ads | Continue a long recording across windows; resume offsets and whole ad interruptions remain correct | Pending |
| Calendar precedence | Exact date beats seasonal, seasonal beats weekly, weekly beats daily; equal-priority overlaps explain blockers | Pending |
| Suspension | Pause one track for two weeks; its cursor holds and unrelated tracks continue | Pending |
| Profiles | Bind one profile to two channels with different media; update its version and explicitly reapply only one | Pending |
| Historical records | Import owned CSV/JSON data; provenance survives; missing recordings require explicit substitutes | Pending |
| Draft isolation | Drag/edit/browse/forecast; channel files, clocks, completed airings and view history remain unchanged | Pending |
| Apply | Current program/committed ads remain protected; next-cycle or safe-future effect agrees with preview | Pending |
| Manual overrides | Existing Manual Studio blocks and saved ad snapshots stay protected in a Planner channel | Pending |
| Manual cycle | Release only after the content/date gates; active program and committed ads finish | Pending |
| Air Once & Done | All planned collections stop after the safe close, including independent loops; slate/off-air/filler matches selection | Pending |
| Source loss | Unplug during a show; failure does not earn completion; return/rescan resumes the unplayed content | Pending |
| Closed-app catch-up | Close for several days and reopen; Guide/playout agree and completions/cycle closures are recorded once | Pending |
| Time zone | Check overnight schedules and both DST transitions with the packaged rules | Pending |
| Controller/keyboard | Navigate controls and dialogs; Home/Guide/Back protects a dirty draft | Pending |
| Scale/cancel | Use a large indexed collection; cancel a forecast and edit again; no stale result or GUI freeze | Pending |
| Relocation | Copy and move the portable setup to another drive letter; rules, profiles, ledgers and source offsets survive | Pending |

The automated master-plan fixture uses a 270-hour series at 15 hours/week,
three shared daily windows, a two-week scoped holiday, a later-finishing 360-hour
collection, an ALL/date/Monday gate, real Apply and simulated closed-app recovery.
Physical decoder, display, USB, gamepad and audio behavior still require this route.
