<template>
  <div class="imu-container">
    <div class="main-content">
      <div class="chart-controls">
        <label>Time Window:</label>
        <select v-model="timeWindow">
          <option :value="5">5s</option>
          <option :value="10">10s</option>
          <option :value="20">20s</option>
          <option :value="60">60s</option>
        </select>
      </div>

      <div class="chart-wrapper">
        <Line :data="orientationChartData" :options="orientationChartOptions" />
      </div>

      <div class="chart-wrapper">
        <Line :data="accelChartData" :options="accelChartOptions" />
      </div>

      <div class="chart-wrapper">
        <Line :data="gyroChartData" :options="gyroChartOptions" />
      </div>
    </div>

    <div class="sidebar" :class="{ 'sim-mode': telemetry.dataSource === 'sim' }">
      <h3>IMU Status</h3>

      <div class="stat-group">
        <div class="stat-box highlight">
          <h4>Mag Heading</h4>
          <div class="value">{{ telemetry.imuMagHeading?.toFixed(1) ?? '0.0' }}°</div>
        </div>
      </div>

      <h3 class="mt-3">Orientation</h3>
      <div class="stat-group">
        <div class="stat-box" :class="{ 'var-hidden': !showRoll }">
          <input type="checkbox" v-model="showRoll" class="var-check" title="Show in chart" />
          <h4>Roll</h4>
          <div class="value">{{ telemetry.imuRoll?.toFixed(2) ?? '0.00' }}°</div>
        </div>
        <div class="stat-box" :class="{ 'var-hidden': !showPitch }">
          <input type="checkbox" v-model="showPitch" class="var-check" title="Show in chart" />
          <h4>Pitch</h4>
          <div class="value">{{ telemetry.imuPitch?.toFixed(2) ?? '0.00' }}°</div>
        </div>
        <div class="stat-box" :class="{ 'var-hidden': !showYaw }">
          <input type="checkbox" v-model="showYaw" class="var-check" title="Show in chart" />
          <h4>Yaw</h4>
          <div class="value">{{ telemetry.imuYaw?.toFixed(2) ?? '0.00' }}°</div>
        </div>
      </div>

      <h3 class="mt-3">Accelerations</h3>
      <div class="stat-group">
        <div class="stat-box" :class="{ 'var-hidden': !showAx }">
          <input type="checkbox" v-model="showAx" class="var-check" title="Show in chart" />
          <h4>Ax</h4>
          <div class="value">{{ telemetry.imuAx?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box" :class="{ 'var-hidden': !showAy }">
          <input type="checkbox" v-model="showAy" class="var-check" title="Show in chart" />
          <h4>Ay</h4>
          <div class="value">{{ telemetry.imuAy?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box" :class="{ 'var-hidden': !showAz }">
          <input type="checkbox" v-model="showAz" class="var-check" title="Show in chart" />
          <h4>Az</h4>
          <div class="value">{{ telemetry.imuAz?.toFixed(2) ?? '0.00' }}</div>
        </div>
      </div>

      <h3 class="mt-3">Angular Rates</h3>
      <div class="stat-group">
        <div class="stat-box" :class="{ 'var-hidden': !showP }">
          <input type="checkbox" v-model="showP" class="var-check" title="Show in chart" />
          <h4>P (Roll Rate)</h4>
          <div class="value">{{ telemetry.imuP?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box" :class="{ 'var-hidden': !showQ }">
          <input type="checkbox" v-model="showQ" class="var-check" title="Show in chart" />
          <h4>Q (Pitch Rate)</h4>
          <div class="value">{{ telemetry.imuQ?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box" :class="{ 'var-hidden': !showR }">
          <input type="checkbox" v-model="showR" class="var-check" title="Show in chart" />
          <h4>R (Yaw Rate)</h4>
          <div class="value">{{ telemetry.imuR?.toFixed(2) ?? '0.00' }}</div>
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

// State
const timeWindow = ref(20) // seconds

// Chart visibility toggles — data is always collected, toggling only hides the dataset
const showRoll  = ref(true)
const showPitch = ref(true)
const showYaw   = ref(true)
const showAx    = ref(true)
const showAy    = ref(true)
const showAz    = ref(true)
const showP     = ref(true)
const showQ     = ref(true)
const showR     = ref(true)

// --- Chart Options base ---
const chartBaseOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false, // Turn off animation for realtime performance
  elements: {
    point: { radius: 0 } // hide points, only lines
  },
  plugins: {
    legend: {
      labels: { color: 'white' }
    }
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

// Setup custom charts options
const orientationChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Orientation (degrees)', color: '#aaa' }
  }
}

const accelChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Acceleration (m/s²)', color: '#aaa' }
  }
}

const gyroChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Angular Rates (rad/s)', color: '#aaa' }
  }
}

// Chart Data (computed from store history — collected globally)
const filteredHistory = computed(() => {
  const cutoff = Date.now() - (timeWindow.value * 1000)
  return telemetry.imuHistory.filter(p => p.timeMs > cutoff)
})

const orientationChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    ...(showRoll.value  ? [{ label: 'Roll'  + simSuffix(), borderColor: '#ff4444', data: filteredHistory.value.map(pt => pt.roll),  borderWidth: 2, tension: 0.1 }] : []),
    ...(showPitch.value ? [{ label: 'Pitch' + simSuffix(), borderColor: '#00C851', data: filteredHistory.value.map(pt => pt.pitch), borderWidth: 2, tension: 0.1 }] : []),
    ...(showYaw.value   ? [{ label: 'Yaw'   + simSuffix(), borderColor: '#33b5e5', data: filteredHistory.value.map(pt => pt.yaw),   borderWidth: 2, tension: 0.1 }] : []),
  ]
}))

const accelChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    ...(showAx.value ? [{ label: 'Ax' + simSuffix(), borderColor: '#ff4444', data: filteredHistory.value.map(pt => pt.ax), borderWidth: 2, tension: 0.1 }] : []),
    ...(showAy.value ? [{ label: 'Ay' + simSuffix(), borderColor: '#00C851', data: filteredHistory.value.map(pt => pt.ay), borderWidth: 2, tension: 0.1 }] : []),
    ...(showAz.value ? [{ label: 'Az' + simSuffix(), borderColor: '#33b5e5', data: filteredHistory.value.map(pt => pt.az), borderWidth: 2, tension: 0.1 }] : []),
  ]
}))

const gyroChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    ...(showP.value ? [{ label: 'P (Roll Rate)'  + simSuffix(), borderColor: '#ff4444', data: filteredHistory.value.map(pt => pt.p), borderWidth: 2, tension: 0.1 }] : []),
    ...(showQ.value ? [{ label: 'Q (Pitch Rate)' + simSuffix(), borderColor: '#00C851', data: filteredHistory.value.map(pt => pt.q), borderWidth: 2, tension: 0.1 }] : []),
    ...(showR.value ? [{ label: 'R (Yaw Rate)'   + simSuffix(), borderColor: '#33b5e5', data: filteredHistory.value.map(pt => pt.r), borderWidth: 2, tension: 0.1 }] : []),
  ]
}))

</script>

<style scoped>
.imu-container {
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
  text-align: left;
}

.stat-box.highlight {
  background-color: #2a2a35;
  border-left: 3px solid #FFA500;
}

.stat-box h4 {
  margin: 0;
  color: #aaa;
  font-size: 0.75em;
  text-transform: uppercase;
  letter-spacing: 1px;
  line-height: 1.3;
  flex: 1;
  padding-right: 8px;
  word-wrap: break-word;
}

.value {
  font-size: 1em;
  font-weight: bold;
  color: white;
  white-space: nowrap;
}

/* Highlight sidebar values cyan when displaying simulation data */
.sim-mode .value { color: #00e5ff; }

.var-check {
  margin-right: 6px;
  accent-color: #FFA500;
  cursor: pointer;
  flex-shrink: 0;
  width: 14px;
  height: 14px;
}

.var-hidden {
  opacity: 0.4;
}
</style>