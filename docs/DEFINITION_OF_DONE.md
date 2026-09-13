# Definition of Done

This is the milestone acceptance record. A criterion is complete only when supported by a runnable path or test evidence, not merely a design statement.

## M1 acceptance

| # | Criterion | Status |
|---:|---|---|
| 1 | Docker Compose PostgreSQL and Redpanda start successfully | **Verified** — both healthy in Compose |
| 2 | Alembic upgrades an empty database | **Verified** — an isolated empty database upgraded, passed `alembic check`, downgraded to base, and upgraded cleanly again |
| 3 | Backend services start cleanly | **Verified** — API, outbox publisher, and projector started; readiness returned `ready` |
| 4 | Frontend loads | **Verified** — Vite served the LivePulse page in the browser |
| 5 | Run Demo Match starts deterministic scenario | **Verified** — started from the page; ten observations completed |
| 6 | Simulated observations normalize into canonical events | **Verified** — normalization unit test and full scenario integration test |
| 7 | Event and outbox commit transactionally | **Verified** — integration test confirms both writes and rollback when outbox insert fails |
| 8 | Outbox publisher sends to Redpanda | **Verified** — integration test received published records |
| 9 | Projector consumes events idempotently | **Verified** — duplicate broker delivery and duplicate projector invocation were ignored |
| 10 | Match state updates correctly | **Verified** — full scenario integration test checks the final projection |
| 11 | Timeline receives exactly one durable entry per event | **Verified** — full scenario produced ten entries; duplicate delivery retained one per event |
| 12 | WebSocket pushes updates | **Verified** — browser updated the match and timeline while connected |
| 13 | Browser updates without polling | **Verified** — the open page received event-driven updates over `/ws` |
| 14 | Duplicate delivery does not double-apply | **Verified** — same event was deliberately published twice to Redpanda |
| 15 | Refresh reconstructs state from authoritative APIs | **Verified** — browser refresh restored 2–1 full-time state and ten timeline entries |
| 16 | Reconnect can recover after missed history | **Verified** — live `/ws` replay returned ten durable items after a stale cursor; the ahead-cursor path returns `resync_required` and is covered by tests |
| 17 | Final result is home 2, away 1, fulltime | **Verified** — Northstar FC 2–1 Harbor United, fulltime, version 10 |
| 18 | Backend tests pass | **Verified** — Ruff clean; pytest: 16 passed with PostgreSQL and Redpanda integration enabled |
| 19 | Frontend tests/build pass | **Verified** — lint/typecheck passed; Vitest: 5 passed; production build passed |
| 20 | CI files are present | **Verified** — GitHub Actions backend and frontend jobs are present (workflow not run on GitHub in this session) |
| 21 | README setup/run commands are accurate | **Verified** — Compose full-stack path rebuilt; the documented Windows venv paths match bootstrap and all four PowerShell scripts parse cleanly |
| 22 | Requirements and DoD reflect implementation accurately | **Verified** — requirements preserve locked P0 status; this table records evidence |

## Project-wide done criteria

- Architectural invariants in `ARCHITECTURE.md` and accepted ADRs are preserved.
- Changes include appropriate boundary tests and local developer instructions.
- Final self-review inspects the diff and records tests, incomplete work, risks, and exact local commands.
- A milestone is not called complete while any mandatory acceptance criterion remains unsatisfied or unverified.

## M1 evidence

Forensic verification on 2026-09-12 with Docker Compose PostgreSQL 16 and Redpanda, Python 3.13, Node 22.17, and npm 10.9.2. Commands and results:

- `docker compose config --quiet` — passed.
- `docker compose up --build -d --wait` — PostgreSQL and Redpanda reported healthy; backend and frontend started after dependencies.
- Fresh migration database — `alembic upgrade head`, `alembic check`, `alembic downgrade base`, `alembic upgrade head`, and `alembic check` all passed; temporary database was removed.
- `python -m ruff check app tests alembic` — passed.
- `$env:LIVEPULSE_INTEGRATION='1'; python -m pytest -q -p no:cacheprovider` — 16 passed, including transactional rollback, broker retry, duplicate/concurrent delivery, stale versions, late inactive-match event preservation, source-scoped reset/rerun, and the PostgreSQL → outbox → Redpanda → projector vertical slice. The Compose backend was stopped during this test run to avoid competing consumers on the shared local topic.
- `npm run lint` — passed.
- `npm test` — 5 passed.
- `npm run build` — passed.
- `npm ci` — clean install passed with no vulnerabilities after the test dependency update.
- `npm audit --json` — zero vulnerabilities.
- Browser/API checks — health live and ready both returned their expected states; malformed route errors returned the stable envelope and request ID; reset cleared the demo surface and triggered a resync; the browser reconnected after backend restart; a running scenario updated the match and timeline over WebSocket without polling; page refresh rebuilt the final projection and timeline; a separate WebSocket reconnect replayed all ten timeline entries from an earlier cursor.

