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

## M1 risks and technical debt

- The local service runs API, outbox publisher, and projector in one backend process. WebSocket fan-out is in-memory and assumes one backend instance; horizontal scaling needs a durable/shared fan-out design.
- If the backend is restarted mid-scenario, its in-memory simulator task is cancelled and the remaining timed observations do not resume automatically. Events already committed, outbox publication, projections, and browser reconnect/resync remain durable; reset and start runs the deterministic scenario again. M1 verifies state/reconnect recovery across backend restart, not simulator-task checkpointing.
- There is no public deployment security/threat model, authentication, production metrics/tracing, or load test in M1.
- Outbox tests inject a broker send error and prove retry; process-kill between broker acknowledgement and the database `published_at` update is not fault-injected. The documented at-least-once duplicate path and idempotent consumer remain the recovery mechanism.
- The initial locked Vitest 3.2.7 dependency produced two moderate entries for the same [GHSA-82fw-gwwq-j7x9 / CVE-2026-84373](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9): direct `vitest` and transitive `@vitest/mocker`. A reachable unauthenticated mocker WebSocket could register a redirect mock and make the dev process read local files; the advisory is in test tooling and requires the mocker plugin path, which this app's ordinary Vite UI server does not register. The patched line is Vitest 4.1.11. Node 22 and Vite 7 meet its documented prerequisites; Vitest 4 has major-version migration changes, but this project's tests use stable APIs and lint/tests/build pass. `@testing-library/dom` is explicit to satisfy Testing Library's peer. Clean `npm ci` and `npm audit --json` now report zero vulnerabilities; no advisory is deferred.
- The GitHub Actions workflow has not been run by GitHub yet; only its local constituent commands and service path were exercised.
