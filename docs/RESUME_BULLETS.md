# LivePulse resume reference

The Portfolio repository contains `public/resume.pdf` but no editable resume source. These verified bullets are the canonical text reference; update the PDF only from an editable original.

**LIVEPULSE — REALTIME PERSONAL EVENT PLATFORM**
Python, FastAPI, PostgreSQL, Redpanda/Kafka, React, TypeScript, Tauri, Docker

- Architected an event-driven platform unifying five external systems with incompatible delivery models through canonical events, a PostgreSQL transactional outbox, Redpanda streams, idempotent projections, durable history, and cursor-based WebSocket recovery.
- Built integrations for live football, Spotify OAuth/playback, read-only Gmail incremental sync, GitHub reconciliation, and weather, including adaptive polling, checkpoint recovery, rate-limit handling, encrypted credentials, deterministic deduplication, and degraded/recovery states.
- Shipped a Windows Tauri command center with semantic realtime motion and a lazy-loaded 3D atmosphere; validated real live-match propagation end to end from provider observation through outbox, Redpanda, projector, REST/WebSocket, and the already-open UI.

Avoid describing LivePulse as a public multi-user production service or claiming scale, user counts, throughput, or FPS measurements.
