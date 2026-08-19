# ADR-0001: Local-first, portable core

**Status:** Accepted  
**Date:** 2026-08-18

## Context

ChannelOS exists in response to a media environment where access is increasingly conditional on accounts, licenses, provider availability, and proprietary applications. Recreating those dependencies inside ChannelOS would contradict the project's purpose.

## Decision

The core system will be local-first and will treat the user's media library as external, durable property.

1. Core channel playback will not require a ChannelOS account or remote authorization server.
2. Media will not be converted into an application-only proprietary container.
3. Channel definitions will use a documented portable format.
4. Volatile runtime state will be separate from channel intent and media.
5. Internet-dependent integrations, if added, will be optional adapters rather than core authorization dependencies.
6. ChannelOS will not inject advertising into local media playback.

## Consequences

### Positive

- The user's library survives application failure or abandonment.
- Backups are understandable.
- Third-party tooling can read channel definitions.
- Offline operation is a first-class test condition.
- Architectural decisions can be judged against a clear ownership boundary.

### Costs

- Some cloud conveniences cannot be treated as assumptions.
- Portable schemas require migration discipline.
- Local metadata and state management become first-class engineering work.
- Provider integrations may be less seamless than proprietary vertically integrated systems.

These costs are accepted because they preserve the project's reason to exist.
