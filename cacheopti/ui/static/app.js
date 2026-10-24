/**
 * CacheCraft / CacheOpti - Modern Performance Studio Frontend Logic
 */

// Global Chart Instances
let latencyChartInstance = null;
let sweepChartInstance = null;
let simInterval = null;

// Tab Switching
function switchTab(tabId) {
  const tabs = ['inspector', 'explorer', 'benchmark', 'simulator', 'settings'];
  tabs.forEach(t => {
    const panel = document.getElementById(`panel-${t}`);
    const btn = document.getElementById(`tab-${t}`);
    if (t === tabId) {
      panel.classList.remove('hidden');
      btn.classList.add('active');
    } else {
      panel.classList.add('hidden');
      btn.classList.remove('active');
    }
  });

  if (tabId === 'benchmark' && latencyChartInstance) {
    latencyChartInstance.resize();
    if (sweepChartInstance) sweepChartInstance.resize();
  }
}

// Global Clear Cache Action
async function clearCache() {
  try {
    await fetch('/api/clear', { method: 'POST' });
    fetchState();
    fetchEntries();
    fetchEvents();
  } catch (err) {
    console.error('Error clearing cache:', err);
  }
}

// State & Telemetry Fetching
async function fetchState() {
  try {
    const res = await fetch('/api/state');
    const data = await res.json();
    if (!data.cache) return;

    const c = data.cache;
    const s = data.service;

    // HUD KPIs
    document.getElementById('kpi-hit-rate').textContent = `${c.hit_rate_pct}%`;
    document.getElementById('kpi-occupancy').textContent = `${c.occupancy} / ${c.capacity}`;
    document.getElementById('kpi-avoided').textContent = s.estimated_external_requests_avoided || 0;

    // Engine Telemetry Card
    document.getElementById('lbl-active-policy').textContent = c.policy;
    document.getElementById('lbl-active-cap').textContent = c.capacity;
    document.getElementById('stat-lookups').textContent = c.total_lookups;
    document.getElementById('stat-hits').textContent = c.hits;
    document.getElementById('stat-misses').textContent = c.misses;
    document.getElementById('stat-evictions').textContent = c.evictions;
    document.getElementById('stat-expirations').textContent = c.expirations;
    document.getElementById('stat-overhead').textContent = `${c.avg_lookup_overhead_us} μs`;
  } catch (err) {
    console.error('Error fetching state:', err);
  }
}

