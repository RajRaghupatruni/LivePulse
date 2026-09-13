"""Verified GitHub webhook processing, kept separate from REST reconciliation."""

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Literal

from uuid6 import uuid7

from app.core.config import LOCKED_GITHUB_REPOSITORIES, Settings, get_settings
from app.providers.github.events import GithubChange, normalize_webhook
from app.providers.github.health import GithubHealthTracker, github_health
from app.providers.github.security import verify_signature
from app.providers.github.storage import persist_webhook_delivery
from app.providers.observations import Observation

LOCKED_REPOSITORIES = LOCKED_GITHUB_REPOSITORIES
WebhookResult = Literal[
    "accepted",
    "duplicate",
    "ignored_unconfigured_repository",
    "unconfigured",
    "invalid_signature",
    "missing_signature",
    "missing_delivery_id",
    "invalid_delivery_id",
]
DeliveryPersister = Callable[..., Awaitable[bool]]


class GithubWebhookProcessor:
    provider_id = "github"

    def __init__(
        self,
        *,
        persist: DeliveryPersister = persist_webhook_delivery,
        health: GithubHealthTracker = github_health,
        settings_getter: Callable[[], Settings] = get_settings,
    ) -> None:
        self._persist = persist
        self._health = health
        self._settings_getter = settings_getter

    async def verify(self, *, headers: Mapping[str, str], body: bytes) -> bool:
        normalized = {key.casefold(): value for key, value in headers.items()}
        settings = self._settings_getter()
        secret = (
            settings.github_webhook_secret.get_secret_value()
            if settings.github_webhook_secret
            else None
        )
        return verify_signature(secret, normalized.get("x-hub-signature-256"), body)

    async def normalize(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
        observed_at: datetime,
    ) -> tuple[Observation[GithubChange], ...]:
        normalized_headers = {key.casefold(): value for key, value in headers.items()}
        settings = self._settings_getter()
        if not await self.verify(headers=headers, body=body) or not self._health.webhook_configured(
            settings
        ):
            return ()
        delivery_id = normalized_headers.get("x-github-delivery", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", delivery_id):
            return ()
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            return ()
        if not isinstance(payload, dict):
            return ()
        repository = payload.get("repository")
        repo_name = repository.get("name") if isinstance(repository, dict) else None
        owner = repository.get("owner") if isinstance(repository, dict) else None
        repo_owner = owner.get("login") if isinstance(owner, dict) else None
        full_name = repository.get("full_name") if isinstance(repository, dict) else None
        configured_owner = settings.github_owner or ""
        if (
            not isinstance(repo_name, str)
            or not isinstance(repo_owner, str)
            or not isinstance(full_name, str)
            or repo_owner.casefold() != configured_owner.casefold()
            or full_name.casefold() != f"{configured_owner}/{repo_name}".casefold()
            or repo_name.casefold() not in _configured_repositories(settings)
        ):
            return ()
        changes = normalize_webhook(
            event_name=normalized_headers.get("x-github-event", ""),
            payload=payload,
            repository=full_name,
            delivery_id=delivery_id,
            observed_at=observed_at.astimezone(UTC),
        )
        correlation_id = uuid7()
        return tuple(
            Observation[GithubChange](
                provider_id=self.provider_id,
                external_entity_id=change.subject_id,
                observed_at=observed_at,
                content=change,
                provider_version=change.dedupe_key,
                checkpoint=change.checkpoint_value,
                correlation_id=correlation_id,
            )
            for change in changes
        )

    async def process(
        self,
        *,
        settings: Settings,
        headers: Mapping[str, str],
        raw_body: bytes,
        observed_at: datetime | None = None,
    ) -> tuple[WebhookResult, tuple[Observation[GithubChange], ...]]:
        normalized_headers = {key.casefold(): value for key, value in headers.items()}
        signature = normalized_headers.get("x-hub-signature-256")
        if not signature:
            return "missing_signature", ()
        secret = (
            settings.github_webhook_secret.get_secret_value()
            if settings.github_webhook_secret
            else None
        )
        if not verify_signature(secret, signature, raw_body):
            return "invalid_signature", ()
        if not self._health.webhook_configured(settings):
            return "unconfigured", ()

        delivery_id = normalized_headers.get("x-github-delivery", "").strip()
        if not delivery_id:
            return "missing_delivery_id", ()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", delivery_id):
            return "invalid_delivery_id", ()
        received_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
        self._health.note_webhook(settings, now=received_at)

        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, ValueError):
            return "accepted", ()
        if not isinstance(payload, dict):
            return "accepted", ()
        repository = payload.get("repository")
        repo_name = repository.get("name") if isinstance(repository, dict) else None
        owner = repository.get("owner") if isinstance(repository, dict) else None
        repo_owner = owner.get("login") if isinstance(owner, dict) else None
        full_name = repository.get("full_name") if isinstance(repository, dict) else None
        configured_owner = settings.github_owner or ""
        if (
            not isinstance(repo_name, str)
            or not isinstance(repo_owner, str)
            or not isinstance(full_name, str)
            or repo_owner.casefold() != configured_owner.casefold()
            or full_name.casefold() != f"{configured_owner}/{repo_name}".casefold()
            or repo_name.casefold() not in _configured_repositories(settings)
        ):
            return "ignored_unconfigured_repository", ()

        event_name = normalized_headers.get("x-github-event", "")
        changes = normalize_webhook(
            event_name=event_name,
            payload=payload,
            repository=full_name,
            delivery_id=delivery_id,
            observed_at=received_at,
        )
        correlation_id = uuid7()
        observations = tuple(
            Observation[GithubChange](
                provider_id="github",
                external_entity_id=change.subject_id,
                observed_at=received_at,
                content=change,
                provider_version=change.dedupe_key,
                checkpoint=change.checkpoint_value,
                correlation_id=correlation_id,
            )
            for change in changes
        )
        accepted = await self._persist(
            delivery_id=delivery_id,
            event_name=event_name,
            observations=observations,
            observed_at=received_at,
        )
        return ("accepted" if accepted else "duplicate"), observations


def _configured_repositories(settings: Settings) -> frozenset[str]:
    del settings
    return LOCKED_REPOSITORIES
