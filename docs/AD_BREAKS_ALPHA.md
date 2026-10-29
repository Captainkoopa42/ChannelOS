# Advertisement Breaks — Alpha Test

This branch adds the first end-to-end advertisement path for fixed Calendar channels.

## Try it

1. Open Library and add/scan the folder that contains your ad videos. ChannelOS must have indexed the files and discovered their durations.
2. Open Channel Studio and edit a channel that uses fixed calendar blocks.
3. Click Ad Breaks in the calendar toolbar.
4. Enable Enable ads in calendar gaps.
5. Paste the full path of each ad folder into the source box, separate paths with semicolons. These paths are kept separate from the channel's ordinary program sources.
6. Choose a selection strategy and click Apply to Draft.
7. Save/apply the channel, and make sure there is a gap between one fixed program's end and the next program's start. Tune to the channel during that gap.

Example: a 60-second program starts at 10:00, and the next fixed program starts at 10:04. The three-minute gap can be filled by 90-, 60-, and 30-second ads. The next scheduled program still starts at 10:04.

## Selection strategies

- Best Fit: uses a one-step lookahead to prefer combinations that leave the least unused time.
- Largest: plays the longest eligible ad that fits, then repeats the choice for the remaining time.
- Smallest: plays the shortest eligible ad that fits, then repeats.
- Sequential: uses a deterministic, opportunity-specific order and skips items that do not fit.

Ads are never trimmed in this alpha. If the remaining gap is too short for any unused ad, normal channel filler takes over for the remainder.

## What is and is not implemented yet

- Implemented: portable schema 0.4 settings, separate ad-folder resolution from normal program media, deterministic ad planning in bounded Calendar gaps, restart-stable selection for an unchanged lineup/library, and a Studio settings dialog.
- Not yet implemented: reusable ad profiles (these alpha settings are per-channel), mid-program/interval breakpoints, fades/crossfades, persisted historical rotation (such as least played), Smoosh/Expand policies, and Guide/HUD ad-break labels.
- This version calculates a gap's plan from the currently indexed ad pool. Keep the same ad files and channel schedule when checking restart determinism.
- Older channel schemas 0.1–0.3 remain supported and do not enable ads unless explicitly configured.

## Automated coverage

The tests/test_ad_breaks.py tests exercise deterministic selection, gap packing, legacy defaults, and a real ChannelRuntime selection sequence that resumes the next fixed program at its original calendar start.