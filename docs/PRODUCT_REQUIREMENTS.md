# LivePulse Product Requirements

This document is the locked product direction and source of truth. Milestone implementation status is explicit so future work cannot silently remove or defer a requirement.

## Product thesis

LivePulse is a single-user personal realtime command center intended to stay open in a local fullscreen desktop application. The current React frontend runs in a local browser for development and fallback, and is structured for a later local desktop shell without importing shell APIs into UI components. Its core is a Python realtime event platform: ingest heterogeneous external state, normalize observations into immutable canonical events, durably persist them, publish them through a durable event stream, process them with idempotent consumers, maintain authoritative projections, expose a unified timeline, and push recoverable realtime updates to the UI. It is designed for observability, failure handling, replay, and evidence-backed testing.

## Locked product direction (P0)

| Requirement | Status |
|---|---|
| Unified Pulse Timeline across product domains | **Implemented** for football, Spotify, GitHub, Gmail, and weather through one durable timeline; final React UI provides domain-aware chronology, safe details, freshness and cursor history |
| Football: EPL, La Liga, Bundesliga, Ligue 1, EFL Championship, Champions League, Europa League, FA Cup, Carabao Cup, Serie A, MLS | **Implemented in M3** with API-Football polling, canonical/outbox events, authoritative football projection, quota-aware cadence, seven-day upcoming horizon, and a durable quiet initial-fixture baseline |
| Spotify current playback and controls | **Implemented in M3 backend** with OAuth, encrypted credentials, playback polling, playback/device endpoints, and typed commands; requires local credentials and an authorized Premium account |
| Exactly five monitored GitHub repositories initially: Strata, Tandem, OptiScale, LivePulse, Portfolio | **Implemented in M3 backend** with HMAC-validated webhooks, delivery dedupe, and bounded REST reconciliation; requires an owner, webhook secret and/or token |
| Read-only Gmail | **Implemented in M3 backend** with `gmail.readonly`, encrypted credentials, bounded metadata sync, and transactional history checkpoints; requires Google OAuth setup |
| Weather | **Implemented** with Open-Meteo current/daily conditions and meaningful-change events, searchable persisted locations, five recent places, and location-aware atmosphere; legacy coordinates/timezone are bootstrap fallback only |
| Persistent live local date/time/day | **Implemented in M1 UI** |
| Deterministic Focus Engine | **Implemented**; football `FocusState` remains authoritative, and ADR 0012 adds server-selected cross-domain `dominant_focus` for important Gmail, CI failures, and provider degradation |
| Adaptive command-center UI | **Implemented in final UI milestone**; provider-backed, reference-led landscape/portrait compositions, state-aware surfaces, and a shell-agnostic platform boundary ready for a later local desktop shell |
| Match Mode | **Implemented**; authoritative match lifecycle drives the main operating stage, with upcoming, live, halftime, event, and full-time transitions |
| Provider and system health visibility | **Implemented in M3** for local components and registered providers, with disconnected/unconfigured, connecting, healthy, stale, rate-limited/degraded, auth-failure, provider-failure, and resyncing states where evidence supports them |
| Full ChatGPT-style chat using GPT-5.6 Luna | **Not implemented** |
| Streaming AI responses | **Not implemented** |
| OpenAI web search for freshness-dependent questions | **Not implemented** |
| LivePulse-aware AI tools | **Not implemented** |
| Command bar for data queries, commands, and general AI questions | **Implemented as a local command palette** for navigation, timer actions, health, and explicit external launch destinations. Data queries and general AI questions remain future work |
| WebSocket reconnect/resynchronization | **Implemented in M1 foundation**; reconnect/refetch and cursor-gap signal |
| Security/threat model | **Implemented for the locked single-user/local-first thesis** — PERSONAL_LOCAL loopback trust boundary, explicit PUBLIC_DEMO isolation, provider controls, deterministic retention, and confirmed local deletion; conventional account authentication is intentionally not part of this product |
| Structured logging | **Implemented in M1 foundation** |
| Metrics and tracing | **Not implemented**; instrumentation boundaries established |
| Failure tests | **Partially implemented through M2**; transaction rollback, transient publish retry, duplicate/concurrent delivery, stale versions, WebSocket recovery, consumer batch commit ordering, health normalization, and focus expiry are tested; process-kill and prolonged broker restart injection remain future work |
| Load tests | **Not implemented** |
| CI | **Implemented in M1 foundation** |
| Terraform production architecture | **Not implemented** |
| Deterministic public demo mode | **Implemented in the final M3 security closure**; it requires a dedicated database/role, explicit host/origin allowlists, disables every real provider, and serves sanitized fixtures only |
| Local data retention and user-initiated deletion | **Implemented in the final M3 security closure**; 365-day default event/timeline retention, dry-run maintenance, and confirmation-gated personal-data purge |

