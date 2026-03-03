<template>
  <div class="sim-results" v-show="results && results.length > 0">
    <h3>Simulation Results</h3>
    
    <div class="charts-grid">
      <!-- XY Track Plot -->
      <div class="chart-box wide">
        <canvas ref="trackCanvas"></canvas>
      </div>

      <!-- Heading -->
      <div class="chart-box">
        <canvas ref="headingCanvas"></canvas>
      </div>

      <!-- Cross-Track Error -->
      <div class="chart-box">
        <canvas ref="cteCanvas"></canvas>
      </div>

      <!-- Speed -->
      <div class="chart-box">
        <canvas ref="speedCanvas"></canvas>
      </div>

      <!-- Heading Error -->
      <div class="chart-box">
        <canvas ref="headingErrCanvas"></canvas>
      </div>

      <!-- Motor Commands -->
      <div class="chart-box">
        <canvas ref="motorCanvas"></canvas>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import {
  Chart, LineController, ScatterController, LineElement, PointElement,
  LinearScale, CategoryScale, Title, Tooltip, Legend, Filler
} from 'chart.js'

Chart.register(
  LineController, ScatterController, LineElement, PointElement,
  LinearScale, CategoryScale, Title, Tooltip, Legend, Filler
)

const props = defineProps({
  results: { type: Array, default: () => [] },
  waypoints: { type: Array, default: () => [] },
})

const trackCanvas = ref(null)
const headingCanvas = ref(null)
const cteCanvas = ref(null)
const speedCanvas = ref(null)
const headingErrCanvas = ref(null)
const motorCanvas = ref(null)

const COLORS = ['#e6194b', '#3cb44b', '#4363d8', '#f032e6', '#42d4f4', '#fabed4']
const RAD2DEG = 180 / Math.PI

// Keep chart instances for cleanup
const charts = {}

const darkDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: {
      display: true,
      position: 'bottom',
      labels: { color: '#ccc', font: { size: 10 }, boxWidth: 14, padding: 8 },
    },
    title: {
      display: true,
      color: '#00E5FF',
      font: { size: 13, weight: 'bold' },
    },
  },
  scales: {
    x: {
      ticks: { color: '#aaa', font: { size: 9 } },
      grid: { color: '#333' },
      title: { display: true, color: '#aaa', font: { size: 10 } },
    },
    y: {
      ticks: { color: '#aaa', font: { size: 9 } },
      grid: { color: '#333' },
      title: { display: true, color: '#aaa', font: { size: 10 } },
    },
  },
  elements: {
    point: { radius: 0 },
    line: { borderWidth: 2 },
  },
}

function profileLabel(r) {
  const cfg = r.config || {}
  return `Salpa 1 #${r.profile_id} (${cfg.payload_kg ?? 25}kg, δ=${cfg.delta ?? 5}m)`
}

function makeChart(canvasRef, key, config) {
  if (charts[key]) {
    charts[key].destroy()
    delete charts[key]
  }
  if (!canvasRef.value) return
  charts[key] = new Chart(canvasRef.value.getContext('2d'), config)
}

