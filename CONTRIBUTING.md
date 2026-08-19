# Contributing to ChannelOS

ChannelOS is pre-alpha. The most important contribution rule right now is to preserve the project's ownership contract while the implementation is still easy to change.

## Before changing architecture

Read:

1. `docs/VISION.md`
2. `docs/ARCHITECTURE.md`
3. `docs/decisions/0001-local-first-portable-core.md`

Changes that make local playback dependent on a cloud account, hide portable configuration in an undocumented format, or make user media dependent on the ChannelOS database conflict with the project direction.

## Development

```bash
python -m pip install -e .[dev]
pytest
```

Keep initial modules small and testable. Prefer explicit deterministic behavior before adding automatic or intelligent scheduling.

## Specs

Changes to the channel-definition format should update the corresponding specification and tests in the same change. Schema changes should be versioned rather than silently changing the meaning of an existing file.
