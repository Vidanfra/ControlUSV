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

      <div class="chart-wrapper">
        <Line :data="headingChartData" :options="headingChartOptions" />
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

      <h3 class="mt-3">INS</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Latitude</h4>
          <div class="value">{{ telemetry.lat.toFixed(8) }}°</div>
        </div>
        <div class="stat-box">
          <h4>Longitude</h4>
          <div class="value">{{ telemetry.lon.toFixed(8) }}°</div>
        </div>
        <div class="stat-box">
          <h4>Altitude</h4>
          <div class="value">{{ telemetry.altitude.toFixed(3) }} m</div>
        </div>
        <div class="stat-box">
          <h4>Heading</h4>
          <div class="value">{{ telemetry.bestHeading.toFixed(1) }}°</div>
        </div>
        <div class="stat-box">
          <h4>SOG</h4>
          <div class="value">{{ (telemetry.speed / 0.514444).toFixed(2) }} kn</div>
        </div>
        <div class="stat-box">
          <h4>Horizontal Error (1 sigma)</h4>
          <div class="value">{{ formatMeters(averageNavHorizontalAccuracyM) }}</div>
        </div>
        <div class="stat-box">
          <h4>Vertical Error (1 sigma)</h4>
          <div class="value">{{ formatMeters(averageNavVerticalAccuracyM) }}</div>
        </div>
      </div>

      <h3 class="mt-3">GNSS Quality</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Horizontal Error (1 sigma)</h4>
          <div class="value">{{ formatMeters(telemetry.gnssHorizontalAccuracyM) }}</div>
        </div>
        <div class="stat-box">
          <h4>Vertical Error (1 sigma)</h4>
          <div class="value">{{ formatMeters(telemetry.gnssVerticalAccuracyM) }}</div>
        </div>
                <div class="stat-box">
          <h4>UTC Time</h4>
          <div class="value small">{{ telemetry.gnssUtcTime || '--' }}</div>
        </div>
        <div class="stat-box">
          <h4>UTC Date</h4>
          <div class="value small">{{ telemetry.gnssUtcDate || '--' }}</div>
        </div>
        <div class="stat-box">
          <h4>Fix Type</h4>
          <div class="value" :style="{ color: fixColor }">{{ fixLabel }}</div>
        </div>
        <div class="stat-box">
          <h4>Satellites</h4>
          <div class="value">{{ telemetry.gnssNumSats ?? 0 }}</div>
        </div>
      </div>

      <h3 class="mt-3">GNSS Position <span class="raw-badge">RAW</span></h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Latitude</h4>
          <div class="value">{{ telemetry.gnssRawLat?.toFixed(8) ?? '0.00000000' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Longitude</h4>
          <div class="value">{{ telemetry.gnssRawLon?.toFixed(8) ?? '0.00000000' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Altitude</h4>
          <div class="value">{{ telemetry.gnssAlt?.toFixed(2) ?? '0.00' }} m</div>
        </div>
      </div>

      <h3 class="mt-3">GNSS Navigation</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>SOG</h4>
          <div class="value">{{ telemetry.gnssSogKnots?.toFixed(2) ?? '0.00' }} kn</div>
        </div>
        <div class="stat-box">
          <h4>COG</h4>
          <div class="value">{{ telemetry.gnssCog?.toFixed(1) ?? '0.0' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Heading (GNSS)</h4>
          <div class="value">{{ telemetry.gnssHeading?.toFixed(1) ?? '0.0' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Heading (MAG)</h4>
          <div class="value">{{ telemetry.imuMagHeading?.toFixed(1) ?? '0.0' }}°</div>
        </div>
      </div>


      <h3 class="mt-3">Plot Series</h3>
      <div class="stat-group">
        <label class="stat-box plot-toggle" :class="{ 'var-hidden': !showInsHeading }">
          <input v-model="showInsHeading" type="checkbox" class="var-check" />
          <span>INS Heading</span>
        </label>
        <label class="stat-box plot-toggle" :class="{ 'var-hidden': !showGnssHeading }">
          <input v-model="showGnssHeading" type="checkbox" class="var-check" />
          <span>GNSS Heading</span>
        </label>
        <label class="stat-box plot-toggle" :class="{ 'var-hidden': !showMagHeading }">
          <input v-model="showMagHeading" type="checkbox" class="var-check" />
          <span>Magnetic Heading</span>
        </label>
        <label class="stat-box plot-toggle" :class="{ 'var-hidden': !showCog }">
          <input v-model="showCog" type="checkbox" class="var-check" />
          <span>COG</span>
        </label>
        <label class="stat-box plot-toggle" :class="{ 'var-hidden': !showGnssPosition }">
          <input v-model="showGnssPosition" type="checkbox" class="var-check" />
          <span>GNSS Position</span>
        </label>
        <label class="stat-box plot-toggle" :class="{ 'var-hidden': !showInsPosition }">
          <input v-model="showInsPosition" type="checkbox" class="var-check" />
          <span>INS Position</span>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
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
const formatMeters = value => value == null ? '--' : `${value.toFixed(3)} m`

const averageNavHorizontalAccuracyM = ref(null)
const averageNavVerticalAccuracyM = ref(null)
let navAccuracySamples = []
let navAccuracyAverageTimer

watch(
  () => [telemetry.navHorizontalAccuracyM, telemetry.navVerticalAccuracyM],
  ([horizontalAccuracyM, verticalAccuracyM]) => {
    navAccuracySamples.push({ horizontalAccuracyM, verticalAccuracyM })
  },
  { immediate: true }
)

onMounted(() => {
  navAccuracyAverageTimer = setInterval(() => {
    const horizontalSamples = navAccuracySamples
      .map(sample => sample.horizontalAccuracyM)
      .filter(Number.isFinite)
    const verticalSamples = navAccuracySamples
      .map(sample => sample.verticalAccuracyM)
      .filter(Number.isFinite)

    if (horizontalSamples.length) {
      averageNavHorizontalAccuracyM.value = horizontalSamples.reduce((sum, value) => sum + value, 0) / horizontalSamples.length
    }
    if (verticalSamples.length) {
      averageNavVerticalAccuracyM.value = verticalSamples.reduce((sum, value) => sum + value, 0) / verticalSamples.length
    }
    navAccuracySamples = []
  }, 500)
})

onUnmounted(() => clearInterval(navAccuracyAverageTimer))

const timeWindow = ref(120)
const showInsHeading = ref(true)
const showGnssHeading = ref(true)
const showMagHeading = ref(true)
const showCog = ref(true)
const showGnssPosition = ref(true)
const showInsPosition = ref(true)

// --- Fix type helpers ---
const fixLabel = computed(() => {
  const fix = telemetry.gnssFixType
  const labels = { 0: 'No Fix', 1: 'GPS', 2: 'DGPS', 4: 'RTK Fix', 5: 'RTK Float' }
  return labels[fix] ?? `Unknown (${fix})`
})

const fixColor = computed(() => {
  const fix = telemetry.gnssFixType
  if (fix === 4) return '#00C851'       // RTK Fix → green
  if (fix === 5) return '#FFA500'       // RTK Float → orange
  if (fix === 2) return '#ffdd00'       // DGPS → yellow
  if (fix === 1) return '#ffdd00'       // GPS → yellow
  return '#e53935'                      // No fix → red
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

const headingChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Heading Comparison (degrees)', color: '#aaa' }
  },
  scales: {
    ...chartBaseOptions.scales,
    y: {
      ...chartBaseOptions.scales.y,
      grace: '5%',
    }
  }
}

// --- Chart data (computed from store history — no setInterval needed) ---
const filteredHistory = computed(() => {
  const cutoff = Date.now() - (timeWindow.value * 1000)
  return telemetry.insComparisonHistory.filter(point => point.timeMs > cutoff)
})

const validGnssPosition = value => Number.isFinite(value) && value !== 0 ? value : null

const headingChartData = computed(() => ({
  labels: filteredHistory.value.map(point => point.label),
  datasets: [
    ...(showInsHeading.value ? [{ label: 'INS Heading', borderColor: '#42d4f4', data: filteredHistory.value.map(point => point.insHeading), borderWidth: 2, pointRadius: 0, tension: 0.1 }] : []),
    ...(showGnssHeading.value ? [{ label: 'GNSS Heading', borderColor: '#ff5252', data: filteredHistory.value.map(point => point.gnssHeading), borderWidth: 1.5, pointRadius: 0, tension: 0.1 }] : []),
    ...(showMagHeading.value ? [{ label: 'Magnetic Heading', borderColor: '#FFA500', data: filteredHistory.value.map(point => point.magHeading), borderWidth: 1.5, pointRadius: 0, tension: 0.1 }] : []),
    ...(showCog.value ? [{ label: 'COG', borderColor: '#7bd88f', data: filteredHistory.value.map(point => point.cog), borderWidth: 1.5, pointRadius: 0, borderDash: [5, 4], tension: 0.1 }] : []),
  ]
}))

const latChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    ...(showGnssPosition.value ? [{ label: 'GNSS CRP Latitude' + simSuffix(), borderColor: '#ff5252', data: filteredHistory.value.map(pt => validGnssPosition(pt.gnssLat)), borderWidth: 1.5, pointRadius: 1, tension: 0.1, fill: false }] : []),
    ...(showInsPosition.value ? [{ label: 'INS Latitude' + simSuffix(), borderColor: '#42d4f4', data: filteredHistory.value.map(pt => pt.insLat), borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false }] : [])
  ]
}))

const lonChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    ...(showGnssPosition.value ? [{ label: 'GNSS CRP Longitude' + simSuffix(), borderColor: '#ff5252', data: filteredHistory.value.map(pt => validGnssPosition(pt.gnssLon)), borderWidth: 1.5, pointRadius: 1, tension: 0.1, fill: false }] : []),
    ...(showInsPosition.value ? [{ label: 'INS Longitude' + simSuffix(), borderColor: '#42d4f4', data: filteredHistory.value.map(pt => pt.insLon), borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false }] : [])
  ]
}))

const altChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    ...(showGnssPosition.value ? [{ label: 'GNSS CRP Altitude' + simSuffix(), borderColor: '#ff5252', data: filteredHistory.value.map(pt => pt.gnssAlt), borderWidth: 1.5, pointRadius: 1, tension: 0.1, fill: false }] : []),
    ...(showInsPosition.value ? [{ label: 'INS Altitude' + simSuffix(), borderColor: '#42d4f4', data: filteredHistory.value.map(pt => pt.insAlt), borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false }] : [])
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
  overflow-y: auto;
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
  flex: 0 0 250px;
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

.raw-badge {
  font-size: 0.6rem;
  font-weight: 700;
  background: #444;
  color: #aaa;
  border: 1px solid #555;
  border-radius: 3px;
  padding: 1px 4px;
  vertical-align: middle;
  letter-spacing: 0.05em;
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
  background-color: #00C851;
  box-shadow: 0 0 8px #00C851;
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
  background-color: #e53935;
  box-shadow: 0 0 8px #e53935;
  animation: pulse-fast 0.7s ease-in-out infinite;
}

.fix-label {
  font-weight: bold;
  font-size: 0.9em;
}

.fix-rtk .fix-label { color: #00C851; }
.fix-float .fix-label { color: #FFA500; }
.fix-gps .fix-label { color: #ffdd00; }
.fix-none .fix-label { color: #e53935; }

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

.plot-toggle {
  justify-content: flex-start;
  gap: 8px;
  color: #ccc;
  font-size: 0.8em;
  font-weight: 600;
  cursor: pointer;
}

.plot-toggle span {
  flex: 1;
}

.var-check {
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: #FFA500;
  cursor: pointer;
  flex-shrink: 0;
}

.var-hidden {
  opacity: 0.4;
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

/* Highlight sidebar values orange when displaying simulation data */
.sim-mode .value { color: #FFA500; }

@media (max-width: 800px) {
  .gnss-container {
    flex-direction: column;
    overflow-y: auto;
  }

  .main-content {
    flex: none;
    overflow: visible;
  }

  .sidebar {
    flex: none;
    max-width: none;
    border-left: none;
    border-top: 2px solid #333;
  }
}
</style>
