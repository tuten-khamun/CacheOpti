# CacheOpti v2.0 — High-Concurrency, Memory-Bounded Caching Engine

[![Tests](https://img.shields.io/badge/tests-53%20passed-success)](tests/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Architecture](https://img.shields.io/badge/architecture-16--Way%20Sharded%20RLock-orange)](docs/adr/001-xfetch-stampede-and-sharded-locking.md)

**CacheOpti v2.0** is an industrial-grade, in-process caching engine engineered in Python for low-latency, high-concurrency environments including Quant Finance, High-Frequency Trading (HFT) feature pipelines, distributed backend services, and cybersecurity telemetry ingestion.

CacheOpti v2.0 is specifically designed to eliminate the three classic pitfalls of in-memory caching:
1. **Cache Stampedes (Thundering Herd)**: Mitigated using the **VLDB XFetch** probabilistic early-expiration algorithm paired with per-key **Single-Flight** request deduplication.
2. **Memory Exhaustion (OOM)**: Governed by **Dual-Bound Eviction** (`max_entries` and `max_bytes`), featuring recursive deep memory accounting for nested data structures, NumPy tensors, and Pandas DataFrames.
3. **Lock Contention**: Distributed across **16 independent cache shards** (`hash(key) & 0x0F`), eliminating global lock bottlenecks.

---

## 🏛️ High-Level Architecture

```
                                    Client Request
                                          │
                                          ▼
                         ┌──────────────────────────────────┐
                         │   ShardedCache (Engine v2.0)     │
                         │    Route: hash(key) & 0x0F       │
                         └─────────────────┬────────────────┘
                                           │
          ┌───────────────┬────────────────┼───────────────┬───────────────┐
          │ (Shard 0)     │ (Shard 1)      │ (Shard 2)     │ ...           │ (Shard 15)
          ▼               ▼                ▼               ▼               ▼
   ┌─────────────┐ ┌─────────────┐  ┌─────────────┐                 ┌─────────────┐
   │ _CacheShard │ │ _CacheShard │  │ _CacheShard │                 │ _CacheShard │
   │ ─────────── │ │ ─────────── │  │ ─────────── │                 │ ─────────── │
   │ • dict      │ │ • dict      │  │ • dict      │                 │ • dict      │
   │ • DLL (LRU) │ │ • DLL (LRU) │  │ • DLL (LRU) │                 │ • DLL (LRU) │
   │ • RLock     │ │ • RLock     │  │ • RLock     │                 │ • RLock     │
   │ • Byte Acct │ │ • Byte Acct │  │ • Byte Acct │                 │ • Byte Acct │
   └─────────────┘ └─────────────┘  └─────────────┘                 └─────────────┘
          │
          ▼
   ┌────────────────────────────────────────────────────────┐
   │ SingleFlight Coalescer + XFetch Probabilistic Trigger   │
   │   - Leader executes loader_fn()                        │
   │   - Followers wait on Event or serve stale value       │
   └───────────────────────────────┬────────────────────────┘
                                   │
                                   ▼
   ┌────────────────────────────────────────────────────────┐
   │ Performance Telemetry (Pre-Allocated NumPy Ring Buffer)│
   │   - Latencies recorded in int64 nanoseconds            │
   │   - Quantiles: p50, p95, p99, p99.9                   │
   └────────────────────────────────────────────────────────┘
```

---

## ⚡ Core Engine Components

### A. Custom LRU Data Structure (`cacheopti.core.lru`)
- **Dictionary + Doubly Linked List**: Hash table provides $\mathcal{O}(1)$ direct key lookup, while an explicit doubly linked list maintains strict Most Recently Used (MRU) to Least Recently Used (LRU) ordering.
- **Sentinel Nodes**: Employs `_head` and `_tail` dummy sentinels, eliminating boundary condition checks and null pointer edge cases during link and unlink operations.
- **Memory-Optimized `_Node` via `__slots__`**: Every node uses `__slots__` to suppress the allocation of an instance `__dict__`, reducing per-entry overhead by over 150 bytes.

### B. Dual-Bound Eviction & Deep Memory Accounting (`cacheopti.core.memory`)
- **Dual Limits**: Enforces both `max_entries` and `max_bytes` simultaneously. If either boundary is breached, entries are evicted from the LRU tail until both limits are satisfied.
- **Deep Recursive Memory Traversal**: `deep_getsizeof()` recursively traverses nested dictionaries, lists, sets, tuples, and user classes.
- **Pandas & NumPy Integration**: Accurately computes contiguous memory buffers for `pandas.DataFrame` (`memory_usage(index=True, deep=True).sum()`) and `numpy.ndarray` (`nbytes`), preventing silent Out-Of-Memory termination.
- **Cycle Detection**: Tracks visited memory addresses via `seen: set[int]` to prevent infinite recursion on circular object graphs.
- **Precise Overwrite Accounting**: Recomputing size deltas on key overwrite ensures memory accounting never drifts over time.

### C. 16-Way Sharded Concurrency (`cacheopti.core.shard`)
- **Independent Shards**: Partitioned into 16 completely autonomous `_CacheShard` instances.
- **Bitwise Routing**: Keys are mapped deterministically via:
  $$\text{shard\_index} = \text{hash}(\text{key}) \ \& \ \text{0x0F}$$
- **Fine-Grained Locking**: Each shard encapsulates its own `threading.RLock`. Multi-threaded operations targeting different shards proceed completely concurrently without cross-thread lock contention.

### D. VLDB XFetch Probabilistic Early Expiration (`cacheopti.core.singleflight`)
- Implements the optimal probabilistic early-expiration algorithm published in VLDB 2015 (*Vattani, Chierichetti, Lowenstein*).
- **Early Recomputation Rule**: An entry approaching its TTL dynamically triggers a refresh with probability:
  $$P(\text{recompute} \mid \Delta) = \min\left(1.0, e^{ - \frac{\Delta}{\beta \cdot \delta} }\right)$$
  Where $\Delta$ is remaining TTL, $\delta$ is previous computation duration, and $\beta$ is aggressiveness parameter.
- **Per-Key Single-Flight Request Coalescing**: When multiple concurrent requests miss or recompute simultaneously, `SingleFlight` coordinates execution so that **exactly ONE worker** invokes the upstream loader, while all remaining concurrent callers share the result.
- **Zero-Latency Stale Serving**: During background refresh, callers receive the existing cached payload in sub-microsecond time with zero blocking delay.

### E. Pre-Allocated NumPy Ring Buffer Telemetry (`cacheopti.core.telemetry`)
- **Sub-Microsecond Latency Recording**: Employs a pre-allocated contiguous 64-bit NumPy array (`np.zeros(capacity, dtype=np.int64)`) to record latency in nanoseconds.
- **Statistical Percentiles**: Vectorially calculates $p50$, $p95$, $p99$, and $p99.9$ using linear rank interpolation.
- **Accurate Concurrency Analysis**: Explicitly lock-guarded to prevent race conditions and lost samples, avoiding misleading claims of "lock-freedom" in Python userspace.

---

## 📐 Applied Mathematics & Theoretical Complexity

### 1. The XFetch Exponential Probability Formula
The probability of triggering an early cache refresh before TTL expiration is:
$$P(\text{recompute}) = \exp\left( - \frac{\Delta}{\beta \cdot \delta} \right)$$

#### Proof of the Landmark Example ($P = e^{-2} \approx 13.53\%$)
When the time remaining until expiration is exactly twice the scaled compute time ($\Delta = 2\beta\delta$):
$$P = \exp\left( - \frac{2 \cdot \beta \cdot \delta}{\beta \cdot \delta} \right) = \exp(-2) = \frac{1}{e^2} \approx 0.135335 \approx \mathbf{13.53\%}$$

As $\Delta \to 0$ (the entry is on the verge of expiring), $P \to e^0 = 1.0$ (100% certainty).

### 2. Shard Collision Probability (Generalized Birthday Problem)
Across $M = 16$ shards, the probability that $k$ concurrent requests touch independent shards without colliding is:
$$P(\text{no collision}) = \prod_{i=0}^{k-1} \left(1 - \frac{i}{16}\right)$$

For two concurrent requests ($k = 2$):
$$P(\text{collision}) = \frac{1}{16} = 6.25\% \implies P(\text{contention-free}) = \mathbf{93.75\%}$$
Compared to a global monolithic lock where contention is guaranteed ($100\%$), 16-way sharding reduces collision probability by over **15x**.

### 3. Complexity Guarantees

| Operation | Algorithm / Mechanism | Time Complexity | Space Complexity |
| :--- | :--- | :--- | :--- |
| **Key Lookup (`get`)** | Hash routing (`hash & 0x0F`) + Dict lookup | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| **Recency Promotion** | DLL unlink + relink at `_head` sentinel | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| **Eviction (`pop_tail`)** | DLL unlink at `_tail` sentinel + dict pop | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| **Memory Sizing (`put`)** | Recursive deep traversal (`deep_getsizeof`) | $\mathcal{O}(V + E)$ on insert | $\mathcal{O}(\text{depth})$ |
| **XFetch Evaluation** | Monotonic delta comparison | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| **Telemetry Append** | NumPy ring buffer circular index write | $\mathcal{O}(1)$ | $\mathcal{O}(N)$ pre-allocated |

---

## 📊 Empirical Benchmarks & Real-World Results

Benchmarked on **Python 3.14.6 (64-bit Windows)** using `benchmarks/stampede_simulation.py`:

### Experiment 1: Cache Stampede Simulation (100 Concurrent Threads, 30ms DB Delay)
When a hot cache key expires under 100 concurrent requests:

```
================================================================================
  EXPERIMENT 1: CACHE STAMPEDE SIMULATION (100 Concurrent Threads)
  Upstream Loader Artificial Delay: 30.0 ms
================================================================================

RESULTS:
  * Naive TTL Cache:     100 upstream DB calls! (100% stampede)
    Latency: p50=30.31ms, p95=30.55ms, p99=30.59ms
  * CacheOpti v2.0:      1 upstream DB call!  (99.0% stampede reduction)
    Latency: p50=25.25ms, p95=30.07ms, p99=30.62ms
```

### Experiment 2: 32-Thread High-Concurrency Throughput (16,000 Total Ops, Zipfian Traffic)

| Engine | Throughput (ops/sec) | $p50$ Latency | $p95$ Latency | $p99$ Latency | Memory Bounds |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Python `functools.lru_cache`** | 691,201 ops/s | $0.50\,\mu\text{s}$ | $0.80\,\mu\text{s}$ | $1.10\,\mu\text{s}$ | ❌ No TTL, No Byte Bounds |
| **Naive TTL Cache** | 856,274 ops/s | $0.30\,\mu\text{s}$ | $0.60\,\mu\text{s}$ | $1.00\,\mu\text{s}$ | ❌ No LRU, No Byte Bounds |
| **CacheOpti v2.0 (`ShardedCache`)** | **269,217 ops/s** | **$2.10\,\mu\text{s}$** | **$3.90\,\mu\text{s}$** | **$7.70\,\mu\text{s}$** | **✅ Strict Dual Bounds & 16 Shards** |

> **Key Takeaway**: While C-level `functools.lru_cache` runs fast in synthetic microbenchmarks, it offers no TTL, no memory bounds, and completely fails under cache stampedes. CacheOpti v2.0 sustains **>269,000 operations per second** with **$2.1\,\mu\text{s}$ median latency**, while providing strict byte limits and complete stampede protection.

---

## 🚀 Quickstart & Usage Guide

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/tuten-khamun/CacheOpti.git
cd CacheOpti
pip install -r requirements.txt
```

### 2. High-Concurrency Usage with `ShardedCache`

```python
from cacheopti import ShardedCache
import pandas as pd
import time

# Initialize 16-way sharded cache with dual bounds: 10,000 entries and 50MB memory
cache = ShardedCache(
    max_entries=10_000,
    max_bytes=50 * 1024 * 1024,  # 50 Megabytes
    default_ttl_seconds=60.0,
    num_shards=16,
)

# Loader function representing an expensive SQL query or feature extraction
def load_market_data(ticker: str) -> pd.DataFrame:
    time.sleep(0.05)  # 50ms compute
    return pd.DataFrame({
        "timestamp": range(1000),
        "price": [100.0 + i * 0.1 for i in range(1000)],
    })

# Probabilistic XFetch lookup with per-key Single-Flight coalescing
df = cache.get_or_compute(
    key="market:AAPL",
    loader_fn=lambda: load_market_data("AAPL"),
    ttl=30.0,
    beta=1.0,
    serve_stale=True,
)

# Inspect high-resolution telemetry
telemetry = cache.get_telemetry()
print(f"Hit Rate: {telemetry['hit_rate_pct']}%")
print(f"p50 Latency: {telemetry['percentiles']['p50_us']} us")
print(f"p99 Latency: {telemetry['percentiles']['p99_us']} us")
print(f"Total Memory: {telemetry['total_bytes']:,} bytes")
```

### 3. Function Decorator Memoization

```python
from cacheopti import CacheEngine, cached

cache = CacheEngine(capacity=100, default_ttl_seconds=30.0)

@cached(cache, ttl_seconds=15.0)
def compute_risk_factors(portfolio_id: int):
    # Heavy quant computation
    return {"portfolio_id": portfolio_id, "var_95": 0.042, "cvar_99": 0.068}

# First call: executes loader
res1 = compute_risk_factors(42)

# Subsequent call: instant in-memory hit (< 2 us)
res2 = compute_risk_factors(42)
```

### 4. Running the Interactive UI Studio
To launch the interactive Dark-Mode Observability HUD:
```bash
python run.py
```
Open **`http://127.0.0.1:8000`** in your browser.

---

## 🧪 Automated Test Suite

Run the complete 53-test automated test suite:
```bash
python -m pytest -v
```

All 53 unit and integration tests execute in **< 2 seconds**:
- `tests/test_v2_lru.py`: Custom `_Node` (`__slots__`), sentinels, O(1) operations.
- `tests/test_v2_memory.py`: Recursive sizing, Pandas DataFrames, cyclic reference safety, overwrites.
- `tests/test_v2_sharding.py`: 16-way independent shards, `hash & 0x0F` key routing, lock isolation.
- `tests/test_v2_xfetch.py`: Mathematical equation verification ($P = e^{-2} \approx 13.53\%$), Single-Flight 50-thread coalescing, stale serving.
- `tests/test_v2_telemetry.py`: Pre-allocated NumPy ring buffer, quantiles ($p50, p95, p99, p99.9$), concurrent write safety.
- `tests/test_v2_concurrency.py`: 32-thread high-contention read/write stress test.
- `tests/test_engine.py`, `test_lru.py`, `test_ttl.py`, etc.: Full backward-compatibility regression tests.

---

## 📁 Repository Structure

```
CacheOpti/
├── run.py                               # Web Studio launcher (multi-threaded HTTP)
├── requirements.txt                     # Dependencies (numpy, pandas, pytest, requests)
├── README.md                            # Comprehensive Engineering Documentation
├── benchmarks/
│   └── stampede_simulation.py           # 32-thread benchmark & stampede simulator
├── docs/
│   └── adr/
│       └── 001-xfetch-stampede-and-sharded-locking.md # Architectural Decision Record
├── cacheopti/
│   ├── __init__.py                      # Package entrypoint (ShardedCache, CacheEngine)
│   ├── server.py                        # Multi-threaded REST API server & static host
│   ├── core/                            # Core Caching Data Structures & Engines
│   │   ├── __init__.py
│   │   ├── lru.py                       # _Node (__slots__) & DoublyLinkedList (sentinels)
│   │   ├── memory.py                    # Recursive deep memory sizer (Pandas/NumPy)
│   │   ├── shard.py                     # _CacheShard (dual-bound LRU & RLock)
│   │   ├── singleflight.py              # Per-key SingleFlight coalescer & async executor
│   │   ├── telemetry.py                 # Pre-allocated NumPy ring buffer (p50-p99.9)
│   │   ├── engine.py                    # ShardedCache & CacheEngine
│   │   ├── node.py                      # Legacy CacheNode model
│   │   ├── entry.py                     # CACHE_MISS sentinel & snapshot models
│   │   ├── policies.py                  # Pluggable policies (LRU, FIFO, LFU)
│   │   └── key_builder.py               # Deterministic key hashing & credential masking
│   ├── instrumentation/                 # Function decorators & metric trackers
│   ├── benchmark/                       # Workload generators (Zipfian, Uniform, etc.)
│   ├── api/                             # REST Countries external API client
│   └── ui/                              # Single-Page Application (HTML5/CSS3/Chart.js)
└── tests/                               # Comprehensive Automated Test Suite (53 tests)
    ├── test_v2_lru.py                   # _Node slots, sentinels, O(1) pointer tests
    ├── test_v2_memory.py                # Deep memory, Pandas/NumPy, overwrite tests
    ├── test_v2_sharding.py              # 16-way sharding & hash mask routing
    ├── test_v2_xfetch.py                # XFetch probability & SingleFlight tests
    ├── test_v2_telemetry.py             # NumPy ring buffer & percentile tests
    ├── test_v2_concurrency.py           # 32-thread stress & race condition tests
    └── test_*.py                        # Existing v1 engine, LRU, TTL, API tests
```

---

## 📜 Architectural Decisions & Engineering Documentation
For in-depth analysis of the mathematical proofs, concurrency trade-offs, and GIL considerations, see:
👉 [**ADR 001: VLDB XFetch, 16-Way Sharded Locking, and Dual-Bound Memory Bounds**](docs/adr/001-xfetch-stampede-and-sharded-locking.md)

---

## 📄 License
MIT License. Engineered for performance engineers, systems architects, and quant developers.
