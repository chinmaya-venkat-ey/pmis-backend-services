"""Logging configuration for pmis-notification-management.

Single source for log setup. Honors `LOG_FORMAT=text|json` and `LOG_LEVEL`
from app.config.settings. JSON output in prod is structured for log
aggregators; text in dev for human readability.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\utilities\\logger.py:1-24
with JSON-output enhancement.
"""
from __future__ import annotations

import json
import logging
import sys

from app.config import settings


class JsonFormatter(logging.Formatter):
    """One JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(settings, "service_name", "pmis-notification-management"),
        }
        # Attach extras attached via logger.info("msg", extra={"foo": "bar"})
        for key in ("request_id", "user_id", "endpoint"):
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Initialize root logger. Idempotent — safe to call multiple times."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()

    # Reset existing handlers (avoid duplicates on reload)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Get a named child logger. Use module's __name__ by convention."""
    return logging.getLogger(name)
