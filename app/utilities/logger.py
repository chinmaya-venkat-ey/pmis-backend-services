"""Logging configuration for pmis-masters-management.

WARNING: Duplicated from services/pmis-notification-management/app/utilities/logger.py.
Canonical version will move to services/pmis-user-management/app/utilities/logger.py
once user-svc is ported. Keep in sync by hand.
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
            "service": getattr(settings, "service_name", "pmis-masters-management"),
        }
        for key in ("request_id", "user_id", "endpoint"):
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Initialize root logger. Idempotent."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()

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
    return logging.getLogger(name)
