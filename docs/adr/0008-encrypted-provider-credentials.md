# ADR 0008: Encrypted provider credential persistence

**Status:** Accepted and implemented in M3

## Context

Spotify and Gmail will eventually hold server-side access and refresh tokens. Plaintext persistence or a token-bearing browser/API model would violate the security boundary, but provider streams should share one schema and encryption mechanism.

## Decision

Add one `provider_connections` record per provider and a shared `provider_checkpoints` table. Encrypt credential blobs at the application boundary with Fernet from the mature `cryptography` package and a `CREDENTIAL_ENCRYPTION_KEY` supplied through the ignored local environment. The ORM credential type accepts only the redacted `EncryptedCredentials` wrapper, not plaintext strings. Decryption is explicit and server-side. Health/log/command contracts do not include credentials.

The key is not generated, committed, or defaulted by the app. Missing/invalid key prevents credential encryption operations only; optional provider configuration does not block startup. Spotify and Gmail implement separate OAuth flows and refresh behavior. No token-bearing browser endpoint exists; connection APIs return safe state only.

## Consequences and risks

- Database backups contain ciphertext rather than provider tokens; the key must be backed up separately and protected.
- Losing the key makes stored credentials unreadable. Key rotation and re-encryption procedures are required before production use.
- Fernet is appropriate for small credential envelopes at rest; it is not a substitute for a production secret manager, host security, or a threat model.
- There is no production claim until authentication, key rotation, restore testing, and the locked security/threat model are complete.
