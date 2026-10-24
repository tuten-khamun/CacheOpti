"""
CacheCraft / CacheOpti - Cache Entry Models and Sentinels.

Defines the CACHE_MISS sentinel to avoid conflating missing keys with cached falsy values,
plus snapshot models for UI telemetry and event auditing.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Optional
import time


class _CacheMissSentinel:
    """Sentinel class representing a cache miss."""

    _instance: Optional[_CacheMissSentinel] = None

    def __new__(cls) -> _CacheMissSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<CACHE_MISS>"

    def __bool__(self) -> bool:
        # Falsy so `if not result` might be caught, but explicit `is CACHE_MISS` is preferred
        return False


CACHE_MISS: Any = _CacheMissSentinel()


def is_cache_miss(val: Any) -> bool:
    """Explicitly check if a value returned from cache lookup is a cache miss."""
    return val is CACHE_MISS


@dataclass(frozen=True)
class CacheEntrySnapshot:
    """Serializable snapshot of a single cache entry for UI inspection."""

    key: str
    value_repr: str
    display_title: str
    display_subtitle: str
    created_at: float
    last_accessed_at: float
    ttl_seconds: Optional[float]
    remaining_ttl: Optional[float]
    access_count: int
    is_expired: bool
    position: int
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _format_clean_display(key: str, val: Any) -> tuple[str, str]:
    """Extract a human-friendly title and subtitle from cached data."""
    # Case 1: Country record
    if isinstance(val, dict) and "common_name" in val:
        flag = val.get("flag_emoji", "🌐")
        name = val.get("common_name", "Unknown Country")
        capital = val.get("capital", "N/A")
        pop = val.get("population", 0)
        
        pop_str = f"{pop:,.0f}" if isinstance(pop, (int, float)) else str(pop)
        if isinstance(pop, (int, float)) and pop >= 1_000_000:
            pop_str = f"{pop / 1_000_000:.1f}M"
        elif isinstance(pop, (int, float)) and pop >= 1_000:
            pop_str = f"{pop / 1_000:.0f}K"

        title = f"{flag} {name}"
        subtitle = f"Capital: {capital} • Pop: {pop_str}"
        return title, subtitle

    # Case 2: General dict
    if isinstance(val, dict):
        title = val.get("title") or val.get("name") or key
        subtitle = f"{len(val)} fields cached"
        return str(title), subtitle

    # Case 3: Key parsing for clean label
    title = str(key)
    if ":" in key:
        parts = key.split(":")
        # e.g., country:name:france:hash -> France
        if len(parts) >= 3 and parts[0] == "country":
            title = parts[2].capitalize()
        elif len(parts) >= 2:
            title = f"{parts[0]}: {parts[1]}"

    val_str = str(val)
    if len(val_str) > 40:
        val_str = val_str[:37] + "..."
    subtitle = f"Value: {val_str}"
    return title, subtitle


def create_snapshot(
    node: Any,
    position: int,
    current_time: Optional[float] = None,
    max_val_len: int = 120,
) -> CacheEntrySnapshot:
    """Construct an inspection snapshot from a live CacheNode."""
    now = current_time if current_time is not None else time.monotonic()
    expired = node.is_expired(now)
    rem = node.remaining_ttl(now)

    title, subtitle = _format_clean_display(node.key, node.value)

    # Clean representation of value without leaking secrets or crashing on large objects
    raw_repr = repr(node.value)
    if len(raw_repr) > max_val_len:
        val_repr = raw_repr[:max_val_len] + "... (truncated)"
    else:
        val_repr = raw_repr

    return CacheEntrySnapshot(
        key=str(node.key),
        value_repr=val_repr,
        display_title=title,
        display_subtitle=subtitle,
        created_at=node.created_at,
        last_accessed_at=node.last_accessed_at,
        ttl_seconds=node.ttl_seconds,
        remaining_ttl=round(rem, 3) if rem is not None else None,
        access_count=node.access_count,
        is_expired=expired,
        position=position,
        status="expired" if expired else "active",
    )
