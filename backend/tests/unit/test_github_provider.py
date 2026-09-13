import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from uuid6 import uuid7

from app.core.config import MONITORED_GITHUB_REPOSITORIES, Settings
from app.providers.base import PollContext
from app.providers.github.client import GithubApiError, normalize_api_error
from app.providers.github.events import normalize_webhook
from app.providers.github.health import GithubHealthTracker
from app.providers.github.reconcile import GithubReconciliationSource
from app.providers.github.security import verify_signature
from app.providers.github.webhook import GithubWebhookProcessor

NOW = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _body(repository: str = "Strata", owner: str = "acme", **fields: object) -> bytes:
    return json.dumps(
        {
            "repository": {
                "name": repository,
                "full_name": f"{owner}/{repository}",
                "owner": {"login": owner},
            },
            **fields,
        },
        separators=(",", ":"),
    ).encode()


def _settings(**kwargs: object) -> Settings:
    return Settings(
        _env_file=None,
        github_owner="acme",
        github_webhook_secret=SecretStr("webhook-secret"),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_webhook_signature_valid_invalid_missing_and_constant_time_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _body(after="commit-1", ref="refs/heads/main", commits=[])
    comparisons: list[tuple[str, str]] = []
    original = hmac.compare_digest

    def compare(left: str, right: str) -> bool:
        comparisons.append((left, right))
        return original(left, right)

    monkeypatch.setattr("app.providers.github.security.hmac.compare_digest", compare)
    assert verify_signature("webhook-secret", _signature("webhook-secret", body), body)
    assert len(comparisons) == 1
    assert not verify_signature("webhook-secret", _signature("wrong", body), body)
    assert not verify_signature("webhook-secret", None, body)

    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": _signature("webhook-secret", body),
    }
    processor = GithubWebhookProcessor(
        persist=_memory_delivery_store(),
        health=GithubHealthTracker(),
        settings_getter=lambda: _settings(),
    )
    assert await processor.verify(headers=headers, body=body)
    normalized = await processor.normalize(headers=headers, body=body, observed_at=NOW)
    assert [change.content.event_type for change in normalized] == ["developer.push.received"]
    result, changes = await processor.process(
        settings=_settings(), headers=headers, raw_body=body, observed_at=NOW
    )
    assert result == "accepted"
    assert [change.content.event_type for change in changes] == ["developer.push.received"]
    assert changes[0].content.payload["delivery_id"] == "delivery-1"

    invalid = {**headers, "X-Hub-Signature-256": _signature("wrong", body)}
    result, _ = await processor.process(
        settings=_settings(), headers=invalid, raw_body=body, observed_at=NOW
    )
    assert result == "invalid_signature"
    result, _ = await processor.process(
        settings=_settings(),
        headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "delivery-2"},
        raw_body=body,
        observed_at=NOW,
    )
    assert result == "missing_signature"


@pytest.mark.asyncio
async def test_webhook_allowlist_rejects_unconfigured_repository_before_persistence() -> None:
    saved: list[str] = []

    async def persist(**kwargs: object) -> bool:
        saved.append(str(kwargs["delivery_id"]))
        return True

    body = _body("OtherRepo", after="commit-2", ref="refs/heads/main", commits=[])
    result, changes = await GithubWebhookProcessor(
        persist=persist, health=GithubHealthTracker()
    ).process(
        settings=_settings(),
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-3",
            "X-Hub-Signature-256": _signature("webhook-secret", body),
        },
        raw_body=body,
        observed_at=NOW,
    )
    assert result == "ignored_unconfigured_repository"
    assert not changes and not saved

    wrong_owner_body = _body(owner="someone-else", after="commit-3", ref="refs/heads/main")
    result, changes = await GithubWebhookProcessor(
        persist=persist, health=GithubHealthTracker()
    ).process(
        settings=_settings(),
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-4",
            "X-Hub-Signature-256": _signature("webhook-secret", wrong_owner_body),
        },
        raw_body=wrong_owner_body,
        observed_at=NOW,
    )
    assert result == "ignored_unconfigured_repository"
    assert not changes and not saved


@pytest.mark.asyncio
async def test_webhook_delivery_identity_deduplicates_repeated_deliveries() -> None:
    persist = _memory_delivery_store()
    processor = GithubWebhookProcessor(persist=persist, health=GithubHealthTracker())
    body = _body(after="commit-5", ref="refs/heads/main", commits=[])
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "delivery-repeat",
        "X-Hub-Signature-256": _signature("webhook-secret", body),
    }
    first, _ = await processor.process(
        settings=_settings(), headers=headers, raw_body=body, observed_at=NOW
    )
    second, _ = await processor.process(
        settings=_settings(), headers=headers, raw_body=body, observed_at=NOW
    )
    assert first == "accepted"
    assert second == "duplicate"


