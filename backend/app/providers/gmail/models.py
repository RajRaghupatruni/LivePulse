"""Safe Gmail metadata shapes used inside the provider boundary."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GmailMessageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    thread_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    sender: str = Field(default="", max_length=320)
    subject: str = Field(default="(no subject)", max_length=300)
    received_at: datetime
    snippet: str = Field(default="", max_length=240)
    is_unread: bool = False
    is_important: bool = False

    @field_validator("received_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        return value.astimezone(UTC)


class GmailMessageDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: GmailMessageMetadata
    change: Literal["initial", "message_added", "labels_changed", "message_removed"]
    history_id: str | None = Field(default=None, max_length=32, pattern=r"^[0-9]+$")


class GmailSyncBatch(BaseModel):
    """A single poll result; checkpoint commits with its canonical events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    history_id: str = Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")
    messages: tuple[GmailMessageDelta, ...] = Field(max_length=5_000)
    resynced: bool = False


@dataclass(frozen=True, slots=True, repr=False)
class GmailMessageBody:
    """Ephemeral body returned only for explicit on-demand retrieval."""

    message_id: str
    thread_id: str
    text: str

    def __repr__(self) -> str:
        return (
            f"GmailMessageBody(message_id={self.message_id!r}, "
            f"thread_id={self.thread_id!r}, text=[REDACTED])"
        )


@dataclass(frozen=True, slots=True)
class GmailThreadMetadata:
    thread_id: str
    messages: tuple[GmailMessageMetadata, ...]


def safe_event_metadata(message: GmailMessageMetadata) -> dict[str, object]:
    """Return the deliberately small metadata subset allowed in canonical events."""

    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "sender": message.sender,
        "subject": message.subject,
        "received_at": message.received_at.isoformat(),
        "snippet": message.snippet,
        "unread": message.is_unread,
        "important": message.is_important,
    }
