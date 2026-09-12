# LivePulse Product Requirements

This document is the locked product direction and source of truth. Milestone implementation status is explicit so future work cannot silently remove or defer a requirement.

## Product thesis

LivePulse is a single-user personal realtime command center intended to stay open on a second monitor all day. Its core is a Python realtime event platform: ingest heterogeneous external state, normalize observations into immutable canonical events, durably persist them, publish them through a durable event stream, process them with idempotent consumers, maintain authoritative projections, expose a unified timeline, and push recoverable realtime updates to the browser. It is designed for observability, failure handling, replay, and evidence-backed testing.

## Locked product direction (P0)

| Requirement | Status |
|---|---|
| Unified Pulse Timeline across product domains | **Implemented in M1 foundation** (football events only); cross-domain unification remains future work |
| Football: EPL, La Liga, Bundesliga, Ligue 1, EFL Championship, Champions League, Europa League, FA Cup, Carabao Cup, Serie A, MLS | **Not implemented**; M1 deterministic simulated match only |
| Spotify current playback and controls | **Not implemented** |
| Exactly five monitored GitHub repositories initially: Strata, Tandem, OptiScale, LivePulse, Portfolio | **Not implemented** |
| Read-only Gmail | **Not implemented** |
| Weather | **Not implemented** |
| Persistent live local date/time/day | **Implemented in M1 UI** |
| Deterministic Focus Engine | **Implemented in M2**; normalized backend-owned focus contract with deterministic football attention, transient event expiry, and persistent lifecycle state; other source priorities remain future work |
| Adaptive command-center UI | **Implemented in M2 foundation**; focus-led desktop shell driven by backend state; future provider surfaces remain absent until implemented |
| Match Mode | **Implemented in M2**; match lifecycle derives Match Mode from backend focus state |
| Provider and system health visibility | **Implemented in M2 for observable local components** (PostgreSQL, Redpanda, outbox publisher, projector, realtime fan-out, and demo source); real provider health is future work |
| Full ChatGPT-style chat using GPT-5.6 Luna | **Not implemented** |
| Streaming AI responses | **Not implemented** |
| OpenAI web search for freshness-dependent questions | **Not implemented** |
| LivePulse-aware AI tools | **Not implemented** |
| Command bar for data queries, commands, and general AI questions | **Implemented in M2 foundation**; explicit local command registry for demo/reset/health/match/close. Data queries and general AI questions remain future work |
| WebSocket reconnect/resynchronization | **Implemented in M1 foundation**; reconnect/refetch and cursor-gap signal |
| Security/threat model | **Not implemented**; required before external integrations/production |
| Structured logging | **Implemented in M1 foundation** |
| Metrics and tracing | **Not implemented**; instrumentation boundaries established |
| Failure tests | **Partially implemented through M2**; transaction rollback, transient publish retry, duplicate/concurrent delivery, stale versions, WebSocket recovery, consumer batch commit ordering, health normalization, and focus expiry are tested; process-kill and prolonged broker restart injection remain future work |
| Load tests | **Not implemented** |
| CI | **Implemented in M1 foundation** |
| Terraform production architecture | **Not implemented** |
| Deterministic public demo mode | **Not implemented**; local deterministic demo only |

## M1 scope

M1 proves the architecture end-to-end with one deterministic simulated football provider and one comeback scenario. It includes a provider-independent immutable event envelope; PostgreSQL event, transactional outbox, match-state, timeline, and idempotency storage; Redpanda publication and consumption with at-least-once delivery; a recoverable WebSocket foundation; APIs; a dark command-center shell; deterministic attention; tests; local infrastructure; scripts; and CI.

M1 does not implement Spotify, Gmail, GitHub, weather, OpenAI, a real football API, Redis, Kubernetes, production deployment, or the future requirements marked not implemented above.

M2 keeps the M1 event path unchanged and adds a backend-owned structured Focus Engine, Match Mode, a desktop focus-led shell, observable local system-health state, richer timeline presentation metadata, recovery-state UX, and an explicit local command-router foundation. The system-health API reports observations and worker heartbeats, not hypothetical provider availability. The command bar does not call AI and clearly identifies unknown natural-language requests as future intelligence functionality.

## Product behavior requirements

- Provider-specific DTOs stop at ingestion adapters and never appear in domain or frontend contracts.
- Canonical events are immutable and timestamped in UTC. Corrections are modeled as new events, never mutation of history.
- An important discovered event is committed together with its outbox message before it is considered published.
- Publication is at-least-once. Consumers must be idempotent.
- Event history answers “what happened”; projections answer “what is true now.”
- The browser treats WebSocket delivery as lossy and can reconstruct authoritative state from APIs.
- The Pulse Timeline is core infrastructure and product functionality.
- Redis, if introduced later, cannot be the only durable copy of critical data.
- Future AI is never authoritative application state and receives no arbitrary database/code execution privileges.

## Milestone status policy

Every milestone must update this table and `DEFINITION_OF_DONE.md`. Future requirements may be changed only through an explicit product decision and documented ADR; they must not disappear through implementation drift.
