<template>
  <div class="gnc-container">
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
        <Line :data="headingChartData" :options="headingChartOptions" />
      </div>
      
      <div class="chart-wrapper">
        <Line :data="motorChartData" :options="motorChartOptions" />
      </div>
    </div>
    
    <div class="sidebar" :class="{ 'sim-mode': telemetry.dataSource === 'sim' }">
      <h3>GNC Variables</h3>
      
      <div class="stat-box">
        <h4>Actual Heading</h4>
        <div class="value">{{ degrees(telemetry.heading) }}&deg;</div>
      </div>
      
      <div class="stat-box">
        <h4>Target Heading</h4>
        <div class="value">{{ degrees(telemetry.targetHeading) }}&deg;</div>
      </div>
      
      <div class="stat-box">
        <h4>Heading Error</h4>
        <div class="value">{{ degrees(telemetry.headingError) }}&deg;</div>
      </div>
      
      <div class="stat-box">
        <h4>Cross Track Error</h4>
        <div class="value">{{ telemetry.crossTrackError.toFixed(2) }} m</div>
      </div>
      
      <div class="stat-box">
        <h4>Motor Port</h4>
        <div class="value motor-port">{{ telemetry.motorPort.toFixed(1) }}%</div>
      </div>
      
      <div class="stat-box">
        <h4>Motor Starboard</h4>
        <div class="value motor-starboard">{{ telemetry.motorStarboard.toFixed(1) }}%</div>
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
const timeWindow = ref(60) // seconds

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
const headingChartOptions = {
  ...chartBaseOptions,
  scales: {
    ...chartBaseOptions.scales,
    y: {
      ...chartBaseOptions.scales.y,
      min: 0,
      max: 360
    }
  }
}

const motorChartOptions = {
  ...chartBaseOptions,
  scales: {
    ...chartBaseOptions.scales,
    y: {
      ...chartBaseOptions.scales.y,
      min: -100,
      max: 100
    }
  }
}

// Utility
const degrees = (rad) => {
  if (rad === undefined || rad === null) return '0.0'
  return (rad * (180 / Math.PI)).toFixed(1)
}

// Chart Data (computed from store history — collected globally)
const filteredHistory = computed(() => {
  const cutoff = Date.now() - (timeWindow.value * 1000)
  return telemetry.gncHistory.filter(p => p.timeMs > cutoff)
})

const headingChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    { label: 'Actual Heading' + simSuffix(), borderColor: '#42A5F5', data: filteredHistory.value.map(pt => pt.actualHeading), borderWidth: 2, tension: 0.1 },
    { label: 'Target Heading' + simSuffix(), borderColor: '#FFA500', data: filteredHistory.value.map(pt => pt.targetHeading), borderWidth: 2, tension: 0.1 }
  ]
}))

const motorChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    { label: 'Port' + simSuffix(), borderColor: '#FF4444', data: filteredHistory.value.map(pt => pt.port), borderWidth: 2, tension: 0.1 },
    { label: 'Starboard' + simSuffix(), borderColor: '#00C851', data: filteredHistory.value.map(pt => pt.starboard), borderWidth: 2, tension: 0.1 }
  ]
}))

</script>

<style scoped>
.gnc-container {
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
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}

.sidebar h3 {
  margin-top: 0;
  margin-bottom: 5px;
  color: #FFA500;
  border-bottom: 1px solid #333;
  padding-bottom: 10px;
}

.stat-box {
  background-color: #252525;
  padding: 12px 15px;
  border-radius: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  text-align: left;
}

.stat-box h4 {
  margin: 0;
  color: #aaa;
  font-size: 0.85em;
  text-transform: uppercase;
  letter-spacing: 1px;
  line-height: 1.3;
  flex: 1;
  padding-right: 10px;
  word-wrap: break-word;
}

.value {
  font-size: 1.4em;
  font-weight: bold;
  color: white;
  white-space: nowrap;
}

.motor-port {
  color: #ff4444;
}

.motor-starboard {
  color: #00C851;
}

/* Highlight sidebar values cyan when displaying simulation data */
.sim-mode .value { color: #00e5ff; }
/* Preserve motor indicator colors in sim mode */
.sim-mode .motor-port { color: #ff4444; }
.sim-mode .motor-starboard { color: #00C851; }
</style>