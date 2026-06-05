"""Test config — set the env the required Settings fields need BEFORE any
app import triggers `Settings()` at module load."""
from __future__ import annotations

import os

os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test-key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test-secret")
os.environ.setdefault("USER_MANAGEMENT_SERVICE_URL", "http://user-svc.test")
