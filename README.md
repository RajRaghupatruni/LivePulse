# LivePulse

LivePulse is a single-user realtime command center built around a durable event platform. M1 proved the event path with a deterministic simulated football match; M2 added backend-owned focus and recovery-aware UI; M3 integrates real football, GitHub, Spotify, Gmail, and weather sources into canonical events, the transactional outbox, Redpanda, idempotent projections, the durable Pulse Timeline, and replayable realtime delivery. Provider credentials are optional, and the application boots without them.

The locked P0 direction and implementation status live in [PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md). Review [ARCHITECTURE.md](docs/ARCHITECTURE.md), its accepted ADRs, and [DEFINITION_OF_DONE.md](docs/DEFINITION_OF_DONE.md) before changing core behavior. Provider setup and data handling are documented in [SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md) and the provider-local READMEs.

## Requirements

- Windows 10/11 with PowerShell 7 or Windows PowerShell 5.1
- Python 3.13
- Node.js 22 and npm
- Docker Desktop with Compose

## Windows quick start

From the repository root in PowerShell:

```powershell
./scripts/bootstrap.ps1
```

This creates `.env` from `.env.example`, waits for healthy PostgreSQL 16 and Redpanda, creates `backend/.venv`, and installs backend/frontend dependencies.

In one PowerShell window start the backend and its outbox publisher/projector workers:

```powershell
./scripts/dev.ps1
```

In another window start the frontend:

```powershell
Set-Location web
npm run dev
```

Open <http://localhost:5173>. The API is at <http://localhost:8000>; OpenAPI docs are at <http://localhost:8000/docs>. The backend runs `alembic upgrade head` before serving requests. PostgreSQL and Redpanda can also be started directly with `docker compose up -d postgres redpanda`.

The development script also waits for PostgreSQL and Redpanda health before running migrations. The all-container path is:

```powershell
docker compose up --build
```

It binds the web client on `127.0.0.1:5173`, API on `127.0.0.1:8000`, PostgreSQL on `127.0.0.1:5432`, and Redpanda Kafka on `127.0.0.1:19092`. `PERSONAL_LOCAL` has no conventional login: it is a single-user local app whose primary trust boundary is loopback isolation. Host and Origin checks cover HTTP and WebSockets, and CORS allows only the exact local frontend origins. Keep these ports off the LAN and internet.

## Demo

Select **Run Demo Match**. Ten deterministic observations arrive over about 54 seconds. Each is normalized by the same ingestion adapter used by future providers. The event and outbox row commit atomically; the publisher sends to `livepulse.events.football.v1`; the projector updates match state and the ordered Pulse Timeline once; the WebSocket pushes notifications. The final score is Northstar FC 2–1 Harbor United. **Reset** cancels an active local scenario, deletes simulator-owned history/projections, and sends connected clients a resync signal. The global timeline cursor sequence is not reset. Each run receives a new match identity, so a delayed event updates only its own match projection and timeline history, never a newer match's projection.

Useful endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/live-state`
- `GET /api/v1/timeline?limit=50`
- `GET /api/v1/system/health`
- `POST /api/v1/demo/scenarios/comeback/start`
- `POST /api/v1/demo/reset`
- `ws://localhost:8000/ws?last_cursor=0`

The command bar stays available at the bottom of the page. Press **Ctrl+K** or **Cmd+K** to focus it. Supported local commands are `run demo`, `reset demo`, `show system health`, `show match`, and `close`; unknown questions are not sent to AI and receive the message that AI chat connects in the intelligence milestone. The header clock uses the browser's local timezone. The health detail panel shows only observed local component/probe and worker-heartbeat state.

## M3 provider integration

The backend registers five real provider paths: API-Football observations; GitHub signed webhooks and bounded reconciliation; Spotify OAuth, playback polling, and typed playback commands; Gmail OAuth and read-only incremental sync; and Open-Meteo current conditions plus meaningful-change events. Poll sources share one bounded scheduler. Provider DTOs end at their adapters. Canonical events use the transactional PostgreSQL outbox and Redpanda, then the idempotent projector writes the Pulse Timeline. Football event families alone update football match state; GitHub, Spotify, Gmail, and weather use one generalized timeline-only projection path. All five optional provider configurations can remain blank without preventing startup.

