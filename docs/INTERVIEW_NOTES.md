# LivePulse interview notes

Use these as reminders, not a script. Keep claims within the evidence recorded in the repository.

## 30-second answer

LivePulse is a local-first realtime command center, but the main engineering problem is normalizing incompatible upstream systems. Football, Gmail, Spotify, GitHub, and weather have different delivery and consistency semantics. Their adapters produce canonical events; PostgreSQL and a transactional outbox make important transitions durable before Redpanda publication; idempotent projectors maintain current state separately from the Pulse Timeline. The React client uses REST as its authoritative snapshot and cursor-based WebSockets for incremental updates and recovery. Real integrations exposed bugs my fixtures missed, including a rejected Gmail history cursor and a live match that the UI still called upcoming.

## What problem does it solve?

It keeps a personal view of five systems and local service health coherent in one desktop workspace. The dashboard is the product surface; the system underneath it is the project thesis.

## Why not poll five APIs from React?

The sources do not share a cadence or failure model. Football needs quota-aware polling and state comparison; Spotify playback is ephemeral; Gmail uses an incremental history cursor; GitHub needs bounded reconciliation and can also accept signed webhooks; weather is a cached location-based observation. Backend adapters own those differences so the UI receives normalized state and durable activity instead of five provider-specific refresh loops.

## Why Redpanda?

It provides a local Kafka-compatible durable event stream that lets ingestion and projection progress independently. PostgreSQL remains the system of record for canonical history and delivery state. Redpanda is not a replacement for durable database state.

## Why a transactional outbox?

Writing PostgreSQL and publishing directly to a broker creates a dual-write gap. The event and outbox row commit in one database transaction, then a separate publisher delivers pending rows. A crash after broker acknowledgement can cause a duplicate, so the contract is at-least-once delivery with idempotent consumers.

## Why separate events from projections?

The event answers “what happened?” and is append-only. The projection answers “what is true now?” and is mutable. That makes current match state efficient to read without losing chronology or relying on replay for every page load.

## Why REST plus WebSocket instead of WebSocket-only?

The browser can miss frames while disconnected, during restart, or while hidden. REST reconstructs authoritative state and timeline history. WebSockets are a lower-latency incremental path with cursor-based replay or resync when history was missed.

## How is at-least-once handled?

The projector inserts a `(consumer, event_id)` identity in the same transaction as timeline and projection changes. Database uniqueness protects concurrent duplicate handling. A replay therefore cannot double a goal or create a second timeline entry.

## What happens when Gmail's cursor becomes invalid?

If `history.list` rejects the persisted cursor with HTTP 400 or 404, one bounded full resync uses a fresh profile history baseline and a bounded recent-message scan with metadata hydration. Credentials are retained. The replacement checkpoint commits atomically with the corresponding durable ingestion work. Other operations' 400/401/403/429 failures are not reinterpreted as cursor expiry.

## Tell me about a real bug

API-Football reported a real match as live and the canonical event pipeline was processing it, but the hero showed “UPCOMING” with a zero countdown. Tracing the complete path found two defects: `/api/v1/live-state` omitted the real-provider projection when no demo match was active, and the frontend did not normalize “First Half” as a live phase. Provider-backed normalized state now wins, stale pre-match snapshots are rejected, and the open browser updates without refresh.

## Why Tauri?

It packages the existing React experience as a Windows desktop app while keeping Python integrations, PostgreSQL state, and Redpanda event distribution in their existing services. The Rust shell owns windowing, readiness/retry, external navigation, and safe OAuth handoff; it does not acquire provider credentials or business state.

## Why not bundle PostgreSQL and Redpanda?

That would add installer and lifecycle complexity without improving the event-system design being demonstrated. Docker Compose remains the v1 local runtime substrate, and Tauri neither starts nor stops containers.

## Security model

`PERSONAL_LOCAL` is single-user and relies on loopback isolation, strict Host/Origin checks, encrypted provider credentials, bounded trusted ingress, and backend ownership of tokens. It is not a remote multi-user service. Gmail requests only `gmail.readonly`. The Tauri capability set does not grant arbitrary shell or filesystem access. PUBLIC_DEMO uses a separate sanitized database/runtime.

## Biggest tradeoff

The system keeps durable history and recovery semantics explicit, but its local v1 remains a single backend instance with in-process scheduler/realtime fan-out and Compose-managed services. Horizontal scaling or a self-contained installer would need real operational requirements before adding shared coordination or a new service lifecycle.

## What would improve in v1.1?

Start with operational evidence rather than expanding feature count: a formal long-duration GPU/runtime profile, fault injection across broker/database restarts, load tests around replay and provider cadence, production metrics/tracing, credential-key rotation/recovery procedures, and a signed installer/update path if distribution warrants it. None is claimed complete in v1.
