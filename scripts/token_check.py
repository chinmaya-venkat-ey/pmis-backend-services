"""Quick JWT diagnostic for project-service.

Usage:
    python scripts/token_check.py <token>

Decodes the token without verifying (so you can see claims even if
the signature is wrong), then attempts to verify against this
service's SECRET_KEY. Reports each failure mode separately so you
can tell whether the problem is:

  - signature mismatch (different SECRET_KEY between monolith and here)
  - token expired
  - user_id not a UUID (pre-doc-26 token shape)
  - jti revoked (logged-out token)

Run from the project-service venv so settings load correctly.
"""
import sys
from datetime import datetime, timezone
from uuid import UUID

from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings


def main(token: str) -> int:
    print(f"Local SECRET_KEY: {settings.SECRET_KEY[:8]}... (length {len(settings.SECRET_KEY)})")
    print(f"Algorithm:       {settings.ALGORITHM}")
    print()

    # 1. Decode WITHOUT verifying signature.
    try:
        payload_unverified = jwt.get_unverified_claims(token)
    except JWTError as e:
        print(f"FAIL: token is not a valid JWT: {e}")
        return 1

    print("Decoded claims (unverified):")
    for k, v in payload_unverified.items():
        if k == "exp":
            try:
                dt = datetime.fromtimestamp(int(v), tz=timezone.utc)
                print(f"  exp        = {v}  ({dt.isoformat()})")
            except Exception:
                print(f"  exp        = {v}")
        else:
            print(f"  {k:10s} = {v}")
    print()

    # 2. user_id shape (doc-27 hotfix).
    user_id = payload_unverified.get("user_id")
    try:
        UUID(str(user_id))
        print(f"OK:   user_id is UUID-shaped ({user_id})")
    except (TypeError, ValueError):
        print(f"FAIL: user_id '{user_id}' is NOT a UUID. Token is pre-doc-26 shape — middleware rejects.")
        return 2

    # 3. exp.
    exp = payload_unverified.get("exp")
    if exp:
        now = datetime.now(timezone.utc).timestamp()
        if int(exp) < now:
            print(f"FAIL: token is EXPIRED ({int(now) - int(exp)}s ago).")
            return 3
        else:
            print(f"OK:   token is not expired (expires in {int(exp) - int(now)}s).")

    # 4. Signature verify against this service's SECRET_KEY.
    try:
        verified = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        print(f"OK:   signature verifies with local SECRET_KEY.")
        print(f"      sub={verified.get('sub')} role={verified.get('role')} is_admin={verified.get('is_admin')}")
        print()
        print("Token should be accepted by project-service.")
        return 0
    except ExpiredSignatureError:
        print("FAIL: signature OK but expired.")
        return 3
    except JWTError as e:
        print(f"FAIL: signature does NOT verify with local SECRET_KEY ({e}).")
        print()
        print(">>> ROOT CAUSE: project-service .env SECRET_KEY does not match the")
        print(">>> instance that minted this token (the monolith).")
        print(">>> Fix: copy SECRET_KEY from the monolith's .env into")
        print(">>> pmis-project-service\\.env, then restart uvicorn.")
        return 4


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/token_check.py <token>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