// Doubly Linked List Visualizer Rendering
async function fetchEntries() {
  try {
    const res = await fetch('/api/entries');
    const data = await res.json();
    const entries = data.entries || [];
    const container = document.getElementById('dll-container');
    if (!container) return;

    if (entries.length === 0) {
      container.innerHTML = `
        <div class="flex items-center gap-3 w-full justify-center py-6 text-slate-500 text-xs mono">
          <span class="px-2.5 py-1 rounded bg-slate-800 text-cyan-400 font-semibold">[HEAD Sentinel]</span>
          <span class="text-purple-400">&larr; &rarr;</span>
          <span class="italic text-slate-500">(Cache Storage is Empty)</span>
          <span class="text-purple-400">&larr; &rarr;</span>
          <span class="px-2.5 py-1 rounded bg-slate-800 text-rose-400 font-semibold">[TAIL Sentinel]</span>
        </div>
      `;
      return;
    }

    let html = `
      <div class="flex-shrink-0 px-2.5 py-2 rounded-lg bg-slate-900 border border-cyan-800/80 text-[11px] mono text-cyan-300 font-bold flex flex-col items-center">
        <span>[HEAD]</span>
        <span class="text-[9px] text-cyan-500">MRU</span>
      </div>
      <div class="pointer-arrow">&larr;&rarr;</div>
    `;

    entries.forEach((entry, idx) => {
      const isMRU = idx === 0;
      const isLRU = idx === entries.length - 1;
      const cardClass = isMRU ? 'mru-head' : (isLRU ? 'lru-tail' : '');
      const priorityLabel = isMRU 
        ? '<span class="text-[9px] px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">MRU HEAD</span>' 
        : (isLRU ? '<span class="text-[9px] px-1.5 py-0.2 rounded bg-rose-950 text-rose-300 border border-rose-800">LRU TAIL</span>' : '');

      // TTL Progress bar calculation
      const ttlSec = entry.ttl_seconds || 30.0;
      const remSec = entry.remaining_ttl !== null ? entry.remaining_ttl : ttlSec;
      const pct = Math.max(0, Math.min(100, (remSec / ttlSec) * 100));
      const barColor = pct > 40 ? 'bg-emerald-400' : (pct > 15 ? 'bg-amber-400' : 'bg-rose-500');

      const title = entry.display_title || entry.key;
      const subtitle = entry.display_subtitle || '';
      
      let cleanKey = entry.key;
      if (cleanKey.includes(':')) {
        const parts = cleanKey.split(':');
        cleanKey = parts.slice(0, 3).join(':');
      }

      html += `
        <div class="node-card ${cardClass} flex-shrink-0">
          <div class="flex items-center justify-between gap-2 mb-1">
            <span class="font-bold text-xs text-white truncate max-w-[130px] flex items-center gap-1" title="${title}">
              ${title}
            </span>
            <span class="text-[10px] mono text-cyan-300 bg-cyan-950/80 px-1.5 py-0.5 rounded border border-cyan-800/60 flex-shrink-0">
              #${entry.access_count} hit${entry.access_count === 1 ? '' : 's'}
            </span>
          </div>

          <div class="text-[11px] text-slate-300 font-medium truncate mb-1" title="${subtitle}">
            ${subtitle}
          </div>

          <div class="mono text-[10px] text-slate-500 truncate mb-2" title="${entry.key}">
            key: ${cleanKey}
          </div>

          <div class="flex items-center justify-between text-[10px]">
            <span class="text-slate-400 mono font-medium">${remSec !== null ? remSec.toFixed(1) + 's left' : 'no TTL'}</span>
            ${priorityLabel}
          </div>

          <div class="ttl-progress-container">
            <div class="ttl-progress-fill ${barColor}" style="width: ${pct}%;"></div>
          </div>
        </div>
      `;

      if (idx < entries.length - 1) {
        html += `<div class="pointer-arrow">&larr;&rarr;</div>`;
      }
    });

    html += `
      <div class="pointer-arrow">&larr;&rarr;</div>
      <div class="flex-shrink-0 px-2.5 py-2 rounded-lg bg-slate-900 border border-rose-800/80 text-[11px] mono text-rose-300 font-bold flex flex-col items-center">
        <span>[TAIL]</span>
        <span class="text-[9px] text-rose-500">LRU</span>
      </div>
    `;

    container.innerHTML = html;
  } catch (err) {
    console.error('Error fetching entries:', err);
  }
}

