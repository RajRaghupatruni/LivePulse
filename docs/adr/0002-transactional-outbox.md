# ADR 0002: Transactional outbox

- Status: Accepted
- Date: 2026-09-12

## Context

PostgreSQL and Redpanda do not share a transaction. Writing an event to the database and then publishing directly can lose publication on a crash; publishing first can expose an event that was never committed.

## Decision

Ingestion commits each canonical event and matching outbox row in one PostgreSQL transaction. A separate publisher retries pending rows and marks publication only after broker acknowledgement. Publishing is at-least-once; consumers deduplicate by event identity.

## Consequences

There is no claim of exactly-once delivery. A crash between broker acknowledgement and DB acknowledgement can publish a duplicate, so the projector uses durable idempotency. Pending records survive restart and can be inspected/retried.