## Locked M3 provider contracts and status

These implementation requirements remain locked. Backend integration paths are implemented and tested in M3. Optional credentials remain local configuration; a missing provider configuration must leave the app bootable and report disconnected/unconfigured health.

- **Football:** cover EPL, La Liga, Bundesliga, Ligue 1, EFL Championship, UEFA Champions League, UEFA Europa League, FA Cup, Carabao Cup, Serie A, and MLS. Target API-Football free tier. Poll adaptively and compare state; use canonical corrections as new events.
- **Spotify:** real OAuth; current playback, track/context/device state, and play/pause/next/previous/seek/volume/device-transfer controls; Premium account required; credentials and refresh tokens remain server-managed and encrypted.
- **GitHub:** monitor exactly Strata, Tandem, OptiScale, LivePulse, and Portfolio initially. Support signed webhook ingestion and startup/catch-up reconciliation so webhook receipt is not the only correctness path.
- **Gmail:** read-only P0. Never send, reply, draft, label, delete, or mutate. Synchronize incrementally with durable checkpoints and expose useful message/thread metadata. Do not add Google Pub/Sub for P0 unless a documented need changes that decision.
- **Weather:** Open-Meteo geocoding and current conditions plus concise daily context; a user-selected location is persisted in PostgreSQL with five recent places and drives refresh and atmospheric time/weather treatment. Legacy coordinates/timezone from ignored local environment/configuration are bootstrap fallback only; never commit a personal location. Physical place labels come from geocoding, never from a timezone name.
- **AI:** M4 only. GPT-5.6 Luna chat, streaming, web search, and LivePulse-aware tools remain not implemented in M3.

All provider observations normalize to immutable canonical events and share the transactional event/outbox, Redpanda, idempotent projector, durable Pulse Timeline, and replay path. Football events alone mutate football match state. Provider-specific DTOs stay inside adapters and do not enter canonical or frontend contracts. The M3 integration baseline added no provider-specific UI; the later selectable-weather extension adds only the user-controlled location selector and atmosphere inputs, not a fabricated provider dashboard.

## Final UI milestone and local desktop target

The final React UI runs locally for `PERSONAL_LOCAL` with real provider-backed data. The delivery target is a local desktop application, likely packaged with Tauri v2 in a separate milestone. Until then, the browser development/fallback surface targets fullscreen landscape at 1440×900, 1600×900 and 1920×1080, plus the locked 1080×1920 portrait composition. The operating environment integrates System Pulse, clock/weather, football Match Mode, the universal Pulse Timeline, read-only Gmail, Spotify, Focus Timer, Quick Launch and the CSS/SVG Pulse Field. Provider surfaces remain truthful and useful when optional credentials are absent; startup, backend readiness, reconnecting, and recovery are visible without requiring a manually started backend to have succeeded.

`web/src/lib/platform.ts` centralizes external launch, fullscreen, authorization entry, preferences, backend lifecycle observations, and local transport behind an injected platform interface. Browser development supplies the fallback implementations. A later desktop packaging milestone will provide native opening/fullscreen, window placement/restoration, shell-backed preference storage, sidecar lifecycle, and packaged assets. This milestone adds no Tauri/Rust code, native plugins/capabilities, embedded ChatGPT, or desktop packaging.

The final UI does not present PUBLIC_DEMO labels, fixtures, controls, or state-specific visuals. M3 PUBLIC_DEMO isolation remains part of backend security and is unchanged. Development-only visual calibration fixtures are dynamically loaded only by Vite development and do not replace provider behavior in production. The UI does not add AI, a ChatGPT API connection, unsupported provider capabilities, or fabricated telemetry.

