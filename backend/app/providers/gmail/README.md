# Gmail provider (read-only P0)

This provider uses server-side Google OAuth Authorization Code flow and the single scope
`https://www.googleapis.com/auth/gmail.readonly`. LivePulse never requests Gmail send, compose,
modify, or full-mailbox access scopes. There are no Gmail mailbox-mutation routes or client
methods. The local `DELETE /api/v1/providers/gmail/connection` endpoint only forgets the
encrypted LivePulse connection and Gmail synchronization checkpoints; it does not call a
Google mailbox mutation API or remove existing timeline history.

## Google Cloud setup

1. Create or select a Google Cloud project and enable the Gmail API.
2. Configure the OAuth consent screen for the intended test users/account.
3. Create an OAuth client with application type **Web application**.
4. Add this exact Authorized redirect URI:
   `http://localhost:8000/api/v1/providers/gmail/oauth/callback`
   Use the matching externally reachable backend origin for a non-local installation.
5. Put the client ID, client secret, redirect URI, and a generated Fernet key in the ignored
   backend environment. The repository `.env.example` names these as `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, and `CREDENTIAL_ENCRYPTION_KEY`.
6. Start the backend and open `http://localhost:8000/api/v1/providers/gmail/oauth/start` in a
   browser. Google redirects to the callback after consent. The callback stores tokens server-side,
   then redirects to a safe status page so the authorization code does not remain in the browser URL.

Google Cloud may require the OAuth app to be in Testing mode with the account added as a test user.
The operator must also protect and back up the encryption key separately from the database; losing
that key makes stored tokens unusable.

## Synchronization and privacy

The first synchronization captures Gmail's current history ID, then lists at most 50 messages from
the last 14 days or marked unread/important. It requests message metadata and headers, not MIME
bodies. The bounded initial list creates received-message and thread-update canonical events.

Subsequent polls use Gmail `history.list(startHistoryId=...)` at a four-minute healthy cadence,
reading at most 50 history records per poll and resuming from the last fully handled history ID.
Message additions create received and thread-update events; known-message removals create a thread
update. Label changes are compared against a bounded set of locally checkpointed unread/important
flags; irrelevant label changes do not create timeline events. Gmail's history ID and up to 500
recent flag snapshots use shared provider checkpoints. Event and outbox inserts and checkpoint
advancement share one database transaction, so a failed ingestion cannot move the cursor past
unaccepted events. Event dedupe keys use stable message identity, while flag-change events use Gmail
history identity.

Gmail expires old history IDs. If `history.list` returns 404, LivePulse captures a new profile
history ID and runs one bounded 50-message rescan. It advances the new checkpoint only with the
normal event/outbox transaction. Stable message/thread dedupe keys suppress events already known
from the earlier sync. Future polls resume from the new history ID; recovery does not loop over the
expired cursor.

Provider records retain dashboard metadata only: message/thread IDs, sender, subject, received
time, a 240-character safe snippet, and unread/important flags. Credentials are encrypted with the
shared Fernet credential type. Raw bodies are never stored in checkpoints, canonical events,
outbox payloads, or logs. A bounded body method exists only at the provider service boundary for
future explicit on-demand AI retrieval; it is ephemeral and is not exposed as an HTTP endpoint.

Health is reported through the shared provider health map: successful sync time, last message
observation, failure count, rate-limit retry time, and safe error codes such as
`reconnect_required` or `authorization_expired`. Missing Google configuration leaves Gmail
disconnected without blocking application startup.

The application registers the Gmail OAuth router and read-only service. When the client settings,
redirect URI, and credential-encryption key are available, the incremental sync source is registered
with the shared poll scheduler. Source construction does not contact Google; synchronization starts
in the background after application startup only when a stored authorization is present. The system
health response reports Gmail state without exposing account identifiers or credentials. M3 does not
add a Gmail-specific frontend surface.

P0 uses shared checkpointed polling instead of Google Pub/Sub. History sync is durable and
reconcilable, and the four-minute cadence is sufficient for a personal dashboard. Deferring Pub/Sub
keeps the 24-hour implementation within the existing backend while avoiding a separate cloud
service, topic lifecycle, and delivery configuration.

## Manual smoke check

After Google setup and consent:

1. Check `GET /api/v1/system/health` and confirm the `gmail` entry becomes healthy after its first
   sync. `last_message_observation_at` may remain null if the bounded scan found no messages.
2. Inspect `provider_connections` and confirm Gmail has the single read-only scope and a ciphertext
   credential value. Never copy the ciphertext or key into an issue or log.
3. Inspect `provider_checkpoints` and confirm a Gmail `history_id` plus at most 500
   `message-state:*` records. Values contain IDs/flags, not message bodies.
4. Inspect `canonical_events` / `outbox_messages` for `mail.message.received` and
   `mail.thread.updated`; confirm the payload contains only dashboard metadata.
5. To exercise reconnection, revoke the app's Google consent and wait for a refresh attempt. Health
   should report a safe reconnect/authorization detail; no token should appear in the response.

CI uses mocked OAuth/Gmail HTTP responses and does not require a real Google account. P0 does not
include a Gmail frontend surface, Pub/Sub, AI classification, or body persistence.
