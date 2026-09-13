# LivePulse M3 security and privacy boundaries

## Deployment boundary

M3 is a single-user local development service. Docker Compose publishes all host ports on
`127.0.0.1`. The API has no user authentication, authorization, CSRF defense for browser
sessions, tenant isolation, or public-demo data partition. Do not expose the backend,
frontend, PostgreSQL, or Redpanda to an untrusted network. A reverse proxy or HTTPS tunnel
does not add the missing application authorization boundary.

The deterministic public demo requirement remains unimplemented. Before public access, add
an authenticated private mode and a separate demo mode that disables personal provider
sources, uses synthetic seeded data, and cannot read private provider tables or timeline
entries. Public demo responses must contain only synthetic data.

## Assets and retained data

Sensitive assets include local provider credentials, Gmail message metadata, Spotify
playback metadata, monitored GitHub activity, personal weather coordinates, canonical event
history, and database backups. PostgreSQL retains canonical events and timeline records
without an automatic retention policy. Gmail stores bounded metadata (sender, subject,
message/thread identity, received time, a safe snippet of at most 240 characters, and
unread/important flags); it does not persist message bodies. Spotify metadata may include
track/episode, artist, context, device, and playback state. GitHub events include only the
normalized activity fields required for timeline display. Weather coordinates are local
configuration and request inputs, not health or event fields.

## Implemented controls

- Spotify requests only `user-read-playback-state` and `user-modify-playback-state`.
  OAuth state is random, single-use, and expires after ten minutes. Access/refresh tokens
  are Fernet-encrypted in `provider_connections`; refresh is serialized. Callback query
  strings and tokens are excluded from logs and API responses.
- Gmail requests only `gmail.readonly`. There are no Gmail mutation routes or client
  methods. Credentials are Fernet-encrypted, message bodies are not persisted, metadata and
  checkpoint history are bounded, and history cursor advancement shares a transaction with
  accepted canonical events and outbox rows. OAuth callback query strings are redacted.
- GitHub webhook signatures use HMAC-SHA256 over the raw request body and constant-time
  comparison. Delivery IDs are durably deduplicated. Processing is restricted to the fixed
  five-repository allowlist. The webhook secret is never logged.
- Football API credentials are sent in the provider header and are not logged. Weather
  coordinates are omitted from provider health, normalized events, and application logs.
- Provider and system health expose safe status/error codes, never tokens, message bodies,
  provider payloads, account identifiers, coordinates, or secrets. Optional credentials
  are blank in `.env.example`; local `.env` is ignored by Git.
- Provider DTOs remain within adapter packages. Immutable canonical events and the shared
  idempotent projector own the persisted timeline. Non-football events cannot mutate
  football match state.

## Key and host operations

The operator generates `CREDENTIAL_ENCRYPTION_KEY` and keeps it outside source control and
separate from database backups. Losing the key makes stored OAuth credentials unreadable.
Rotation, re-encryption, secret-manager integration, restore exercises, and a documented
credential deletion/retention workflow are not implemented. Secure the host account, local
`.env`, Docker daemon, and database backups. Do not include real credentials or personal
coordinates in issues, logs, screenshots, or committed fixtures.

## Remaining P0 security work

M3 does not make the app safe for multi-user or public use. Authentication and authorization,
public-demo isolation, origin/CSRF design, retention/deletion controls, key rotation and
recovery, audit logging, and production deployment hardening remain P0 incomplete. No live
provider account is configured by default; enabling an integration is an explicit local
operator action. M4 AI and provider-specific frontend surfaces are out of scope.
