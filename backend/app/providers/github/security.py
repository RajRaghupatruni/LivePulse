"""GitHub webhook HMAC-SHA256 verification helpers."""

import hashlib
import hmac
import re


def verify_signature(secret: str | None, signature: str | None, raw_body: bytes) -> bool:
    """Verify the signature over the exact request bytes using constant-time comparison."""
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    supplied = signature.removeprefix("sha256=")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", supplied):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
