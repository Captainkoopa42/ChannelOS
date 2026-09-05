# Channel Studio Concept

**Status:** First calendar implementation landed; longer-term design continues

**Implementation:** Week/month calendar Studio, media bin, timeline, and Auto Fill

**Existing Channel Builder:** Must remain available

## Purpose

ChannelOS should eventually have a visual channel-programming workspace that feels familiar to someone who has used a video or audio editor.

The interaction metaphor is an editor: browse media, drag it into a workspace, arrange programming blocks, inspect their settings, preview the resulting schedule, and save deliberately.

Channel Studio is **not** a video editor. It does not render, transcode, cut, move, or take ownership of the user's media files. It edits ChannelOS programming instructions that reference the canonical owned-media Library.

## Preserve both ways of working

The existing Channel Builder is liked and should not be replaced.

ChannelOS should follow the same pattern used by the Library:

- The new content-first Library is the primary browsing experience.
- The old Library became the secondary **Manage Sources** experience.
- A future visual **Channel Studio** becomes the creative programming experience.
- The existing Channel Builder remains the dependable quick/classic management experience.

Provisional names such as **Classic Builder**, **Quick Builder**, and **Channel Studio** describe the distinction; final interface labels can be chosen later.

## Plain-language model

- **Library:** Find the media the user owns.
- **Classic Builder:** Create and manage a channel with straightforward fields and programming settings.
- **Channel Studio:** Visually arrange how a channel is programmed.
- **Add to Channel:** Carry a Library selection into the programming workspace.
- **Save/Apply:** Deliberately commit the edited programming to the channel.

Nothing should silently alter a broadcasting channel merely because the user selected media or opened Channel Studio.

## Visual workspace concept

A possible layout is:

```text
+--------------------+--------------------------------+-------------------+
| Library / Media Bin| Channel Programming Canvas     | Inspector         |
|                    |                                |                   |
| Movies             | [Bumper][Episode][Episode]     | Selected block    |
| Shows              | [Movie--------------------]    | Order / behavior  |
| Clips              | [Shuffle Pool: Short Clips]    | In/out or rules   |
| Collections        |                                | Validation        |
+--------------------+--------------------------------+-------------------+
```

The canvas represents channel programming, not a newly rendered media file. Block width may communicate duration, while grouping and block type communicate scheduling behavior.

The initial Studio does not need to implement every block shown above.

## Library-to-Studio behavior

The smallest understandable first workflow is:

1. Open Channel Studio.
2. Browse the canonical Library in the Studio's media pane.
3. Drag one or more owned-media assets into a draft channel sequence.
4. Reorder or remove the draft blocks.
5. Validate the resulting channel definition.
6. Press Save/Apply.
7. Only then does ChannelOS update the channel's programming.

A later Library shortcut may say **Open in Channel Studio**. It would carry the current Library selection into the Studio without immediately changing any channel.

Possible future conveniences include starting a new channel from selected media or adding a real collection/folder as a group. These are ideas, not requirements for the first Studio version.

UI shelves such as Continue Watching, search results, and All Media are browsing views and must not automatically become channel sources. Only durable media identities, real collections, folders/sources, or explicit programming rules should be saved.

## Important terminology

### Draft sequence or programming list

A draft sequence is the ordered programming being edited. It is not an immediate live-playback queue and does not interrupt the current broadcast.

Example:

```text
1. Fellowship of the Ring
2. The Two Towers
3. Return of the King
```

Adding The Hobbit creates a draft change. The broadcasting channel changes only after Save/Apply.

### Fixed media

A fixed programming block references exact stable media asset IDs.

Example: a trilogy channel contains exactly three selected films. Adding more films to the surrounding folder does not change that fixed selection.

### Dynamic source

A dynamic programming block references a durable source or rule.

Example: a Fortnite recordings folder is a rotating source. Newly indexed eligible recordings can become part of that channel without manually adding every file.

The existing ChannelOS source-based channel system is already conceptually close to dynamic programming. Channel Studio should visualize this behavior rather than inventing a second incompatible media system.

## Architectural invariants

1. The existing Channel Builder remains usable.
2. Channel Studio and the Classic Builder operate on the same canonical channel definitions wherever their feature sets overlap.
3. The canonical media index remains the source of stable asset identity.
4. Editing a channel never edits, moves, or owns the underlying media files.
5. Opening Studio or selecting media never changes the live channel.
6. Save/Apply is explicit and validated.
7. On Demand watch history remains unrelated to channel programming.
8. Channel programming continues to produce authoritative Broadcast Clock truth.
9. A simpler editor must never silently erase Studio features it cannot represent.
10. Existing portable YAML channel definitions remain a compatibility boundary unless a versioned schema change is intentionally designed.

## Implemented first boundary

The first Channel Studio slice now supports:

- create or open a channel,
- edit channel number and name,
- week and month calendar views,
- fixed clock-based blocks stored as stable Library asset IDs,
- sequential or shuffle filler for all uncovered time,
- Auto Fill that generates real editable blocks for the visible range,
- drag exact Library assets into the draft,
- reorder and remove blocks,
- validate before saving,
- preview durations and exact local calendar times,
- return to the Classic Builder without losing representable information.

Recurring weekly templates, weighted rotations, bumpers, virtual in/out points,
marathons, nested collections, and multiple editor lanes remain later work.

## Decisions made for the first implementation

- Studio writes the explicit portable Channel Definition `0.2` calendar extension.
- Applying a changed calendar changes the schedule signature and uses the normal
  runtime re-anchor/Viewer Clock invalidation behavior.
- Classic Builder remains available, while Studio is the safe editor for a
  calendar channel so advanced blocks are not silently erased.
- Fixed blocks reference stable Library asset IDs; source roots remain the
  dynamic filler pool.
- The initial canvas is a clock-based week/month horizon with one timeline lane.
- Opening, browsing, Auto Fill, and drag/drop remain draft-only. Apply is explicit.

Undo/redo, durable unsaved-draft recovery, and recurring calendar templates are
still intentionally unresolved.

## Product intent in one sentence

> Keep the dependable existing Channel Builder, while adding a visual workspace where the user can drag, arrange, and program owned media like an editor—without ChannelOS ever pretending to edit or take ownership of the media itself.
