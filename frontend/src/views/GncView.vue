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

      <div class="chart-wrapper">
        <Line :data="speedChartData" :options="speedChartOptions" />
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
        <h4>COG</h4>
        <div class="value">{{ (telemetry.gnssCog || 0).toFixed(1) }}&deg;</div>
      </div>

      <div class="stat-box">
        <h4>SOG</h4>
        <div class="value">{{ (telemetry.gnssSogKnots || 0).toFixed(2) }} kn</div>
      </div>

      <div class="stat-box">
        <h4>Reference Speed</h4>
        <div class="value">{{ (telemetry.refSpeedKn || 0).toFixed(2) }} kn</div>
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

      <div class="stat-box">
        <h4>Distance to WP</h4>
        <div class="value">{{ (telemetry.distToWp || 0).toFixed(1) }} m</div>
      </div>

      <div class="stat-box">
        <h4>Target WP</h4>
        <div class="value">{{ targetWpLabel }}</div>
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
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  elements: { point: { radius: 0 } },
  interaction: { mode: 'index', intersect: false },
  plugins: { legend: { labels: { color: 'white' } } },
  scales: {
    x: { ticks: { color: '#aaa', maxTicksLimit: 10 }, grid: { color: '#333' } },
    y: {
      type: 'linear', position: 'left',
      min: 0, max: 360,
      ticks: { color: '#4fc3f7' },
      grid: { color: '#333' },
      title: { display: true, text: 'Heading [°]', color: '#4fc3f7' }
    },
    y2: {
      type: 'linear', position: 'right',
      ticks: { color: '#ef5350' },
      grid: { drawOnChartArea: false },
      title: { display: true, text: 'Heading Error [°]', color: '#ef5350' }
    }
  }
}

const motorChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  elements: { point: { radius: 0 } },
  interaction: { mode: 'index', intersect: false },
  plugins: { legend: { labels: { color: 'white' } } },
  scales: {
    x: { ticks: { color: '#aaa', maxTicksLimit: 10 }, grid: { color: '#333' } },
    y: {
      type: 'linear', position: 'left',
      min: -100, max: 100,
      ticks: { color: '#aaa' },
      grid: { color: '#333' },
      title: { display: true, text: 'Motor [%]', color: '#aaa' }
    },
    y2: {
      type: 'linear', position: 'right',
      ticks: { color: '#aaa' },
      grid: { drawOnChartArea: false },
      title: { display: true, text: 'CTE [m]', color: '#aaa' }
    }
  }
}

// Dual-Y chart: surge/sway speed (left, knots) + surge/sway accel (right)
const speedChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  elements: { point: { radius: 0 } },
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { labels: { color: 'white' } },
    title: { display: false }
  },
  scales: {
    x: {
      ticks: { color: '#aaa', maxTicksLimit: 10 },
      grid: { color: '#333' }
    },
    y: {
      type: 'linear',
      position: 'left',
      ticks: { color: '#4fc3f7' },
      grid: { color: '#333' },
      title: { display: true, text: 'Speed [kn]', color: '#4fc3f7' }
    }
  }
}

// Utility
const degrees = (rad) => {
  if (rad === undefined || rad === null) return '0.0'
  return (rad * (180 / Math.PI)).toFixed(1)
}

// Target WP label — mirrors Mission Planner naming
const targetWpLabel = computed(() => {
  // Station keeping shows its own label regardless of wp_index
  if (telemetry.stationActive || telemetry.vehicleMode === 'STATION') return 'STATION WP'

  const total = telemetry.missionWaypoints.length
  if (total < 2) return '—'

  // PathFollower.wp_index is the FROM-waypoint index in the backend list.
  // The backend always prepends a bridge WP (current vehicle position), so:
  //   backend list = [bridge, wp[0], wp[1], ..., wp[total-1]]
  // The vehicle is heading TO backend[wp_index + 1] = frontend[wp_index].
  //
  // In reverse the backend receives the waypoints already reversed:
  //   backend list = [bridge, ME, WPN, ..., WP1, MS]
  // So TO-waypoint = frontend[total - 1 - wp_index].
  const wpIdx = telemetry.currentWpIndex || 0
  let frontendIdx
  if (telemetry.wpRouteDirection === 'reverse') {
    frontendIdx = (total - 1) - wpIdx
  } else {
    frontendIdx = wpIdx
  }

  // Clamp to valid range (handles loop transitions / edge cases)
  frontendIdx = Math.max(0, Math.min(total - 1, frontendIdx))

  if (frontendIdx === 0)         return 'MISSION START'
  if (frontendIdx >= total - 1)  return 'MISSION END'
  return 'WP ' + frontendIdx
})

