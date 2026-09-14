# LivePulse security, privacy, and local operations

## Product trust model

LivePulse personal mode is `PERSONAL_LOCAL`: a single-user, local-first application, not a
multi-user SaaS service. It does **not** implement conventional user authentication or
authorization. Its primary authentication boundary is the local machine and loopback network
isolation. Keep PERSONAL_LOCAL bound and published to loopback; do not expose its full API to a
LAN, reverse proxy, public tunnel, or untrusted browser. A development tunnel may forward only
the signed GitHub webhook endpoint when its exact hostname is explicitly configured.

The typed `LIVEPULSE_MODE` setting defaults to `PERSONAL_LOCAL`. The only other supported
mode is `PUBLIC_DEMO`, intended for a portfolio/demo deployment with synthetic data. The
selected mode is reported as `runtime_mode` in system health. Secrets, database URLs,
personal configuration, and account identifiers are not returned.

## PERSONAL_LOCAL network boundary

- `scripts/dev.ps1` binds Uvicorn to `127.0.0.1`. The backend container listens on its
  private container interface, while Docker publishes it only as `127.0.0.1:8000`.
- The normal Compose host publications are PostgreSQL `127.0.0.1:5432`, Redpanda
  `127.0.0.1:19092` and `127.0.0.1:9644`, API `127.0.0.1:8000`, and web `127.0.0.1:5173`.
- ASGI middleware rejects non-loopback Host values and unsupported browser Origin values
  for both HTTP and WebSocket requests. The sole Host exception is an HTTP `POST` to exactly
  `/api/v1/webhooks/github` when the parsed hostname exactly matches an entry in
  `GITHUB_WEBHOOK_ALLOWED_HOSTS`. Configure this as a JSON array of hostnames only, such as
  `["abc123.ngrok-free.app"]`; it grants no access to other routes, methods, or WebSockets.
  Origin validation and CORS remain unchanged. CORS is limited to the two exact development
  origins `http://localhost:5173` and `http://127.0.0.1:5173`; it is never wildcarded.
  Other requests without an Origin (for example, the configured Spotify/Gmail top-level OAuth
  callbacks) still require a trusted loopback Host.
- This trust boundary protects against accidental LAN/public exposure. Processes and users
  already trusted on the same machine are inside the personal-mode boundary.

## PUBLIC_DEMO isolation

PUBLIC_DEMO fails to start unless all of the following are explicit:

- `PUBLIC_DEMO_DATABASE_URL` points to a dedicated database, accessed with a dedicated
  database role. Both its database name and role must differ from the personal target.
- `PUBLIC_DEMO_ALLOWED_HOSTS` and `PUBLIC_DEMO_ALLOWED_ORIGINS` are exact non-wildcard
  JSON arrays. Host and Origin must match those allowlists.

The runtime engine and Alembic use only `PUBLIC_DEMO_DATABASE_URL`; there is no fallback to
`DATABASE_URL`. The included `docker-compose.public-demo.yml` provides a separate PostgreSQL
service, database role, volume, Redpanda service, and web/API stack. It passes no provider
credentials or weather coordinates. Every published port is loopback-bound by default.

Settings discard API-Football, Spotify, GitHub, Google, weather-location, and encryption-key
values in PUBLIC_DEMO—even if a copied environment contains realistic secrets. No real
provider is registered. OAuth, playback/control, GitHub webhook/reconciliation, weather, and
real football provider routes are blocked. All real providers report `configured=false`,
`connected=false`, and `disabled_in_public_demo`; provider connection rows from a personal
database are never opened. The only event source is the existing deterministic fictional
match scenario. Live-state, timeline, replay, and WebSocket data come from the isolated demo
database.

For an internet-facing portfolio, configure the exact public hostname and HTTPS frontend
Origin in the demo allowlists and keep the demo database private. The supplied compose file
remains loopback-only; publishing it externally is an explicit operator/network decision.

## Provider security and privacy controls

- **Spotify:** Requests only `user-read-playback-state` and
  `user-modify-playback-state`. OAuth state is random, one-use, and expires after ten
  minutes. Access/refresh tokens are encrypted with Fernet in `provider_connections`;
  refresh is serialized within the single process. Authorization codes and tokens are not
  logged or returned. `DELETE /api/v1/providers/spotify/connection` removes local tokens and
  playback cache; revoke the app grant separately in the Spotify account when required.
