"""
CacheCraft / CacheOpti - Production REST Server & Static File Host.

Built using Python's standard library http.server and socketserver.
Zero external web framework dependencies, fully multi-threaded,
and serves both high-performance JSON API endpoints and the modern SPA interface.
"""

from __future__ import annotations
import json
import mimetypes
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from cacheopti.core.engine import CacheEngine
from cacheopti.core.policies import LRUPolicy, FIFOPolicy, LFUPolicy
from cacheopti.api.client import DynamicApiClient
from cacheopti.api.country_service import CountryService
from cacheopti.benchmark.workloads import (
    generate_zipfian_workload,
    generate_uniform_workload,
    generate_cyclic_workload,
    generate_thrashing_workload,
)
from cacheopti.benchmark.runner import BenchmarkRunner


class AppState:
    """Thread-safe global application state holding cache engine and services."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cache = CacheEngine(capacity=6, default_ttl_seconds=30.0, policy=LRUPolicy())
        self.client = DynamicApiClient()
        self.service = CountryService(cache_engine=self.cache, api_client=self.client)

        # Simulator state
        self.sim_workload: list[str] = ["A", "B", "C", "A", "D", "B", "E", "C", "F", "A"]
        self.sim_index: int = 0
        self.sim_history: list[dict[str, Any]] = []

    def set_config(
        self,
        capacity: int,
        default_ttl: float,
        policy_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        auth_type: str = "auto",
    ) -> None:
        with self.lock:
            # Policy switch
            if policy_name.upper() == "FIFO":
                pol = FIFOPolicy()
            elif policy_name.upper() == "LFU":
                pol = LFUPolicy()
            else:
                pol = LRUPolicy()

            # Preserve existing entries if possible or create freshly sized cache
            old_storage = list(self.cache._storage.values())
            self.cache = CacheEngine(
                capacity=max(1, capacity),
                default_ttl_seconds=default_ttl,
                policy=pol,
            )
            # Reinsert entries within new capacity
            for node in old_storage[:capacity]:
                self.cache.put(node.key, node.value, ttl_seconds=node.ttl_seconds)

            # Update API client
            clean_key = api_key.strip() if api_key else None
            self.client = DynamicApiClient(
                base_url=base_url or "https://restcountries.com/v3.1",
                api_key=clean_key,
                auth_type=auth_type,
            )
            self.service = CountryService(cache_engine=self.cache, api_client=self.client)


# Global singleton state
state = AppState()

# Resolve path to static UI files
STATIC_DIR = os.path.join(os.path.dirname(__file__), "ui", "static")


class CacheOptiRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler dispatching REST API routes and serving static UI assets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _read_body_json(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw)
        except Exception:
            pass
        return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/state":
            with state.lock:
                cache_st = state.cache.get_state()
                svc_st = state.service.get_service_stats()
                return self._send_json({
                    "cache": cache_st,
                    "service": svc_st,
                    "api_key_configured": bool(state.client.api_key),
                    "base_url": state.client.base_url,
                })

        elif path == "/api/entries":
            with state.lock:
                entries = [e.to_dict() for e in state.cache.get_entries()]
                return self._send_json({"entries": entries})

        elif path == "/api/events":
            with state.lock:
                events = state.cache.get_recent_events(limit=50)
                return self._send_json({"events": events})

        elif path == "/api/sim/state":
            with state.lock:
                return self._send_json({
                    "workload": state.sim_workload,
                    "index": state.sim_index,
                    "history": state.sim_history[-20:],
                })

        # Static assets or index.html fallback
        if path == "/" or not os.path.exists(os.path.join(STATIC_DIR, path.lstrip("/"))):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body_json()

        if path == "/api/clear":
            with state.lock:
                state.cache.clear()
                state.cache.reset_metrics()
                state.client.reset_stats()
                state.service.service_lookups = 0
                state.service.service_hits = 0
                state.service.service_misses = 0
                return self._send_json({"status": "cleared"})

        elif path == "/api/config":
            capacity = int(body.get("capacity", 6))
            default_ttl = float(body.get("default_ttl", 30.0))
            policy = str(body.get("policy", "LRU"))
            api_key = body.get("api_key")
            base_url = body.get("base_url")
            auth_type = body.get("auth_type", "auto")

            state.set_config(
                capacity=capacity,
                default_ttl=default_ttl,
                policy_name=policy,
                api_key=api_key,
                base_url=base_url,
                auth_type=auth_type,
            )
            return self._send_json({"status": "configured", "capacity": capacity, "policy": policy})

        elif path == "/api/country/search":
            name = str(body.get("name", "")).strip()
            use_cache = bool(body.get("use_cache", True))
            ttl = float(body["ttl"]) if "ttl" in body and body["ttl"] is not None else None

            if not name:
                return self._send_json({"error": "Country name required"}, status=400)

            with state.lock:
                res = state.service.get_country_by_name(name, use_cache=use_cache, ttl_seconds=ttl)
                return self._send_json(res)

        elif path == "/api/benchmark/run":
            workload_type = str(body.get("workload_type", "zipfian")).lower()
            num_ops = min(200, max(10, int(body.get("num_ops", 50))))
            cap = min(50, max(1, int(body.get("capacity", 6))))
            ttl = float(body.get("ttl", 30.0))

            # Sample key domain
            keys = ["france", "japan", "brazil", "germany", "india", "canada", "italy", "egypt", "mexico", "spain"]
            if workload_type == "uniform":
                workload = generate_uniform_workload(keys, num_requests=num_ops)
            elif workload_type == "cyclic":
                workload = generate_cyclic_workload(keys[:cap], num_cycles=max(1, num_ops // len(keys[:cap])))
            elif workload_type == "thrash":
                workload = generate_thrashing_workload(capacity=cap, multiplier=3, cycles=max(1, num_ops // (cap * 3)))
            else:
                workload = generate_zipfian_workload(keys, num_requests=num_ops, alpha=1.3)

            # Synthetic deterministic operation (fast matrix/hash simulation to isolate cache dynamics)
            def benchmark_op(key_name: str) -> dict[str, Any]:
                total = 0
                for i in range(120_000):
                    total += (i ^ hash(key_name)) & 0xFFF
                return {"result": total, "key": key_name}

            result = BenchmarkRunner.run_comparison(
                operation=benchmark_op,
                workload=workload,
                cache_capacity=cap,
                cache_ttl_seconds=ttl,
                workload_name=f"{workload_type.capitalize()} Workload",
            )

            # Also generate a capacity sweep for charting
            sweep = BenchmarkRunner.run_capacity_sweep(
                operation=benchmark_op,
                workload=workload,
                capacities=[2, 4, 8, 16],
                default_ttl_seconds=ttl,
            )

            return self._send_json({
                "result": result.to_dict(),
                "capacity_sweep": sweep,
            })

        elif path == "/api/sim/step":
            with state.lock:
                if state.sim_index >= len(state.sim_workload):
                    state.sim_index = 0  # Loop back

                item_key = state.sim_workload[state.sim_index]
                state.sim_index += 1

                # Execute step in cache
                now = time.monotonic()
                val = state.cache.get(item_key)
                was_hit = val is not None and str(val) != "<CACHE_MISS>"

                if not was_hit:
                    # Synthetic compute
                    computed = f"ComputedVal({item_key})"
                    state.cache.put(item_key, computed)
                    action = "MISS_INSERT"
                else:
                    action = "HIT_PROMOTED"

                record = {
                    "step": len(state.sim_history) + 1,
                    "key": item_key,
                    "action": action,
                    "was_hit": was_hit,
                    "cache_size": len(state.cache._storage),
                    "capacity": state.cache.capacity,
                    "timestamp": time.time(),
                }
                state.sim_history.append(record)

                entries = [e.to_dict() for e in state.cache.get_entries()]
                return self._send_json({
                    "step_record": record,
                    "next_index": state.sim_index,
                    "entries": entries,
                })

        elif path == "/api/sim/reset":
            with state.lock:
                state.sim_index = 0
                state.sim_history.clear()
                state.cache.clear()
                return self._send_json({"status": "reset"})

        else:
            return self._send_json({"error": "Endpoint not found"}, status=404)


def start_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Launch the multi-threaded HTTP server."""
    server = ThreadingHTTPServer((host, port), CacheOptiRequestHandler)
    print("=" * 50)
    print(">> CacheOpti Performance Studio running at:")
    print(f"   http://{host}:{port}")
    print("=" * 50)
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = start_server(port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CacheOpti server...")
        server.shutdown()
