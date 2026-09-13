# ADR 0011: Explicit local/demo modes and personal-data lifecycle

- Status: Accepted and implemented
- Date: 2026-09-13

## Context

LivePulse is a single-user, local-first personal command center. Provider OAuth credentials,
personal timeline events, email metadata, playback state, repository activity, and weather
location are not suitable for an accidentally public service. The product also needs a
sanitized portfolio/demo mode and a deliberate local history lifecycle without introducing
multi-user SaaS authentication or an enterprise compliance subsystem.

## Decision

Use a typed `LIVEPULSE_MODE` with `PERSONAL_LOCAL` as its default and `PUBLIC_DEMO` as the
only alternate mode. PERSONAL_LOCAL has no conventional account login; its primary trust
boundary is local-machine/loopback isolation. Development and Docker host ports bind to
loopback. ASGI middleware checks Host and browser Origin for HTTP and WebSocket traffic,
while CORS permits exact configured local origins only.

PUBLIC_DEMO requires a separate database URL, database name, login role, and explicit
non-wildcard host/origin allowlists. Its engine never opens the personal `DATABASE_URL`.
Settings discard personal provider secrets and location values, provider registration is
empty, private-provider endpoints are blocked, and the deterministic fictional simulator
is the only source. The supplied demo Compose stack owns a distinct database volume and
Redpanda instance and exposes only loopback host ports by default.

`RETENTION_DAYS` defaults to 365 and is applied by a bounded, deterministic CLI in dry-run
mode unless explicitly applied. Retention deletes only old, published, durably projected
events and their derived timeline/outbox/idempotency rows. Active/current match state,
pending work, provider connections, and all provider checkpoints remain because their
deletion could compromise authoritative state or incremental synchronization. Redpanda uses
the same topic retention interval. Retired event UUIDs and hashed dedupe identities remain
as minimal tombstones to make retries/replay idempotent without retaining event payloads.

A separate confirmation-gated purge removes all canonical history and projections, provider
checkpoints, tombstones, the active-match pointer, and the mixed-domain Redpanda topic. It
deletes encrypted provider connection rows and blanks local provider configuration only
when the operator passes explicit flags. Database migrations and schema remain intact.

## Consequences

- There is no claim of multi-user authentication or remote private-mode support.
- PUBLIC_DEMO may be intentionally published only with sanitized synthetic data and explicit
  host/origin configuration; the bundled Compose publication remains loopback-only.
- Local operators can preview retention, apply it in bounded batches, disconnect one
  provider, delete historical data, or perform a full confirmed purge as distinct actions.
- Single-instance scheduling, key rotation/recovery, distributed coordination, and
  production deployment hardening remain future operational work.