def test_github_webhook_event_mappings_and_irrelevant_action_suppression() -> None:
    repository = "acme/Strata"
    opened = normalize_webhook(
        event_name="pull_request",
        payload={
            "action": "opened",
            "number": 12,
            "pull_request": {
                "title": "Add integration",
                "created_at": "2026-09-12T17:00:00Z",
                "html_url": "https://github.com/acme/Strata/pull/12",
                "user": {"login": "dev"},
            },
        },
        repository=repository,
        delivery_id="delivery-pr-open",
        observed_at=NOW,
    )
    merged = normalize_webhook(
        event_name="pull_request",
        payload={
            "action": "closed",
            "number": 12,
            "pull_request": {
                "merged": True,
                "merged_at": "2026-09-12T18:00:00Z",
            },
        },
        repository=repository,
        delivery_id="delivery-pr-merged",
        observed_at=NOW,
    )
    assert [change.event_type for change in opened] == ["developer.pull_request.opened"]
    assert [change.event_type for change in merged] == ["developer.pull_request.merged"]

    def run(action: str, conclusion: str | None = None):
        run_payload = {
            "action": action,
            "workflow_run": {
                "id": 700,
                "run_number": 21,
                "run_attempt": 1,
                "name": "CI",
                "run_started_at": "2026-09-12T17:20:00Z",
                "updated_at": "2026-09-12T17:30:00Z",
                "conclusion": conclusion,
            },
        }
        return normalize_webhook(
            event_name="workflow_run",
            payload=run_payload,
            repository=repository,
            delivery_id=f"delivery-{action}-{conclusion}",
            observed_at=NOW,
        )

    assert [item.event_type for item in run("in_progress")] == ["developer.workflow.started"]
    assert [item.event_type for item in run("completed", "success")] == [
        "developer.workflow.started",
        "developer.workflow.completed",
    ]
    assert [item.event_type for item in run("completed", "failure")][-1] == (
        "developer.workflow.failed"
    )
    assert run("requested") == ()
    assert normalize_webhook(
        event_name="pull_request",
        payload={"action": "synchronize", "number": 12, "pull_request": {}},
        repository=repository,
        delivery_id="delivery-irrelevant",
        observed_at=NOW,
    ) == ()
    deployment = normalize_webhook(
        event_name="deployment_status",
        payload={
            "deployment": {"id": 8, "environment": "production", "ref": "commit"},
            "deployment_status": {
                "id": 9,
                "state": "success",
                "created_at": "2026-09-12T17:45:00Z",
            },
        },
        repository=repository,
        delivery_id="delivery-deployment",
        observed_at=NOW,
    )
    assert [change.event_type for change in deployment] == ["developer.deployment.completed"]


