# API-Football provider

LivePulse's real football adapter uses the API-Football v3 API at `https://v3.football.api-sports.io` with the `x-apisports-key` header. The provider is optional: without `API_FOOTBALL_KEY`, its health is `disconnected` and it makes no network requests. HTTP calls use a pooled async `httpx` client with separate connect/read/write/pool timeouts.

Competition IDs are resolved from `/leagues?current=true`; the adapter matches the returned competition name and country to the locked set and stores the resolved map in `provider_checkpoints` for seven days. It does not rely on ID guesses. It recognizes aliases including `EPL`, `Champions League`, and `League Cup` while retaining canonical labels such as `Premier League`, `UEFA Champions League`, and `Carabao Cup`.

## Request budget and polling

The provider uses a local daily budget of 100 requests and reserves the final five calls. It reconciles that budget with `x-ratelimit-requests-limit`, `x-ratelimit-requests-remaining`, and `X-RateLimit-Remaining` when supplied. Production HTTP requests are serialized and spaced 6.1 seconds apart to stay under the roughly ten-per-minute free-tier limit. The persisted counter resets at 00:00 UTC; if headers are absent, the 100-call local limit remains authoritative. The `/api/v1/system/health` football entry includes request use, remaining local/provider quota, and the next UTC reset when configured.

Schedule discovery maintains a rolling seven-day horizon (today through six days ahead), with one `/fixtures?league=...&season=...&from=...&to=...&timezone=UTC` request per resolved competition and a 20-hour cache. This provides an upcoming-match view beyond tomorrow while limiting discovery to roughly 11 calls per day for the 11 locked competitions. The resolved competition catalog is cached for seven days. The provider follows paging metadata if a scoped window has multiple pages. Live discovery uses the cheapest useful batch: one `/fixtures?live=...` request covers all resolved locked leagues, rather than polling each competition. If that response omits needed events, one `/fixtures?ids=...` request fetches selected details in batches of at most 20 IDs. The provider does not request statistics, players, lineups, standings, or odds separately.

Cadence is state- and quota-aware, and health reports both the chosen interval and its reason. A relevant live match refreshes every 150 seconds while more than 50 calls remain. For 31–50 remaining calls the cadence floor is three minutes; 16–30 gives five minutes; 6–15 gives ten minutes; the final five calls are reserved and polling waits for the next UTC reset once that reserve is reached. If selected fixture-detail requests make a poll cost more than one call, the cadence lengthens proportionally. Halftime uses five minutes. Upcoming matches are checked at 150 seconds within five minutes of kickoff, five minutes within 30 minutes, 30 minutes within three hours, one hour within six hours, and every 3–12 hours farther out. With no live or upcoming fixture, checks slow to 12 hours. A full-time match receives one final detail verification after two minutes. The live query batches all locked leagues, so a healthy live cadence costs about 24 batched fixture calls per hour (plus any needed detail batches), rather than 24 calls per competition. The roughly 11 daily competition-discovery calls and five-call reserve leave about 84 calls for live/detail work; quota tiers spread those calls over the day instead of spending them at a fixed fast interval. The scheduler adds jitter, applies exponential transient-error backoff, honors `Retry-After`, and cancels cleanly at shutdown. Provider cooldowns and daily-budget exhaustion suppress requests until eligible; after UTC reset, normal cadence resumes.

## Event comparison and persistence

Each fixture's last accepted state, score, status, version, and provider-event identities live in `provider_checkpoints`. Repeated identical snapshots and repeated events in an event array create no new canonical events. API-Football does not consistently expose an event ID, so the adapter hashes fixture, event kind, minute, team, player, and (for cards/substitutions) detail and incoming-player fields. Goal identity omits mutable detail so a VAR detail change does not become a second goal. A reported score increase not accounted for by the event list creates a deterministic goal observation; a score decrease or mismatch creates `football.match.score_corrected`. Repeated unchanged scores never imply a goal.

Provider event minutes are combined with the fixture's actual kickoff time when available. Otherwise the scheduled kickoff plus elapsed minutes is used as the best available UTC occurrence-time estimate. Poll observation time is retained separately. Late events can be appended with their earlier occurrence time; stale lower-minute snapshots cannot regress stored score or lifecycle. The event and matching outbox record are persisted through the M1 repository in the same transaction as checkpoint advancement. The provider never writes to `match_state` or `pulse_timeline`; the existing projector remains authoritative. Fixture discovery is exposed as the read-only `GET /api/v1/football/fixtures` response with `today`, `upcoming`, and `live` lists.

## Failure and health behavior

401/403 reports an authentication/provider authorization failure; other permanent provider configuration errors report provider failure. Transient timeouts, transport errors, and 5xx responses retry through the shared scheduler; 429 responses report `rate_limited` with the provider cooldown. Quota headers are retained when present. Health is secret-free and includes last success, last observation, consecutive failures, cadence reason, remaining quota, and cooldown. Error bodies and the API key are never logged.

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