The GitHub Actions workflow YAML parsed and its commands match the local scripts, but it was not dispatched to GitHub during this run. M1 is verified against its acceptance criteria; future product requirements remain locked in `PRODUCT_REQUIREMENTS.md` with explicit not-implemented status.

## M2 acceptance

| # | Criterion | Status / evidence |
|---:|---|---|
| 1 | Existing M1 tests still pass | **Verified** — M1 backend pipeline/recovery coverage passes in the 20-test backend suite; existing frontend cases remain in the 20-test suite |
| 2 | Main screen is focus-led, not a generic dashboard | **Verified** — inspected live app at desktop viewport; match focus, system rail, and durable timeline form the workspace |
| 3 | Live local day/date/time | **Verified** — browser shows local weekday/date and a ticking local clock without API polling |
| 4 | Demo still uses the M1 event path | **Verified** — live browser demo progressed over WebSocket; backend integration test covers the durable pipeline |
| 5 | Match Mode follows lifecycle | **Verified** — domain FocusState is supplied through REST/WS; demo displayed halftime, live, and full-time modes |
| 6 | Goal/red-card attention is transient | **Verified** — deterministic 12-second expiry and goal/red-card priorities covered by backend focus tests |
| 7 | Focus returns to persistent lifecycle state | **Verified** — expiry derives persistent state from current match status; full-time demo settled at 30/100 |
| 8 | Pulse Timeline remains first-class and durable | **Verified** — API-backed timeline shows all ten persisted scenario events, newest first |
| 9 | New live events animate meaningfully | **Verified** — Framer Motion entrance is limited to newly received items; reduced-motion is honored |
| 10 | Historical reload does not replay entrance animations | **Verified** — `AnimatePresence initial={false}` suppresses initial-history entrance; refreshed browser showed reconstructed history |
| 11 | LIVE / RECONNECTING / RESYNCING are truthful | **Verified** — connection hook state machine and status component tests pass; socket reconnect refetches snapshots |
| 12 | System-health API reports observed state | **Verified** — local PostgreSQL, Redpanda, publisher, projector, realtime, and demo source returned healthy in Compose; dependency degradation/unknown/stale heartbeat normalization is tested |
| 13 | Health details are useful and restrained | **Verified** — browser detail panel showed per-component status, safe detail codes, timestamps, and realtime client count |
| 14 | Command bar keyboard shortcut works | **Verified** — Ctrl+K browser check and component test focus the input; Cmd+K uses the same meta-key handler |
| 15 | Local deterministic commands work | **Verified** — command registry and component tests cover run demo, reset, health, match, and close routes |
| 16 | Unknown natural language does not fake AI | **Verified** — UI test checks the explicit “AI chat connects in the intelligence milestone.” response |
| 17 | Refresh reconstructs authoritative state | **Verified** — after completion, browser reload restored 2–1 full-time, version 10, ten events, focus 30, and healthy system state |
| 18 | WebSocket recovery remains correct | **Verified** — replay/gap tests pass; an inactive-match notification test verifies timeline retention plus authoritative active-state refresh, with stale state rejected |
| 19 | Accessibility basics | **Verified by code review and component tests** — semantic buttons/status, labeled command input, visible focus tokens, Escape handling, contrast tokens, and reduced-motion rules |
| 20 | Frontend production build | **Verified** — `npm run build` passed |
| 21 | Backend tests | **Verified** — Ruff clean; PostgreSQL/Redpanda integration-enabled pytest: 20 passed |
| 22 | Frontend tests | **Verified** — Vitest: 20 passed across 7 files |
| 23 | Ruff/lint/typecheck | **Verified** — Ruff and `npm run lint` passed (lint command includes TypeScript typecheck) |
| 24 | Documentation status ledger | **Verified** — product status, architecture, README, ADRs, and this table updated without removing future P0 requirements |

M2 validation environment: Windows PowerShell, Python 3.13, Node 22.17, npm 10.9.2, Docker Compose PostgreSQL 16/Redpanda, and the existing in-app browser. `docker compose up --build -d --wait` reported all services healthy. `python -m alembic upgrade head` and `python -m alembic check` passed for the added timeline source migration. `docker compose config --quiet`, Ruff, frontend lint/typecheck, Vitest (20 passed), production build, and the integration-enabled backend suite (20 passed) passed. The browser ran the complete 54-second demo through the command bar and then reloaded to the persisted final state. A final `docker compose ps` recheck was denied by the local Docker API socket sandbox; the app remained `LIVE`, reported all systems nominal, and rendered all observed components ready after the demo. GitHub-hosted CI was not run remotely.

## M2 risks and technical debt

