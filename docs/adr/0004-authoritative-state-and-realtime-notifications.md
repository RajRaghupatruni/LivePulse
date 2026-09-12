# ADR 0004: REST snapshots remain authoritative; realtime is incremental

- **Status:** Accepted
- **Date:** 2026-09-12

## Context

WebSocket delivery can be interrupted, duplicated, or outlive the state snapshot a browser is rendering. A second-monitor command center must remain useful after refresh and recover from missed messages without treating a socket stream as durable state.

## Decision

REST live-state and timeline endpoints reconstruct the authoritative browser view. WebSocket messages are incremental notifications carrying durable timeline cursors and state/event identity. The frontend rejects stale versions within one match. A notification for a different match is kept as timeline history but triggers an authoritative REST refresh because the projector can emit inactive-match history and only REST identifies the active match. Timeline items are deduplicated by event identity, and connection UX distinguishes reconnecting from resynchronizing.

## Consequences

- A browser refresh can reconstruct the match and timeline without replaying every socket message.
- Cursor replay improves recovery, while an explicit resync signal remains valid when replay is impossible.
- WebSocket fan-out is not an event store and must not become the only source of truth.
- Multi-instance fan-out remains future work; the local in-memory manager is scoped to one backend process.
