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
- Live account/API behavior has not been exercised; operators must configure API-Football, Spotify OAuth plus Premium authorization, GitHub owner/token/webhook secret, and Gmail OAuth consent. Weather uses a persisted UI selection; legacy coordinates/timezone are optional first-run bootstrap only.
- Gmail message bodies are not stored; bounded sender/subject/snippet metadata is retained. Production encryption-key rotation/recovery is future work.
- A process kill between broker acknowledgement and the outbox `published_at` update is not fault-injected. At-least-once retry and projector idempotency handle duplicate publication.
- At the M3 closure, M4 AI, provider-specific UI, distributed scheduling, production metrics/tracing, load tests, Terraform, and the adaptive command-center redesign remained out of scope. The final UI milestone and selectable-weather extension below supersede the UI-status items; the remaining engineering items are still future work.

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

## Final UI milestone: reference-led local desktop-ready application

This acceptance section records the final React UI milestone on `codex/final-ui`. The delivery target is a local desktop application, likely Tauri v2 in a later milestone. The browser remains the development/fallback host for this milestone; it is not the final packaging target. No Tauri/Rust code, plugins, capabilities, sidecar manager, monitor placement, or installer is included. The earlier browser-only product-format statement in historical M1/M2/M3 records does not override this current target.

| Criterion | Status / evidence |
|---|---|
| Locked landscape and portrait visual contracts | **Verified** — the supplied references are tracked in `docs/ui-reference/`; the implemented composition retains the NYC skyline, top environment/System Pulse, dominant match stage, Gmail and Recent Signals, Spotify, Quick Launch, and footer in both orientations |
| Desktop-first and portrait layouts | **Verified** — inspected at 1920×1080 and 1080×1920, with no horizontal overflow; responsive geometry also inspected at 1600×900, 1440×900, and 1366×768 |
| Personal-local provider truth | **Verified** — production UI consumes current backend/provider surfaces; optional providers stay unconfigured/unavailable without fabricated production state; deterministic visual states are loaded only by Vite development |
| Football lifecycle and detail flow | **Verified** — current/upcoming/live/halftime/full-time rendering, match controls, selected-match persistence, return-to-auto, event emphasis, schedule/update views, and truthful unavailable lineup/stat states are implemented; detail modal and its tabs were exercised in the browser |
| Gmail read-only surface | **Verified** — curated bounded rows, message metadata detail, and a bounded expanded inbox dialog work; message bodies are not retained, and no message mutation controls exist |
| Universal Pulse Timeline | **Verified** — chronology, event expansion, full-history route, older cursor pagination, stable identity dedupe, and REST/WebSocket reconciliation use the existing backend contract |
| Spotify playback surface | **Verified** — playback/art/track/progress/device and supported controls are rendered from backend state; controls use backend-confirmed results and remain disabled or truthful when no authorized playback session is available |
| Focus Timer and Focus posture | **Verified** — 25/50/90 minute sessions, pause/resume/end, preference restoration, quieted peripheral emphasis, and critical-alert visibility are implemented; all three presets and lifecycle controls were exercised in the browser |
| System Pulse and backend lifecycle | **Verified** — local infrastructure/realtime and provider freshness expand from the header instrument; startup, ready, unavailable, reconnect, and recovery are separate; a failed health endpoint is shown unavailable even when a shell lifecycle snapshot says ready |
| Selectable weather location | **Verified by unit/component tests and migration checks** — Open-Meteo search, durable selection/five recents, shared-scheduler refresh, selected-place atmosphere, and a system-local dashboard clock; Docker-based runtime inspection of the new UI was unavailable in this session |
| Single-window interactions | **Verified** — Home/Timeline/Focus/Settings, football details, Gmail details, command palette, Escape dismissal, and local destination setup stay in one LivePulse window; only intentional destination launches use the external-launch service |
| Shell-agnostic platform boundary | **Verified** — `web/src/lib/platform.ts` centralizes external launching, authorization entry, fullscreen, API/WebSocket URL selection, backend lifecycle observation, and preferences; native APIs are absent from React components |
| Reduced motion, keyboard, focus, and semantics | **Verified by component tests, accessibility-tree inspection, and reduced-motion styles** — semantic controls, dialog roles and focus handling, visible focus tokens, keyboard navigation, Escape handling, and reduced-motion transitions are present |
| PUBLIC_DEMO is dormant in the UI | **Verified** — no demo labels or controls appear in production; backend isolation remains in place and covered by its security tests |
| Startup and long-open runtime behavior | **Verified by code and runtime review** — wake sequence never blocks input; polling/reconnects are bounded and pause while hidden; timers/listeners/socket cleanup on teardown; no perpetual WebGL/canvas animation is introduced |
| Tauri packaging readiness boundary | **Completed in the subsequent Windows desktop-shell milestone** — the same React app runs in Tauri v2, with explicit loopback endpoints, native external URL opening, fullscreen/window controls, readiness gating, and Windows installers |

