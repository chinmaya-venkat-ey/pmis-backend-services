"""S3 storage backend for pmis-file-store.

All configuration is sourced from environment variables via app.config.settings
(never hardcoded). Supports:
  - Real AWS S3
  - MinIO (via S3_ENDPOINT_URL)
  - AWS LocalStack (via S3_ENDPOINT_URL)

Dynamic S3 key structure:
  {S3_KEY_PREFIX}/{folder}/{entity_type}/{entity_id}/{YYYY}/{MM}/{uuid}_{filename}
  or (when entity_type/entity_id not provided):
  {S3_KEY_PREFIX}/{folder}/{YYYY}/{MM}/{uuid}_{filename}

Public surface:
  S3Client.upload_bytes(key, data, content_type, metadata) -> public_url | None
  S3Client.presign_get(key, expires_in)                    -> pre-signed URL
  S3Client.delete(key)                                     -> None
  S3Client.exists(key)                                     -> bool
  S3Client.head(key)                                       -> dict | None
  build_s3_key(prefix, folder, entity_type, entity_id, filename) -> str
  sanitize_filename(raw)                                   -> str
  get_s3_client()                                          -> S3Client (singleton)
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Optional
from uuid import uuid4

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.errors import S3DeleteError, S3PresignError, S3UploadError
from app.utilities.logger import get_logger


logger = get_logger(__name__)

# Reject control chars, path separators, and Windows-reserved chars.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_NAME_IN_KEY = 100


def sanitize_filename(raw: str) -> str:
    """Return a filesystem-safe, S3-key-safe version of ``raw``."""
    name = unicodedata.normalize("NFC", raw or "").strip()
    name = _UNSAFE_CHARS.sub("_", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    if len(name) > _MAX_NAME_IN_KEY:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            stem = stem[: _MAX_NAME_IN_KEY - len(ext) - 1]
            name = f"{stem}.{ext}"
        else:
            name = name[:_MAX_NAME_IN_KEY]
    return name or "unnamed"


def build_s3_key(
    prefix: str,
    folder: str,
    entity_type: Optional[str],
    entity_id: Optional[str],
    filename: str,
) -> str:
    """Build a unique, collision-safe S3 object key.

    Layout:
      {prefix}/{folder}/{entity_type}/{entity_id}/{YYYY}/{MM}/{uuid}_{filename}
      {prefix}/{folder}/{YYYY}/{MM}/{uuid}_{filename}   (no entity)

    All segments are sanitized to be valid S3 key components.
    """
    now = datetime.now(timezone.utc)
    parts = [prefix.strip("/"), folder.strip("/")]

    if entity_type:
        parts.append(re.sub(r"[^a-zA-Z0-9_\-]", "_", entity_type).lower())
    if entity_id:
        parts.append(re.sub(r"[^a-zA-Z0-9_\-]", "_", entity_id))

    parts.extend([f"{now.year:04d}", f"{now.month:02d}"])
    unique = uuid4().hex[:16]
    parts.append(f"{unique}_{sanitize_filename(filename)}")

    return "/".join(p for p in parts if p)


class S3Client:
    """Thin wrapper around boto3 S3 client.

    All credentials and endpoint are injected via settings — this class
    contains zero hardcoded configuration. Instantiate once at startup via
    get_s3_client().
    """

    def __init__(
        self,
        *,
        bucket_name: str,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        endpoint_url: Optional[str],
        public_url_base: Optional[str],
        presigned_url_expires: int,
    ):
        self._bucket = bucket_name
        self._public_base = (public_url_base or "").rstrip("/") or None
        self._presigned_expires = presigned_url_expires

        session = boto3.session.Session()
        kwargs: Dict[str, Any] = {
            "service_name": "s3",
            "region_name": region,
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "config": BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        }
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url

        self._client = session.client(**kwargs)
        logger.info(
            "S3Client initialised | bucket=%s | region=%s | endpoint=%s",
            bucket_name, region, endpoint_url or "AWS default",
        )

    # ----------------------------------------------------------------- upload

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Upload raw bytes to S3 and return the permanent public URL (if
        ``public_url_base`` is configured) or None (caller will presign).

        Raises S3UploadError on failure.
        """
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={k: v for k, v in (metadata or {}).items() if v},
            )
            logger.debug("S3 upload OK | bucket=%s | key=%s | bytes=%d", self._bucket, key, len(data))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            raise S3UploadError(
                f"S3 upload failed (code={code}): {exc.response['Error']['Message']}"
            ) from exc
        except Exception as exc:
            raise S3UploadError(f"S3 upload failed: {exc}") from exc

        if self._public_base:
            return f"{self._public_base}/{key}"
        return None  # caller must use presign_get

    # --------------------------------------------------------------- presign

    def presign_get(self, key: str, expires_in: Optional[int] = None) -> str:
        """Generate a time-limited pre-signed GET URL.

        Raises S3PresignError on failure.
        """
        ttl = expires_in or self._presigned_expires
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=ttl,
            )
            return url
        except ClientError as exc:
            raise S3PresignError(f"Failed to presign URL for key={key}: {exc}") from exc
        except Exception as exc:
            raise S3PresignError(f"Presign failed: {exc}") from exc

    # ----------------------------------------------------------------- delete

    def delete(self, key: str) -> None:
        """Delete a single S3 object.

        Raises S3DeleteError on failure. Idempotent — deleting a
        non-existent key is not an error.
        """
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.debug("S3 delete OK | bucket=%s | key=%s", self._bucket, key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            raise S3DeleteError(
                f"S3 delete failed (code={code}): {exc.response['Error']['Message']}"
            ) from exc
        except Exception as exc:
            raise S3DeleteError(f"S3 delete failed: {exc}") from exc

    # ------------------------------------------------------------------ exists

    def exists(self, key: str) -> bool:
        """Return True iff the object exists in S3."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    # -------------------------------------------------------------------- head

    def head(self, key: str) -> Optional[Dict[str, Any]]:
        """Return S3 object metadata dict or None if not found."""
        try:
            return self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return None
            raise

    # ------------------------------------------------------------------- probe

    def health_check(self) -> bool:
        """Probe S3 connectivity by listing one object from the bucket."""
        try:
            self._client.list_objects_v2(Bucket=self._bucket, MaxKeys=1)
            return True
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Optional[S3Client] = None
_lock = Lock()


def get_s3_client() -> S3Client:
    """Return the process-wide S3Client (lazy-initialised from settings)."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from app.config import settings
                _client = S3Client(
                    bucket_name=settings.s3_bucket_name,
                    region=settings.s3_region,
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                    endpoint_url=settings.s3_endpoint_url or None,
                    public_url_base=settings.s3_public_url_base or None,
                    presigned_url_expires=settings.s3_presigned_url_expires,
                )
    return _client


def reset_s3_client_for_tests() -> None:
    """Clear the cached client (tests only)."""
    global _client
    with _lock:
        _client = None