// Event Audit Log Fetching
async function fetchEvents() {
  try {
    const res = await fetch('/api/events');
    const data = await res.json();
    const events = data.events || [];
    const container = document.getElementById('event-log-container');
    if (!container) return;

    if (events.length === 0) {
      container.innerHTML = `<div class="text-slate-600 italic">No events logged yet. Perform operations to observe events.</div>`;
      return;
    }

    container.innerHTML = events.slice().reverse().map(e => {
      let badgeClass = 'text-slate-400 bg-slate-800';
      if (e.type === 'HIT') badgeClass = 'text-emerald-400 bg-emerald-950/80 border border-emerald-800';
      else if (e.type === 'MISS') badgeClass = 'text-amber-400 bg-amber-950/80 border border-amber-800';
      else if (e.type === 'EVICT') badgeClass = 'text-rose-400 bg-rose-950/80 border border-rose-800';
      else if (e.type === 'EXPIRE') badgeClass = 'text-purple-400 bg-purple-950/80 border border-purple-800';

      const timeStr = new Date(e.timestamp * 1000).toLocaleTimeString();
      return `
        <div class="flex items-start gap-2 py-0.5 border-b border-slate-900/60">
          <span class="text-slate-500 text-[10px]">${timeStr}</span>
          <span class="text-[10px] font-bold px-1.5 py-0.2 rounded ${badgeClass}">${e.type}</span>
          <span class="text-slate-200 font-semibold truncate max-w-[130px]">${e.key}</span>
          <span class="text-slate-400 truncate text-[11px]">${e.details}</span>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Error fetching events:', err);
  }
}

// Country Explorer Functions
async function executeCountrySearch() {
  const input = document.getElementById('input-country-search');
  const name = input.value.trim();
  if (!name) return;

  const useCache = document.getElementById('chk-use-cache').checked;
  const card = document.getElementById('country-result-card');

  try {
    const res = await fetch('/api/country/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, use_cache: useCache }),
    });
    const result = await res.json();

    if (result.is_error) {
      alert(`Lookup Error: ${result.error_message}`);
      return;
    }

    const d = result.data;
    card.classList.remove('hidden');

    // Populate Data Fields
    document.getElementById('country-flag-icon').textContent = d.flag_emoji || '🌐';
    document.getElementById('country-name-title').textContent = d.common_name;
    document.getElementById('country-official-name').textContent = d.official_name;
    document.getElementById('country-latency-val').textContent = `${result.latency_ms.toFixed(2)} ms`;

    // Source Badge
    const badge = document.getElementById('country-source-badge');
    if (result.from_cache) {
      badge.textContent = 'CACHE HIT';
      badge.className = 'text-xs px-2.5 py-0.5 rounded font-medium badge-hit';
    } else {
      badge.textContent = 'NETWORK FETCH';
      badge.className = 'text-xs px-2.5 py-0.5 rounded font-medium badge-miss';
    }

    // Waterfall Breakdown
    const netTime = result.network_latency_ms || 0;
    const cacheTimeUs = result.lookup_overhead_us || 0;
    const cacheTimeMs = cacheTimeUs / 1000.0;

    document.getElementById('lbl-net-time').textContent = `${netTime.toFixed(2)} ms`;
    document.getElementById('lbl-cache-time').textContent = `${cacheTimeUs.toFixed(1)} μs`;

    const totalWaterfall = Math.max(0.001, netTime + cacheTimeMs);
    const netPct = (netTime / totalWaterfall) * 100;
    const cachePct = (cacheTimeMs / totalWaterfall) * 100;

    document.getElementById('bar-waterfall-net').style.width = `${netPct}%`;
    document.getElementById('bar-waterfall-cache').style.width = `${cachePct}%`;

    const speedupBadge = document.getElementById('country-speedup-badge');
    if (result.from_cache && netTime === 0) {
      speedupBadge.textContent = 'Retrieved in < 0.05ms';
    } else {
      speedupBadge.textContent = result.from_cache ? 'Accelerated' : 'Uncached Network Call';
    }

    // Detail Grid
    document.getElementById('val-capital').textContent = d.capital || 'N/A';
    document.getElementById('val-region').textContent = `${d.region} / ${d.subregion}`;
    document.getElementById('val-population').textContent = Number(d.population).toLocaleString();
    document.getElementById('val-currencies').textContent = d.currencies.join(', ') || 'N/A';

    fetchState();
    fetchEntries();
    fetchEvents();
  } catch (err) {
    console.error('Error searching country:', err);
  }
}

function quickCountry(name) {
  document.getElementById('input-country-search').value = name;
  executeCountrySearch();
}

// Benchmark Lab Functions
async function runBenchmark() {
  const workload = document.getElementById('bench-workload').value;
  const numOps = parseInt(document.getElementById('bench-ops').value, 10);
  const cap = parseInt(document.getElementById('bench-cap').value, 10);
  const btn = document.getElementById('btn-run-benchmark');

  btn.disabled = true;
  btn.innerHTML = `<span>⏳ Benchmarking...</span>`;

  try {
    const res = await fetch('/api/benchmark/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workload_type: workload,
        num_ops: numOps,
        capacity: cap,
      }),
    });
    const payload = await res.json();
    const r = payload.result;
    const sweep = payload.capacity_sweep || [];

    document.getElementById('bench-results-container').classList.remove('hidden');

    // KPI Cards
    document.getElementById('res-speedup').textContent = `${r.speedup_factor}x`;
    document.getElementById('res-saved').textContent = `${r.observed_time_saved_ms} ms`;
    document.getElementById('res-hit-rate').textContent = `${r.hit_rate_pct}%`;
    document.getElementById('res-hit-count').textContent = `${r.hits} hits / ${r.misses} misses`;
    document.getElementById('res-overhead').textContent = `${r.avg_lookup_overhead_us} μs`;

    // Detailed Stats Table
    document.getElementById('tbl-uncached-total').textContent = `${r.uncached_total_ms} ms`;
    document.getElementById('tbl-cached-total').textContent = `${r.cached_total_ms} ms`;
    document.getElementById('tbl-diff-total').textContent = `-${r.observed_time_saved_ms} ms`;

    document.getElementById('tbl-uncached-mean').textContent = `${r.uncached_mean_ms} ms`;
    document.getElementById('tbl-cached-mean').textContent = `${r.cached_mean_ms} ms`;
    document.getElementById('tbl-diff-mean').textContent = `${(r.uncached_mean_ms / Math.max(0.001, r.cached_mean_ms)).toFixed(1)}x faster`;

    document.getElementById('tbl-uncached-median').textContent = `${r.uncached_median_ms} ms`;
    document.getElementById('tbl-cached-median').textContent = `${r.cached_median_ms} ms`;
    document.getElementById('tbl-diff-median').textContent = `${(r.uncached_median_ms / Math.max(0.001, r.cached_median_ms)).toFixed(1)}x faster`;

    document.getElementById('tbl-uncached-p95').textContent = `${r.uncached_p95_ms} ms`;
    document.getElementById('tbl-cached-p95').textContent = `${r.cached_p95_ms} ms`;
    document.getElementById('tbl-diff-p95').textContent = `${(r.uncached_p95_ms / Math.max(0.001, r.cached_p95_ms)).toFixed(1)}x faster`;

    // Render Chart 1: Latency Samples
    renderLatencyChart(r.samples_uncached, r.samples_cached);

    // Render Chart 2: Capacity Sweep
    renderSweepChart(sweep);

    fetchState();
    fetchEntries();
    fetchEvents();
  } catch (err) {
    console.error('Error running benchmark:', err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span>🚀 Run Experiment</span>`;
  }
}

function renderLatencyChart(uncachedSamples, cachedSamples) {
  const ctx = document.getElementById('chart-latency').getContext('2d');
  if (latencyChartInstance) latencyChartInstance.destroy();

  const labels = uncachedSamples.map((_, i) => `#${i + 1}`);

  latencyChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Uncached Latency (ms)',
          data: uncachedSamples,
          borderColor: '#f43f5e',
          backgroundColor: 'rgba(244, 63, 94, 0.1)',
          borderWidth: 2,
          tension: 0.2,
          pointRadius: 2,
        },
        {
          label: 'Cached Latency (ms)',
          data: cachedSamples,
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.1)',
          borderWidth: 2,
          tension: 0.2,
          pointRadius: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { grid: { color: '#1e293b' }, ticks: { color: '#64748b' } },
        y: { grid: { color: '#1e293b' }, ticks: { color: '#64748b' } },
      },
      plugins: {
        legend: { labels: { color: '#94a3b8' } },
      },
    },
  });
}

