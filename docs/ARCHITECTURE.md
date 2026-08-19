# ChannelOS Architecture

**Status:** Draft 0.1  
**Phase:** 0 — Skeleton

## Architectural objective

ChannelOS should behave like a television system while remaining structurally subordinate to the user's media library.

The core architectural rule is simple:

> ChannelOS may index, schedule, remember, and present media. It must not become the only thing capable of interpreting or recovering that media.

## System boundaries

```text
+---------------------------------------------------------+
|                    TV / Remote UI                      |
|            Live View | Guide | Library                 |
+---------------------------+-----------------------------+
                            |
                            | local API / IPC
                            v
+---------------------------------------------------------+
|                    Channel Runtime                     |
|        tuning | continuity | now/next | handoff        |
+---------------------+-------------------+---------------+
                      |                   |
                      v                   v
+---------------------------+   +-------------------------+
|    Programming Engine     |   |    Playback Adapter     |
| sequence | shuffle | time |   | mpv / VLC / future     |
+-------------+-------------+   +------------+------------+
              |                              |
              +---------------+--------------+
                              v
+---------------------------------------------------------+
|                 Media Index / State                    |
| ids | metadata | history | mappings | playback state   |
+---------------------------+-----------------------------+
                            |
                            v
+---------------------------------------------------------+
|                    Source Adapters                     |
|        local filesystem | NAS | removable media        |
+---------------------------------------------------------+
```

## Separation of concerns

### Media

The media layer is owned by the user and exists independently of ChannelOS. Early implementations should reference files by path plus stable identity metadata rather than importing media into an application-controlled container.

### Definitions

Channel definitions describe intent: channel number, name, source selectors, and programming behavior. They must be human-readable and versioned.

### Runtime state

Watch progress, current sequence position, repeat history, generated schedule, and cache data belong in runtime state. Runtime state must never be required to recover the underlying media.

### Programming

The programming engine converts a channel definition plus indexed media plus runtime state into an ordered timeline. Its choices should be explainable.

### Playback

Phase 0 should delegate decoding to a mature player. ChannelOS owns selection and handoff, not codecs.

### UI

The TV UI is a client of the runtime. It should not contain the authoritative scheduling logic. That separation makes future desktop, appliance, phone-remote, and multi-TV clients possible.

## Initial implementation choices

- **Language:** Python for the first reference core and test harness.
- **Definitions:** YAML, versioned with `schema_version`.
- **State:** SQLite when persistent runtime state begins.
- **Playback:** external adapter first, likely mpv as the initial target.
- **Communication:** local-only process calls initially; local API/IPC once UI and runtime split.
- **Networking:** no internet requirement for core channel operation.

These are implementation choices, not ownership invariants. They can change without changing the project's identity.

## Trust boundaries

A future plugin/source system should assume extensions are untrusted until explicitly granted capability. Plugins should not silently receive unrestricted filesystem or network access.

## Phase 0 exit condition

Phase 0 is complete when ChannelOS can:

1. Load a documented channel definition.
2. Resolve at least one local media source.
3. Assign stable indexed identities to discovered files.
4. Hand one selected media item to a playback adapter.
5. Preserve the distinction between portable definition and disposable runtime state.

The current repository implements item 1 and establishes the contract needed for the rest.
