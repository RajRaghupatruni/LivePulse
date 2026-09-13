# ADR 0003: Redpanda event stream

- Status: Accepted
- Date: 2026-09-12

## Context

M1 needs a local durable Kafka-compatible stream to prove event publication, partitioning, consumer offsets, and restart behavior without introducing a managed cloud dependency.

## Decision

Run Redpanda in Docker Compose and use one versioned topic, `livepulse.events.football.v1`, with a modest local partition count. The outbox publishes all M3 canonical domains to that existing topic, keyed by subject ID. Its football-specific name is retained for compatibility; the topic remains a generic canonical-event stream. The Python service uses aiokafka, an asyncio Kafka client.

## Consequences

Kafka-compatible operations and partition ordering are available locally. M1–M3 remain at-least-once and use PostgreSQL as durable source/history. Topic count and broker configuration stay deliberately small; production sizing, security, and any future topic migration are later work.
