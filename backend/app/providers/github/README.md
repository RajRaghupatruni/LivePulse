# GitHub provider

This adapter supports signed webhook delivery plus read-only REST reconciliation. It emits only
normalized developer events through the existing canonical-event/outbox transaction; it never
writes timeline rows directly.

## Configuration and repository scope

Set `GITHUB_OWNER` to the GitHub user or organization that owns all five monitored repositories:
`Strata`, `Tandem`, `OptiScale`, `LivePulse`, and `Portfolio`. This list is fixed in code and cannot
be widened or narrowed by environment configuration. The adapter does not enumerate the account.

`GITHUB_WEBHOOK_SECRET` enables webhook verification. `GITHUB_TOKEN` enables reconciliation.
Either capability can run without the other. Store both values only in the ignored local `.env`;
neither appears in health responses or logs.

## Webhook setup

1. Make the LivePulse backend reachable from GitHub over HTTPS (for local development, use a
   trusted development tunnel). Docker Compose binds host ports to `127.0.0.1`; it does not create
   an inbound public endpoint or tunnel.
2. In the GitHub organization/repository webhook settings, create a webhook pointed at
   `https://<your-livepulse-host>/api/v1/webhooks/github`, with content type `application/json`.
3. Configure a high-entropy webhook secret in GitHub and the same value as `GITHUB_WEBHOOK_SECRET`
   in LivePulse's local `.env`. Restart LivePulse after changing the environment.
4. Subscribe to `push`, `pull_request`, `workflow_run`, and `deployment_status` events. The
   `deployment` event alone is not needed; terminal deployment status is received separately.
5. Use GitHub's recent-deliveries page to verify responses. The endpoint validates the original
   body bytes with `X-Hub-Signature-256` (HMAC-SHA256), compares signatures in constant time, and
   uses `X-GitHub-Delivery` for durable delivery deduplication.

Only the configured owner and allowlisted repository names are accepted for event production.
Unknown repository deliveries are acknowledged but ignored. Pushes, opened/merged pull requests,
workflow starts/completions/failures, and successful/failed deployment statuses are normalized;
other actions do not create events.

## Reconciliation

When `GITHUB_TOKEN` is present, the application registers the reconciliation source with the shared
poll scheduler. The first five-minute poll runs in the background after application startup; source
construction itself makes no provider request. The poll uses timeout, jitter, exponential
backoff, and `Retry-After` support from the shared scheduler. It checks at most the ten most
recently updated pull requests, ten recent workflow runs, and three deployments per configured
repository, then fetches each selected deployment's latest status. Shared provider checkpoints are
keyed by repository/resource ID and transition, so previously recorded semantic changes are
skipped while later workflow/deployment transitions remain detectable. Canonical event IDs also
deduplicate webhook and reconciliation observations against one another.

For a fine-grained token, select only the five monitored repositories and grant repository
permissions `Metadata: read` (GitHub requires this), `Pull requests: read`, `Actions: read`, and
`Deployments: read`. The current REST endpoints are covered by GitHub's
[fine-grained token permission matrix](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
No contents-write permission is used; push events arrive through webhooks. A classic token needs
the least repository-read scope that covers the selected repositories. Reconciliation health is
separate from webhook health at `GET /api/v1/providers/github/health`.

## Health and limitations

The health endpoint distinguishes webhook configuration/listening/last receipt from REST
reconciliation configuration/status/last attempt/last success. Without a token, a configured
webhook can still run, while reconciliation is reported disconnected and the combined GitHub
provider is degraded. Webhook delivery needs an inbound HTTPS route; no tunnel or public endpoint
is created by LivePulse.

Reconciliation intentionally samples bounded recent pages rather than mirroring repository
history. Push reconciliation is not implemented; webhook delivery is the push path. Only the
latest status of a small recent deployment page is polled. Older transitions outside those pages
can be missed if both webhook delivery and bounded catch-up are unavailable for a long period.
