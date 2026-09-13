# ADR 0010: Quota-aware football polling and rolling fixture horizon

**Status:** Accepted and implemented in M3

## Context

The local API-Football budget is 100 calls per UTC day, with five calls reserved. A static
ten-minute live interval is too slow for an active followed match, while polling every
competition independently at a short cadence exceeds the free-tier budget.

## Decision

Resolve and cache the locked competition catalog, then discover fixtures for a rolling
seven-day UTC horizon with one scoped request per competition and a 20-hour result cache.
Refresh the catalog weekly. Query live fixtures once across all resolved competitions and
fetch fixture details only when needed, in batches of at most 20 IDs.

For a relevant live match, use 150 seconds while quota is healthy. Degrade to a three-minute
floor with 31–50 requests remaining, five minutes with 16–30, and ten minutes with 6–15.
Hold the final five-call reserve until the next UTC reset. Lengthen cadence proportionally
when a poll requires additional detail requests. Use slower state-based checks for halftime,
upcoming fixtures, and periods with no live/upcoming match. Honor `Retry-After` and surface
the selected interval, reason, quota remainder, cooldown, and reset through provider health.

## Consequences

- A live query costs one request per batch rather than one per competition. At 150 seconds,
  the base cadence is about 24 batched live queries per hour, plus occasional detail batches.
- The rolling discovery cache costs about 11 calendar calls per day for the 11 locked
  competitions; the five-call reserve remains protected.
- Runtime tests deterministically cover healthy cadence, quota degradation, no-live slowdown,
  Retry-After, daily budget exhaustion, and recovery after reset.
- The scheduler remains single-instance. Cross-instance quota coordination is future work.
