<template>
  <div class="gnss-container">
    <div class="main-content">
      <div class="chart-controls">
        <label>Time Window:</label>
        <select v-model="timeWindow">
          <option :value="30">30s</option>
          <option :value="60">1 min</option>
          <option :value="120">2 min</option>
          <option :value="300">5 min</option>
        </select>
      </div>

      <!-- Latitude chart -->
      <div class="chart-wrapper">
        <Line :data="latChartData" :options="latChartOptions" />
      </div>

      <!-- Longitude chart -->
      <div class="chart-wrapper">
        <Line :data="lonChartData" :options="lonChartOptions" />
      </div>

      <!-- Altitude chart -->
      <div class="chart-wrapper">
        <Line :data="altChartData" :options="altChartOptions" />
      </div>
    </div>

    <div class="sidebar" :class="{ 'sim-mode': telemetry.dataSource === 'sim' }">
      <h3>GNSS Status</h3>

      <!-- Fix quality indicator -->
      <div class="fix-indicator" :class="fixClass">
        <div class="fix-dot"></div>
        <span class="fix-label">{{ fixLabel }}</span>
      </div>

      <div class="stat-group">
        <div class="stat-box">
          <h4>UTC Time</h4>
          <div class="value small">{{ telemetry.gnssUtcTime || '--' }}</div>
        </div>
        <div class="stat-box">
          <h4>UTC Date</h4>
          <div class="value small">{{ telemetry.gnssUtcDate || '--' }}</div>
        </div>
      </div>

      <h3 class="mt-3">Position</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Latitude</h4>
          <div class="value">{{ telemetry.lat?.toFixed(8) ?? '0.00000000' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Longitude</h4>
          <div class="value">{{ telemetry.lon?.toFixed(8) ?? '0.00000000' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Altitude</h4>
          <div class="value">{{ telemetry.gnssAlt?.toFixed(2) ?? '0.00' }} m</div>
        </div>
      </div>

      <h3 class="mt-3">Navigation</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>COG</h4>
          <div class="value">{{ telemetry.gnssCog?.toFixed(1) ?? '0.0' }}°</div>
        </div>
        <div class="stat-box">
          <h4>SOG</h4>
          <div class="value">{{ telemetry.gnssSogKnots?.toFixed(2) ?? '0.00' }} kn</div>
        </div>
        <div class="stat-box">
          <h4>Heading (Dual-Ant)</h4>
          <div class="value">{{ telemetry.gnssHeading?.toFixed(1) ?? '0.0' }}°</div>
        </div>
      </div>

      <h3 class="mt-3">Quality</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Fix Type</h4>
          <div class="value" :style="{ color: fixColor }">{{ fixLabel }}</div>
        </div>
        <div class="stat-box">
          <h4>Satellites</h4>
          <div class="value">{{ telemetry.gnssNumSats ?? 0 }}</div>
        </div>
        <div class="stat-box">
          <h4>HDOP</h4>
          <div class="value">{{ telemetry.gnssHdop?.toFixed(2) ?? '99.99' }} m</div>
        </div>
        <div class="stat-box">
          <h4>VDOP</h4>
          <div class="value">{{ telemetry.gnssVdop?.toFixed(2) ?? '99.99' }} m</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js'
import { Line } from 'vue-chartjs'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
)

const telemetry = useTelemetryStore()

const simSuffix = () => telemetry.dataSource === 'sim' ? ' (SIM)' : ''

const timeWindow = ref(120)

// --- Fix type helpers ---
const fixLabel = computed(() => {
  const fix = telemetry.gnssFixType
  const labels = { 0: 'No Fix', 1: 'GPS', 2: 'DGPS', 4: 'RTK Fix', 5: 'RTK Float' }
  return labels[fix] ?? `Unknown (${fix})`
})

const fixColor = computed(() => {
  const fix = telemetry.gnssFixType
  if (fix === 4) return '#00cc00'       // RTK Fix → green
  if (fix === 5) return '#FFA500'       // RTK Float → orange
  if (fix === 2) return '#ffdd00'       // DGPS → yellow
  if (fix === 1) return '#ffdd00'       // GPS → yellow
  return '#ff4444'                      // No fix → red
})

const fixClass = computed(() => {
  const fix = telemetry.gnssFixType
  if (fix === 4) return 'fix-rtk'
  if (fix === 5 || fix === 2) return 'fix-float'
  if (fix === 1) return 'fix-gps'
  return 'fix-none'
})

// --- Chart options ---
const chartBaseOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  elements: { point: { radius: 0 } },
  plugins: {
    legend: { labels: { color: 'white' } }
  },
  scales: {
    x: {
      ticks: { color: '#aaa', maxTicksLimit: 10 },
      grid: { color: '#333' }
    },
    y: {
      ticks: { color: '#aaa' },
      grid: { color: '#333' }
    }
  }
}

const latChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Latitude (°)', color: '#aaa' }
  }
}

const lonChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Longitude (°)', color: '#aaa' }
  }
}

const altChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Altitude (m)', color: '#aaa' }
  }
}

// --- Chart data (computed from store history — no setInterval needed) ---
const filteredHistory = computed(() => {
  const cutoff = Date.now() - (timeWindow.value * 1000)
  return telemetry.gnssHistory.filter(p => p.timeMs > cutoff)
})

const latChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    { label: 'Latitude' + simSuffix(), borderColor: '#33b5e5', data: filteredHistory.value.map(pt => pt.lat), borderWidth: 2, tension: 0.2, fill: false }
  ]
}))

const lonChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    { label: 'Longitude' + simSuffix(), borderColor: '#FFA500', data: filteredHistory.value.map(pt => pt.lon), borderWidth: 2, tension: 0.2, fill: false }
  ]
}))

const altChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    { label: 'Altitude' + simSuffix(), borderColor: '#00C851', data: filteredHistory.value.map(pt => pt.alt), borderWidth: 2, tension: 0.2, fill: false }
  ]
}))
</script>

<style scoped>
.gnss-container {
  display: flex;
  height: calc(100vh - 50px);
  background-color: #121212;
  color: white;
}

.main-content {
  flex: 3;
  display: flex;
  flex-direction: column;
  padding: 20px;
  gap: 20px;
  overflow: hidden;
}

.chart-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  background-color: #1e1e1e;
  padding: 10px 15px;
  border-radius: 8px;
}

.chart-controls select {
  background-color: #333;
  color: white;
  border: 1px solid #555;
  padding: 5px;
  border-radius: 4px;
}

.chart-wrapper {
  flex: 1;
  background-color: #1e1e1e;
  border-radius: 8px;
  padding: 15px;
  position: relative;
  min-height: 0;
}

.sidebar {
  flex: 1;
  max-width: 350px;
  background-color: #1a1a1a;
  border-left: 2px solid #333;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
}

.sidebar h3 {
  margin-top: 0;
  margin-bottom: 3px;
  color: #FFA500;
  border-bottom: 1px solid #333;
  padding-bottom: 6px;
  font-size: 0.85rem;
}

.mt-3 {
  margin-top: 12px !important;
}

/* Fix Indicator */
.fix-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background-color: #252525;
}

.fix-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  animation: pulse 1.5s ease-in-out infinite;
}

.fix-rtk .fix-dot {
  background-color: #00cc00;
  box-shadow: 0 0 8px #00cc00;
}

.fix-float .fix-dot {
  background-color: #FFA500;
  box-shadow: 0 0 8px #FFA500;
}

.fix-gps .fix-dot {
  background-color: #ffdd00;
  box-shadow: 0 0 8px #ffdd00;
}

.fix-none .fix-dot {
  background-color: #ff4444;
  box-shadow: 0 0 8px #ff4444;
  animation: pulse-fast 0.7s ease-in-out infinite;
}

.fix-label {
  font-weight: bold;
  font-size: 0.9em;
}

.fix-rtk .fix-label { color: #00cc00; }
.fix-float .fix-label { color: #FFA500; }
.fix-gps .fix-label { color: #ffdd00; }
.fix-none .fix-label { color: #ff4444; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes pulse-fast {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* Stat boxes */
.stat-group {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
}

.stat-box {
  background-color: #252525;
  padding: 8px 10px;
  border-radius: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-box h4 {
  margin: 0;
  color: #aaa;
  font-size: 0.75em;
  text-transform: uppercase;
  letter-spacing: 1px;
  flex: 1;
  padding-right: 8px;
}

.value {
  font-size: 1em;
  font-weight: bold;
  color: white;
  white-space: nowrap;
}

.value.small {
  font-size: 0.85em;
}

/* Highlight sidebar values cyan when displaying simulation data */
.sim-mode .value { color: #00e5ff; }
</style>
