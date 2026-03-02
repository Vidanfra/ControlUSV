<template>
  <div class="power-container">
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
        <Line :data="voltageChartData" :options="voltageChartOptions" />
      </div>

      <div class="chart-wrapper">
        <Line :data="currentChartData" :options="currentChartOptions" />
      </div>

      <div class="chart-wrapper">
        <Line :data="powerChartData" :options="powerChartOptions" />
      </div>
    </div>

    <div class="sidebar">
      <h3>Power Status</h3>

      <div class="stat-group">
        <div class="stat-box">
          <h4>Voltage</h4>
          <div class="value">{{ telemetry.batteryVoltage?.toFixed(2) ?? '0.00' }} V</div>
        </div>
        <div class="stat-box">
          <h4>Current</h4>
          <div class="value">{{ telemetry.batteryCurrent?.toFixed(2) ?? '0.00' }} A</div>
        </div>
        <div class="stat-box">
          <h4>Power</h4>
          <div class="value">{{ telemetry.batteryPower?.toFixed(1) ?? '0.0' }} W</div>
        </div>
      </div>

      <h3 class="mt-3">Energy</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Consumed (SW)</h4>
          <div class="value">{{ telemetry.batteryAccumulatedWh?.toFixed(2) ?? '0.00' }} Wh</div>
        </div>
        <div class="stat-box">
          <h4>Consumed (HW)</h4>
          <div class="value">{{ telemetry.batteryEnergyWh ?? 0 }} Wh</div>
        </div>
        <div class="stat-box">
          <h4>Battery Level</h4>
          <div class="value" :class="levelClass">{{ telemetry.batteryLevelPct?.toFixed(1) ?? '0.0' }} %</div>
        </div>
        <div class="stat-box">
          <h4>Capacity</h4>
          <div class="value">{{ telemetry.batteryCapacityWh?.toFixed(0) ?? '500' }} Wh</div>
        </div>
      </div>

      <h3 class="mt-3">Measurement</h3>
      <div class="stat-group">
        <div class="stat-box">
          <h4>Started</h4>
          <div class="value small">{{ measurementStartStr }}</div>
        </div>
        <div class="stat-box">
          <h4>Duration</h4>
          <div class="value">{{ measurementDuration }}</div>
        </div>
      </div>

      <h3 class="mt-3">Alarms</h3>
      <div class="stat-group">
        <div class="stat-box" :class="{ alarm: telemetry.batteryHighAlarm }">
          <h4>High Voltage</h4>
          <div class="value" :class="{ 'alarm-text': telemetry.batteryHighAlarm }">
            {{ telemetry.batteryHighAlarm ? 'ALARM' : 'OK' }}
          </div>
        </div>
        <div class="stat-box" :class="{ alarm: telemetry.batteryLowAlarm }">
          <h4>Low Voltage</h4>
          <div class="value" :class="{ 'alarm-text': telemetry.batteryLowAlarm }">
            {{ telemetry.batteryLowAlarm ? 'ALARM' : 'OK' }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
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

const timeWindow = ref(120)
const history = ref([])

// --- Computed helpers ---
const measurementStartStr = computed(() => {
  const ts = telemetry.batteryMeasurementStart
  if (!ts || ts === 0) return '--'
  return new Date(ts * 1000).toLocaleTimeString()
})

const measurementDuration = computed(() => {
  const ts = telemetry.batteryMeasurementStart
  if (!ts || ts === 0) return '--'
  const elapsed = Math.floor(Date.now() / 1000 - ts)
  if (elapsed < 0) return '--'
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
})

const levelClass = computed(() => {
  const pct = telemetry.batteryLevelPct || 0
  if (pct < 20) return 'level-critical'
  if (pct < 40) return 'level-low'
  return 'level-ok'
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

const voltageChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Voltage (V)', color: '#aaa' }
  }
}

const currentChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Current (A)', color: '#aaa' }
  }
}

const powerChartOptions = {
  ...chartBaseOptions,
  plugins: {
    ...chartBaseOptions.plugins,
    title: { display: true, text: 'Power (W)', color: '#aaa' }
  }
}

// --- Chart data refs ---
const voltageChartData = ref({ labels: [], datasets: [] })
const currentChartData = ref({ labels: [], datasets: [] })
const powerChartData = ref({ labels: [], datasets: [] })

let updateInterval = null

const updateCharts = () => {
  const now = Date.now()

  history.value.push({
    timeMs: now,
    label: new Date(now).toISOString().substr(11, 8),
    voltage: telemetry.batteryVoltage || 0,
    current: telemetry.batteryCurrent || 0,
    power: telemetry.batteryPower || 0
  })

  const cutoff = now - (timeWindow.value * 1000)
  while (history.value.length > 0 && history.value[0].timeMs < cutoff) {
    history.value.shift()
  }

  const labels = history.value.map(pt => pt.label)

  voltageChartData.value = {
    labels,
    datasets: [
      { label: 'Voltage', borderColor: '#FFA500', data: history.value.map(pt => pt.voltage), borderWidth: 2, tension: 0.2, fill: false }
    ]
  }

  currentChartData.value = {
    labels,
    datasets: [
      { label: 'Current', borderColor: '#33b5e5', data: history.value.map(pt => pt.current), borderWidth: 2, tension: 0.2, fill: false }
    ]
  }

  powerChartData.value = {
    labels,
    datasets: [
      { label: 'Power', borderColor: '#ff4444', data: history.value.map(pt => pt.power), borderWidth: 2, tension: 0.2, fill: false }
    ]
  }
}

onMounted(() => {
  updateInterval = setInterval(updateCharts, 500)
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
}

.stat-box.alarm {
  background-color: #3a1a1a;
  border: 1px solid #ff4444;
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

.value.level-ok {
  color: #00cc00;
}

.value.level-low {
  color: #FFA500;
}

.value.level-critical {
  color: #ff4444;
}

.value.alarm-text {
  color: #ff4444;
}
</style>