Final UI validation used the locked image comparison, the running local browser application, unit/component tests, production build, backend checks, and a rebuilt personal-local Compose stack. The visual-fixture selector was used only on the development server; the production bundle check confirms it does not expose fixture controls or data. No live provider credentials/accounts were configured for this pass, so provider-facing OAuth and external playback/launch side effects were not invoked. The Docker runtime showed the local API ready, the frontend healthy, and the browser realtime connection live.

At the time of this UI milestone, Tauri packaging remained future work. The following Tauri v2 desktop-shell milestone below supersedes that planning status. OAuth return navigation into a packaged shell, service-process ownership, monitor-specific placement, and browser lifecycle differences remain documented limitations; the React UI continues to use one window for product navigation. A Tauri WebView origin is integrated with the PERSONAL_LOCAL trust boundary as one exact origin, without widening other Host/Origin rules.

The browser WebSocket 403 blocker was caused by a trust-check comparison bug: the middleware parsed an Origin into `(scheme, host, port)` but compared only the scheme string to a set of parsed origin tuples, so even an explicitly allowed browser origin failed. The check now compares the full normalized tuple against the exact allowlist entry. Tests confirm the configured Vite origin upgrades successfully, an unlisted loopback port is rejected, and an untrusted host/origin remains blocked for both HTTP and WebSocket requests. This fixes the browser upgrade without loosening PERSONAL_LOCAL's boundary.

## Windows Tauri v2 desktop shell

The current desktop-shell milestone packages the existing React/Vite UI with a small Tauri v2 Rust host. Docker Compose remains responsible for PostgreSQL, Redpanda, and FastAPI; the desktop app checks `/health/ready`, shows a startup/unavailable/retry surface, and recovers when the backend becomes available. It neither starts nor stops Docker services. The frontend continues to run in browser development mode, while Tauri development binds Vite to loopback only.

The Tauri adapter selects the local API and WebSocket endpoints, routes HTTP(S) opening through the scoped opener plugin, provides fullscreen/maximize behavior, and keeps browser fallbacks. The shell grants no shell-command or filesystem capability. The exact `http://tauri.localhost` packaged origin and `http://127.0.0.1:5174` Tauri development origin are accepted only in PERSONAL_LOCAL; other Host/Origin rules and PUBLIC_DEMO behavior remain unchanged. Tauri development uses a separate loopback port so it does not collide with the browser/Compose Vite server. The window opens maximized, remains resizable with a usable minimum, and the window-state plugin remembers normal geometry and fullscreen state while falling back to OS placement if the saved bounds no longer intersect an attached monitor. Packaged Spotify/Gmail OAuth opens a fixed backend start URL in the system browser; one-use provider state selects a static no-store completion page, and the desktop UI polls safe connection status with a bounded timeout. Browser development retains frontend redirects. Automatic Compose startup, embedded databases/brokers, signing, and self-contained installation are out of scope.

Validation for this milestone: frontend tests **53 passed** (final rerun), frontend lint/typecheck/build and npm audit passed (0 vulnerabilities); backend tests **174 passed, 15 skipped**, Ruff passed; PostgreSQL/Redpanda integration tests **15 passed**; `cargo fmt --check`, `cargo check`, and `cargo clippy -D warnings` passed; `docker compose config --quiet` passed. Windows NSIS and MSI installers were produced under `src-tauri/target/release/bundle/`. Docker readiness, exact Tauri-dev CORS, and API/WebSocket reachability were verified. The Tauri process launched and the same Vite UI loaded, but native window visual inspection was not available in this execution environment.

