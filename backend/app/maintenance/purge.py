"""Explicit, confirmation-gated deletion of local personal LivePulse data."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path

from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import UnknownTopicOrPartitionError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import RuntimeMode, get_settings
from app.storage.database import SessionFactory, engine
from app.storage.models import (
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    DemoControlRow,
    MatchStateRow,
    OutboxMessageRow,
    ProviderCheckpointRow,
    ProviderConnectionRow,
    PulseTimelineRow,
    RetiredEventRow,
)

CONFIRMATION_TEXT = "PURGE PERSONAL LIVEPULSE DATA"
LOCAL_PROVIDER_CONFIG_KEYS = frozenset(
    {
        "API_FOOTBALL_KEY",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REDIRECT_URI",
        "GITHUB_OWNER",
        "GITHUB_TOKEN",
        "GITHUB_WEBHOOK_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "WEATHER_LATITUDE",
        "WEATHER_LONGITUDE",
        "WEATHER_TIMEZONE",
        "CREDENTIAL_ENCRYPTION_KEY",
    }
)


@dataclass(frozen=True)
class PurgeReport:
    dry_run: bool
    canonical_events: int
    outbox_rows: int
    timeline_rows: int
    processed_event_rows: int
    retired_event_tombstones: int
    match_state_rows: int
    provider_checkpoints: int
    provider_connections: int
    local_provider_configuration_cleared: bool
    broker_topic: str
    broker_history_deleted: bool


async def purge_personal_data(
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    include_provider_connections: bool = False,
    dry_run: bool = True,
    broker_topic: str | None = None,
    delete_broker_history: bool = True,
    clear_local_provider_configuration: bool = False,
) -> PurgeReport:
    """Preview or remove local event history, projections, checkpoints, and optionally links."""
    settings = get_settings()
    if settings.runtime_mode is not RuntimeMode.PERSONAL_LOCAL:
        raise RuntimeError("personal-data purge is unavailable in PUBLIC_DEMO mode")
    topic = broker_topic or settings.kafka_topic
    local_provider_configuration_cleared = False

    async with session_factory() as session:
        counts = {
            "canonical_events": int(
                await session.scalar(select(func.count()).select_from(CanonicalEventRow)) or 0
            ),
            "outbox_rows": int(
                await session.scalar(select(func.count()).select_from(OutboxMessageRow)) or 0
            ),
            "timeline_rows": int(
                await session.scalar(select(func.count()).select_from(PulseTimelineRow)) or 0
            ),
            "processed_event_rows": int(
                await session.scalar(select(func.count()).select_from(ConsumerProcessedEventRow))
                or 0
            ),
            "retired_event_tombstones": int(
                await session.scalar(select(func.count()).select_from(RetiredEventRow)) or 0
            ),
            "match_state_rows": int(
                await session.scalar(select(func.count()).select_from(MatchStateRow)) or 0
            ),
            "provider_checkpoints": int(
                await session.scalar(select(func.count()).select_from(ProviderCheckpointRow)) or 0
            ),
            "provider_connections": (
                int(
                    await session.scalar(select(func.count()).select_from(ProviderConnectionRow))
                    or 0
                )
                if include_provider_connections
                else 0
            ),
        }
        await session.commit()
        if not dry_run:
            if delete_broker_history:
                await _delete_topic(topic, settings.kafka_bootstrap_servers)
            async with session.begin():
                await session.execute(delete(CanonicalEventRow))
                await session.execute(delete(MatchStateRow))
                await session.execute(delete(ProviderCheckpointRow))
                await session.execute(delete(RetiredEventRow))
                await session.execute(
                    update(DemoControlRow)
                    .where(DemoControlRow.id == 1)
                    .values(active_match_id=None)
                )
                if include_provider_connections:
                    await session.execute(delete(ProviderConnectionRow))
            if clear_local_provider_configuration:
                local_provider_configuration_cleared = clear_local_provider_config_file()

    return PurgeReport(
        dry_run=dry_run,
        **counts,
        local_provider_configuration_cleared=local_provider_configuration_cleared,
        broker_topic=topic,
        broker_history_deleted=not dry_run and delete_broker_history,
    )


def clear_local_provider_config_file(path: Path | None = None) -> bool:
    """Blank provider secrets/coordinates in the ignored root .env, without printing values."""
    env_path = path or Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return False
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    cleaned: list[str] = []
    for line in lines:
        content = line.rstrip("\r\n")
        newline = line[len(content) :]
        if "=" in content and not content.lstrip().startswith("#"):
            name = content.split("=", 1)[0].strip()
            if name in LOCAL_PROVIDER_CONFIG_KEYS:
                cleaned.append(f"{name}={newline}")
                changed = True
                continue
        cleaned.append(line)
    if changed:
        env_path.write_text("".join(cleaned), encoding="utf-8")
    return changed


async def _delete_topic(topic: str, bootstrap_servers: str) -> None:
    """Remove the mixed-domain topic so old personal payloads cannot survive in Redpanda."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers, request_timeout_ms=15000)
    try:
        await admin.start()
        try:
            await admin.delete_topics([topic], timeout_ms=15000)
        except UnknownTopicOrPartitionError:
            pass
    finally:
        try:
            await admin.close()
        except Exception:
            pass


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Preview or purge personal LivePulse data")
    parser.add_argument("--confirm", default="", help=f"Type exactly: {CONFIRMATION_TEXT}")
    parser.add_argument(
        "--include-provider-connections",
        action="store_true",
        help="Also delete encrypted OAuth/provider connection records",
    )
    parser.add_argument(
        "--clear-local-provider-config",
        action="store_true",
        help="Also blank provider keys and weather coordinates in the ignored root .env",
    )
    args = parser.parse_args()
    apply = args.confirm == CONFIRMATION_TEXT
    report = await purge_personal_data(
        include_provider_connections=args.include_provider_connections,
        dry_run=not apply,
        clear_local_provider_configuration=args.clear_local_provider_config,
    )
    import json

    print(json.dumps(asdict(report), indent=2))
    if not apply:
        print(f'No data deleted. Re-run with --confirm "{CONFIRMATION_TEXT}" to apply.')
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