@pytest.mark.asyncio
async def test_rest_reconciliation_uses_ids_and_checkpoints_to_suppress_repeat_events() -> None:
    settings = _settings(github_token=SecretStr("token"))
    checkpoint_values: dict[str, str] = {}
    checkpoint_queries: list[tuple[str, ...]] = []

    async def read_checkpoints(keys):
        checkpoint_queries.append(tuple(keys))
        return {key: checkpoint_values[key] for key in keys if key in checkpoint_values}

    class FakeClient:
        def __init__(self) -> None:
            self.paths: list[str] = []

        async def get_json(self, path: str, *, params=None):
            self.paths.append(path)
            if path.endswith("/pulls"):
                return [
                    {
                        "number": 1,
                        "title": "Open PR",
                        "created_at": "2026-09-11T10:00:00Z",
                        "html_url": "https://github.com/acme/Strata/pull/1",
                    },
                    {
                        "number": 2,
                        "title": "Merged PR",
                        "created_at": "2026-09-10T10:00:00Z",
                        "merged_at": "2026-09-11T11:00:00Z",
                    },
                ]
            if path.endswith("/actions/runs"):
                return {
                    "workflow_runs": [
                        {
                            "id": 50,
                            "run_number": 4,
                            "run_attempt": 1,
                            "name": "CI",
                            "status": "completed",
                            "conclusion": "success",
                            "run_started_at": "2026-09-12T08:00:00Z",
                            "updated_at": "2026-09-12T08:03:00Z",
                        }
                    ]
                }
            if path.endswith("/deployments"):
                return [{"id": 90, "environment": "production", "ref": "main"}]
            if path.endswith("/statuses"):
                return [
                    {
                        "id": 91,
                        "state": "success",
                        "created_at": "2026-09-12T08:10:00Z",
                    }
                ]
            raise AssertionError(f"unexpected GitHub API path: {path}")

    client = FakeClient()
    source = GithubReconciliationSource(
        settings,
        client=client,  # type: ignore[arg-type]
        checkpoint_reader=read_checkpoints,
        health=GithubHealthTracker(),
    )
    context = PollContext(correlation_id=uuid7(), scheduled_at=NOW)
    first = await source.observe(context=context)
    assert {item.content.event_type for item in first} == {
        "developer.pull_request.opened",
        "developer.pull_request.merged",
        "developer.workflow.started",
        "developer.workflow.completed",
        "developer.deployment.completed",
    }
    assert len(first) == 6 * len(MONITORED_GITHUB_REPOSITORIES)
    # Each repository costs pulls, workflow runs, deployments, and deployment
    # status calls (when a deployment exists).
    assert len(client.paths) == 4 * len(MONITORED_GITHUB_REPOSITORIES)
    assert all(
        any(f"/repos/acme/{repository}/" in path for path in client.paths)
        for repository in MONITORED_GITHUB_REPOSITORIES
    )
    assert len(set(client.paths)) == 4 * len(MONITORED_GITHUB_REPOSITORIES)
    for item in first:
        checkpoint_values[item.content.checkpoint_key] = item.content.checkpoint_value
    second = await source.observe(context=context)
    assert second == ()
    assert len(checkpoint_queries) == 2


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (401, {}, "github_unauthorized"),
        (403, {}, "github_forbidden"),
        (
            403,
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790000000"},
            "github_rate_limited",
        ),
        (429, {"Retry-After": "10"}, "github_rate_limited"),
        (500, {}, "github_server_error"),
        (503, {}, "github_server_error"),
    ],
)
def test_github_api_http_failures_have_safe_normalized_codes(
    status: int, headers: dict[str, str], expected: str
) -> None:
    error: GithubApiError = normalize_api_error(status, headers, now=NOW)
    assert error.detail_code == expected
    assert expected not in {"github_rate_limited"} or error.retry_after is not None


def test_github_health_distinguishes_webhook_and_reconciliation() -> None:
    tracker = GithubHealthTracker()
    webhook_only = _settings()
    tracker.initialize(webhook_only)
    before = tracker.snapshot(webhook_only, now=NOW)
    assert before["webhook"]["configured"] is True
    assert before["webhook"]["listening"] is True
    assert before["reconciliation"]["configured"] is False
    assert before["reconciliation"]["status"] == "disconnected"
    assert before["status"] == "degraded"
    tracker.note_webhook(webhook_only, now=NOW)
    after = tracker.snapshot(webhook_only, now=NOW)
    assert after["webhook"]["last_received_at"] == NOW.isoformat()

    token_settings = _settings(github_token=SecretStr("token"))
    tracker.initialize(token_settings)
    tracker.note_reconciliation_success(now=NOW)
    healthy = tracker.snapshot(token_settings, now=NOW)
    assert healthy["reconciliation"]["status"] == "healthy"
    assert healthy["reconciliation"]["last_success_at"] == NOW.isoformat()
    stale = tracker.snapshot(token_settings, now=datetime(2026, 9, 12, 19, 0, tzinfo=UTC))
    assert stale["reconciliation"]["status"] == "stale"
    assert stale["reconciliation"]["detail_code"] == "reconciliation_stale"


def test_github_configuration_cannot_expand_the_locked_repository_set() -> None:
    settings = _settings(github_repositories="EverythingElse")
    assert settings.provider_configuration()["github"] is True
    assert GithubHealthTracker.webhook_configured(settings) is True
    assert MONITORED_GITHUB_REPOSITORIES == (
        "Strata",
        "Tandem",
        "OptiScale",
        "LivePulse",
        "Portfolio",
    )


def _memory_delivery_store():
    deliveries: set[str] = set()

    async def persist(**kwargs: object) -> bool:
        delivery_id = str(kwargs["delivery_id"])
        if delivery_id in deliveries:
            return False
        deliveries.add(delivery_id)
        return True

    return persist
