import time
from collections import OrderedDict

def expensive_calculation(n):
    total = 0
    for i in range(500000):
        total += (i ^ n)
    return total

class TTLCache:
    def __init__(self, capacity=3, ttl_seconds=2.0):
        self.capacity = capacity
        self.ttl = ttl_seconds
        # Stores key -> (value, creation_timestamp)
        self.cache = OrderedDict()

    def get(self, key):
        current_time = time.time()

        if key in self.cache:
            value, timestamp = self.cache[key]
            age = current_time - timestamp

            # 1. Check if the entry has expired
            if age <= self.ttl:
                print(f"[HIT]  Key {key} found (Age: {age:.2f}s <= TTL: {self.ttl}s)")
                self.cache.move_to_end(key)  # Refresh LRU position
                return value
            
            # Entry expired: remove stale data
            print(f"[EXPIRED] Key {key} expired (Age: {age:.2f}s > TTL: {self.ttl}s). Recomputing...")
            del self.cache[key]
        else:
            print(f"[MISS] Key {key} not found. Computing...")

        # 2. Compute fresh result on cache miss or expiration
        val = expensive_calculation(key)

        # 3. Handle capacity limits before storing
        if len(self.cache) >= self.capacity:
            evicted_key, _ = self.cache.popitem(last=False)
            print(f"[EVICT] Cache full. Evicted oldest entry: {evicted_key}")

        # 4. Save result with current timestamp
        self.cache[key] = (val, time.time())
        return val

# Initialize a cache with capacity 3 and a 2-second lifetime
ttl_cache = TTLCache(capacity=3, ttl_seconds=2.0)

print("--- 1. Initial Access (Misses) ---")
ttl_cache.get(1)
ttl_cache.get(2)

print("\n--- 2. Immediate Re-access (Hits) ---")
ttl_cache.get(1)  # Retrieved instantly

print("\n--- 3. Waiting 2.5 seconds for entries to expire ---")
time.sleep(2.5)

ttl_cache.get(1)  # Miss due to expiration -> recalculated and timestamp refreshed

print("\n--- 4. Testing Capacity + Eviction with Fresh Items ---")
ttl_cache.get(2)  # Entry 2 was expired from before, recomputes
ttl_cache.get(3)  # Added (Cache now holds: 1, 2, 3)
ttl_cache.get(4)  # Cache full -> evicts key 1 (least recently used)