function renderSweepChart(sweepData) {
  const ctx = document.getElementById('chart-sweep').getContext('2d');
  if (sweepChartInstance) sweepChartInstance.destroy();

  const labels = sweepData.map(d => `Cap: ${d.capacity}`);
  const hitRates = sweepData.map(d => d.hit_rate_pct);

  sweepChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Hit Rate %',
          data: hitRates,
          backgroundColor: '#a855f7',
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { grid: { display: false }, ticks: { color: '#64748b' } },
        y: { grid: { color: '#1e293b' }, ticks: { color: '#64748b' }, min: 0, max: 100 },
      },
      plugins: {
        legend: { labels: { color: '#94a3b8' } },
      },
    },
  });
}

// Simulator Functions
async function initSimulatorUI() {
  try {
    const res = await fetch('/api/sim/state');
    const data = await res.json();
    renderSimSequence(data.workload, data.index);
  } catch (err) {
    console.error('Error fetching sim state:', err);
  }
}

function renderSimSequence(workload, currentIndex) {
  const track = document.getElementById('sim-sequence-track');
  if (!track) return;

  track.innerHTML = workload.map((k, idx) => {
    const isCurrent = idx === currentIndex;
    const isPast = idx < currentIndex;
    const style = isCurrent 
      ? 'bg-cyan-500 text-black font-bold ring-2 ring-cyan-300' 
      : (isPast ? 'bg-slate-800 text-slate-400' : 'bg-slate-900 text-slate-300 border border-slate-700');
    return `<span class="px-2.5 py-1 rounded-md ${style}">${k}</span>`;
  }).join('<span class="text-slate-600">&rarr;</span>');
}

