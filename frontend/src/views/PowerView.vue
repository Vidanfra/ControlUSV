<template>
  <div class="power-container">
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
        <Line :data="voltageChartData" :options="voltageChartOptions" />
      </div>

      <div class="chart-wrapper">
        <Line :data="currentChartData" :options="currentChartOptions" />
      </div>
    </div>

    <div class="sidebar">
      <h3>Battery Status</h3>

      <div class="stat-box">
        <h4>Voltage</h4>
        <div class="value">{{ telemetry.batteryVoltage.toFixed(2) }} V</div>
      </div>

      <div class="stat-box">
        <h4>Current</h4>
        <div class="value">{{ telemetry.batteryCurrent.toFixed(2) }} A</div>
      </div>

      <div class="stat-box">
        <h4>Instant Power</h4>
        <div class="value">{{ telemetry.batteryPower.toFixed(1) }} W</div>
      </div>

      <div class="stat-box">
        <h4>Capacity</h4>
        <div class="value">{{ telemetry.batteryCapacityWh.toFixed(0) }} Wh</div>
      </div>
      
      <div class="stat-box">
        <h4>Consumed Energy</h4>
        <div class="value">{{ telemetry.batteryAccumulatedWh.toFixed(1) }} Wh</div>
      </div>

      <div class="stat-box">
        <h4>Level</h4>
        <div class="value" :class="levelClass">{{ telemetry.batteryLevelPct.toFixed(1) }}%</div>
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
const timeWindow = ref(60) // seconds

// History array
const history = ref([])

const levelClass = computed(() => {
    if (telemetry.batteryLevelPct > 50) return 'level-high'
    if (telemetry.batteryLevelPct > 20) return 'level-med'
    return 'level-low'
})

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
const voltageChartOptions = {
  ...chartBaseOptions,
  scales: {
    ...chartBaseOptions.scales,
    y: {
      ...chartBaseOptions.scales.y,
      min: 10,
      max: 15
    }
  }
}

const currentChartOptions = {
  ...chartBaseOptions,
  scales: {
    ...chartBaseOptions.scales,
    y: {
      ...chartBaseOptions.scales.y,
      // Leaving y axis auto-scale for current, since it can vary widely
    }
  }
}

// Chart Data Structures (Reactive Refs attached to the Line component)
const voltageChartData = ref({
  labels: [],
  datasets: [
    { label: 'Voltage (V)', borderColor: '#FFA500', data: [], borderWidth: 2, tension: 0.1 }
  ]
})

const currentChartData = ref({
  labels: [],
  datasets: [
    { label: 'Current (A)', borderColor: '#42A5F5', data: [], borderWidth: 2, tension: 0.1 }
  ]
})

let updateInterval = null

// Real-time Update Logic
const updateCharts = () => {
    const now = Date.now()
    
    let voltage = telemetry.batteryVoltage || 0.0
    let current = telemetry.batteryCurrent || 0.0

    // Push new point
    history.value.push({
      timeMs: now,
      label: new Date(now).toISOString().substr(11, 8), // HH:mm:ss
      voltage: voltage,
      current: current
    })

    // Filter old points based on timeWindow
    const cutoff = now - (timeWindow.value * 1000)
    
    // Shift buffer logic to prevent memory leaks
    while (history.value.length > 0 && history.value[0].timeMs < cutoff) {
        history.value.shift()
    }

    // Map history to chart data
    voltageChartData.value = {
      labels: history.value.map(pt => pt.label),
      datasets: [
        { label: 'Voltage (V)', borderColor: '#FFA500', data: history.value.map(pt => pt.voltage), borderWidth: 2, tension: 0.1 }
      ]
    }
    
    currentChartData.value = {
      labels: history.value.map(pt => pt.label),
      datasets: [
        { label: 'Current (A)', borderColor: '#42A5F5', data: history.value.map(pt => pt.current), borderWidth: 2, tension: 0.1 }
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
.power-container {
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

.level-high {
  color: #00C851;
}

.level-med {
  color: #FFA500;
}

.level-low {
  color: #ff4444;
}
</style>