- System health is an in-process, single-instance view. Worker heartbeats expire after a bounded interval; it is not a distributed health registry, and health probes can add connection setup cost.
- The realtime fan-out remains in-memory and the local Compose app is a single backend instance. Horizontal scaling requires shared fan-out/recovery infrastructure.
- Transient attention uses the projected event update time and browser timer, then refetches authoritative state at expiry. A temporarily unavailable API can leave last-known attention visible while the connection reports degraded.
- The command registry is local frontend routing only. Data queries, AI, streaming, citations, and authorization are not implemented.
- Accessibility was checked with the semantic tree, component tests, and source inspection; no automated screen-reader or keyboard-only end-to-end suite was run.
- GitHub Actions was inspected and its commands match local checks, but remote GitHub execution was not initiated.

## M1 risks and technical debt

- The local service runs API, outbox publisher, and projector in one backend process. WebSocket fan-out is in-memory and assumes one backend instance; horizontal scaling needs a durable/shared fan-out design.
- If the backend is restarted mid-scenario, its in-memory simulator task is cancelled and the remaining timed observations do not resume automatically. Events already committed, outbox publication, projections, and browser reconnect/resync remain durable; reset and start runs the deterministic scenario again. M1 verifies state/reconnect recovery across backend restart, not simulator-task checkpointing.
- There is no public deployment security/threat model, authentication, production metrics/tracing, or load test in M1.

## M3 provider integration acceptance

M3 integrates real backend adapters while preserving the M1/M2 event and recovery invariants. Provider credentials are optional and no external provider is contacted during source construction or application startup.

| Criterion | Status / evidence |
|---|---|
| Football adapter covers all eleven locked competitions and preserves match projection authority | **Verified** — mocked provider pipeline and PostgreSQL/Redpanda integration; one batched live query and seven-day fixture horizon |
| Football cadence adapts to live state and daily quota | **Verified** — deterministic tests cover healthy live cadence, low-quota tiers, no-live slowdown, Retry-After, budget exhaustion, reset recovery, and detail-request cost |
| GitHub webhook/reconciliation registration and fixed allowlist | **Verified** — app-start registration test, HMAC/delivery-dedupe and mocked REST tests; exactly five repositories accepted |
| Spotify OAuth, playback polling, commands, and health are runtime-wired | **Verified** — router and command registration test; mocked OAuth/API tests; missing config remains disconnected/degraded |
| Gmail read-only OAuth and incremental sync are runtime-wired | **Verified** — mocked OAuth/API tests; Gmail has only `gmail.readonly`; checkpoints commit atomically with accepted event/outbox work |
| Weather polling, normalized current API, meaningful-change event, and health are runtime-wired | **Verified** — mocked Open-Meteo tests and safe empty-coordinate parsing |
| Non-football domains share a timeline-only projection path | **Verified** — mixed PostgreSQL/Redpanda test for football, Spotify, GitHub, Gmail, weather, duplicates, replay, active match preservation, and non-football match-state isolation |
| Late events and at-least-once delivery do not regress authoritative state | **Verified** — projector/reducer regression tests; consumer commits only after durable projection |
| Zero-provider-credential startup and coherent health | **Verified** — startup test and Compose runtime health endpoint show optional providers disconnected without preventing readiness |
| Security and privacy boundaries documented and tested | **Verified for the locked single-user/local-first scope** — PERSONAL_LOCAL loopback trust boundary, PUBLIC_DEMO isolation, provider security checks, retention, and confirmation-gated purge are covered by tests and `SECURITY_AND_PRIVACY.md` |
| Database migrations and provider checkpoints | **Verified** — upgrade/current/check pass; Gmail expired-history recovery and atomic checkpoint tests pass |
| Backend and frontend validation | **Verified after final validation run below** — results recorded before commit |
| No M4 AI or major UI redesign added | **Verified** — frontend changes are limited to provider health typing and deterministic mixed-timeline ordering |

## M3 integration validation record (before final P0 closure)

The initial M3 provider-integration validation on 2026-09-12/13 used Python 3.13, PostgreSQL 16, Redpanda, Node 22, and npm. External provider HTTP was mocked; no live provider credentials or accounts were used. The final P0 security/privacy closure validation below supersedes its security, migration, and suite-count details.

