# LivePulse

LivePulse is a single-user realtime command center built around a durable event platform. M1 proves the end-to-end path using one deterministic simulated football match: observation → normalization → PostgreSQL event and transactional outbox → Redpanda → idempotent projection → Pulse Timeline → recoverable WebSocket → browser. M2 adds a focus-led desktop shell, backend-owned deterministic Match Mode/attention, observed component health, explicit local commands, and visible reconnect/resync states without changing that event path.

The locked P0 direction and implementation status live in [PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md). Review [ARCHITECTURE.md](docs/ARCHITECTURE.md), its accepted ADRs, and [DEFINITION_OF_DONE.md](docs/DEFINITION_OF_DONE.md) before changing core behavior.

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

It exposes the web client on port 5173, API on 8000, PostgreSQL on 5432, and Redpanda Kafka on 19092.

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

## Tests and checks

```powershell
./scripts/test.ps1
```

That runs Ruff and backend unit tests, then frontend lint/typecheck, Vitest, and production build. The PostgreSQL + Redpanda vertical integration test is opt-in locally:

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

M1/M2 are local development/demo foundations, not a public deployment. M2's deterministic Focus Engine and Match Mode derive from server state; REST remains authoritative and WebSocket remains recoverable incremental delivery. Later milestones are locked in the product requirements, including real provider integrations, security/threat model, full AI chat/search/tools, production instrumentation, load tests, Terraform, and deterministic public demo mode.