function plotAll(results, waypoints) {
  if (!results || results.length === 0) return

  // --- XY Track (scatter mode — East vs North) ---
  const trackDatasets = results.map((r, i) => ({
    label: profileLabel(r),
    data: r.E.map((e, j) => ({ x: e, y: r.N[j] })),
    borderColor: COLORS[i % COLORS.length],
    showLine: true,
    fill: false,
  }))
  if (waypoints && waypoints.length > 0) {
    const origin = waypoints[0]
    const R = 6371000
    trackDatasets.push({
      label: 'Waypoints',
      data: waypoints.map(wp => ({
        x: (wp.lon - origin.lon) * Math.PI / 180 * R * Math.cos(origin.lat * Math.PI / 180),
        y: (wp.lat - origin.lat) * Math.PI / 180 * R,
      })),
      borderColor: '#00E5FF',
      backgroundColor: '#00E5FF',
      showLine: true,
      borderDash: [6, 4],
      borderWidth: 1,
      pointRadius: 5,
      pointStyle: 'rectRot',
    })
  }
  makeChart(trackCanvas, 'track', {
    type: 'scatter',
    data: { datasets: trackDatasets },
    options: {
      ...darkDefaults,
      maintainAspectRatio: true,
      aspectRatio: 1,
      plugins: {
        ...darkDefaults.plugins,
        title: { ...darkDefaults.plugins.title, text: 'XY Track (NED)' },
      },
      scales: {
        x: { ...darkDefaults.scales.x, title: { ...darkDefaults.scales.x.title, text: 'East [m]' } },
        y: { ...darkDefaults.scales.y, title: { ...darkDefaults.scales.y.title, text: 'North [m]' } },
      },
    },
  })

  // Decimate time labels for line charts (show max ~40 labels)
  const allTimes = results[0].time
  const step = Math.max(1, Math.floor(allTimes.length / 40))
  const sparseLabels = allTimes.map((t, i) => i % step === 0 ? t : '')

  // --- Heading ---
  const headingDatasets = []
  results.forEach((r, i) => {
    headingDatasets.push({
      label: `${profileLabel(r)} — Actual`,
      data: r.psi.map(v => ((v * RAD2DEG) % 360 + 360) % 360),
      borderColor: COLORS[i % COLORS.length],
    })
    headingDatasets.push({
      label: `${profileLabel(r)} — Desired`,
      data: r.psi_d.map(v => ((v * RAD2DEG) % 360 + 360) % 360),
      borderColor: COLORS[i % COLORS.length],
      borderDash: [6, 3],
      borderWidth: 1.5,
    })
  })
  makeChart(headingCanvas, 'heading', {
    type: 'line',
    data: { labels: sparseLabels, datasets: headingDatasets },
    options: {
      ...darkDefaults,
      plugins: {
        ...darkDefaults.plugins,
        title: { ...darkDefaults.plugins.title, text: 'Heading' },
      },
      scales: {
        x: { ...darkDefaults.scales.x, title: { ...darkDefaults.scales.x.title, text: 'Time [s]' } },
        y: { ...darkDefaults.scales.y, min: 0, max: 360, title: { ...darkDefaults.scales.y.title, text: 'Heading [deg]' } },
      },
    },
  })

  // --- CTE ---
  makeChart(cteCanvas, 'cte', {
    type: 'line',
    data: {
      labels: sparseLabels,
      datasets: results.map((r, i) => ({
        label: profileLabel(r),
        data: r.cte,
        borderColor: COLORS[i % COLORS.length],
      })),
    },
    options: {
      ...darkDefaults,
      plugins: {
        ...darkDefaults.plugins,
        title: { ...darkDefaults.plugins.title, text: 'Cross-Track Error' },
      },
      scales: {
        x: { ...darkDefaults.scales.x, title: { ...darkDefaults.scales.x.title, text: 'Time [s]' } },
        y: { ...darkDefaults.scales.y, title: { ...darkDefaults.scales.y.title, text: 'CTE [m]' } },
      },
    },
  })

  // --- Speed ---
  makeChart(speedCanvas, 'speed', {
    type: 'line',
    data: {
      labels: sparseLabels,
      datasets: results.map((r, i) => ({
        label: profileLabel(r),
        data: r.speed,
        borderColor: COLORS[i % COLORS.length],
      })),
    },
    options: {
      ...darkDefaults,
      plugins: {
        ...darkDefaults.plugins,
        title: { ...darkDefaults.plugins.title, text: 'Speed' },
      },
      scales: {
        x: { ...darkDefaults.scales.x, title: { ...darkDefaults.scales.x.title, text: 'Time [s]' } },
        y: { ...darkDefaults.scales.y, title: { ...darkDefaults.scales.y.title, text: 'Speed [m/s]' } },
      },
    },
  })

  // --- Heading Error ---
  makeChart(headingErrCanvas, 'headingErr', {
    type: 'line',
    data: {
      labels: sparseLabels,
      datasets: results.map((r, i) => ({
        label: profileLabel(r),
        data: r.psi_error.map(v => v * RAD2DEG),
        borderColor: COLORS[i % COLORS.length],
      })),
    },
    options: {
      ...darkDefaults,
      plugins: {
        ...darkDefaults.plugins,
        title: { ...darkDefaults.plugins.title, text: 'Heading Error' },
      },
      scales: {
        x: { ...darkDefaults.scales.x, title: { ...darkDefaults.scales.x.title, text: 'Time [s]' } },
        y: { ...darkDefaults.scales.y, title: { ...darkDefaults.scales.y.title, text: 'Error [deg]' } },
      },
    },
  })

  // --- Motor Commands ---
  const motorDatasets = []
  results.forEach((r, i) => {
    motorDatasets.push({
      label: `${profileLabel(r)} — n₁ (port)`,
      data: r.n1,
      borderColor: COLORS[i % COLORS.length],
    })
    motorDatasets.push({
      label: `${profileLabel(r)} — n₂ (stbd)`,
      data: r.n2,
      borderColor: COLORS[i % COLORS.length],
      borderDash: [4, 3],
      borderWidth: 1.5,
    })
  })
  makeChart(motorCanvas, 'motor', {
    type: 'line',
    data: { labels: sparseLabels, datasets: motorDatasets },
    options: {
      ...darkDefaults,
      plugins: {
        ...darkDefaults.plugins,
        title: { ...darkDefaults.plugins.title, text: 'Motor Commands' },
      },
      scales: {
        x: { ...darkDefaults.scales.x, title: { ...darkDefaults.scales.x.title, text: 'Time [s]' } },
        y: { ...darkDefaults.scales.y, title: { ...darkDefaults.scales.y.title, text: 'Speed [rad/s]' } },
      },
    },
  })
}

async function safePlot() {
  // Double nextTick ensures DOM is ready after v-show toggle
  await nextTick()
  await nextTick()
  plotAll(props.results, props.waypoints)
}

watch(() => props.results, async (newResults) => {
  if (newResults && newResults.length > 0) {
    await safePlot()
  }
}, { deep: true })

onMounted(() => {
  if (props.results && props.results.length > 0) {
    safePlot()
  }
})

onUnmounted(() => {
  Object.values(charts).forEach(c => { try { c.destroy() } catch {} })
})
</script>

<style scoped>
.sim-results {
  padding: 10px 0;
}

.sim-results h3 {
  color: #00E5FF;
  margin: 0 0 10px 0;
  font-size: 1rem;
}

.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.chart-box {
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 8px;
  height: 300px;
  position: relative;
}

.chart-box.wide {
  grid-column: 1 / -1;
  height: 380px;
}
</style>
