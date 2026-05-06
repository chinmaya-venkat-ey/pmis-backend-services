"""
Shared utility functions.
"""
import re
from typing import Optional


def is_valid_email(email: str) -> bool:
    """
    Validate email format.

    Args:
        email: Email address to validate

    Returns:
        True if valid email format, False otherwise
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def is_valid_login(login: str) -> bool:
    """
    Validate login format.

    Args:
        login: Login to validate

    Returns:
        True if valid login format, False otherwise
    """
    # Login must be 3-50 characters, alphanumeric with underscores and hyphens
    pattern = r'^[a-zA-Z0-9_-]{3,50}$'
    return re.match(pattern, login) is not None


def is_valid_password(password: str) -> bool:
    """
    Validate password strength.

    Args:
        password: Password to validate

    Returns:
        True if password meets requirements, False otherwise
    """
    # Minimum 8 characters
    if len(password) < 8:
        return False

    return True


def normalize_email(email: str) -> str:
    """
    Normalize email address.

    Args:
        email: Email to normalize

    Returns:
        Normalized email (lowercase)
    """
    return email.lower().strip()


def normalize_login(login: str) -> str:
    """
    Normalize login.

    Args:
        login: Login to normalize

    Returns:
        Normalized login (lowercase)
    """
    return login.lower().strip()


def normalize_string(value: str) -> str:
    """
    Normalize a general string.

    Args:
        value: String to normalize

    Returns:
        Normalized string (stripped whitespace)
    """
    return value.strip() if value else ""
