# ChannelOS 0.0.6 Windows acceptance route

Record Windows version, device/controller model, candidate commit from
`PACKAGE-BOM.json`, downloaded ZIP SHA-256, result and any log path for each check.
Use a copy of an existing setup for upgrade tests and retain the pre-upgrade copy.

| Check | Expected result | Device result |
|---|---|---|
| Fresh extraction and New Library | Starts without separately installed Python/Qt/VLC; indexes owned media | Pending |
| Upgrade a copied 0.0.5 setup | Same channels and viewer positions; schema-2 backup retained | Pending |
| Library Add to Channel | Adds an outside clip without changing ads, shuffle settings or calendar blocks | Pending |
| Numeric input race | Type 1, immediately Home/Guide, return to channel 37; no stale CH 1 or delayed retune | Pending |
| Alternative tuning | Type 1 then channel-up/down/previous/Guide tune; only the selected channel tunes | Pending |
| Unavailable sources | One missing source leaves healthy channels playable; all missing leaves management usable; reconnect/rescan recovers | Pending |
| Source removal | Blocks removal of a used file/subfolder/calendar/filler/ad source; unused source removal leaves original files | Pending |
| Delete/recreate | Reused number starts fresh with ads off when selected; predecessor history remains archived | Pending |
| Advanced ads | Override duration/fitting/trim; Preview, Apply and reopen agree; Cancel and Use Profile Defaults work | Pending |
| Studio arranging | Unequal swaps and moves have correct ad timing; fixed starts never shift silently | Pending |
| Queue and ledger | Insert earlier shows, browse ahead, remove future shows and restart; no duplicate queue use or abandoned airing counts | Pending |
| Live / behind / ahead | Pause, seek, change channel, restart and Go Live preserve the intended clocks | Pending |
| Audio devices | Switch speakers/headphones while playing; audio follows selection and survives restart appropriately | Pending |
| Controller | Navigate all screens, unplug/replug XInput controller, tune and manage dialogs without trapped focus | Pending |
| Physical USB move | Copy/open setup, safely close, move to another port/PC/drive letter and reopen with media, plans and history intact | Pending |

A defect report should include the action sequence, expected/actual result, media
and ad durations, the tested commit/checksum and relevant ChannelOS logs. Keep
user media private; small owned test clips are sufficient for reproduction.
