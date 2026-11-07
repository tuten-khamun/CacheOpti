"""
CacheOpti v2.0 - Per-Key Single-Flight Coordination & Background Worker Pool.

Suppresses duplicate concurrent upstream invocations for the same key.
When 100 concurrent requests miss or attempt early recomputation on key 'X',
exactly ONE worker executes loader_fn while the remaining 99 callers wait
on the leader's event or receive stale values during background refresh.
"""

from __future__ import annotations
import concurrent.futures
import threading
from typing import Any, Callable, Dict, Optional, Tuple


class _FlightCall:
    """Internal coordination record for an in-flight key computation."""

    __slots__ = ("event", "result", "delta_ns", "exc", "waiters")

    def __init__(self) -> None:
        self.event: threading.Event = threading.Event()
        self.result: Any = None
        self.delta_ns: int = 0
        self.exc: Optional[BaseException] = None
        self.waiters: int = 1


class SingleFlight:
    """
    Coordinates concurrent function execution so that only one execution
    is in flight for a given key at any time. If duplicate calls arrive,
    subsequent callers wait for the original call to complete and share its result.
    """

    def __init__(self, max_background_workers: int = 16) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._calls: Dict[str, _FlightCall] = {}
        # Dedicated thread pool for non-blocking background early-refresh execution
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_background_workers,
            thread_name_prefix="cacheopti-singleflight",
        )

    def do(
        self,
        key: str,
        fn: Callable[[], Tuple[Any, int]],
    ) -> Tuple[Any, int, bool]:
        """
        Execute `fn` if no other call for `key` is currently in flight.
        If another call is in flight, wait for it and return the shared result.

        Returns:
            (result, delta_ns, is_leader)
            is_leader is True if this invocation actually ran `fn`, False if it waited.
        """
        with self._lock:
            if key in self._calls:
                call = self._calls[key]
                call.waiters += 1
                is_leader = False
            else:
                call = _FlightCall()
                self._calls[key] = call
                is_leader = True

        if not is_leader:
            call.event.wait()
            if call.exc is not None:
                raise call.exc
            return call.result, call.delta_ns, False

        # Leader path
        try:
            val, delta_ns = fn()
            call.result = val
            call.delta_ns = delta_ns
        except BaseException as exc:
            call.exc = exc
            raise exc
        finally:
            with self._lock:
                self._calls.pop(key, None)
            call.event.set()

        return call.result, call.delta_ns, True

    def is_in_flight(self, key: str) -> bool:
        """Check if an asynchronous or synchronous flight is currently executing for key."""
        with self._lock:
            return key in self._calls

    def submit_background(
        self,
        key: str,
        task_fn: Callable[[], None],
    ) -> bool:
        """
        Submit a background refresh task if no flight is already active for key.
        Returns True if task was submitted, False if another flight was already running.
        """
        with self._lock:
            if key in self._calls:
                return False
            call = _FlightCall()
            self._calls[key] = call

        def _worker() -> None:
            try:
                task_fn()
            except BaseException as exc:
                call.exc = exc
            finally:
                with self._lock:
                    self._calls.pop(key, None)
                call.event.set()

        try:
            self._executor.submit(_worker)
            return True
        except Exception:
            with self._lock:
                self._calls.pop(key, None)
            return False

    def shutdown(self, wait: bool = False) -> None:
        """Cleanly shut down background thread pool."""
        self._executor.shutdown(wait=wait)
