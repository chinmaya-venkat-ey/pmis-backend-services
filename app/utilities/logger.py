import logging
import sys

from app.config import settings


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