The normalized provider-observation contract is an adapter boundary before canonical domain events. Polling, webhook verification/normalization, and commands are separate capabilities; no provider is required to implement all of them.

## Reserved canonical event taxonomy

Names below are reserved contracts, not claims that corresponding events or providers exist. Event history stays immutable; corrections use a new event.

- Football: `football.match.scheduled`, `football.match.kickoff`, `football.match.goal`, `football.match.score_corrected`, `football.match.yellow_card`, `football.match.red_card`, `football.match.substitution`, `football.match.halftime`, `football.match.second_half`, `football.match.fulltime`.
- Spotify: `spotify.playback.started`, `spotify.playback.paused`, `spotify.playback.resumed`, `spotify.track.changed`, `spotify.device.changed`, `spotify.context.changed`.
- GitHub: `developer.workflow.started`, `developer.workflow.completed`, `developer.workflow.failed`, `developer.pull_request.opened`, `developer.pull_request.merged`, `developer.push.received`, `developer.deployment.completed`, `developer.deployment.failed`.
- Gmail: `mail.message.received`, `mail.thread.updated`.
- Weather: `weather.conditions.updated`. `weather.alert.changed` is reserved only if the selected free source later provides a useful alert concept; do not synthesize alerts.

## M1 scope

M1 proves the architecture end-to-end with one deterministic simulated football provider and one comeback scenario. It includes a provider-independent immutable event envelope; PostgreSQL event, transactional outbox, match-state, timeline, and idempotency storage; Redpanda publication and consumption with at-least-once delivery; a recoverable WebSocket foundation; APIs; a dark command-center shell; deterministic attention; tests; local infrastructure; scripts; and CI.

M1 does not implement Spotify, Gmail, GitHub, weather, OpenAI, a real football API, Redis, Kubernetes, production deployment, or the future requirements marked not implemented above.

M2 keeps the M1 event path unchanged and adds a backend-owned structured Focus Engine, Match Mode, a desktop focus-led shell, observable local system-health state, richer timeline presentation metadata, recovery-state UX, and an explicit local command-router foundation. The system-health API reports observations and worker heartbeats, not hypothetical provider availability. The command bar does not call AI and clearly identifies unknown natural-language requests as future intelligence functionality.

M3 Provider Integration delivers real backend adapters for API-Football, GitHub, Spotify, Gmail, and Open-Meteo on the shared provider foundation. Runtime wiring includes one poll scheduler, GitHub webhook ingestion, Spotify OAuth/playback/commands, Gmail OAuth and incremental read-only sync, current-weather API and meaningful-change events, provider health, and domain-aware projector behavior for the universal timeline. The final M3 security closure adds explicit PERSONAL_LOCAL/PUBLIC_DEMO modes, trusted-local host/origin checks, a separate sanitized demo database, retention, and confirmed local deletion. M3 does not add the major adaptive UI redesign or M4 AI.

## Product behavior requirements

- Provider-specific DTOs stop at ingestion adapters and never appear in domain or frontend contracts.
- Canonical events are immutable and timestamped in UTC. Corrections are modeled as new events, never mutation of history.
- An important discovered event is committed together with its outbox message before it is considered published.
- Publication is at-least-once. Consumers must be idempotent.
- Event history answers “what happened”; projections answer “what is true now.”
- The browser treats WebSocket delivery as lossy and can reconstruct authoritative state from APIs.
- The Pulse Timeline is core infrastructure and product functionality.
- PERSONAL_LOCAL is a single-user local-first mode whose primary trust boundary is loopback isolation; it does not claim conventional user authentication or support remote multi-user access.
- PUBLIC_DEMO must use an isolated database/role and sanitized deterministic data; personal provider credentials, checkpoints, events, and history are unavailable in that mode.
- Personal event/timeline retention is explicit and bounded by default; the operator can preview/apply pruning and can request a confirmed full local-data purge.
- Redis, if introduced later, cannot be the only durable copy of critical data.
- Future AI is never authoritative application state and receives no arbitrary database/code execution privileges.

## Milestone status policy

Every milestone must update this table and `DEFINITION_OF_DONE.md`. Future requirements may be changed only through an explicit product decision and documented ADR; they must not disappear through implementation drift.