// Chart Data (computed from store history — collected globally)
const filteredHistory = computed(() => {
  const cutoff = Date.now() - (timeWindow.value * 1000)
  return telemetry.gncHistory.filter(p => p.timeMs > cutoff)
})

const headingChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    { label: 'Actual Heading' + simSuffix(), borderColor: '#42A5F5', yAxisID: 'y', data: filteredHistory.value.map(pt => pt.actualHeading), borderWidth: 2, tension: 0.1 },
    { label: 'Target Heading' + simSuffix(), borderColor: '#FFA500', yAxisID: 'y', data: filteredHistory.value.map(pt => pt.targetHeading), borderWidth: 2, tension: 0.1 },
    { label: 'Heading Error' + simSuffix(), borderColor: '#ef5350', yAxisID: 'y2', data: filteredHistory.value.map(pt => pt.headingError), borderWidth: 1.5, tension: 0.1, borderDash: [4, 2] },
  ]
}))

const motorChartData = computed(() => {
  const isSim = telemetry.dataSource === 'sim'
  return {
    labels: filteredHistory.value.map(pt => pt.label),
    datasets: [
      {
        label: 'Port' + simSuffix(),
        borderColor: isSim ? '#FFA500' : '#e53935',
        yAxisID: 'y',
        data: filteredHistory.value.map(pt => pt.port),
        borderWidth: 2,
        tension: 0.1
      },
      {
        label: 'Starboard' + simSuffix(),
        borderColor: isSim ? '#FFD700' : '#00C851',
        yAxisID: 'y',
        data: filteredHistory.value.map(pt => pt.starboard),
        borderWidth: 2,
        tension: 0.1
      },
      {
        label: 'CTE [m]' + simSuffix(),
        borderColor: '#aaa',
        yAxisID: 'y2',
        data: filteredHistory.value.map(pt => pt.cte || 0),
        borderWidth: 1.5,
        tension: 0.1,
        borderDash: [4, 2]
      }
    ]
  }
})

// Speed + acceleration chart (dual Y, speed in knots)
const MS_TO_KN = 1 / 0.5144
const speedChartData = computed(() => ({
  labels: filteredHistory.value.map(pt => pt.label),
  datasets: [
    {
      label: 'Surge u [kn]' + simSuffix(),
      borderColor: '#4fc3f7',
      data: filteredHistory.value.map(pt => (pt.surgeVel || 0) * MS_TO_KN),
      yAxisID: 'y',
      borderWidth: 2,
      tension: 0.1
    },
    {
      label: 'Sway v [kn]' + simSuffix(),
      borderColor: '#81c784',
      data: filteredHistory.value.map(pt => (pt.swayVel || 0) * MS_TO_KN),
      yAxisID: 'y',
      borderWidth: 1.5,
      tension: 0.1
    },
    {
      label: 'Ref Speed [kn]',
      borderColor: '#FFA500',
      borderDash: [6, 3],
      data: filteredHistory.value.map(pt => pt.refSpeedKn || 0),
      yAxisID: 'y',
      borderWidth: 1.5,
      tension: 0
    }
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
  color: #e53935;
}

.motor-starboard {
  color: #00C851;
}

/* Highlight sidebar values orange when displaying simulation data */
.sim-mode .value { color: #FFA500; }
/* Preserve motor indicator colors in sim mode */
.sim-mode .motor-port { color: #e53935; }
.sim-mode .motor-starboard { color: #00C851; }
</style>