<template>
  <div class="signal-panel">
    <div class="header">
      <h3>Link Quality</h3>
      <span class="transport-tag" :class="'tag-' + store.linkTransport" :title="transportTooltip">
        {{ store.linkTransportLabel }}
      </span>
    </div>

    <div class="latency-row">
      <span class="latency-value" :style="{ color: quality.color }">
        {{ isConnected && latencyHistory.length ? Math.round(latencyMs) : '--' }}
      </span>
      <span class="latency-unit">ms</span>
      <span class="trend" :class="'trend-' + trend" :title="trendTooltip">{{ trendArrow }}</span>
    </div>

    <!-- Quality bar: full = fast link -->
    <div class="quality-bar">
      <div class="quality-fill" :style="{ width: qualityPct + '%', background: quality.color }"></div>
    </div>
    <div class="quality-label" :style="{ color: quality.color }">{{ quality.label }}</div>

    <!-- Rolling latency history (oldest → newest) -->
    <div class="sparkline">
      <div
        v-for="(s, i) in paddedHistory"
        :key="i"
        class="spark-bar"
        :class="{ lost: s.lost, empty: s.empty }"
        :style="s.style"
        :title="s.title"
      ></div>
    </div>

    <div class="stats">
      <div class="stat">
        <label>Avg</label>
        <span>{{ latencyHistory.length ? Math.round(latencyAvgMs) + ' ms' : '--' }}</span>
      </div>
      <div class="stat">
        <label>Jitter</label>
        <span>{{ latencyHistory.length ? Math.round(latencyJitterMs) + ' ms' : '--' }}</span>
      </div>
      <div class="stat">
        <label>Loss</label>
        <span :class="{ warn: latencyLossPct > 5 }">
          {{ latencyHistory.length ? latencyLossPct.toFixed(0) + ' %' : '--' }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useTelemetryStore } from '../stores/telemetry'

const SPARK_SLOTS = 40
const store = useTelemetryStore()
const {
  isConnected, latencyMs, latencyAvgMs, latencyJitterMs, latencyLossPct, latencyHistory,
} = storeToRefs(store)

const quality = computed(() => store.linkQuality)
const qualityPct = computed(() => store.linkQualityPct)
const trend = computed(() => store.linkTrend)

const trendArrow = computed(() =>
  trend.value === 'improving' ? '▲' : trend.value === 'degrading' ? '▼' : '■'
)
const trendTooltip = computed(() =>
  trend.value === 'improving' ? 'Latency improving'
    : trend.value === 'degrading' ? 'Latency degrading' : 'Latency stable'
)

const transportTooltip = computed(() => {
  const iface = store.linkIface ? ` via ${store.linkIface}` : ''
  return `${store.linkClientIp || 'client'} → ${store.linkServerIp || 'server'}${iface}`
})

// Right-aligned fixed-width sparkline; bars scale against a 500 ms ceiling.
const paddedHistory = computed(() => {
  const h = latencyHistory.value.slice(-SPARK_SLOTS)
  const pad = SPARK_SLOTS - h.length
  const slots = []
  for (let i = 0; i < pad; i++) slots.push({ empty: true, style: { height: '2px' }, title: '' })
  for (const v of h) {
    if (v === null) {
      slots.push({ lost: true, style: { height: '100%' }, title: 'No response' })
      continue
    }
    const pct = Math.max(8, Math.min(100, (v / 500) * 100))
    slots.push({
      style: { height: pct + '%', background: colorFor(v) },
      title: `${Math.round(v)} ms`,
    })
  }
  return slots
})

function colorFor(rtt) {
  if (rtt >= 1000) return '#e53935'
  if (rtt >= 400) return '#ff7043'
  if (rtt >= 150) return '#FFA500'
  if (rtt >= 60) return '#9ccc65'
  return '#00C851'
}
</script>

<style scoped>
.signal-panel {
  background: rgba(30, 30, 30, 0.95);
  color: #fff;
  padding: 12px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 195px;
  box-sizing: border-box;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

h3 {
  margin: 0;
  font-size: 0.85rem;
  color: #FFA500;
}

.transport-tag {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 2px 6px;
  border-radius: 10px;
  white-space: nowrap;
  background: #444;
  color: #ddd;
  border: 1px solid #666;
  cursor: help;
}

.tag-wifi {
  background: rgba(0, 200, 81, 0.18);
  color: #00C851;
  border-color: #00C851;
}

.tag-ethernet,
.tag-loopback {
  background: rgba(120, 180, 255, 0.18);
  color: #78b4ff;
  border-color: #78b4ff;
}

.tag-zerotier,
.tag-vpn {
  background: rgba(255, 165, 0, 0.18);
  color: #FFA500;
  border-color: #FFA500;
}

.latency-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.latency-value {
  font-family: monospace;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1;
}

.latency-unit {
  font-size: 0.7rem;
  color: #aaa;
}

.trend {
  margin-left: auto;
  font-size: 0.75rem;
  cursor: help;
}

.trend-improving { color: #00C851; }
.trend-degrading { color: #e53935; }
.trend-stable    { color: #888; }

.quality-bar {
  height: 8px;
  background: #333;
  border-radius: 4px;
  overflow: hidden;
}

.quality-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease, background 0.3s ease;
}

.quality-label {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-align: right;
}

.sparkline {
  display: flex;
  align-items: flex-end;
  gap: 1px;
  height: 28px;
  background: #262626;
  border-radius: 3px;
  padding: 2px;
}

.spark-bar {
  flex: 1;
  min-width: 1px;
  border-radius: 1px;
  background: #00C851;
}

.spark-bar.empty {
  background: #3a3a3a;
}

.spark-bar.lost {
  background: repeating-linear-gradient(
    45deg, #e53935, #e53935 2px, #7a1f1f 2px, #7a1f1f 4px
  );
}

.stats {
  display: flex;
  justify-content: space-between;
  gap: 4px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.stat label {
  font-size: 0.6rem;
  color: #888;
  text-transform: uppercase;
}

.stat span {
  font-size: 0.75rem;
  font-family: monospace;
  color: #ddd;
}

.stat span.warn {
  color: #e53935;
  font-weight: 700;
}
</style>
