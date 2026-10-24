# CacheOpti — High-Performance Observable Caching Studio

[![Tests](https://img.shields.io/badge/tests-29%20passed-success)](tests/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**CacheOpti** is an interactive caching laboratory and performance profiling engine engineered to make caching mechanics transparent, verifiable, and observable.

Instead of treating caching as an opaque black box, CacheOpti exposes the internal pointers, recency shifts, TTL decays, and capacity evictions in real time, while quantifying empirical performance gains (latency waterfalls, speedup factors, and network request avoidance).

---

## 🎯 Key Capabilities

- **Observable In-Memory Data Structures**: Combines a Python `dict` (for $O(1)$ key lookup) with an explicit **Doubly Linked List** (for $O(1)$ MRU-to-LRU pointer updates and tail evictions).
- **Monotonic TTL Expiration**: Evaluates validity lazily on access using `time.monotonic()` to guard against wall-clock leaps and NTP adjustments.
- **Falsy Value Preservation**: Uses an explicit `CACHE_MISS` sentinel singleton, ensuring valid falsy values (`0`, `False`, `None`, `[]`, `{}`) are correctly cached as hits.
- **Dynamic API Integration**: Interacts with the real REST Countries API v3.1. Operates seamlessly with public unauthenticated endpoints and dynamically supports custom API keys, headers (`X-API-Key`), Bearer tokens, or query parameters.
- **Controlled Benchmarking Lab**: Side-by-side comparative benchmarking across realistic workload distributions (Zipfian power-law 80/20, Uniform, Cyclic, and Thrashing) with defensible statistical percentiles (Mean, Median p50, 95th Percentile p95, Speedup Factor, and Net Time Saved).
- **Interactive Step-by-Step Simulator**: Step through access patterns one by one with live animated explanations of node promotion and capacity eviction.
- **Zero-Dependency Native Architecture**: Core engine, instrumentation, and HTTP server run entirely on Python's standard library with zero external web framework overhead.

---

## 🏗️ Architecture & Data Structures

```
+-------------------------------------------------------------------------+
|                              CacheEngine                                |
|                                                                         |
|  +---------------------------+       +-------------------------------+  |
|  |       Hash Map (dict)     |       |       Doubly Linked List      |  |
|  |                           |       |                               |  |
|  |  "user:1"  ---------->    |  +--> | [HEAD (MRU Sentinel)]         |  |
|  |  "country:fr" -------->   |  |    |        ^   |                  |  |
|  |  "data:42" ---------->    |  |    |        |   v                  |  |
|  +---------------------------+  |    | [Node: user:1]                |  |
|                                 |    |        ^   |                  |  |
|                                 +--- |        |   v                  |  |
|                                      | [Node: country:fr]            |  |
|                                      |        ^   |                  |  |
|                                      |        |   v                  |  |
|                                      | [TAIL (LRU Sentinel)]         |  |
|                                      +-------------------------------+  |
+-------------------------------------------------------------------------+
```

### Time Complexity Guarantees

| Operation | Mechanism | Time Complexity |
| :--- | :--- | :--- |
| **Lookup (`get`)** | Hash Map key lookup | $O(1)$ |
| **Recency Promotion** | Unlink node + insert after Head sentinel | $O(1)$ |
| **TTL Check** | Compare elapsed monotonic seconds against TTL | $O(1)$ |
| **Capacity Eviction** | Pop node immediately preceding Tail sentinel | $O(1)$ |
| **Insert (`put`)** | Insert after Head sentinel + store in dict | $O(1)$ |

---

## 📂 Project Structure

```
Week 2/
├── run.py                           # Application launcher (opens browser UI)
├── requirements.txt                 # Dependencies (requests for external API)
├── .env.example                     # Environment template for custom API keys
├── .gitignore                       # Git exclusion rules
├── README.md                        # Documentation & Architecture guide
├── cacheopti/
│   ├── __init__.py
│   ├── server.py                    # Multi-threaded REST API server & static host
│   ├── core/                        # Core caching data structures & engine
│   │   ├── __init__.py
│   │   ├── node.py                  # CacheNode & DoublyLinkedList (O(1) pointers)
│   │   ├── entry.py                 # CACHE_MISS sentinel & snapshot models
│   │   ├── policies.py              # BaseCachePolicy, LRUPolicy, FIFOPolicy, LFUPolicy
│   │   ├── key_builder.py           # Deterministic key hashing & credential masking
│   │   └── engine.py                # CacheEngine (TTL, capacity, eviction, telemetry)
│   ├── instrumentation/             # Performance tracking & function decorators
│   │   ├── __init__.py
│   │   ├── decorator.py             # @cached decorator
│   │   ├── metrics.py               # Latency percentiles & observed time saved
│   │   └── tracker.py               # Thread-safe operation registry & event buffer
│   ├── benchmark/                   # Controlled profiler & workload generators
│   │   ├── __init__.py
│   │   ├── workloads.py             # Zipfian, Uniform, Cyclic, Thrash distributions
│   │   └── runner.py                # BenchmarkRunner (cold vs warm cache, speedups)
│   ├── api/                         # Dynamic external REST client & services
│   │   ├── __init__.py
│   │   ├── client.py                # Resilient HTTP client with dynamic auth
│   │   └── country_service.py       # REST Countries client with latency waterfall
│   └── ui/                          # Modern Dark-Mode Developer Studio
│       ├── __init__.py
│       └── static/
│           ├── index.html           # Single-Page Application interface
│           ├── styles.css           # Modern technical dark theme
│           └── app.js               # Reactive HUD, DLL visualizer, Chart.js graphs
└── tests/                           # Comprehensive automated test suite
    ├── __init__.py
    ├── test_engine.py               # Hits, misses, falsy values, key collision tests
    ├── test_ttl.py                  # Monotonic clock TTL, lazy purge, remaining seconds
    ├── test_lru.py                  # Capacity eviction, recency survival, FIFO & LFU
    ├── test_instrumentation.py      # @cached decorator, error safety, latency tracking
    ├── test_api_client.py           # Mocked API calls, network error handling, tokens
    ├── test_benchmark.py            # Synthetic workloads and comparative benchmark stats
    ├── test_integration.py          # End-to-end country caching and expiration flows
    └── test_server.py               # REST API server endpoint integration tests
```

---

## 🚀 Quickstart Guide

### 1. Installation
Clone or navigate to the project directory:
```bash
pip install -r requirements.txt
```

### 2. Launch the Studio
Start the CacheOpti Performance Studio:
```bash
python run.py
```
This automatically starts the server and opens your browser at **`http://127.0.0.1:8000`**.

### 3. Run Automated Tests
Run the entire unit and integration test suite:
```bash
python -m unittest discover -s tests -v
```
All 29 tests execute in **< 0.01 seconds** using mocked networks and monotonic mock clocks.

---

## 🔑 Authentication & API Key Handling

- **Public REST Countries v3.1** (`https://restcountries.com/v3.1`) is open and requires **no API key**.
- If you wish to test with an authenticated gateway, API proxy, or another REST provider:
  1. Set the environment variable in `.env`:
     ```env
     REST_COUNTRIES_API_KEY=your_key_here
     REST_COUNTRIES_AUTH_TYPE=header  # header | bearer | query_param
     REST_COUNTRIES_BASE_URL=https://your-custom-api.com
     ```
  2. Or configure it dynamically live inside the **Settings & API Key** panel in the web UI.
  3. **Security Guarantee:** All API keys and authorization headers are automatically masked in cache keys and logs (`[REDACTED_SECRET]`) to prevent credential leakage.

---

## 📊 Benchmark Methodology

CacheOpti avoids single-request bias by implementing rigorous statistical standards:

1. **Separation of Network vs Cache Overhead**:
   - Network I/O typically ranges from `100 ms` to `800 ms`.
   - In-memory cache lookup overhead is measured in microseconds (`< 0.05 ms`).
2. **Cold-Start vs Steady-State Warm Cache**:
   - Initial misses during cache population are isolated from warm-cache hits.
3. **Defensible Time Saved Formula**:
   $$\text{Observed Time Saved} = (\text{Mean Uncached Latency} \times \text{Hits}) - \sum \text{Cached Hit Latencies}$$
4. **Realistic Access Distributions**:
   - **Zipfian (80/20)**: Models real web traffic where a small fraction of keys receive the vast majority of requests.
   - **Thrashing**: Demonstrates what happens when the working set exceeds cache capacity under LRU.

---

## 🛠️ Reusing the Cache Engine in Your Code

The caching engine is completely independent of the UI and can be embedded directly into any Python script, service, or CLI:

```python
from cacheopti.core.engine import CacheEngine
from cacheopti.instrumentation.decorator import cached

# Initialize a cache with capacity of 100 items and a 60-second TTL
cache = CacheEngine(capacity=100, default_ttl_seconds=60.0)

# Memoize any expensive Python function
@cached(cache, ttl_seconds=15.0)
def fetch_heavy_dataset(dataset_id: int):
    # Expensive computation or database call...
    return {"id": dataset_id, "data": [i ** 2 for i in range(100000)]}

# First call: cache miss, executes function
result1 = fetch_heavy_dataset(42)

# Second call: instant cache hit (< 0.05 ms)
result2 = fetch_heavy_dataset(42)

# Inspect live telemetry
print(cache.get_state())
```

---

## 📄 License
MIT License. Built for performance engineers, systems architects, and curious developers.
