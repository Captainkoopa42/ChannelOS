# Channel Definition Format

**Specification:** ChannelOS Channel Definition 0.1 and 0.2

**Status:** Draft

## Purpose

A channel definition is a portable, human-readable description of a ChannelOS channel. It describes what the user intends the channel to be. It does **not** contain volatile runtime state such as current playback position or generated schedule cache.

The initial serialization format is YAML.

## Minimal valid channel

```yaml
schema_version: "0.1"
channel: 7
name: Sci-Fi
sources:
  - path: /media/TV/Stargate SG-1
programming:
  mode: sequential
```

## Top-level fields

### `schema_version`

Required string. Supported values are:

- `0.1` for sequential and shuffle channels,
- `0.2` for the compatible calendar extension used by Channel Studio.

### `channel`

Required integer from `1` through `9999`. Leading-zero display is a UI concern, so channel `7` may be rendered as `07` without storing it as a string.

### `name`

Required non-empty string.

### `description`

Optional human-readable string.

### `sources`

Required non-empty list. Draft 0.1 supports filesystem path sources:

```yaml
sources:
  - path: /media/TV/Stargate SG-1
  - path: /media/TV/Star Trek - The Next Generation
```

A later schema may add typed selectors such as collection IDs, tags, or adapter-backed sources. New source types must not silently change the meaning of existing definitions.

### `programming`

Required mapping.

Draft 0.1 fields:

- `mode`: required; `sequential` or `shuffle`
- `preserve_episode_order`: optional boolean, default `false`. For `sequential`
  channels, `true` makes source declaration order authoritative and applies a
  deterministic media-aware order inside each source: explicit season/episode
  markers first, then episode/leading ordinals, then release-year-like tokens,
  then natural path order. This requires no cloud metadata and never renames
  user files. `Preview` remains the authoritative way to inspect the resolved
  program order before saving.
- `avoid_repeat_days`: optional non-negative integer, default `0`

Example:

```yaml
programming:
  mode: shuffle
  preserve_episode_order: false
  avoid_repeat_days: 14
```

Draft 0.2 retains those fields and adds calendar programming:

- `mode: calendar`
- `filler_mode`: `sequential` or `shuffle`; this is the ordinary channel pool
  used wherever no fixed calendar block is airing
- `calendar`: a non-empty list of exact fixed blocks

Each fixed block contains an aware ISO-8601 `start_utc` and a stable Library
`asset_id`. ChannelOS sorts blocks by their normalized UTC start and rejects
duplicate starts, unavailable assets, unknown/non-positive durations, and
overlapping programs.

```yaml
schema_version: "0.2"
channel: 9
name: Saturday Television
sources:
  - path: /media/TV
programming:
  mode: calendar
  filler_mode: shuffle
  preserve_episode_order: false
  avoid_repeat_days: 0
  calendar:
    - start_utc: "2026-09-12T12:00:00+00:00"
      asset_id: "sha256:0123456789abcdef..."
    - start_utc: "2026-09-12T12:24:00+00:00"
      asset_id: "sha256:fedcba9876543210..."
presentation:
  number_width: 3
```

The Studio displays dates and times in the machine's local timezone, but saves
aware UTC timestamps so the portable definition is unambiguous. Calendar
blocks are one-time fixed starts. Before, between, and after those blocks, the
configured filler cycle keeps the channel broadcasting without decoding every
channel in the background.

### `presentation`

Optional display hints. These do not change media ownership or scheduling semantics.

```yaml
presentation:
  number_width: 2
```

## Runtime state is separate

The following do **not** belong in the portable channel definition:

- current media item
- current playback timestamp
- generated schedule cache
- recently played item IDs
- scanner cache
- generated/resolved media lists (an explicit 0.2 calendar block may contain
  the stable asset ID the user deliberately scheduled)

Those values belong in runtime state and may be safely deleted without altering the user's channel intent.

## Validation philosophy

The parser rejects ambiguous or unsupported input early. Unknown fields are
rejected so mistakes are visible rather than silently ignored. Schema
migrations are explicit; a 0.1 channel never silently acquires 0.2 semantics.

## Portability rule

A third-party program should be able to implement this specification without importing ChannelOS source code. That is a feature, not a leak.
