# ADR 0009: Domain-aware projection and universal Pulse Timeline

**Status:** Accepted and implemented in M3

## Context

The M1 projector owned football match state and the timeline. M3 adds Spotify, GitHub,
Gmail, and weather events. Cloning a timeline consumer for every provider risks divergent
idempotency and cursor behavior, while allowing unrelated event families into the football
reducer risks corrupting the active match.

## Decision

Keep one idempotent projector and one durable timeline. Route only `football.match.*`
canonical events through the football reducer. Route every other canonical event through a
shared timeline-only path. In one database transaction, claim `(consumer, event_id)`, apply
the optional football state update, and append the timeline entry. Commit Kafka offsets only
after the durable projection transaction succeeds. Duplicate or stale deliveries must not
duplicate timeline entries or regress match state.

The durable cursor remains the replay watermark. Timeline presentation sorts by occurrence
timestamp, then cursor for deterministic ties. Late football events therefore appear at
their historical position while cursor replay remains monotonic. Late post-fulltime events
are history-only unless the event is an explicit score correction.

## Consequences

- Non-football events never create or mutate `match_state`.
- All domains share the same canonical event, outbox, Redpanda, idempotency, timeline, and
  reconnect/replay path.
- The existing Kafka topic name `livepulse.events.football.v1` is retained for compatibility,
  although M3 uses it for all canonical domains.
- Tests cover duplicates, mixed-domain ordering, active-match authority, late football
  events, durable replay, and commit-after-projection behavior.
