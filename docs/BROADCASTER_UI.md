# ChannelOS Broadcaster / Channel Builder

**Status:** First functional management slice  
**Product mode:** Broadcaster / Management

## Product rule

> **The user is not merely the audience. The user is the broadcaster.**

Broadcaster mode exists to let a person create and program persistent television channels without hand-writing configuration files.

It does not replace the channel-definition format, the scheduler, or the television runtime. The interface edits durable user intent; the existing ChannelOS runtime remains authoritative for what actually airs.

```text
Broadcaster UI
      |
      v
portable channel definition (YAML)
      |
      v
resolver + programming/runtime validation
      |
      v
ChannelRuntime / Broadcast Clock
      |
      +----> Guide
      |
      +----> Live TV
```

## First slice

The first Broadcaster slice provides:

- a real Broadcaster home showing the active lineup,
- current and next programming projected from the real Guide,
- mouse interaction inside the management surface,
- keyboard navigation and text entry,
- Create Channel,
- explicit Edit Existing Channel,
- channel name and description,
- numeric channel identity,
- sequential or deterministic-shuffle programming,
- preserve-order and repeat-window controls,
- source selection from already indexed library roots,
- real program-order preview before save,
- immediate Guide/runtime reload after a successful save,
- portable YAML output using Channel Definition 0.1.

The current couch shell still accepts explicit channel YAML files at startup. Broadcaster-managed definitions are additionally discovered from the configured channel-definition directory, which defaults to:

```text
channels/
```

This directory is intentionally separate from `.channelos/` runtime databases. Channel definitions are durable user intent, not disposable cache/runtime state.

In a development checkout, `/channels/` is gitignored so channels created while testing the application are not accidentally committed to the source repository.

## Safety model

Channel management is destructive enough that overwrite behavior must be explicit.

### Create never means overwrite

If a requested channel number already exists, **Create Channel fails** and tells the user to open the existing channel for editing.

If the canonical managed filename already exists but ChannelOS does not recognize it as that channel's active definition, ChannelOS also refuses to overwrite it.

There is no implicit "last writer wins" behavior.

### Edit is a separate operation

Editing begins from a selected existing channel. During this first slice, its numeric channel identity is locked.

Renumbering is deliberately not treated as a normal field edit because a channel number participates in television identity, tuning history, deterministic scheduling, and continuity state. A future explicit renumber workflow can define those semantics instead of silently mutating them.

### Validate before write

Before creating or updating a definition, ChannelOS runs the candidate through:

1. the public Channel Definition 0.1 validator,
2. the canonical media resolver,
3. the actual `ChannelRuntime.open` path against a disposable runtime database.

That means unresolved sources, missing/invalid durations, and impossible shuffle repeat guarantees fail **before** the live definition is written.

### Atomic writes and edit backup

A successful write is staged to a temporary file in the destination directory, flushed, and atomically replaced into place.

An explicit edit first copies the previous definition to a sibling `.bak` file, then performs the atomic replacement.

These protections are not substitutes for future full Export My Television / version history, but they prevent the management UI from casually destroying a working channel definition.

## Program preview

Preview does not create a second scheduling engine.

It resolves the candidate definition through the same canonical library and uses the same sequential order or `deterministic_shuffle_order` used by ChannelRuntime. Preview validation uses a disposable RuntimeStore, so previewing does not alter the actual Broadcast Clock or Viewer Clock.

## Immediate Guide integration

After a successful create/edit, the couch application rebuilds the active `GuideService` and `TelevisionRuntime` from the saved portable definitions while reusing the real persistent `RuntimeStore`.

Consequences:

- unchanged schedules retain their persisted epochs,
- a changed schedule signature receives the existing runtime's normal re-anchor behavior,
- the newly created channel appears in the Guide immediately,
- numeric tuning addresses the new lineup immediately,
- the UI does not maintain a fake second copy of channel truth.

## External automation and LLM authoring

The human-readable channel definition is intentionally more than an internal persistence format. It is an open authoring boundary.

The Broadcaster UI is one way to create a channel, but it must not become the only way. Any local or external tool that can produce a valid documented ChannelOS definition can act as a broadcaster-side authoring tool while ChannelOS remains responsible for validation and execution.

Possible authors include:

- the built-in Broadcaster UI,
- a local script,
- PowerShell or shell automation,
- a scheduled household task,
- another media-management application,
- a local LLM,
- a browser-hosted LLM used by the owner,
- or a future third-party ChannelOS programming tool.

For example, once richer programming rules exist, a user should be able to ask an LLM something conceptually like:

> Build me a Saturday-morning cartoon channel, keep older shows before noon, avoid repeats for a week, and make it Channel 4.

The LLM does not need to become part of ChannelOS. It can author or revise a portable definition, which ChannelOS then validates through the same public schema, resolver, and runtime path used by the built-in Broadcaster.

```text
human request
      |
      v
LLM / script / external tool
      |
      v
portable ChannelOS YAML
      |
      v
ChannelOS validation
      |
      v
real programming/runtime
```

This preserves an important ownership property: **the automation may be disposable; the television is not.** If the LLM, script, website, or helper application disappears, the resulting channel definition remains readable, portable, editable, and usable by ChannelOS.

Future programming-level schema design should preserve this property. Advanced features such as time blocks, marathons, weighted rotations, seasonal rules, bumpers, and feature slots should remain representable through documented durable definitions wherever practical rather than existing only as opaque UI state.

ChannelOS should therefore avoid making an LLM service, cloud account, or particular automation provider a dependency. AI-assisted programming can be powerful precisely because the durable output belongs to the user rather than to the assistant that generated it.

## Mouse and keyboard model

Broadcaster is the first management-oriented ChannelOS surface where ordinary mouse and full keyboard interaction are first-class rather than incidental.

Current bindings include:

```text
Home / Broadcaster
B                 Open Broadcaster from Home
Mouse click        Select/open Broadcaster card

Broadcaster list
Up / Down          Select channel
N                  New channel
E / Enter          Edit selected channel
Mouse click        Select channel
Double click       Edit selected channel

Channel editor
Tab / Shift+Tab    Move through fields
Mouse              Focus/edit controls
Ctrl+S             Save
Esc                Cancel editor / return
```

Text fields, combo boxes, spin boxes, check boxes, source controls, Preview, Save, and Cancel are all normal Qt controls, so mouse and keyboard behavior use the platform UI system rather than a parallel hand-coded text-entry mechanism.

## What this slice intentionally does not pretend to solve

The first slice closes the basic loop:

```text
indexed owned media
      -> create a channel
      -> choose sources and programming mode
      -> validate / preview
      -> save portable definition
      -> Guide updates
      -> tune and watch
```

The following Broadcaster work remains real future work rather than placeholder claims:

- Add to Channel from Library,
- explicit channel renumber workflow,
- delete/remove channel with confirmation and continuity rules,
- reorderable/manual programming lists,
- programming blocks,
- time-of-day schedules,
- weighted rotations,
- marathons,
- feature/movie slots,
- bumpers and station IDs,
- seasonal rules,
- richer channel artwork/presentation,
- management undo/history beyond the current edit backup,
- full export/import integration.

The architectural target remains the same: ChannelOS should make operating a personal television network approachable without hiding or confiscating the durable definitions that make that television recognizable.