- `python -m ruff check app tests alembic` — passed.
- `python -m compileall -q app tests alembic` — passed.
- `python -m pytest -q -p no:cacheprovider` — **121 passed, 10 skipped**. The 10 skips are gated PostgreSQL/Redpanda integration cases; two Starlette/httpx deprecation warnings remain in test dependencies.
- `$env:LIVEPULSE_INTEGRATION='1'; python -m pytest -q -p no:cacheprovider tests/integration` — **10 passed** against local PostgreSQL + Redpanda. This includes the adapter-observation → canonical/outbox → broker → projector path for football, GitHub, Spotify, Gmail, and weather; duplicate delivery, mixed-domain timeline/replay, Gmail/football checkpoints, and football match-state isolation.
- `python -m alembic upgrade head`, `python -m alembic current`, and `python -m alembic check` — passed; current revision is `0003_provider_foundation`, with no model drift.
- `docker compose config --quiet` and `docker compose up --build -d --wait` — passed. PostgreSQL, Redpanda, backend, and web services reported healthy.
- Runtime HTTP checks — `/health/live` returned `live`, `/health/ready` returned `ready`, system health returned `healthy`, all five providers returned `disconnected` with `configured=false`, and the frontend returned HTTP 200. Compose host ports bind to loopback.
- `npm test -- --run` — **21 passed across 7 files**; `npm run lint` (includes TypeScript typecheck) and `npm run build` passed; `npm audit --json` reported **0 vulnerabilities**.

GitHub-hosted CI was not dispatched during this integration pass.

## M3 limitations and future work

- PERSONAL_LOCAL remains single-user and has no conventional account authentication. Its intended boundary is loopback/local-machine isolation; it must not be exposed directly to an untrusted network.
- Provider scheduler, health, and OAuth refresh serialization are single-instance/in-process. Multi-instance coordination and distributed quota limiting remain future work.
- Live account/API behavior has not been exercised; operators must configure API-Football, Spotify OAuth plus Premium authorization, GitHub owner/token/webhook secret, Gmail OAuth consent, and local weather coordinates/timezone as applicable.
- Gmail message bodies are not stored; bounded sender/subject/snippet metadata is retained. Production encryption-key rotation/recovery is future work.
- A process kill between broker acknowledgement and the outbox `published_at` update is not fault-injected. At-least-once retry and projector idempotency handle duplicate publication.
- M4 AI, provider-specific UI, distributed scheduling, production metrics/tracing, load tests, Terraform, and the adaptive command-center redesign remain out of scope.

## Final P0 security, privacy, and runtime-mode closure

The final closure is implemented on `codex/m3-integration`. It adds explicit PERSONAL_LOCAL and PUBLIC_DEMO modes, loopback/exact Host and Origin checks (including WebSockets), a separately configured demo database and provider-disabled demo runtime, deterministic 365-day default history retention, and an explicit-confirmation local personal-data purge. No conventional user login or multi-user boundary is claimed. The PUBLIC_DEMO Compose profile uses separate PostgreSQL/Redpanda services and loopback-published ports. See `SECURITY_AND_PRIVACY.md` and ADR 0011 for the exact contract.

Final local validation on 2026-09-13 used Python 3.13, PostgreSQL 16, Redpanda, Node 22, and npm. No live provider credentials or accounts were used.

- `python -m ruff check app tests alembic` and `python -m compileall -q app tests alembic` — passed.
- `python -m pytest -q -p no:cacheprovider` — **130 passed, 12 skipped**. The skips are the opt-in database/broker integration suite; two Starlette/httpx deprecation warnings remain in the test dependencies.
- `$env:LIVEPULSE_INTEGRATION='1'; python -m pytest -q tests/integration` — **12 passed** against PostgreSQL and Redpanda, including retention invariants, confirmation-gated purge, provider disconnect behavior, fresh startup after purge, and dedupe after tombstoning.
- `python -m alembic current` — `0004_retired_event_tombstones`; `python -m alembic check` — no new upgrade operations.
- `docker compose config --quiet` and `docker compose -f docker-compose.public-demo.yml config --quiet` — passed. Both Compose profiles built and started with `--wait`; PostgreSQL, Redpanda, API, and web were healthy in each profile.
- PERSONAL_LOCAL runtime probes — live/ready returned `live`/`ready`; system health was `healthy` and reported `PERSONAL_LOCAL`; all five providers were `disconnected/configured=false`. Unsupported Host returned 400 and unsupported Origin returned 403. Inspected published ports for both stacks were bound to `127.0.0.1`.
- PUBLIC_DEMO runtime probes — health returned `PUBLIC_DEMO`; all five providers reported `disconnected/configured=false/disabled_in_public_demo`; initial private state/timeline was empty; Spotify OAuth, GitHub webhook, and football-provider paths returned 404; web returned HTTP 200. Settings and route tests confirmed realistic credential values are discarded, the dedicated demo database is selected, and state/timeline reads return only the isolated demo store.
- `npm test -- --run` — **21 passed across 7 files**; `npm run lint` (includes typecheck), `npm run build`, and `npm audit --audit-level=low` passed with **0 vulnerabilities**.

The supplied PUBLIC_DEMO Compose stack was stopped after runtime checks; its separate sanitized volume was retained. The PERSONAL_LOCAL no-credential stack remains available on loopback. Remote GitHub-hosted CI was not dispatched; local CI-equivalent validation is the release evidence.
