# Planner inside Channel Studio

The Broadcast Planner is no longer a separate screen in Channels. It is the
**Planner** tab of Channel Studio, after Day, Week and Month. Nothing in the
calendar tabs was removed or changed.

## One channel, one Apply

- **Identity.** Studio's channel number, name and description are the only
  identity fields. The Planner tab has none of its own.
- **Apply.** Studio's *Apply to Channel* (and Ctrl+S) applies whichever tab you
  are on. When planner rules exist, Studio sends its identity, calendar blocks
  and ad settings together with the planner rules in one mutation. Apply waits
  for a current forecast and refuses a Blocked one, naming the first issue.
- **Media bin.** On the Planner tab the Studio bin's first tab becomes
  **COLLECTIONS**: the planner's indexed collections, with + Track, + Rerun,
  + Filler pool and drag-to-hour. AD BIN is unchanged.
- **Ads.** Studio's Ad Breaks / Advanced Ad Settings drive the planner forecast.
- **Draft state.** One *UNAPPLIED DRAFT* badge and one discard prompt cover
  calendar and planner edits. Planner feedback appears in Studio's footer.

## Routing

- Channels → *Open Studio* (or double-click / Edit) opens planner channels on
  the Planner tab and calendar channels on their calendar.
- *New Planner* and *Open Planner* were removed from Channels. A new planner
  channel starts with *New in Studio* → Planner.

## Converting a calendar channel

A calendar channel's Planner tab starts empty. Adding the first track or airing
window asks **Make this a Planner channel?** *Keep Calendar* leaves the draft
exactly as it was; *Use Planner* adds the rule. The channel only changes on
Apply, and its Studio blocks stay fixed as protected manual blocks that the
planner schedules around.

## Readable controls

Rule values are shown as words (for example *Play filler*, *Fit inside the
window*, *Next safe moment*). The first-show anchor is a date picker plus a
time in the channel's time zone, chosen from the IANA list; the stored value is
still an ISO timestamp with the correct UTC offset for that date. Times that a
daylight-saving change skips are refused with an explanation.
