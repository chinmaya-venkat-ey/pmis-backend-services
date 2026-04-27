"""Shared validators and normalizers — ported from the monolith."""
import re


def is_valid_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def is_valid_login(login: str) -> bool:
    """3-50 chars, alphanumeric + underscore + hyphen."""
    pattern = r"^[a-zA-Z0-9_-]{3,50}$"
    return re.match(pattern, login) is not None


def is_valid_password(password: str) -> bool:
    """Minimum 8 characters — matches monolith behaviour."""
    return len(password) >= 8


def normalize_email(email: str) -> str:
    return email.lower().strip()


def normalize_login(login: str) -> str:
    return login.lower().strip()


def normalize_string(value: str) -> str:
    return value.strip() if value else ""
