# LivePulse Spotify provider

This package implements a server-side Spotify Authorization Code connection, current playback polling, Spotify player commands, provider health, and canonical playback events. It does not stream, download, proxy, or store audio. Track and episode names, artist names, album/show names, artwork URLs, and player metadata are provider metadata only.

## App registration and local configuration

1. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Copy its Client ID and Client Secret into the ignored local `.env` as `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`.
3. Register this exact local Redirect URI in the app settings and set the same value in `.env`:

   ```text
   http://127.0.0.1:8000/api/v1/providers/spotify/oauth/callback
   ```

   Replace the origin and port only when the backend is served elsewhere. Keep the callback path exactly `/api/v1/providers/spotify/oauth/callback`. Spotify requires the authorization request and token exchange to use the exact registered URI. Use HTTPS outside local loopback; Spotify does not accept `localhost` as a redirect host.
4. Generate a Fernet key and set it as `CREDENTIAL_ENCRYPTION_KEY`. For example, from the backend environment run `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep the key out of source control and back it up separately from the database.
5. The operator's Spotify account must have Premium for a development-mode app. Spotify also requires the app owner to have Premium; add any other test users to the app's Users and Access allowlist. Development mode is limited to five authenticated users.

## OAuth and credential lifecycle

`GET /api/v1/providers/spotify/oauth/start` redirects to Spotify's Authorization Code flow. The provider creates a 256-bit-plus random state, accepts it once, and expires it after ten minutes. `GET /api/v1/providers/spotify/oauth/callback` validates state before exchanging the code. Both the authorization request and the token exchange use the configured redirect URI verbatim. The callback strips its query string before response access logging so the authorization code is not written to request logs. The client secret and token exchange remain on the backend.

Access and refresh tokens, expiry, and granted scopes are serialized into one Fernet-encrypted blob in the shared `provider_connections` record. The API returns only connection state and safe freshness details. Refresh is serialized by a process-local asyncio lock; a concurrent request reuses a token another request has already refreshed. A rotated refresh token replaces the old one, while a response with no refresh token preserves the existing value. Spotify refresh tokens currently expire after six months, and refresh does not extend that lifetime. An `invalid_grant` response clears unusable local credentials and reports `authorization_expired` / `reconnect_required`.

`DELETE /api/v1/providers/spotify/connection` removes the local encrypted credentials and cached playback state. This disconnects LivePulse locally. Spotify does not document a general Web API token-revocation endpoint; to revoke the app authorization at Spotify too, remove LivePulse from [your Spotify account's apps](https://www.spotify.com/account/apps/).

The OAuth state and refresh lock are in-process, matching the accepted single-instance scheduler ADR. A multi-instance deployment needs shared state/locking before it is supported.

## Scopes

The provider requests exactly:

- `user-read-playback-state` to read `GET /me/player`, including the current track or episode, progress, active device, playback mode, and context.
- `user-modify-playback-state` to control, seek, change volume, and transfer playback.

It does not call `GET /me/player/currently-playing`, so it does not request `user-read-currently-playing`. It requests no profile, email, library, playlist, or listening-history access.

## Polling and rate limits

Register `spotify_provider.poll_source` with the shared `PollScheduler` and use `spotify_provider.event_sink.handle` as its observation handler. The source adapts its cadence to the most recent response:

| State | Base interval |
|---|---:|
| Playing | 5 seconds |
| Paused with an active playback state | 20 seconds |
| No active playback/device (`204`) | 60 seconds |

The scheduler adds 10% jitter, bounds concurrent work, times out polls after 15 seconds, and applies capped exponential backoff up to five minutes after errors. A Spotify `429` response becomes the shared scheduler's absolute `Retry-After` delay; missing or malformed headers use a 60-second fallback. The source tracks normalized state in memory and suppresses unchanged polling results. Progress-only movement is reflected in the current playback DTO but does not create timeline events.

## Current playback and events

`GET /api/v1/providers/spotify/playback` returns the latest provider-owned playback DTO and its observation age. `GET /api/v1/providers/spotify/devices` returns currently available Connect devices for device selection before a transfer command. Playback state is an in-memory scheduler cache, not a second durable projection. It is empty until the first successful poll after startup; the shared canonical history remains durable in PostgreSQL and its transactional outbox.

Meaningful changes map to the reserved event family:

| State transition | Canonical event |
|---|---|
| First observed active playback | `spotify.playback.started` |
| Playing to paused | `spotify.playback.paused` |
| Same paused item resumes | `spotify.playback.resumed` |
| Track or episode identity changes | `spotify.track.changed` |
| Device identity/name/type changes | `spotify.device.changed` |
| Context URI/type changes | `spotify.context.changed` |

Each event gets a deterministic dedupe key from its type, Spotify's playback-change timestamp when provided, and the event's normalized metadata. Events use the existing `CanonicalEvent` model and `persist_event_and_outbox` transaction. The shared projector writes non-football canonical events to the durable timeline with its normal idempotency check and leaves football match state/focus untouched. Spotify player progress ticks, repeat/shuffle-only changes, and volume-only changes do not emit an event because the locked event family has no corresponding event type.

## Commands

`POST /api/v1/providers/spotify/commands` accepts the shared typed `CommandRequest` and implements:

| Command | Spotify request |
|---|---|
| `spotify.play` | `PUT /me/player/play` |
| `spotify.pause` | `PUT /me/player/pause` |
| `spotify.next` | `POST /me/player/next` |
| `spotify.previous` | `POST /me/player/previous` |
| `spotify.seek` | `PUT /me/player/seek?position_ms=...` |
| `spotify.volume` | `PUT /me/player/volume?volume_percent=...` |
| `spotify.transfer_device` | `PUT /me/player` with one `device_ids` entry |

Seek accepts integer seconds from 0 through 86,400 and sends milliseconds. Volume is an integer from 0 through 100. Transfer requires a nonblank device ID. The provider maps `204` to success; `401` refreshes once and retries once; `403` returns a stable provider error explaining that Premium or an allowed device may be required; missing-device `404` maps to `invalid_state`; and `429` maps to `rate_limited` with a safe retry hint. No command accepts an arbitrary method, URL, or path.

Player control, seeking, volume, and transfer require Spotify Premium. Device availability, Spotify app mode, account allowlisting, and changing Spotify quota rules can also cause `403` responses.

## Router and integration

The provider router is exported from `app.providers.spotify.router` as `router`; `create_spotify_router(provider=...)` supports isolated registration and tests. The main app can register it with `app.include_router(router)`. The provider composition object also exposes `poll_source`, `event_sink.handle`, `command_target`, and `health`. No main-app route or lifespan wiring is added in this provider branch.

## Manual check

After app registration and environment setup, open `GET /api/v1/providers/spotify/oauth/start` in a browser, approve the requested playback scopes, and confirm that the callback returns only `{ "provider": "spotify", "connected": true }`. Then inspect `GET /api/v1/providers/spotify/connection` and `GET /api/v1/providers/spotify/playback`, and exercise a player command while a Spotify Connect device is active. Provider tests use mocked HTTP and do not require an account.
