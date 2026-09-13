# API-Football provider

LivePulse's real football adapter uses the API-Football v3 API at `https://v3.football.api-sports.io` with the `x-apisports-key` header. The provider is optional: without `API_FOOTBALL_KEY`, its health is `disconnected` and it makes no network requests. HTTP calls use a pooled async `httpx` client with separate connect/read/write/pool timeouts.

Competition IDs are resolved from `/leagues?current=true`; the adapter matches the returned competition name and country to the locked set and stores the resolved map in `provider_checkpoints` for seven days. It does not rely on ID guesses. It recognizes aliases including `EPL`, `Champions League`, and `League Cup` while retaining canonical labels such as `Premier League`, `UEFA Champions League`, and `Carabao Cup`.

## Request budget and polling

The provider uses a local daily budget of 100 requests and reserves the final five calls. It reconciles that budget with `x-ratelimit-requests-limit`, `x-ratelimit-requests-remaining`, and `X-RateLimit-Remaining` when supplied. Production HTTP requests are serialized and spaced 6.1 seconds apart to stay under the roughly ten-per-minute free-tier limit. The persisted counter resets at 00:00 UTC; if headers are absent, the 100-call local limit remains authoritative. The `/api/v1/system/health` football entry includes request use, remaining local/provider quota, and the next UTC reset when configured.

Schedule discovery uses one `/fixtures?league=...&season=...&from=...&to=...&timezone=UTC` request for each resolved competition, scoped to today and tomorrow, then caches normalized results for at most 20 hours. This avoids scanning every match in the world just to find the locked competitions. It follows paging metadata when a scoped competition window has multiple pages. Live discovery is dormant until a known fixture is within six hours of kickoff or already live, then one `/fixtures?live=...` request covers all resolved locked leagues. If that response omits events, one `/fixtures?ids=...` request fetches selected details in batches of at most 20 IDs. The provider does not request statistics, players, lineups, standings, or odds separately.

Cadence is state-based: no nearby match sleeps for up to 12 hours; matches more than three hours away are checked sparsely; a kickoff within three hours is checked every 30 minutes or less; within 30 minutes every 12 minutes; live every 10 minutes; halftime every 18 minutes; and a full-time match receives one final detail verification after two minutes. Cadence slows further as the daily remainder crosses 50, 30, and 15 calls. The scheduler adds jitter, applies exponential transient-error backoff, honors `Retry-After`, and cancels cleanly at shutdown. A depleted local budget waits until the next UTC reset rather than sending a request.

## Event comparison and persistence

Each fixture's last accepted state, score, status, version, and provider-event identities live in `provider_checkpoints`. Repeated identical snapshots and repeated events in an event array create no new canonical events. API-Football does not consistently expose an event ID, so the adapter hashes fixture, event kind, minute, team, player, and (for cards/substitutions) detail and incoming-player fields. Goal identity omits mutable detail so a VAR detail change does not become a second goal. A reported score increase not accounted for by the event list creates a deterministic goal observation; a score decrease or mismatch creates `football.match.score_corrected`. Repeated unchanged scores never imply a goal.

Provider event minutes are combined with the fixture's actual kickoff time when available. Otherwise the scheduled kickoff plus elapsed minutes is used as the best available UTC occurrence-time estimate. Poll observation time is retained separately. Late events can be appended with their earlier occurrence time; stale lower-minute snapshots cannot regress stored score or lifecycle. The event and matching outbox record are persisted through the M1 repository in the same transaction as checkpoint advancement. The provider never writes to `match_state` or `pulse_timeline`; the existing projector remains authoritative. Fixture discovery is exposed as the read-only `GET /api/v1/football/fixtures` response with `today`, `upcoming`, and `live` lists.

## Failure and health behavior

401/403 and permanent provider configuration errors report `unavailable`; transient timeouts, transport errors, and 5xx responses retry through the shared scheduler; 429 responses report `rate_limited` with the provider cooldown. Quota headers are retained when present. Health is secret-free and includes last success, last observation, consecutive failures, and cooldown. Error bodies and the API key are never logged.

## Configuration and tests

Set `API_FOOTBALL_KEY` in the ignored root `.env` file. Do not add it to source, test fixtures, or logs. Install backend dependencies with the repository's normal backend setup. The default provider tests use committed API-shaped JSON fixtures and mocked HTTP; they do not need a key or API quota:

```powershell
Set-Location backend
python -m pytest tests/providers/football -q
python -m ruff check app tests alembic
```

The manual live smoke check makes exactly two calls: a focused current-league search for Premier League and one batched `/fixtures?live=...` request using the resolved API ID. It prints only resolved competition and fixture counts:

```powershell
Set-Location backend
python scripts/football_live_smoke.py
```

Official references: [API-Football v3 documentation](https://www.api-football.com/documentation-v3), [rate-limit headers and quota behavior](https://www.api-football.com/news/post/how-ratelimit-works), and [quota-aware fixture batching, including the 20-ID limit](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage).