- **Gmail:** Requests only `gmail.readonly`; the client and router expose no mutation
  operations. Credentials are Fernet-encrypted. Message bodies are not persisted; message
  metadata/snippets are bounded. History checkpoints advance transactionally with accepted
  canonical-event/outbox work, and expired `historyId` recovery is handled. Callback query
  values are redacted from Uvicorn access logs. `DELETE /api/v1/providers/gmail/connection`
  clears the local encrypted connection and Gmail sync checkpoints but leaves canonical
  event/timeline history intact. Revoke Google's external app grant separately if required.
- **GitHub:** Webhook HMAC-SHA256 validates the raw body with constant-time comparison.
  Delivery identity is deduplicated durably, and normalization/reconciliation is restricted
  to the five configured repositories in the fixed allowlist. Secrets and raw webhook
  payloads are not logged. GitHub webhooks and reconciliation are unavailable in
  PUBLIC_DEMO.
- **Football:** API-Football credentials are sent in the provider header and are excluded
  from logs, DTOs, and health. PUBLIC_DEMO ignores the key and disables the real source.
- **Weather:** Coordinates are read only from PERSONAL_LOCAL configuration, sent to
  Open-Meteo, and omitted from logs, canonical payloads, and health. PUBLIC_DEMO clears them.
- **Shared:** Provider DTOs stop at adapters. Health returns safe status/detail codes only.
  Settings and encrypted credential representations redact secrets. OAuth callback queries
  are stripped before server access logging; `httpx` and `httpcore` URL logging is disabled.
  Unexpected HTTP errors return stable messages and request IDs rather than exception text.

## Retention and deletion

`RETENTION_DAYS` defaults to **365 days** and accepts 30–3650 days. The service compares
canonical-event `ingested_at` with the cutoff and processes at most 1,000 rows per run.
Only published, durably projected events are eligible. Dry-run is the default; `--apply`
executes the displayed plan. Active/live match history, current match-state source events,
pending outbox/projector work, provider connections, and incremental-sync checkpoints are
preserved. Old inactive football state is pruned only with all of its retired event history.
Deleting a canonical event cascades its timeline, outbox, and projector idempotency rows;
the monotonic timeline sequence is not reset. A minimal tombstone retains only the opaque
event UUID and SHA-256 hash of its dedupe key. The Redpanda topic is configured to use the
same retention window; broker cleanup is asynchronous.

Run maintenance from `backend/` with the API/scheduler stopped:

```powershell
python -m app.maintenance.retention
python -m app.maintenance.retention --apply
```

The confirmation-gated full purge removes canonical events, timeline/outbox/idempotency
history, tombstones, match projections and active pointer, provider checkpoints, and the
mixed-domain Redpanda topic. By default it preserves encrypted provider connection rows;
`--include-provider-connections` explicitly removes those too. Schema and Alembic history
are never deleted. A no-argument invocation is a dry-run:

```powershell
python -m app.maintenance.purge
python -m app.maintenance.purge --confirm "PURGE PERSONAL LIVEPULSE DATA" --include-provider-connections --clear-local-provider-config
```

For a complete clean start, stop the backend/API scheduler but keep PostgreSQL and Redpanda
available, then run the confirmed purge with the connection and local-config flags. Restart
afterwards so no configured source repopulates history. Without the connection flag,
encrypted Spotify/Gmail connections remain and can be used again. The local-config flag
blanks provider secrets and weather coordinates in the ignored root `.env`; externally
injected environment variables must be cleared by the operator. Disconnecting one provider removes
its local credentials/checkpoints (where applicable) but retains its historical events;
retention removes only eligible old history; a full purge removes all local history and
optionally stored connections.

## Keys, backups, and limitations

Generate `CREDENTIAL_ENCRYPTION_KEY` locally and keep it outside source control and separate
from database backups. Losing it makes stored OAuth credentials unreadable. Production key
rotation/re-encryption, restore exercises, and secret-manager integration remain future
operational work. Secure the host account, ignored `.env`, Docker daemon, and backups. No
real provider credentials or personal coordinates belong in committed fixtures.

The runtime remains single-instance. Cross-instance scheduling/locking, public production
deployment hardening, and multi-user authentication are not supported or claimed. Remote
GitHub-hosted CI remains a release-validation step; no real provider account is required by
automated tests.
