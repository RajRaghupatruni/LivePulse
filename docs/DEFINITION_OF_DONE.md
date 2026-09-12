# Definition of Done

This is the milestone acceptance record. A criterion is complete only when supported by a runnable path or test evidence, not merely a design statement.

## M1 acceptance

| # | Criterion | Status |
|---:|---|---|
| 1 | Docker Compose PostgreSQL and Redpanda start successfully | **Verified** — both healthy in Compose |
| 2 | Alembic upgrades an empty database | **Verified** — initial migration ran against a fresh PostgreSQL volume |
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
| 16 | Reconnect can recover after missed history | **Verified** — `last_cursor=0` replayed ten durable items; an ahead cursor returned `resync_required` |
| 17 | Final result is home 2, away 1, fulltime | **Verified** — Northstar FC 2–1 Harbor United, fulltime, version 10 |
| 18 | Backend tests pass | **Verified** — Ruff clean; pytest: 9 passed with PostgreSQL and Redpanda integration enabled |
| 19 | Frontend tests/build pass | **Verified** — lint/typecheck passed; Vitest: 3 passed; production build passed |
| 20 | CI files are present | **Verified** — GitHub Actions backend and frontend jobs are present (workflow not run on GitHub in this session) |
| 21 | README setup/run commands are accurate | **Verified** — Compose full-stack path built and started; individual commands match the tested services |
| 22 | Requirements and DoD reflect implementation accurately | **Verified** — requirements preserve locked P0 status; this table records evidence |

## Project-wide done criteria

- Architectural invariants in `ARCHITECTURE.md` and accepted ADRs are preserved.
- Changes include appropriate boundary tests and local developer instructions.
- Final self-review inspects the diff and records tests, incomplete work, risks, and exact local commands.
- A milestone is not called complete while any mandatory acceptance criterion remains unsatisfied or unverified.

## M1 evidence

Verified on 2026-09-12 with Docker Compose PostgreSQL 16 and Redpanda, Python 3.13, and Node 22. Commands and results:

- `docker compose up --build -d` — PostgreSQL, Redpanda, backend, and frontend started; database migration ran in the backend container.
- `python -m ruff check app tests alembic` — passed.
- `$env:LIVEPULSE_INTEGRATION='1'; python -m pytest -q -p no:cacheprovider` — 9 passed, including the full simulated comeback through PostgreSQL, outbox, Redpanda, projector, projection, timeline, duplicate delivery, and transactional rollback.
- `npm run lint` — passed.
- `npm test` — 3 passed.
- `npm run build` — passed.
- Browser check — scenario completed at 2–1 full-time; refresh reconstructed state; websocket cursor replay and resync signal were verified; a live goal raised the displayed Focus Engine attention to 95 without polling.

The GitHub Actions workflow is present but was not dispatched to GitHub during this local run. M1 is verified against its acceptance criteria; future product requirements remain locked in `PRODUCT_REQUIREMENTS.md` with explicit not-implemented status.

## M1 risks and technical debt

- The local service runs API, outbox publisher, and projector in one backend process. WebSocket fan-out is in-memory and assumes one backend instance; horizontal scaling needs a durable/shared fan-out design.
- There is no public deployment security/threat model, authentication, production metrics/tracing, or load test in M1.
- Automated failure coverage checks transactional rollback and duplicate delivery. Prolonged broker outage, process-kill, and restart recovery still need dedicated fault-injection tests.
- `npm ci` reported two moderate dependency advisories. Their package-level impact has not been triaged in M1.
- The GitHub Actions workflow has not been run by GitHub yet; only its local constituent commands and service path were exercised.
