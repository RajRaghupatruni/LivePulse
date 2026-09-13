"""Low-frequency REST catch-up for configured pull requests, workflow runs and deployments."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from app.core.config import LOCKED_GITHUB_REPOSITORIES, Settings
from app.providers.base import PollContext, PollSchedule
from app.providers.github.client import GithubApiError, GithubRestClient
from app.providers.github.events import (
    GithubChange,
    repository_checkpoint_key,
    resource_subject_id,
)
from app.providers.github.health import GithubHealthTracker, github_health
from app.providers.github.storage import github_checkpoints
from app.providers.observations import Observation
from app.providers.scheduler import RetryAfterError

CheckpointReader = Callable[[Sequence[str]], Awaitable[dict[str, str]]]


class GithubReconciliationSource:
    provider_id = "github"
    schedule = PollSchedule(
        interval=timedelta(minutes=5),
        timeout=timedelta(seconds=90),
        max_backoff=timedelta(minutes=30),
        jitter_ratio=0.15,
    )

    def __init__(
        self,
        settings: Settings,
        *,
        client: GithubRestClient | None = None,
        checkpoint_reader: CheckpointReader = github_checkpoints,
        health: GithubHealthTracker = github_health,
    ) -> None:
        if not settings.github_owner or not settings.github_token:
            raise ValueError("GitHub reconciliation requires owner and token configuration")
        self._owner = settings.github_owner
        self._repos = _configured_repositories(settings)
        self._client = client or GithubRestClient(settings.github_token)
        self._checkpoint_reader = checkpoint_reader
        self._health = health

    def cadence(self, *, context: PollContext) -> timedelta:
        return self.schedule.interval

    async def observe(self, *, context: PollContext) -> Sequence[Observation[BaseModel]]:
        observed_at = datetime.now(UTC)
        self._health.note_reconciliation_attempt(now=observed_at)
        try:
            candidates: list[GithubChange] = []
            for repository in self._repos:
                candidates.extend(await self._repository_changes(repository, observed_at))
            checkpoints = await self._checkpoint_reader(
                [change.checkpoint_key for change in candidates if change.checkpoint_key]
            )
            fresh = [
                change
                for change in candidates
                if not change.checkpoint_key or change.checkpoint_key not in checkpoints
            ]
        except asyncio.CancelledError:
            self._health.note_reconciliation_failure(
                "github_poll_cancelled", now=observed_at
            )
            raise
        except GithubApiError as exc:
            self._health.note_reconciliation_failure(
                exc.detail_code, rate_limited_until=exc.retry_after
            )
            if exc.retry_after:
                raise RetryAfterError(exc.retry_after, exc.detail_code) from exc
            raise
        except Exception:
            self._health.note_reconciliation_failure("github_reconciliation_failed")
            raise
        self._health.note_reconciliation_success(now=observed_at)
        return tuple(
            Observation[GithubChange](
                provider_id="github",
                external_entity_id=change.subject_id,
                observed_at=observed_at,
                content=change,
                provider_version=change.dedupe_key,
                checkpoint=change.checkpoint_value,
                correlation_id=context.correlation_id,
            )
            for change in fresh
        )

    async def _repository_changes(
        self, repository: str, observed_at: datetime
    ) -> list[GithubChange]:
        owner = quote(self._owner, safe="")
        name = quote(repository, safe="")
        full_name = f"{self._owner}/{repository}"
        repo_key = repository_checkpoint_key(full_name)
        prefix = f"/repos/{owner}/{name}"
        changes: list[GithubChange] = []

        pull_requests = await self._json_list(
            f"{prefix}/pulls",
            {"state": "all", "sort": "updated", "direction": "desc", "per_page": 10},
        )
        for pull in pull_requests:
            number = _integer(pull.get("number"), 0)
            if number < 1:
                continue
            base = {
                "number": number,
                "title": _text(pull.get("title")),
                "url": _text(pull.get("html_url")),
                "author": _nested_text(pull, "user", "login"),
                "base_ref": _nested_text(pull, "base", "ref"),
                "head_ref": _nested_text(pull, "head", "ref"),
            }
            subject = resource_subject_id(full_name, f"PR-{number}")
            opened_key = f"pull:{repo_key}:{number}:opened"
            changes.append(
                _change(
                    repository=full_name,
                    event_type="developer.pull_request.opened",
                    subject_type="pull_request",
                    subject_id=subject,
                    occurred_at=_timestamp(pull.get("created_at"), observed_at),
                    identity=f"pull-request:{number}:opened",
                    payload=base,
                    checkpoint_key=opened_key,
                )
            )
            if pull.get("merged_at"):
                changes.append(
                    _change(
                        repository=full_name,
                        event_type="developer.pull_request.merged",
                        subject_type="pull_request",
                        subject_id=subject,
                        occurred_at=_timestamp(pull.get("merged_at"), observed_at),
                        identity=f"pull-request:{number}:merged",
                        payload=base,
                        checkpoint_key=f"pull:{repo_key}:{number}:merged",
                    )
                )

        workflow_result = await self._client.get_json(
            f"{prefix}/actions/runs", params={"per_page": 10}
        )
        runs = workflow_result.get("workflow_runs", []) if isinstance(workflow_result, dict) else []
        if isinstance(runs, list):
            for run in runs:
                if not isinstance(run, dict):
                    continue
                run_id = _integer(run.get("id"), 0)
                attempt = _integer(run.get("run_attempt"), 1)
                if run_id < 1:
                    continue
                subject = resource_subject_id(full_name, f"RUN-{run_id}")
                base = {
                    "run_id": run_id,
                    "run_number": _integer(run.get("run_number"), 0),
                    "workflow": _text(run.get("name"), "Workflow"),
                    "branch": _text(run.get("head_branch")),
                    "url": _text(run.get("html_url")),
                    "actor": _nested_text(run, "actor", "login"),
                    "attempt": attempt,
                }
                checkpoint_prefix = f"workflow:{repo_key}:{run_id}:{attempt}"
                status = _text(run.get("status"))
                started_at = _timestamp(run.get("run_started_at"), None)
                if status in {"in_progress", "completed"} and started_at:
                    changes.append(
                        _change(
                            repository=full_name,
                            event_type="developer.workflow.started",
                            subject_type="workflow_run",
                            subject_id=subject,
                            occurred_at=started_at,
                            identity=f"workflow:{run_id}:attempt:{attempt}:started",
                            payload=base,
                            checkpoint_key=f"{checkpoint_prefix}:started",
                        )
                    )
                if status == "completed":
                    conclusion = _text(run.get("conclusion"), "unknown")
                    if conclusion == "success":
                        event_type = "developer.workflow.completed"
                    elif conclusion in {
                        "failure",
                        "cancelled",
                        "timed_out",
                        "action_required",
                        "startup_failure",
                    }:
                        event_type = "developer.workflow.failed"
                    else:
                        continue
                    changes.append(
                        _change(
                            repository=full_name,
                            event_type=event_type,
                            subject_type="workflow_run",
                            subject_id=subject,
                            occurred_at=_timestamp(run.get("updated_at"), observed_at),
                            identity=f"workflow:{run_id}:attempt:{attempt}:{conclusion}",
                            payload={**base, "conclusion": conclusion},
                            checkpoint_key=f"{checkpoint_prefix}:completed",
                        )
                    )

        deployments = await self._json_list(f"{prefix}/deployments", {"per_page": 3})
        for deployment in deployments:
            deployment_id = _integer(deployment.get("id"), 0)
            if deployment_id < 1:
                continue
            statuses = await self._json_list(
                f"{prefix}/deployments/{deployment_id}/statuses", {"per_page": 1}
            )
            if not statuses:
                continue
            status = statuses[0]
            state = _text(status.get("state"))
            if state not in {"success", "failure", "error"}:
                continue
            status_id = _integer(status.get("id"), 0)
            event_type = "developer.deployment.completed"
            if state != "success":
                event_type = "developer.deployment.failed"
            changes.append(
                _change(
                    repository=full_name,
                    event_type=event_type,
                    subject_type="deployment",
                    subject_id=resource_subject_id(full_name, f"DEPLOY-{deployment_id}"),
                    occurred_at=_timestamp(status.get("created_at"), observed_at),
                    identity=f"deployment:{deployment_id}:{state}:{status_id}",
                    payload={
                        "deployment_id": deployment_id,
                        "status_id": status_id,
                        "environment": _text(deployment.get("environment")),
                        "ref": _text(deployment.get("ref")),
                        "state": state,
                        "url": _text(status.get("environment_url")),
                    },
                    checkpoint_key=f"deployment:{repo_key}:{deployment_id}:{state}",
                )
            )
        return changes

    async def _json_list(self, path: str, params: Mapping[str, str | int]) -> list[dict[str, Any]]:
        result = await self._client.get_json(path, params=params)
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]


def _change(
    *,
    repository: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    occurred_at: datetime,
    identity: str,
    payload: dict[str, object],
    checkpoint_key: str,
) -> GithubChange:
    return GithubChange(
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        occurred_at=occurred_at,
        dedupe_key=f"github:{repository.casefold()}:{identity}",
        payload={"repository": repository, **payload},
        checkpoint_key=checkpoint_key,
    )


def _configured_repositories(settings: Settings) -> tuple[str, ...]:
    return tuple(
        name
        for name in settings.github_repositories
        if name.casefold() in LOCKED_GITHUB_REPOSITORIES
    )


def _text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _integer(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _nested_text(payload: dict[str, Any], key: str, child: str) -> str:
    nested = payload.get(key)
    return _text(nested.get(child)) if isinstance(nested, dict) else ""


def _timestamp(value: object, fallback: datetime | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return fallback
    return parsed.astimezone(UTC)
