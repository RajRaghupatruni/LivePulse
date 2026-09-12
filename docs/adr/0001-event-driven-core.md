# ADR 0001: Event-driven core

- Status: Accepted
- Date: 2026-09-12

## Context

LivePulse must bring heterogeneous changing state into one durable timeline while maintaining a separate current view and supporting replay, recovery, and later providers. Directly writing UI state from providers would couple integrations to the frontend and lose history.

## Decision

All provider observations pass through ingestion and normalization into immutable, provider-independent canonical events. Events are the durable “what happened” record. Consumers build authoritative projections such as match state and the Pulse Timeline. The browser reads projections through APIs and receives best-effort WebSocket notifications.

## Consequences

Provider adapters can change without changing domain/frontend contracts. Replay and idempotent consumers become possible. The architecture has more components than a direct CRUD app, but M1 exercises the full path with one deterministic simulator. The timeline remains core functionality as product domains grow.
