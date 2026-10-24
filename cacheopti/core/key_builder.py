"""
CacheCraft / CacheOpti - Deterministic and Secure Key Generation.

Generates reproducible cache keys across various Python data types,
ensuring calls with different inputs never collide, while masking sensitive
parameters (API keys, authorization headers, passwords).
"""

from __future__ import annotations
import hashlib
import json
from typing import Any

SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "auth",
    "authorization",
    "secret",
    "password",
    "secret_key",
}


def _sanitize_value(key: str, val: Any) -> Any:
    """Mask sensitive fields so credentials never enter cache keys or logs."""
    if any(s in key.lower() for s in SENSITIVE_FIELD_NAMES):
        return "[REDACTED_SECRET]"
    return val


def normalize_argument(arg: Any) -> Any:
    """Recursively convert arguments into deterministic, serializable structures."""
    if isinstance(arg, (int, float, bool, str)) or arg is None:
        # Include type indicator to prevent int(1) colliding with str("1")
        return [type(arg).__name__, arg]
    elif isinstance(arg, (list, tuple, set)):
        return [type(arg).__name__, [normalize_argument(x) for x in arg]]
    elif isinstance(arg, dict):
        # Sort dictionary keys deterministically and sanitize sensitive keys
        sorted_items = [
            (k, normalize_argument(_sanitize_value(str(k), v)))
            for k, v in sorted(arg.items(), key=lambda item: str(item[0]))
        ]
        return ["dict", sorted_items]
    elif hasattr(arg, "__dict__"):
        return ["object", normalize_argument(arg.__dict__)]
    else:
        return [type(arg).__name__, str(arg)]


def build_cache_key(
    prefix: str,
    *args: Any,
    **kwargs: Any,
) -> str:
    """
    Build a deterministic, collision-resistant, and sanitized cache key.
    
    Structure:
        <prefix>::<short_hash_or_preview>
    """
    normalized_payload = {
        "prefix": prefix,
        "args": [normalize_argument(a) for a in args],
        "kwargs": {
            k: normalize_argument(_sanitize_value(k, v))
            for k, v in sorted(kwargs.items())
        },
    }

    serialized = json.dumps(
        normalized_payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )

    # Compute SHA-256 for collision resistance
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    # Create a human-friendly prefix preview when possible
    preview_parts: list[str] = []
    for a in args[:2]:
        s = str(a).strip()
        if s and len(s) <= 20 and s.isalnum():
            preview_parts.append(s)
    for k in sorted(kwargs.keys())[:2]:
        v = kwargs[k]
        if k.lower() not in SENSITIVE_FIELD_NAMES and isinstance(v, (str, int)):
            s = str(v).strip()
            if s and len(s) <= 15 and s.isalnum():
                preview_parts.append(f"{k}={s}")

    if preview_parts:
        preview_str = "_".join(preview_parts)
        return f"{prefix}:{preview_str}:{digest}"
    return f"{prefix}:{digest}"
