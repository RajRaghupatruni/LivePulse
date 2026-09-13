"""Deterministic, operator-invoked retention for durable event history."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import delete, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import RuntimeMode, get_settings
from app.projections.projector import CONSUMER_NAME
from app.storage.database import SessionFactory, engine
from app.storage.models import (
    CanonicalEventRow,
    ConsumerProcessedEventRow,
    DemoControlRow,
    MatchStateRow,
    OutboxMessageRow,
    PulseTimelineRow,
    RetiredEventRow,
)


@dataclass(frozen=True)
class RetentionReport:
    cutoff: str
    dry_run: bool
    eligible_events: int
    eligible_timeline_rows: int
    eligible_inactive_match_projections: int
    removed_timeline_rows: int
    removed_inactive_match_projections: int
    protected_active_match_events: int
    deferred_unpublished_events: int
    deferred_unprojected_events: int
    retained_last_state_events: int
    retained_connections_and_checkpoints: bool = True


async def apply_retention(
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    retention_days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = True,
    max_events: int = 1000,
) -> RetentionReport:
    """Plan or apply one bounded pruning batch, preserving current provider state."""
    settings = get_settings()
    if settings.runtime_mode is not RuntimeMode.PERSONAL_LOCAL:
        raise RuntimeError("retention maintenance is available only in PERSONAL_LOCAL mode")
    days = settings.retention_days if retention_days is None else retention_days
    if days < 30:
        raise ValueError("retention must be at least 30 days")
    if max_events < 1:
        raise ValueError("max_events must be positive")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = current - timedelta(days=days)

    async with session_factory() as session:
        async with session.begin():
            active_match_id = await session.scalar(
                select(DemoControlRow.active_match_id).where(DemoControlRow.id == 1)
            )
            matches = list(await session.scalars(select(MatchStateRow)))
            live_match_ids = {
                item.match_id for item in matches if item.status.casefold() in {"live", "halftime"}
            }
            protected_subjects = live_match_ids | ({active_match_id} if active_match_id else set())
            last_state_event_ids = {
                item.last_event_id
                for item in matches
                if item.last_event_id is not None
                and (item.updated_at >= cutoff or item.match_id in protected_subjects)
            }

            old_filter = CanonicalEventRow.ingested_at < cutoff
            deferred_unpublished = int(
                await session.scalar(
                    select(func.count())
                    .select_from(CanonicalEventRow)
                    .outerjoin(
                        OutboxMessageRow,
                        OutboxMessageRow.event_id == CanonicalEventRow.event_id,
                    )
                    .where(
                        old_filter,
                        or_(
                            OutboxMessageRow.event_id.is_(None),
                            OutboxMessageRow.published_at.is_(None),
                        ),
                    )
                )
                or 0
            )
            deferred_unprojected = int(
                await session.scalar(
                    select(func.count())
                    .select_from(CanonicalEventRow)
                    .join(OutboxMessageRow, OutboxMessageRow.event_id == CanonicalEventRow.event_id)
                    .outerjoin(
                        ConsumerProcessedEventRow,
                        (ConsumerProcessedEventRow.event_id == CanonicalEventRow.event_id)
                        & (ConsumerProcessedEventRow.consumer_name == CONSUMER_NAME),
                    )
                    .where(
                        old_filter,
                        OutboxMessageRow.published_at.is_not(None),
                        ConsumerProcessedEventRow.event_id.is_(None),
                    )
                )
                or 0
            )
            protected_active = 0
            if protected_subjects:
                protected_active = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(CanonicalEventRow)
                        .where(
                            old_filter,
                            CanonicalEventRow.event_type.startswith("football.match."),
                            CanonicalEventRow.subject_id.in_(protected_subjects),
                        )
                    )
                    or 0
                )
            retained_last = 0
            if last_state_event_ids:
                retained_last = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(CanonicalEventRow)
                        .where(old_filter, CanonicalEventRow.event_id.in_(last_state_event_ids))
                    )
                    or 0
                )

            eligible_query = (
                select(CanonicalEventRow)
                .join(
                    OutboxMessageRow,
                    OutboxMessageRow.event_id == CanonicalEventRow.event_id,
                )
                .join(
                    ConsumerProcessedEventRow,
                    (ConsumerProcessedEventRow.event_id == CanonicalEventRow.event_id)
                    & (ConsumerProcessedEventRow.consumer_name == CONSUMER_NAME),
                )
                .where(
                    old_filter,
                    OutboxMessageRow.published_at.is_not(None),
                    not_(CanonicalEventRow.event_id.in_(last_state_event_ids))
                    if last_state_event_ids
                    else True,
                )
            )
            if protected_subjects:
                eligible_query = eligible_query.where(
                    or_(
                        not_(CanonicalEventRow.event_type.startswith("football.match.")),
                        CanonicalEventRow.subject_id.not_in(protected_subjects),
                    )
                )
            eligible = list(
                await session.scalars(
                    eligible_query.order_by(
                        CanonicalEventRow.ingested_at, CanonicalEventRow.event_id
                    ).limit(max_events)
                )
            )

            eligible_ids = {item.event_id for item in eligible}
            eligible_hashes = {
                sha256(item.dedupe_key.encode("utf-8")).hexdigest() for item in eligible
            }
            existing_hashes: set[str] = set()
            if eligible_hashes:
                existing_hashes = set(
                    await session.scalars(
                        select(RetiredEventRow.dedupe_hash).where(
                            RetiredEventRow.dedupe_hash.in_(eligible_hashes)
                        )
                    )
                )

            timeline_count = 0
            if eligible_ids:
                timeline_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(PulseTimelineRow)
                        .where(PulseTimelineRow.event_id.in_(eligible_ids))
                    )
                    or 0
                )

            stale_candidates = [
                item
                for item in matches
                if item.updated_at < cutoff
                and item.match_id not in protected_subjects
                and item.last_event_id in eligible_ids
            ]
            stale_ids = {item.match_id for item in stale_candidates}
            inactive_to_remove: set[str] = set()
            if stale_ids:
                subject_events = list(
                    await session.execute(
                        select(CanonicalEventRow.subject_id, CanonicalEventRow.event_id).where(
                            CanonicalEventRow.event_type.startswith("football.match."),
                            CanonicalEventRow.subject_id.in_(stale_ids),
                        )
                    )
                )
                all_by_subject: dict[str, set[object]] = {subject: set() for subject in stale_ids}
                for subject_id, event_id in subject_events:
                    all_by_subject[subject_id].add(event_id)
                inactive_to_remove = {
                    subject
                    for subject, event_ids in all_by_subject.items()
                    if event_ids and event_ids.issubset(eligible_ids)
                }

            if not dry_run and eligible:
                retired_at = current
                session.add_all(
                    [
                        RetiredEventRow(
                            event_id=item.event_id,
                            dedupe_hash=sha256(item.dedupe_key.encode("utf-8")).hexdigest(),
                            retired_at=retired_at,
                        )
                        for item in eligible
                        if sha256(item.dedupe_key.encode("utf-8")).hexdigest()
                        not in existing_hashes
                    ]
                )
                await session.flush()
                await session.execute(
                    delete(CanonicalEventRow).where(CanonicalEventRow.event_id.in_(eligible_ids))
                )
            if not dry_run and inactive_to_remove:
                await session.execute(
                    delete(MatchStateRow).where(MatchStateRow.match_id.in_(inactive_to_remove))
                )

    return RetentionReport(
        cutoff=cutoff.isoformat(),
        dry_run=dry_run,
        eligible_events=len(eligible),
        eligible_timeline_rows=timeline_count,
        eligible_inactive_match_projections=len(inactive_to_remove),
        removed_timeline_rows=timeline_count if not dry_run else 0,
        removed_inactive_match_projections=len(inactive_to_remove) if not dry_run else 0,
        protected_active_match_events=protected_active,
        deferred_unpublished_events=deferred_unpublished,
        deferred_unprojected_events=deferred_unprojected,
        retained_last_state_events=retained_last,
    )


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Preview or apply LivePulse event retention")
    parser.add_argument("--days", type=int, help="Override RETENTION_DAYS for this run")
    parser.add_argument("--apply", action="store_true", help="Apply this pruning batch")
    parser.add_argument("--max-events", type=int, default=1000)
    args = parser.parse_args()
    report = await apply_retention(
        retention_days=args.days, dry_run=not args.apply, max_events=args.max_events
    )
    import json

    print(json.dumps(asdict(report), indent=2))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
