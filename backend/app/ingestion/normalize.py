from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.events import CanonicalEvent, FootballEventType, FootballPayload


class ProviderObservation:
    """Adapter-only shape. It is deliberately not returned from application APIs."""

    def __init__(
        self,
        event_type: FootballEventType,
        match_id: str,
        run_id: UUID,
        sequence: int,
        occurred_at: datetime,
        observed_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        self.event_type = event_type
        self.match_id = match_id
        self.run_id = run_id
        self.sequence = sequence
        self.occurred_at = occurred_at
        self.observed_at = observed_at
        self.payload = payload


def normalize_football_observation(observation: ProviderObservation) -> CanonicalEvent:
    payload = FootballPayload.model_validate(observation.payload).model_dump(
        mode="json", exclude_none=True
    )
    return CanonicalEvent(
        source="demo-football",
        event_type=observation.event_type.value,
        subject_type="match",
        subject_id=observation.match_id,
        occurred_at=observation.occurred_at,
        observed_at=observation.observed_at,
        version=observation.sequence,
        dedupe_key=f"demo-football:{observation.run_id}:{observation.sequence}",
        correlation_id=observation.run_id,
        payload=payload,
    )