Packaged OAuth completion follow-up: Spotify and Gmail desktop callbacks now return fixed, secret-free pages after a valid one-use desktop state, and browser-mode callbacks still redirect to the configured frontend. The desktop connection waiter uses persisted connection status, refreshes provider views on success, and stops after success, timeout, open failure, or unmount. The Gmail status endpoint returns no account identifiers or credential material. Validation for this follow-up: backend **175 passed, 15 skipped**, opt-in PostgreSQL/Redpanda integration **15 passed**, frontend **58 passed across 14 files**, Ruff, lint/typecheck, production build, npm audit (**0 vulnerabilities**), Rust fmt/check/clippy, and NSIS/MSI Tauri builds passed. Docker Compose rebuilt and reported PostgreSQL, Redpanda, API, and web healthy. Full interactive OAuth approval in a real system-browser session remains a manual provider-account verification item.

Final validation for this checkout:

- Frontend: `npm test -- --run` — **31 passed across 9 files**; `npm run lint` (TypeScript plus ESLint), `npm run build`, and `npm audit --audit-level=low` passed; audit reported **0 vulnerabilities**. The production JavaScript bundle contains no visual-fixture selector or fixture data.
- Backend: Ruff and `compileall` passed; the default suite reported **140 passed, 12 skipped**, and the opt-in PostgreSQL/Redpanda integration suite reported **12 passed**. Migration `0005_dominant_focus` is current and `alembic check` reported no pending operations.
- Runtime: `docker compose up --build -d --wait` completed with PostgreSQL, Redpanda, API, and web healthy. The actual browser route reported backend ready and realtime live. Optional providers were truthfully unconfigured because this validation did not use live provider credentials or accounts.
- Visual/runtime review: the locked 1920×1080 and 1080×1920 compositions were inspected along with 1600×900, 1440×900, and 1366×768; no horizontal overflow was observed. Development fixture interactions and core keyboard/dialog flows were exercised without launching external applications or mutating provider data.

## Selectable weather location extension

Weather now has a compact header location selector backed by Open-Meteo geocoding. Selection and five recent places persist in PostgreSQL; the existing poll source reads the active selection and performs a prompt refresh through the shared scheduler. Per-location weather snapshots and event baselines preserve the existing canonical event/outbox path and prevent cross-city comparisons. The atmosphere uses observed weather categories and the selected place's local time, while the dashboard clock remains tied to the system. Legacy coordinate/timezone environment values are first-run bootstrap fallback only; when they are absent, the UI offers a clear location-selection state. The physical place name always comes from geocoding.

The focused unit/component checks cover geocoding normalization and caching, selected/recent persistence, location switching, suppression of a browsing-only event, selected-timezone atmosphere, selector errors, and location-matched weather display.

Validation for this extension:

- `python -m ruff check app tests alembic` — passed; `python -m pytest -q -p no:cacheprovider` — **146 passed, 12 skipped**.
- `$env:LIVEPULSE_INTEGRATION='1'; python -m pytest -q -p no:cacheprovider tests/integration/test_event_pipeline.py::test_provider_observations_reach_timeline_through_outbox_and_redpanda` — **1 passed**, including weather event/outbox/timeline delivery and location-selection restoration.
- The initial complete opt-in integration suite reported **9 passed, 3 failed** because its broker events shared the configured production topic with the already-running PERSONAL_LOCAL projector. The test harness now assigns each opt-in pytest process a disposable UUID-scoped topic before application settings are imported, then deletes it at session end. Integration tests continue to use their own consumer groups; the production topic and consumer configuration are unchanged. The harness also disposes its shared async database pool between module-scoped pytest event loops.
- `python -m alembic upgrade head`, `python -m alembic current`, and `python -m alembic check` — passed; revision `0006_weather_locations` is current and there is no model drift.
- `npm test -- --run` — **37 passed across 11 files**; `npm run lint` and `npm run build` passed. `docker compose config --quiet` passed.
- `.env.example` retains blank weather coordinate/timezone placeholders. No live provider credentials or location values were added to the repository.

### API-Football baseline and provider-state correction

The first successful API-Football fixture ingestion now commits per-fixture checkpoints and a durable baseline marker without creating scheduled timeline entries for the pre-existing fixture set. Later unseen fixtures and meaningful live changes continue through the existing canonical event, transactional outbox, Redpanda, and projector path. Existing fixture checkpoints on upgraded databases count as an established baseline. The football hero distinguishes a healthy empty window from provider failure, rate limiting, and missing configuration; it may retain last-known match context while showing a provider status indicator. This correction uses the existing checkpoint schema and requires no migration.

