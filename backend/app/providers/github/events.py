"""GitHub-specific payload normalization before canonical event construction."""

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GithubEventType = Literal[
    "developer.push.received",
    "developer.pull_request.opened",
    "developer.pull_request.merged",
    "developer.workflow.started",
    "developer.workflow.completed",
    "developer.workflow.failed",
    "developer.deployment.completed",
    "developer.deployment.failed",
]


class GithubChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: GithubEventType
    subject_type: str
    subject_id: str = Field(max_length=100)
    occurred_at: datetime
    dedupe_key: str = Field(max_length=255)
    payload: dict[str, Any]
    checkpoint_key: str | None = Field(default=None, max_length=150)
    checkpoint_value: str = "1"

    @field_validator("occurred_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GitHub event timestamps must be timezone-aware")
        return value.astimezone(UTC)


def normalize_webhook(
    *,
    event_name: str,
    payload: dict[str, Any],
    repository: str,
    delivery_id: str,
    observed_at: datetime,
) -> tuple[GithubChange, ...]:
    """Map only useful GitHub webhook transitions; irrelevant actions return no changes."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    repo = repository.casefold()
    repo_checkpoint = repository_checkpoint_key(repository)
    changes: list[GithubChange] = []

    def add(
        event_type: GithubEventType,
        subject_type: str,
        subject_id: str,
        occurred_at: datetime,
        identity: str,
        normalized: dict[str, Any],
        checkpoint_key: str | None = None,
    ) -> None:
        changes.append(
            GithubChange(
                event_type=event_type,
                subject_type=subject_type,
                subject_id=subject_id,
                occurred_at=occurred_at,
                dedupe_key=f"github:{repo}:{identity}",
                payload={"repository": repository, **normalized, "delivery_id": delivery_id},
                checkpoint_key=checkpoint_key,
            )
        )

    action = payload.get("action")
    if event_name == "push":
        after = _text(payload.get("after"), "unknown")
        ref = _text(payload.get("ref"), "unknown")
        head = payload.get("head_commit")
        occurred_at = _timestamp(head.get("timestamp") if isinstance(head, dict) else None)
        commits = payload.get("commits")
        add(
            "developer.push.received",
            "repository",
            repository_subject_id(repository),
            occurred_at or observed_at,
            f"push:{after}" if after != "unknown" else f"delivery:{delivery_id}:push",
            {
                "ref": ref,
                "before": _text(payload.get("before"), ""),
                "after": after,
                "commit_count": _integer(
                    payload.get("size"), len(commits) if isinstance(commits, list) else 0
                ),
                "sender": _nested_text(payload, "sender", "login"),
            },
        )
    elif event_name == "pull_request" and isinstance(payload.get("pull_request"), dict):
        pull = payload["pull_request"]
        number = _integer(payload.get("number"), 0)
        if number < 1:
            return ()
        subject_id = resource_subject_id(repository, f"PR-{number}")
        base = {
            "number": number,
            "title": _text(pull.get("title"), ""),
            "url": _text(pull.get("html_url"), ""),
            "author": _nested_text(pull, "user", "login"),
            "base_ref": _nested_text(pull, "base", "ref"),
            "head_ref": _nested_text(pull, "head", "ref"),
        }
        if action == "opened":
            add(
                "developer.pull_request.opened",
                "pull_request",
                subject_id,
                _timestamp(pull.get("created_at")) or observed_at,
                f"pull-request:{number}:opened",
                base,
                f"pull:{repo_checkpoint}:{number}:opened",
            )
        elif action == "closed" and pull.get("merged") is True:
            add(
                "developer.pull_request.merged",
                "pull_request",
                subject_id,
                _timestamp(pull.get("merged_at")) or observed_at,
                f"pull-request:{number}:merged",
                base,
                f"pull:{repo_checkpoint}:{number}:merged",
            )
    elif event_name == "workflow_run" and isinstance(payload.get("workflow_run"), dict):
        run = payload["workflow_run"]
        run_id = _integer(run.get("id"), 0)
        if run_id < 1:
            return ()
        subject_id = resource_subject_id(repository, f"RUN-{run_id}")
        base = {
            "run_id": run_id,
            "run_number": _integer(run.get("run_number"), 0),
            "workflow": _text(run.get("name"), "Workflow"),
            "branch": _text(run.get("head_branch"), ""),
            "url": _text(run.get("html_url"), ""),
            "actor": _nested_text(run, "actor", "login"),
            "attempt": _integer(run.get("run_attempt"), 1),
        }
        if action == "in_progress":
            add(
                "developer.workflow.started",
                "workflow_run",
                subject_id,
                _timestamp(run.get("run_started_at"))
                or _timestamp(run.get("created_at"))
                or observed_at,
                f"workflow:{run_id}:attempt:{base['attempt']}:started",
                base,
                f"workflow:{repo_checkpoint}:{run_id}:{base['attempt']}:started",
            )
        elif action == "completed":
            attempt = base["attempt"]
            conclusion = _text(run.get("conclusion"), "unknown")
            if conclusion == "success":
                outcome = "developer.workflow.completed"
            elif conclusion in {
                "failure",
                "cancelled",
                "timed_out",
                "action_required",
                "startup_failure",
            }:
                outcome = "developer.workflow.failed"
            else:
                return ()
            add(
                "developer.workflow.started",
                "workflow_run",
                subject_id,
                _timestamp(run.get("run_started_at"))
                or _timestamp(run.get("created_at"))
                or observed_at,
                f"workflow:{run_id}:attempt:{attempt}:started",
                base,
                f"workflow:{repo_checkpoint}:{run_id}:{attempt}:started",
            )
            add(
                outcome,
                "workflow_run",
                subject_id,
                _timestamp(run.get("updated_at"))
                or _timestamp(run.get("completed_at"))
                or observed_at,
                f"workflow:{run_id}:attempt:{attempt}:{conclusion}",
                {**base, "conclusion": conclusion},
                f"workflow:{repo_checkpoint}:{run_id}:{attempt}:completed",
            )
    elif event_name == "deployment_status" and isinstance(payload.get("deployment"), dict):
        deployment = payload["deployment"]
        status = payload.get("deployment_status")
        if not isinstance(status, dict):
            return ()
        state = _text(status.get("state"), "")
        if state not in {"success", "failure", "error"}:
            return ()
        deployment_id = _integer(deployment.get("id"), 0)
        status_id = _integer(status.get("id"), 0)
        if deployment_id < 1:
            return ()
        event_type = "developer.deployment.completed"
        if state != "success":
            event_type = "developer.deployment.failed"
        add(
            event_type,
            "deployment",
            resource_subject_id(repository, f"DEPLOY-{deployment_id}"),
            _timestamp(status.get("created_at")) or observed_at,
            f"deployment:{deployment_id}:{state}:{status_id}",
            {
                "deployment_id": deployment_id,
                "status_id": status_id,
                "environment": _text(deployment.get("environment"), ""),
                "ref": _text(deployment.get("ref"), ""),
                "state": state,
                "url": _text(status.get("environment_url"), ""),
            },
            f"deployment:{repo_checkpoint}:{deployment_id}:{state}",
        )
    return tuple(changes)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _text(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _integer(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _nested_text(payload: dict[str, Any], key: str, child: str) -> str:
    nested = payload.get(key)
    return _text(nested.get(child), "") if isinstance(nested, dict) else ""


def repository_checkpoint_key(repository: str) -> str:
    return hashlib.sha256(repository.casefold().encode("utf-8")).hexdigest()[:16]


def repository_subject_id(repository: str) -> str:
    if len(repository) <= 70:
        return repository
    suffix = hashlib.sha256(repository.casefold().encode("utf-8")).hexdigest()[:12]
    return f"{repository[:57]}~{suffix}"


def resource_subject_id(repository: str, resource: str) -> str:
    return f"{repository_subject_id(repository)}#{resource}"
