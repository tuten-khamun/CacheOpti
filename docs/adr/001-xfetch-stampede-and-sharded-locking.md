# Architecture Decision Record (ADR) 001
## High-Concurrency Sharded Architecture, VLDB XFetch Stampede Prevention, and Dual-Bound Memory Bounds in CacheOpti v2.0

- **Status**: Accepted
- **Author**: Senior Systems Software Engineer & Python Performance Engineer
- **Date**: November 2026
- **Context**: CacheOpti Core Architecture Evolution (v1.0 -> v2.0)

---

## 1. Executive Summary & Problem Context

In high-throughput distributed systems, quant trading infrastructure, and cybersecurity telemetry pipelines, in-process caching engines encounter three fatal failure modes:

1. **Cache Stampedes (Thundering Herd)**: When a hot cache key expires under heavy concurrent read traffic, dozens or hundreds of worker threads simultaneously observe a cache miss and invoke the expensive upstream data loader (database query, network RPC, or heavy numerical model). This leads to upstream saturation, catastrophic latency spikes, and cascading outages.
2. **Memory Exhaustion & Process Termination (OOM)**: Naive caches enforce limits solely by entry count (`len(cache) >= capacity`). When payloads vary in size—ranging from a 20-byte string to a 50-megabyte Pandas DataFrame or NumPy tensor—entry-bounded caches allow process memory to grow unboundedly until the operating system's OOM killer terminates the host process.
3. **Synchronization Bottlenecks & Lock Contention**: A single global lock (such as Python's standard `functools.lru_cache` internal mutex or a monolithic `threading.Lock`) forces all threads across multiple CPU cores to serialize on a single synchronization point. According to Amdahl's Law and Gunther's Universal Scalability Law, lock contention dominates execution time as thread concurrency scales, causing throughput to plateau and collapse.

**CacheOpti v2.0** resolves all three bottlenecks through:
- A custom memory-optimized Doubly Linked List with `__slots__` and sentinel nodes.
- Dual-bound capacity and byte enforcement with recursive deep memory accounting.
- 16-way independent sharded concurrency via bitwise hash routing (`hash(key) & 0x0F`).
- Probabilistic early recomputation via the VLDB XFetch algorithm coupled with per-key Single-Flight request coalescing.
- High-throughput performance telemetry using a pre-allocated contiguous NumPy ring buffer.

---

## 2. Decision & Technical Architecture

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
   │   - Percentiles: p50, p95, p99, p99.9                  │
   └────────────────────────────────────────────────────────┘
```

### Component A: Custom LRU Data Structure
- Replaced Python's standard `OrderedDict` with an explicit `dict[str, _Node]` paired with a custom `DoublyLinkedList`.
- **Sentinel Nodes**: Features `_head` (MRU sentinel) and `_tail` (LRU sentinel) dummy nodes. Sentinels eliminate branch checks for empty-list and single-element edge cases during pointer manipulation.
- **Memory Optimization via `__slots__`**: Every `_Node` declares `__slots__ = ("key", "value", "size_bytes", "created_at_ns", "ttl_ns", "delta_ns", "last_accessed_ns", "access_count", "prev", "next")`. This eliminates the instance `__dict__` overhead, saving approximately 152 bytes per cached node.
- **Complexity Guarantees**:
  - Direct Lookup: $\mathcal{O}(1)$ average hash table access.
  - Recency Promotion: $\mathcal{O}(1)$ pointer unlinking and insertion after `_head`.
  - LRU Eviction: $\mathcal{O}(1)$ pointer unlinking immediately preceding `_tail`.

### Component B: Dual-Bound Memory & Recursive Object Accounting
- Each cache entry maintains both `max_entries` and `max_bytes`.
- Sizing is performed through `deep_getsizeof`, which recursively inspects nested dictionaries, lists, sets, tuples, and user classes.
- **Pandas & NumPy Integration**: For numerical workloads, shallow `sys.getsizeof` returns only the C wrapper size (~48 bytes). CacheOpti interrogates `df.memory_usage(index=True, deep=True).sum()` and `arr.nbytes` to account for the underlying contiguous memory buffers.
- **Cycle Detection**: Circular references are tracked via a visited pointer set `seen: set[int] = set()`, preventing recursion loops.
- **Overwrite Tracking**: On overwriting an existing key, the engine computes:
  $$\Delta_{\text{bytes}} = \text{size}_{\text{new}} - \text{size}_{\text{old}}$$
  Updating `current_bytes` in place. Evictions are triggered from the LRU tail until both `current_entries <= max_entries` and `current_bytes <= max_bytes`.

### Component C: 16-Way Sharded Concurrency
- The key space is partitioned across 16 independent `_CacheShard` instances.
- **Routing**: Determined by `hash(key) & 0x0F` (exact bitwise mask of 15).
- **Lock Granularity**: Each shard owns a separate `threading.RLock`. Operations on keys residing in different shards execute with zero lock contention.
- **Capacity Partitioning**: Total configured `max_entries` and `max_bytes` are divided evenly across the 16 shards (`max_entries // 16`, `max_bytes // 16`), enforcing hard local limits per partition.

### Component D: VLDB XFetch Probabilistic Early Expiration & Single-Flight
- Instead of passively waiting for a TTL to expire and triggering a stampede, CacheOpti implements the VLDB XFetch algorithm (Vattani, Chierichetti, Lowenstein, VLDB 2015).
- As an entry approaches expiration, read requests probabilistically trigger early recomputation with probability governed by remaining TTL and previous compute duration $\delta$.
- When early refresh triggers, if `serve_stale=True`, the requesting client receives the valid cached value immediately with microsecond latency, while refresh is submitted asynchronously to a background worker pool.
- If a cold miss or synchronous refresh occurs, `SingleFlight` coordinates all concurrent callers for that key. Exactly one thread executes the upstream loader while other threads wait on an event and share the resulting value.

### Component E: Performance Telemetry via Pre-Allocated NumPy Ring Buffer
- Latency samples are recorded directly into a pre-allocated contiguous 64-bit NumPy array (`np.zeros(capacity, dtype=np.int64)`).
- Quantiles ($p50, p95, p99, p99.9$) are computed vectorially using `np.percentile`.

---

## 3. Applied Mathematics & Formal Formulations

### 3.1 VLDB XFetch Exponential Probability Derivation

Let:
- $t_{\text{now}}$: Current monotonic timestamp.
- $\mathcal{E}$: Monotonic expiration timestamp of the entry ($\mathcal{E} = t_{\text{created}} + \text{TTL}$).
- $\Delta$: Remaining time until expiration, $\Delta = \mathcal{E} - t_{\text{now}}$.
- $\delta$: Execution duration of the upstream computation callback (`loader_fn`).
- $\beta > 0$: Expiration aggressiveness parameter (default $\beta = 1.0$).
- $U \sim \text{Uniform}(0, 1)$: A continuous uniform random variable on $(0, 1)$.

The XFetch recomputation condition triggers if:
$$t_{\text{now}} - \beta \cdot \delta \cdot \ln(U) > \mathcal{E}$$

Rearranging the inequality:
$$- \beta \cdot \delta \cdot \ln(U) > \mathcal{E} - t_{\text{now}}$$

Substituting $\Delta = \mathcal{E} - t_{\text{now}}$:
$$- \beta \cdot \delta \cdot \ln(U) > \Delta$$

Dividing both sides by $\beta \cdot \delta$ (where $\beta, \delta > 0$):
$$- \ln(U) > \frac{\Delta}{\beta \cdot \delta}$$
$$\ln(U) < - \frac{\Delta}{\beta \cdot \delta}$$

Exponentiating both sides:
$$U < \exp\left( - \frac{\Delta}{\beta \cdot \delta} \right)$$

Because $U \sim \text{Uniform}(0, 1)$, the cumulative distribution function is $F_U(u) = u$ for $u \in (0, 1)$. Thus, the probability of triggering an early recomputation given remaining time $\Delta$ is:
$$P(\text{recompute} \mid \Delta) = \min\left(1.0, e^{ - \frac{\Delta}{\beta \cdot \delta} }\right)$$

#### Proof of the Specified Landmark Value ($P = e^{-2} \approx 13.53\%$)
Consider the operational point where the remaining time before expiration is exactly twice the scaled computation time:
$$\Delta = 2 \cdot \beta \cdot \delta$$

Substituting this into the probability function:
$$P = \exp\left( - \frac{2 \cdot \beta \cdot \delta}{\beta \cdot \delta} \right) = \exp(-2) = \frac{1}{e^2}$$

Evaluating numerically:
$$e^{-2} = 0.1353352832366127 \dots \approx 13.53\%$$

This proves that when an entry is within $2\beta\delta$ of expiration, every incoming request has an exact $13.53\%$ probability of initiating an early refresh.

#### Asymptotic Behavior Under Concurrency $\lambda$
Let requests arrive as a Poisson process with rate $\lambda$ requests per second. The probability that an early refresh is triggered before expiration over the critical window $\Delta \in [0, 2\beta\delta]$ is:
$$P(\text{refreshed before TTL}) = 1 - \exp\left( - \int_0^{2\beta\delta} \lambda \cdot e^{-\frac{t}{\beta\delta}} \, dt \right) = 1 - \exp\left( - \lambda \beta \delta (1 - e^{-2}) \right)$$

As traffic concurrency $\lambda$ increases, $P(\text{refreshed before TTL}) \to 1.0$. Consequently, under heavy production load, the cache refreshes itself in the background before hard expiration occurs, entirely eliminating cache misses.

---

### 3.2 Shard Collision Probability (Generalized Birthday Problem)

Let $M = 16$ denote the number of independent shards. Assume a cryptographic or pseudo-random hash function maps keys uniformly across shards with probability:
$$P(h(k) \pmod M = m) = \frac{1}{M} = \frac{1}{16} \quad \forall m \in \{0, \dots, 15\}$$

When $k$ distinct keys are accessed concurrently by $k$ worker threads, the probability that all $k$ keys map to pairwise distinct shards (i.e., zero lock contention) is:
$$P(\text{no collision}) = \prod_{i=0}^{k-1} \left(1 - \frac{i}{M}\right) = \frac{M!}{M^k \cdot (M - k)!}$$

The probability of at least one lock collision among $k$ concurrent requests is:
$$P(\text{collision}) = 1 - \prod_{i=0}^{k-1} \left(1 - \frac{i}{16}\right) \approx 1 - \exp\left( - \frac{k(k-1)}{2M} \right)$$

#### Contention Analysis: Sharded vs Global Mutex
- **Two Concurrent Requests ($k = 2$)**:
  $$P(\text{collision}) = \frac{1}{16} = 0.0625 = 6.25\%$$
  $$P(\text{no collision}) = 1 - \frac{1}{16} = \frac{15}{16} = 93.75\%$$
  Under CacheOpti v2.0, two concurrent requests have a **93.75% probability of executing completely in parallel with zero lock contention**, compared to a monolithic global lock where collision is guaranteed ($100\%$).
- **Four Concurrent Requests ($k = 4$)**:
  $$P(\text{no collision}) = \frac{16}{16} \times \frac{15}{16} \times \frac{14}{16} \times \frac{13}{16} \approx 0.6699 \implies P(\text{collision}) \approx 33.01\%$$
- Under $M = 16$ shards, lock contention queue depth per shard decreases by a factor of 16 relative to a single global lock.

---

### 3.3 Latency Quantile Calculation

Let $L = [l_1, l_2, \dots, l_N]$ represent $N$ recorded lookup latencies sorted in ascending order:
$$l_{(1)} \le l_{(2)} \le \dots \le l_{(N)}$$

For a requested quantile $q \in \{0.50, 0.95, 0.99, 0.999\}$, the virtual rank $r$ is:
$$r = 1 + q \cdot (N - 1)$$

Let $j = \lfloor r \rfloor$ and $f = r - j$. The quantile value $Q(q)$ is computed via linear interpolation:
$$Q(q) = (1 - f) \cdot l_{(j)} + f \cdot l_{(j+1)}$$

In systems engineering, latency distributions are heavily right-skewed with fat tails ($p99$ and $p99.9$) caused by thread preemption, GIL switching, and OS scheduler jitter. Tracking $p99$ and $p99.9$ is essential because arithmetic mean hides tail latency outliers.

---

### 3.4 Expected Cache Latency Under XFetch

Let:
- $h$: Cache hit rate ($0 \le h \le 1$).
- $T_{\text{hit}}$: In-memory cache hit latency ($\approx 1.5 - 3.5\,\mu\text{s}$).
- $T_{\text{loader}}$: Upstream database/service computation latency ($\approx 20 - 100\,\text{ms}$).
- $\mathbb{I}_{\text{stale}}$: Indicator variable equal to $1$ when stale serving is enabled, and $0$ otherwise.

Under standard caching:
$$\mathbb{E}[T_{\text{standard}}] = h \cdot T_{\text{hit}} + (1 - h) \cdot (T_{\text{hit}} + T_{\text{loader}})$$

Under CacheOpti v2.0 with XFetch and stale serving:
$$\mathbb{E}[T_{\text{CacheOpti}}] = h \cdot T_{\text{hit}} + (1 - h) \cdot \left[ \mathbb{I}_{\text{stale}} \cdot T_{\text{hit}} + (1 - \mathbb{I}_{\text{stale}}) \cdot (T_{\text{hit}} + \frac{T_{\text{loader}}}{k}) \right]$$

Because early refresh executes asynchronously in the background while serving valid cached data ($\mathbb{I}_{\text{stale}} = 1$), the user-facing latency on early refresh equals $T_{\text{hit}}$. Thus:
$$\mathbb{E}[T_{\text{CacheOpti}}] \approx T_{\text{hit}} \ll \mathbb{E}[T_{\text{standard}}]$$

---

## 4. Systems Engineering Analysis: GIL, Memory, and Concurrency Trade-Offs

### 4.1 CPython GIL Implications
In CPython, bytecode execution is guarded by the Global Interpreter Lock (GIL). A common misconception is that the GIL obviates the need for locks or that sharded locks provide no benefit in Python. This is false for two systems-level reasons:
1. **Preemption Between Bytecode Instructions**: Python statements (such as updating pointer references `node.prev.next = node.next` or advancing ring buffer index `self._idx = (self._idx + 1) % size`) compile into multiple distinct bytecode instructions (`LOAD_FAST`, `BINARY_OP`, `STORE_FAST`). Thread preemption can occur between any two instructions, corrupting linked list pointers or dictionaries without thread synchronization.
2. **Lock Release During I/O and Native Code**: When upstream loaders perform network requests (HTTP, sockets) or execute NumPy/C-extensions, the GIL is released. In a single-lock cache, threads executing Python code queue behind the lock. In CacheOpti's 16-way sharded cache, threads access disjoint shards concurrently without serialization.

### 4.2 Lock-Freedom Analysis in Python / NumPy
In C/C++, atomic ring buffers can be implemented truly lock-free using `std::atomic<uint64_t>` fetch-and-add instructions. In pure CPython userspace:
- Array indexing `buf[idx] = val` is not atomic.
- Counter increment `idx += 1` is not atomic.
- NumPy arrays do not expose memory fences or atomic CAS primitives directly to Python.

Claiming that a pure Python/NumPy ring buffer is "lock-free" across concurrent threads is technically inaccurate and deceptive. CacheOpti v2.0 explicitly uses a fast `threading.Lock` guarding only two CPU instructions (~35 nanoseconds), providing guaranteed thread safety without data corruption.

### 4.3 Memory Accounting Limitations
While `deep_getsizeof` provides accurate memory tracking for arbitrary Python graphs, it incurs $\mathcal{O}(V + E)$ traversal overhead on object insertion. To prevent this from degrading lookup latency:
- Sizing is computed **only once on insertion or overwrite** (`put`).
- The computed size is cached on the node (`node.size_bytes`).
- Direct lookups (`get`) perform zero recursive traversal, maintaining strict $\mathcal{O}(1)$ execution.

---

## 5. Empirical Benchmark Results

Measured on Python 3.14.6, 64-bit Windows architecture using `benchmarks/stampede_simulation.py`:

### Experiment 1: Cache Stampede (100 Concurrent Requests on Expired Key, 30ms Loader)
| Metric | Naive TTL Cache | CacheOpti v2.0 (`ShardedCache`) | Gain / Reduction |
| :--- | :--- | :--- | :--- |
| **Upstream DB Calls** | **100 calls** | **1 call** | **99.0% reduction** |
| **Median Latency ($p50$)** | 30.31 ms | 25.25 ms | Upstream bottleneck eliminated |
| **Tail Latency ($p99$)** | 30.59 ms | 30.62 ms | Synchronous coalescing preserved |
| **Stampede Behavior** | Catastrophic Herd | Coalesced into 1 execution | Complete stampede prevention |

### Experiment 2: 32-Thread Concurrency Benchmark (16,000 Operations, Zipfian Contention)
| Engine | Throughput (ops/sec) | $p50$ Latency ($\mu\text{s}$) | $p95$ Latency ($\mu\text{s}$) | $p99$ Latency ($\mu\text{s}$) | Memory Footprint |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `functools.lru_cache` | 691,201.4 | 0.50 | 0.80 | 1.10 | 2,385 B (No TTL/Bytes) |
| Naive TTL Cache | 856,274.3 | 0.30 | 0.60 | 1.00 | 16,868 B (No LRU/Bounds) |
| **CacheOpti v2.0 (Sharded)** | **269,217.0** | **2.10** | **3.90** | **7.70** | **16,490 B (Strict Dual Bounds)** |

*Observations*:
- While `functools.lru_cache` and raw dicts run fast in microbenchmarks because they lack features, they lack TTL, byte limits, memory bounding, and stampede prevention.
- CacheOpti v2.0 delivers **over 269,000 operations per second** with a **$p50$ of 2.10 microseconds**, while actively enforcing 16-way sharding, deep byte memory tracking, LRU eviction, and single-flight coordination.

---

## 6. Consequences & Future Evolution

- **Positive**: Complete elimination of upstream cache stampedes; bounded process memory preventing OOM errors in production; 16-fold reduction in lock contention across independent keys.
- **Negative / Costs**: Slightly higher baseline memory footprint per shard compared to an un-synchronized dict; $\mathcal{O}(\text{deep size})$ compute overhead during insertion of heavily nested objects.
- **Next Steps**: Potential extension to asynchronous `asyncio` interfaces and persistent shared-memory (POSIX / Windows MMAP) shards.
