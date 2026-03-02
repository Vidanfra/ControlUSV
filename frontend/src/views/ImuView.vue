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

    <div class="sidebar">
      <h3>IMU Status</h3>

      <div class="stat-group">
        <div class="stat-box highlight">
          <h4>Mag Heading</h4>
          <div class="value">{{ telemetry.imuMagHeading?.toFixed(1) ?? '0.0' }}°</div>
        </div>
      </div>

      <h3 class="mt-3">Orientation</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Roll</h4>
          <div class="value">{{ telemetry.imuRoll?.toFixed(2) ?? '0.00' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Pitch</h4>
          <div class="value">{{ telemetry.imuPitch?.toFixed(2) ?? '0.00' }}°</div>
        </div>
        <div class="stat-box">
          <h4>Yaw</h4>
          <div class="value">{{ telemetry.imuYaw?.toFixed(2) ?? '0.00' }}°</div>
        </div>
      </div>

      <h3 class="mt-3">Accelerations</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Ax</h4>
          <div class="value">{{ telemetry.imuAx?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box">
          <h4>Ay</h4>
          <div class="value">{{ telemetry.imuAy?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box">
          <h4>Az</h4>
          <div class="value">{{ telemetry.imuAz?.toFixed(2) ?? '0.00' }}</div>
        </div>
      </div>

      <h3 class="mt-3">Angular Rates</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>P (Roll Rate)</h4>
          <div class="value">{{ telemetry.imuP?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box">
          <h4>Q (Pitch Rate)</h4>
          <div class="value">{{ telemetry.imuQ?.toFixed(2) ?? '0.00' }}</div>
        </div>
        <div class="stat-box">
          <h4>R (Yaw Rate)</h4>
          <div class="value">{{ telemetry.imuR?.toFixed(2) ?? '0.00' }}</div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
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

// State
const timeWindow = ref(20) // seconds

// History array
const history = ref([])

// Chart Options base
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

// Chart Data Structures
const orientationChartData = ref({ labels: [], datasets: [] })
const accelChartData = ref({ labels: [], datasets: [] })
const gyroChartData = ref({ labels: [], datasets: [] })

let updateInterval = null

// Real-time Update Logic
const updateCharts = () => {
    const now = Date.now()
    
    // Push new point
    history.value.push({
      timeMs: now,
      label: new Date(now).toISOString().substr(11, 8), // HH:mm:ss
      roll: telemetry.imuRoll || 0.0,
      pitch: telemetry.imuPitch || 0.0,
      yaw: telemetry.imuYaw || 0.0,
      ax: telemetry.imuAx || 0.0,
      ay: telemetry.imuAy || 0.0,
      az: telemetry.imuAz || 0.0,
      p: telemetry.imuP || 0.0,
      q: telemetry.imuQ || 0.0,
      r: telemetry.imuR || 0.0
    })

    // Filter old points based on timeWindow
    const cutoff = now - (timeWindow.value * 1000)
    
    // Shift buffer logic to prevent memory leaks
    while (history.value.length > 0 && history.value[0].timeMs < cutoff) {
        history.value.shift()
    }

    const labels = history.value.map(pt => pt.label)

    // Map history to chart data
    orientationChartData.value = {
      labels,
      datasets: [
        { label: 'Roll', borderColor: '#ff4444', data: history.value.map(pt => pt.roll), borderWidth: 2, tension: 0.1 },
        { label: 'Pitch', borderColor: '#00C851', data: history.value.map(pt => pt.pitch), borderWidth: 2, tension: 0.1 },
        { label: 'Yaw', borderColor: '#33b5e5', data: history.value.map(pt => pt.yaw), borderWidth: 2, tension: 0.1 }
      ]
    }
    
    accelChartData.value = {
      labels,
      datasets: [
        { label: 'Ax', borderColor: '#ff4444', data: history.value.map(pt => pt.ax), borderWidth: 2, tension: 0.1 },
        { label: 'Ay', borderColor: '#00C851', data: history.value.map(pt => pt.ay), borderWidth: 2, tension: 0.1 },
        { label: 'Az', borderColor: '#33b5e5', data: history.value.map(pt => pt.az), borderWidth: 2, tension: 0.1 }
      ]
    }

    gyroChartData.value = {
      labels,
      datasets: [
        { label: 'P (Roll Rate)', borderColor: '#ff4444', data: history.value.map(pt => pt.p), borderWidth: 2, tension: 0.1 },
        { label: 'Q (Pitch Rate)', borderColor: '#00C851', data: history.value.map(pt => pt.q), borderWidth: 2, tension: 0.1 },
        { label: 'R (Yaw Rate)', borderColor: '#33b5e5', data: history.value.map(pt => pt.r), borderWidth: 2, tension: 0.1 }
      ]
    }
}

onMounted(() => {
  // Update at 10Hz
  updateInterval = setInterval(updateCharts, 100)
})

onUnmounted(() => {
  if (updateInterval) clearInterval(updateInterval)
})

watch(timeWindow, () => {
    updateCharts()
})

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
</style>