async function simStep() {
  try {
    const res = await fetch('/api/sim/step', { method: 'POST' });
    const data = await res.json();
    const r = data.step_record;

    const explain = document.getElementById('sim-explanation-text');
    if (r.was_hit) {
      explain.innerHTML = `<span class="text-emerald-400 font-bold">[CACHE HIT]</span> Accessed key <b>${r.key}</b>. Node unlinked and promoted to <b>MRU Head</b> in O(1) time.`;
    } else {
      explain.innerHTML = `<span class="text-amber-400 font-bold">[CACHE MISS]</span> Key <b>${r.key}</b> was not in cache. Result computed and inserted at <b>MRU Head</b>. (If full, LRU tail evicted).`;
    }

    const stateRes = await fetch('/api/sim/state');
    const simState = await stateRes.json();
    renderSimSequence(simState.workload, data.next_index);

    fetchState();
    fetchEntries();
    fetchEvents();
  } catch (err) {
    console.error('Error executing sim step:', err);
  }
}

function simAutoPlay() {
  const btn = document.getElementById('btn-sim-auto');
  if (simInterval) {
    clearInterval(simInterval);
    simInterval = null;
    btn.textContent = '🔄 Auto Play';
    btn.classList.remove('bg-rose-600');
  } else {
    simInterval = setInterval(simStep, 1000);
    btn.textContent = '⏸ Pause';
    btn.classList.add('bg-rose-600');
  }
}

async function simReset() {
  if (simInterval) {
    clearInterval(simInterval);
    simInterval = null;
    document.getElementById('btn-sim-auto').textContent = '🔄 Auto Play';
  }
  await fetch('/api/sim/reset', { method: 'POST' });
  document.getElementById('sim-explanation-text').textContent = 'Simulator reset. Click "Next Access" to begin.';
  initSimulatorUI();
  fetchState();
  fetchEntries();
  fetchEvents();
}

// Settings
async function saveConfiguration() {
  const cap = parseInt(document.getElementById('cfg-capacity').value, 10);
  const ttl = parseFloat(document.getElementById('cfg-ttl').value);
  const pol = document.getElementById('cfg-policy').value;
  const apiKey = document.getElementById('cfg-api-key').value;
  const authType = document.getElementById('cfg-auth-type').value;
  const baseUrl = document.getElementById('cfg-base-url').value;

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        capacity: cap,
        default_ttl: ttl,
        policy: pol,
        api_key: apiKey,
        auth_type: authType,
        base_url: baseUrl,
      }),
    });
    if (res.ok) {
      alert('Configuration successfully saved and applied!');
      fetchState();
      fetchEntries();
    }
  } catch (err) {
    console.error('Error saving config:', err);
  }
}

function toggleApiKeyVisibility() {
  const inp = document.getElementById('cfg-api-key');
  const eye = document.getElementById('eye-icon');
  if (inp.type === 'password') {
    inp.type = 'text';
    eye.textContent = '🙈';
  } else {
    inp.type = 'password';
    eye.textContent = '👁️';
  }
}

// Periodic Telemetry Poll (every 1.5 seconds)
setInterval(() => {
  fetchState();
  fetchEntries();
  fetchEvents();
}, 1500);

// Initialize on Load
window.addEventListener('DOMContentLoaded', () => {
  fetchState();
  fetchEntries();
  fetchEvents();
  initSimulatorUI();
});
