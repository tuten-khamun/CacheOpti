"""
CacheCraft / CacheOpti - Dynamic REST API Client.

A resilient, configurable HTTP client capable of interacting with public or
authenticated APIs. Sanitizes secrets, handles network timeouts, and strictly
tracks external network calls separately from cache lookups.
"""

from __future__ import annotations
import os
import time
from dataclasses import dataclass
from typing import Any, Optional
import requests


@dataclass
class ApiResponse:
    """Standardized response container for API interactions."""

    status_code: int
    data: Any
    latency_ms: float
    is_error: bool = False
    error_message: Optional[str] = None
    from_cache: bool = False


class DynamicApiClient:
    """
    HTTP client with dynamic authentication support:
    - Public open endpoints (REST Countries default - no key needed)
    - Custom header key (e.g. X-API-Key: <key>)
    - Bearer token (Authorization: Bearer <token>)
    - Query parameter (e.g. ?apiKey=<key>)
    """

    def __init__(
        self,
        base_url: str = "https://restcountries.com/v3.1",
        api_key: Optional[str] = None,
        auth_type: str = "auto",  # 'auto', 'none', 'header', 'bearer', 'query_param'
        header_name: str = "X-API-Key",
        query_param_name: str = "apiKey",
        timeout_seconds: float = 6.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # Check environment variable if key not provided
        self.api_key = api_key or os.getenv("REST_COUNTRIES_API_KEY", "").strip() or None
        self.auth_type = auth_type
        self.header_name = header_name
        self.query_param_name = query_param_name
        self.timeout_seconds = timeout_seconds

        self.total_network_requests: int = 0
        self.total_network_errors: int = 0
        self.total_network_latency_ms: float = 0.0

        self._session = requests.Session()

    def _prepare_headers_and_params(
        self, params: Optional[dict[str, Any]]
    ) -> tuple[dict[str, str], dict[str, Any]]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "CacheOpti-Performance-Lab/1.0",
        }
        query_params: dict[str, Any] = dict(params or {})

        if not self.api_key:
            return headers, query_params

        # If a key is configured, attach according to chosen or detected auth mode
        mode = self.auth_type.lower()
        if mode == "header" or (mode == "auto" and "restcountries.com" not in self.base_url):
            headers[self.header_name] = self.api_key
        elif mode == "bearer":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif mode == "query_param":
            query_params[self.query_param_name] = self.api_key

        return headers, query_params

    def get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> ApiResponse:
        """Execute a real HTTP GET request and record external telemetry."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers, query_params = self._prepare_headers_and_params(params)

        start_ns = time.perf_counter_ns()
        self.total_network_requests += 1

        try:
            resp = self._session.get(
                url,
                headers=headers,
                params=query_params,
                timeout=self.timeout_seconds,
            )
            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.total_network_latency_ms += latency_ms

            if resp.status_code == 404:
                return ApiResponse(
                    status_code=404,
                    data=None,
                    latency_ms=round(latency_ms, 2),
                    is_error=True,
                    error_message=f"Resource not found (404) at {endpoint}",
                )

            resp.raise_for_status()
            data = resp.json()
            return ApiResponse(
                status_code=resp.status_code,
                data=data,
                latency_ms=round(latency_ms, 2),
                is_error=False,
            )

        except requests.exceptions.Timeout:
            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.total_network_errors += 1
            return ApiResponse(
                status_code=408,
                data=None,
                latency_ms=round(latency_ms, 2),
                is_error=True,
                error_message=f"Request timed out after {self.timeout_seconds}s",
            )
        except requests.exceptions.ConnectionError:
            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.total_network_errors += 1
            return ApiResponse(
                status_code=503,
                data=None,
                latency_ms=round(latency_ms, 2),
                is_error=True,
                error_message="Network connection error or remote host unreachable",
            )
        except requests.exceptions.RequestException as e:
            latency_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.total_network_errors += 1
            return ApiResponse(
                status_code=getattr(e.response, "status_code", 500) if hasattr(e, "response") else 500,
                data=None,
                latency_ms=round(latency_ms, 2),
                is_error=True,
                error_message=str(e),
            )

    @property
    def avg_network_latency_ms(self) -> float:
        if self.total_network_requests == 0:
            return 0.0
        return self.total_network_latency_ms / self.total_network_requests

    def reset_stats(self) -> None:
        self.total_network_requests = 0
        self.total_network_errors = 0
        self.total_network_latency_ms = 0.0
