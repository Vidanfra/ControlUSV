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
    
    <div class="sidebar">
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
import { ref, onMounted, onUnmounted, watch } from 'vue'
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
const timeWindow = ref(60) // seconds

// History arrays
const history = ref([])

// Utility
const degrees = (rad) => {
  if (rad === undefined || rad === null) return '0.0'
  return (rad * (180 / Math.PI)).toFixed(1)
}

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

// Chart Data Structures (Reactive Refs attached to the Line component)
const headingChartData = ref({
  labels: [],
  datasets: [
    { label: 'Actual Heading', borderColor: '#42A5F5', data: [], borderWidth: 2, tension: 0.1 },
    { label: 'Target Heading', borderColor: '#FFA500', data: [], borderWidth: 2, tension: 0.1 }
  ]
})

const motorChartData = ref({
  labels: [],
  datasets: [
    { label: 'Port', borderColor: '#FF4444', data: [], borderWidth: 2, tension: 0.1 },
    { label: 'Starboard', borderColor: '#00C851', data: [], borderWidth: 2, tension: 0.1 }
  ]
})

let updateInterval = null

// Real-time Update Logic
const updateCharts = () => {
    const now = Date.now()
    
    // Convert current rad to deg (0-360) for Heading Chart
    let actualDeg = (telemetry.heading * (180/Math.PI)) % 360
    if (actualDeg < 0) actualDeg += 360
    if (isNaN(actualDeg)) actualDeg = 0
    
    let targetDeg = (telemetry.targetHeading * (180/Math.PI)) % 360
    if (targetDeg < 0) targetDeg += 360
    if (isNaN(targetDeg)) targetDeg = 0

    // Push new point
    history.value.push({
      timeMs: now,
      label: new Date(now).toISOString().substr(11, 8), // HH:mm:ss
      actualHeading: actualDeg,
      targetHeading: targetDeg,
      port: telemetry.motorPort || 0,
      starboard: telemetry.motorStarboard || 0
    })

    // Filter old points based on timeWindow
    const cutoff = now - (timeWindow.value * 1000)
    
    // Shift buffer logic to prevent memory leaks! We use while shift
    while (history.value.length > 0 && history.value[0].timeMs < cutoff) {
        history.value.shift()
    }

    // Map history to chart data
    headingChartData.value = {
      labels: history.value.map(pt => pt.label),
      datasets: [
        { label: 'Actual Heading', borderColor: '#42A5F5', data: history.value.map(pt => pt.actualHeading), borderWidth: 2, tension: 0.1 },
        { label: 'Target Heading', borderColor: '#FFA500', data: history.value.map(pt => pt.targetHeading), borderWidth: 2, tension: 0.1 }
      ]
    }
    
    motorChartData.value = {
      labels: history.value.map(pt => pt.label),
      datasets: [
        { label: 'Port', borderColor: '#FF4444', data: history.value.map(pt => pt.port), borderWidth: 2, tension: 0.1 },
        { label: 'Starboard', borderColor: '#00C851', data: history.value.map(pt => pt.starboard), borderWidth: 2, tension: 0.1 }
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
</style>