Validation on 2026-09-13: `python -m pytest backend/tests -q` — **148 passed, 15 skipped**; `$env:LIVEPULSE_INTEGRATION='1'; python -m pytest -q -p no:cacheprovider backend/tests/integration` — **15 passed** against local PostgreSQL/Redpanda; `python -m ruff check backend` passed; frontend Vitest — **41 passed across 11 files**, `npm run lint`, and `npm run build` passed. After rebuilding the local stack, the real API-Football fixture endpoint reported healthy with 24 today, 168 upcoming, and 2 live; the browser selected San Diego vs Philadelphia Union, and no scheduled-bootstrap rows appeared in the newest 100 timeline entries. No migration was required.

### Integration isolation follow-up (2026-09-13)

The full opt-in PostgreSQL/Redpanda suite now runs deterministically while the normal local API/projector remains running. `tests/integration/conftest.py` sets a process-local `KAFKA_TOPIC` such as `livepulse.events.integration.<uuid>` before importing application settings; this topic is deleted after the test session. Production `.env` and broker settings are untouched. The integration session completed with **12 passed** against the running local services, and the default backend suite completed with **146 passed, 12 skipped**. Ruff passed. A real runtime weather smoke searched Open-Meteo for Celina, selected the returned result, observed refreshed clear conditions, and confirmed the PostgreSQL-backed selection was still returned by a fresh location-state request. Docker Desktop was available for this follow-up.

## LivePulse v1 release closeout (2026-09-14)

The v1 closeout records the architecture and verified behavior of the Windows-first Tauri command center without adding an application demo mode or synthetic production data. `README.md` is the architecture-first project introduction; the locked requirements ledger and earlier milestone records remain preserved. `docs/INTERVIEW_NOTES.md` and `docs/RESUME_BULLETS.md` contain evidence-backed presentation material. The Portfolio repository now has a dedicated LivePulse case study and architecture visual. The Portfolio repository only contained a PDF resume, so no editable resume document was changed.

Final local validation for this closeout:

- Backend: `python -m pytest -q -p no:cacheprovider` — **175 passed, 15 skipped**. The skips are the opt-in integration tests; two existing Starlette/httpx deprecation warnings and an asyncio cleanup runtime warning were emitted. `python -m ruff check app tests alembic` passed.
- PostgreSQL/Redpanda: with PostgreSQL and Redpanda healthy, `$env:LIVEPULSE_INTEGRATION = '1'; python -m pytest -q -p no:cacheprovider tests/integration` — **15 passed**. Integration events use the suite's isolated UUID-scoped topic.
- Database: `python -m alembic check` — no new upgrade operations detected.
- Frontend: `npm test -- --run` — **70 passed across 17 files**; `npm run lint`, `npm run build`, and `npm audit --audit-level=low` passed. Audit found **0 vulnerabilities**. The build reports the existing lazy-loaded Three.js chunk at about 746 kB raw / 192 kB gzip; the atmosphere is deferred to its own chunk.
- Tauri Rust: `cargo fmt --check`, `cargo check`, and `cargo clippy -- -D warnings` passed. Installer generation was not repeated for this documentation/case-study closeout; the existing NSIS and MSI installers were produced by the prior desktop-shell validation.
- Runtime: `docker compose config --quiet` passed. PostgreSQL and Redpanda reported healthy. The running PERSONAL_LOCAL API returned `live` and `ready`; `/api/v1/system/health` returned healthy with football, Spotify, Gmail, GitHub, and weather each configured and healthy. A live-state snapshot and timeline request returned successfully.
- Portfolio: `npm test -- --run` — **35 passed across 7 files**; `npm run lint`, `npm run typecheck`, and `npm run build` passed. Playwright `npm run test:e2e` — **43 passed, 3 skipped**; the LivePulse case study passed desktop and mobile layouts without horizontal overflow.
- `git diff --check` passed in both repositories. GitHub-hosted CI was not run remotely.

Known v1 boundaries remain: Docker Compose must be running for the packaged desktop app; the Windows installers are unsigned; packaged OAuth account consent was not automated; the project does not claim multi-user hosting, load-test results, full metrics/tracing, Terraform, AI chat, or a long-duration graphics benchmark. These are explicit follow-on limits, not implemented v1 behavior.
