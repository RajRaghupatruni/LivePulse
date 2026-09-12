# ADR 0007: Single-instance provider scheduler

**Status:** Accepted for the M3 integration foundation

## Context

Football, Spotify, Gmail, and Weather need scheduled observation with different cadences and failure behavior. P0 runs one backend instance, and GitHub webhooks should not be forced into a polling loop.

## Decision

Provide a small asyncio scheduler over explicitly registered poll sources. It bounds concurrent jobs, times out each observe/observation-handoff operation, asks each source for its next cadence, jitters intervals, applies capped exponential backoff after failures, honors an absolute provider `Retry-After`, and updates provider health. Scheduler shutdown cancels active poll tasks and awaits them. Each registered source has one long-lived task; polling does not spawn an unbounded task per tick.

The scheduler is not distributed and does not own provider-specific cadence. A later football source can adapt cadence from scheduled/soon/live/halftime/fulltime state. Webhook sources use their own verified request path, and durable synchronization cursors use shared checkpoint storage.

## Consequences

- Provider polling failures remain visible and retry rather than silently stopping.
- Provider observations are handed to an application callback; the source itself does not write projections or timeline state.
- The scheduler starts no work unless concrete sources are registered.
- Multi-instance leases, persistent schedules, and global rate-limit coordination remain future operational work.