Set local values in the ignored `.env` copied from `.env.example`. Spotify and Gmail require a generated `CREDENTIAL_ENCRYPTION_KEY`; GitHub webhook and reconciliation capabilities are independently configured; football needs an API-Football key; weather requires local latitude, longitude, and timezone. Empty weather coordinates parse as unconfigured. Source construction does not make provider API calls during app startup. See each provider README for OAuth permissions, scopes, quota behavior, and local setup. M4 AI and the high-fidelity adaptive UI remain out of scope.

## Runtime modes and privacy maintenance

`LIVEPULSE_MODE` defaults to `PERSONAL_LOCAL`. To launch the sanitized `PUBLIC_DEMO`, use
its separate Compose file and a fresh URL-safe database password:

```powershell
$env:PUBLIC_DEMO_DB_PASSWORD = (python -c "import secrets; print(secrets.token_hex(32))")
docker compose -f docker-compose.public-demo.yml up --build -d --wait
```

Open <http://localhost:5174>. This stack has a dedicated PostgreSQL volume/role and Redpanda
instance, passes no provider credentials or personal coordinates, ignores personal provider
configuration even if secrets are present in another environment, blocks provider routes,
and serves only the fictional deterministic match scenario. Its host ports bind to loopback.
For a deliberate public portfolio deployment, set exact `PUBLIC_DEMO_ALLOWED_HOSTS` and
`PUBLIC_DEMO_ALLOWED_ORIGINS` for the reverse-proxy hostname/HTTPS origin and keep the demo
database private. The mode never falls back to the PERSONAL_LOCAL database.

Retention is a deterministic operator command, not a background deletion loop. It defaults
to 365 days, previews the next bounded batch, and preserves current football projections,
pending delivery/projection work, provider connections, and incremental-sync checkpoints:

```powershell
Set-Location backend
python -m app.maintenance.retention
python -m app.maintenance.retention --apply
```

To disconnect one account, use `DELETE /api/v1/providers/spotify/connection` or
`DELETE /api/v1/providers/gmail/connection`; this clears that local connection (and Gmail's
sync checkpoints) while keeping its historical timeline events. For a full local purge,
stop the backend scheduler but leave PostgreSQL and Redpanda running, inspect the dry-run,
then confirm explicitly:

```powershell
python -m app.maintenance.purge
python -m app.maintenance.purge --confirm "PURGE PERSONAL LIVEPULSE DATA" --include-provider-connections --clear-local-provider-config
```

That removes canonical/timeline/outbox/projection/checkpoint history, drops the mixed-domain
Redpanda topic, deletes encrypted OAuth connection rows, and blanks provider keys and weather
coordinates in the ignored root `.env`. It leaves migrations/schema intact. Clear any
externally injected provider environment variables before restarting.

## Tests and checks

```powershell
./scripts/test.ps1
```

That runs Ruff and backend tests, then frontend lint/typecheck, Vitest, and production build. The PostgreSQL + Redpanda integration suite is opt-in locally:

```powershell
docker compose up -d --wait postgres redpanda
# Stop the local projector first if the full Compose backend is running.
docker compose stop backend
Set-Location backend
$env:DATABASE_URL = 'postgresql+asyncpg://livepulse:livepulse@localhost:5432/livepulse'
$env:KAFKA_BOOTSTRAP_SERVERS = 'localhost:19092'
$env:LIVEPULSE_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest
docker compose up -d --wait backend
```

CI runs that vertical test against PostgreSQL and Redpanda services, alongside lint, frontend tests, and build.

## Delivery and recovery semantics

Publication and consumption are at-least-once, not exactly-once. A crash after broker acknowledgement and before marking an outbox row published can republish the same canonical event. The projector records `(consumer, event_id)` in the same transaction as state and timeline updates, so duplicates do not double-apply. WebSocket messages are notifications, not authority: reconnect replays rows after the supplied cursor, and the client reloads live state and timeline from REST. PostgreSQL holds the critical event history; Redis is intentionally absent.

PERSONAL_LOCAL is a local development/personal foundation without conventional account authentication; do not expose that mode publicly. PUBLIC_DEMO is separately isolated and only for sanitized deterministic content. M2's deterministic Focus Engine and Match Mode derive from server state; REST remains authoritative and WebSocket remains recoverable incremental delivery. M4 AI, provider-specific UI, distributed scheduling, production key rotation/restore procedures, metrics/tracing, load tests, Terraform, and the adaptive command-center redesign remain out of scope.
