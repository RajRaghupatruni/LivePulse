"""Signed GitHub webhook and secret-free provider health endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.providers.github.health import github_health
from app.providers.github.webhook import GithubWebhookProcessor

router = APIRouter()
processor = GithubWebhookProcessor()


@router.post("/api/v1/webhooks/github", status_code=202)
async def github_webhook(request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    status, changes = await processor.process(
        settings=get_settings(),
        headers=request.headers,
        raw_body=raw_body,
        observed_at=datetime.now(UTC),
    )
    if status in {"missing_signature", "invalid_signature"}:
        raise HTTPException(status_code=401, detail="GitHub webhook signature is invalid")
    if status == "unconfigured":
        raise HTTPException(status_code=503, detail="GitHub webhook is not configured")
    if status in {"missing_delivery_id", "invalid_delivery_id"}:
        raise HTTPException(status_code=400, detail="GitHub delivery identity is required")
    return {"status": status, "normalized_events": len(changes)}


@router.get("/api/v1/providers/github/health")
async def github_provider_health() -> dict[str, object]:
    return github_health.snapshot(get_settings())
