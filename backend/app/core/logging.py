import json
import logging
import sys
from datetime import UTC, datetime

from app.core.config import get_settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        item: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": get_settings().service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "request_id",
            "correlation_id",
            "event_id",
            "event_type",
            "subject_id",
            "consumer",
            "error_code",
            "http_method",
            "http_path",
            "http_status",
        ):
            value = getattr(record, key, None)
            if value is not None:
                item[key] = value
        if record.exc_info:
            item["exception"] = self.formatException(record.exc_info)
        return json.dumps(item, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # httpx request logs include full URLs. Keep them quiet so OAuth codes/state and
    # other query material cannot leak through a third-party client logger.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
