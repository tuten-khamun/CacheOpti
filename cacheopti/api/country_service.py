"""
CacheCraft / CacheOpti - Country Data Service with Caching and Normalization.

Wraps DynamicApiClient with CacheEngine to demonstrate real API caching,
latency waterfall comparison, and request avoidance metrics.
"""

from __future__ import annotations
import time
from typing import Any, Optional
from cacheopti.core.engine import CacheEngine
from cacheopti.core.entry import is_cache_miss
from cacheopti.core.key_builder import build_cache_key
from cacheopti.api.client import DynamicApiClient, ApiResponse


def _format_country_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract standard fields from REST Countries payload."""
    name_obj = raw.get("name", {})
    common_name = name_obj.get("common", "Unknown")
    official_name = name_obj.get("official", common_name)
    capitals = raw.get("capital", [])
    capital_str = ", ".join(capitals) if isinstance(capitals, list) else str(capitals or "N/A")

    currencies = raw.get("currencies", {})
    curr_list = [f"{k} ({v.get('name', '')})" for k, v in currencies.items()] if isinstance(currencies, dict) else []

    languages = raw.get("languages", {})
    lang_list = list(languages.values()) if isinstance(languages, dict) else []

    flags = raw.get("flags", {})
    flag_png = flags.get("png", "")
    flag_emoji = raw.get("flag", "🌐")

    return {
        "common_name": common_name,
        "official_name": official_name,
        "cca2": raw.get("cca2", ""),
        "cca3": raw.get("cca3", ""),
        "capital": capital_str,
        "region": raw.get("region", "N/A"),
        "subregion": raw.get("subregion", "N/A"),
        "population": raw.get("population", 0),
        "currencies": curr_list,
        "languages": lang_list,
        "flag_emoji": flag_emoji,
        "flag_url": flag_png,
    }


class CountryService:
    """Service providing country information with cached acceleration."""

    def __init__(
        self,
        cache_engine: Optional[CacheEngine] = None,
        api_client: Optional[DynamicApiClient] = None,
    ) -> None:
        self.cache = cache_engine if cache_engine is not None else CacheEngine(capacity=10, default_ttl_seconds=60.0)
        self.client = api_client if api_client is not None else DynamicApiClient()

        self.service_lookups: int = 0
        self.service_hits: int = 0
        self.service_misses: int = 0

    def get_country_by_name(
        self,
        country_name: str,
        use_cache: bool = True,
        ttl_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        """Lookup a country by name with optional caching."""
        self.service_lookups += 1
        clean_name = country_name.strip().lower()
        cache_key = build_cache_key("country:name", clean_name)

        lookup_start_ns = time.perf_counter_ns()
        if use_cache:
            cached_data = self.cache.get(cache_key)
            lookup_overhead_us = (time.perf_counter_ns() - lookup_start_ns) / 1000.0

            if not is_cache_miss(cached_data):
                self.service_hits += 1
                total_latency_ms = lookup_overhead_us / 1000.0
                return {
                    "source": "CACHE_HIT",
                    "from_cache": True,
                    "cache_key": cache_key,
                    "latency_ms": round(total_latency_ms, 3),
                    "lookup_overhead_us": round(lookup_overhead_us, 2),
                    "network_latency_ms": 0.0,
                    "data": cached_data,
                    "is_error": False,
                    "error_message": None,
                }
        else:
            lookup_overhead_us = 0.0

        # Cache Miss or uncached request: call external API
        self.service_misses += 1
        api_resp: ApiResponse = self.client.get(f"name/{clean_name}")

        if api_resp.is_error or not api_resp.data:
            return {
                "source": "NETWORK_ERROR",
                "from_cache": False,
                "cache_key": cache_key,
                "latency_ms": api_resp.latency_ms,
                "lookup_overhead_us": round(lookup_overhead_us, 2),
                "network_latency_ms": api_resp.latency_ms,
                "data": None,
                "is_error": True,
                "error_message": api_resp.error_message or "Country not found",
            }

        # Format first matched result
        country_list = api_resp.data if isinstance(api_resp.data, list) else [api_resp.data]
        formatted_entry = _format_country_record(country_list[0]) if country_list else None

        # Store in cache if enabled and valid
        if use_cache and formatted_entry is not None:
            self.cache.put(cache_key, formatted_entry, ttl_seconds=ttl_seconds)

        return {
            "source": "NETWORK_FETCH",
            "from_cache": False,
            "cache_key": cache_key,
            "latency_ms": api_resp.latency_ms,
            "lookup_overhead_us": round(lookup_overhead_us, 2),
            "network_latency_ms": api_resp.latency_ms,
            "data": formatted_entry,
            "is_error": False,
            "error_message": None,
        }

    def get_service_stats(self) -> dict[str, Any]:
        """Return combined metrics across cache and external network calls."""
        return {
            "service_lookups": self.service_lookups,
            "service_hits": self.service_hits,
            "service_misses": self.service_misses,
            "network_requests": self.client.total_network_requests,
            "network_errors": self.client.total_network_errors,
            "estimated_external_requests_avoided": self.service_hits,
            "avg_network_latency_ms": round(self.client.avg_network_latency_ms, 2),
        }
