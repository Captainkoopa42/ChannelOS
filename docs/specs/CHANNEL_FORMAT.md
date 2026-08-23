# Channel Definition Format

**Specification:** ChannelOS Channel Definition 0.1  
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

Required string. For the initial draft the only supported value is `0.1`.

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
- resolved absolute media IDs

Those values belong in runtime state and may be safely deleted without altering the user's channel intent.

## Validation philosophy

The parser should reject ambiguous or unsupported input early. Unknown top-level keys are rejected in draft 0.1 so mistakes are visible rather than silently ignored. Future schema migrations should be explicit.

## Portability rule

A third-party program should be able to implement this specification without importing ChannelOS source code. That is a feature, not a leak.
