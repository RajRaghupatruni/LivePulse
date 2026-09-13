# ADR 0012: Additive cross-domain dominant focus

**Status:** Accepted and implemented

## Context

The original deterministic Focus Engine owns football lifecycle and short-lived
football events. It cannot express an important Gmail event, a GitHub workflow
failure, or a configured provider that has degraded. The local browser must not invent
priorities from provider payloads, and the football `FocusState` contract must
remain authoritative for Match Mode.

## Decision

Keep the existing `focus` object and `attention` compatibility score unchanged.
Add `dominant_focus` to the authoritative `GET /api/v1/live-state` snapshot. It
contains one server-selected signal with priority, domain, reason, subject/event
identity, transient/persistent classification, occurrence and observation times,
and an optional expiry. It does not replace or mutate match state.

The selector applies this bounded policy:

- Football uses the existing Focus Engine score, including its existing 12-second
  goal/red-card expiry and persistent lifecycle bands.
- A canonical mail event with `important=true` and no removal marker receives
  priority 85 for 12 seconds from observation.
- A canonical GitHub workflow/deployment failure receives priority 80 for 12
  seconds from observation. This is event emphasis only, not an open-incident
  claim.
- A configured provider with cached health in degraded, stale, rate-limited,
  authentication-failure, provider-failure, or unavailable state receives
  persistent priority 65 until the provider health registry reports recovery.
  Unconfigured optional providers do not create attention candidates.
- Highest priority wins. Equal priority uses newest `observed_at`, then stable
  domain and subject identity ordering.

The selector reads existing canonical/timeline rows and in-process cached health;
it does not call provider APIs. A composite `(event_type, cursor)` index bounds
the recent event-family query. The WebSocket remains a recoverable notification
stream. After an event update, the client refreshes the authoritative live-state
snapshot for the current dominant signal.

## Consequences

- Gmail and GitHub emphasis is explicitly evidence-backed and expires without
  client-side scoring or unresolved-incident inference.
- A live match remains visible in its reserved hero slot even when another
  cross-domain signal temporarily wins `dominant_focus`.
- Provider degradation can change the environmental emphasis while System Pulse
  continues to show the exact provider state and freshness.
- No provider payload body, credential, or raw error is added to the contract.
- One PostgreSQL index is added; no table, event, or provider contract changes.
