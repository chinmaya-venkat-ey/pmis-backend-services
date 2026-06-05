"""Test config — set env before any app import triggers Settings()."""
from __future__ import annotations

import os

os.environ.setdefault("USER_MANAGEMENT_SERVICE_URL", "http://user-svc.test")
