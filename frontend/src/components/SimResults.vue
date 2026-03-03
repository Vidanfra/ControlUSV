<template>
  <div class="sim-results" v-if="results && results.length > 0">
    <h3>Simulation Results</h3>
    
    <div class="charts-grid">
      <!-- XY Track Plot -->
      <div class="chart-box wide">
        <div ref="trackPlot" class="plotly-chart"></div>
      </div>

      <!-- Heading -->
      <div class="chart-box">
        <div ref="headingPlot" class="plotly-chart"></div>
      </div>

      <!-- Cross-Track Error -->
      <div class="chart-box">
        <div ref="ctePlot" class="plotly-chart"></div>
      </div>

      <!-- Speed -->
      <div class="chart-box">
        <div ref="speedPlot" class="plotly-chart"></div>
      </div>

      <!-- Heading Error -->
      <div class="chart-box">
        <div ref="headingErrPlot" class="plotly-chart"></div>
      </div>

      <!-- Motor Commands -->
      <div class="chart-box">
        <div ref="motorPlot" class="plotly-chart"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onUnmounted } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  results: { type: Array, default: () => [] },
  waypoints: { type: Array, default: () => [] },
})

const trackPlot = ref(null)
const headingPlot = ref(null)
const ctePlot = ref(null)
const speedPlot = ref(null)
const headingErrPlot = ref(null)
const motorPlot = ref(null)

const COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
const RAD2DEG = 180 / Math.PI

const darkLayout = {
  paper_bgcolor: '#1e1e1e',
  plot_bgcolor: '#1e1e1e',
  font: { color: '#ccc', size: 11 },
  margin: { l: 50, r: 20, t: 35, b: 40 },
  legend: { orientation: 'h', y: -0.15, font: { size: 10 } },
  xaxis: { gridcolor: '#333', zerolinecolor: '#444' },
  yaxis: { gridcolor: '#333', zerolinecolor: '#444' },
}

function plotAll(results, waypoints) {
  if (!results || results.length === 0) return
  
  // --- XY Track ---
  const trackTraces = results.map((r, i) => ({
    x: r.E,
    y: r.N,
    mode: 'lines',
    name: `Profile ${r.profile_id}`,
    line: { color: COLORS[i % COLORS.length], width: 2 },
  }))
  // Add waypoints
  if (waypoints && waypoints.length > 0) {
    // Convert lat/lon to N/E using first WP as origin
    const origin = waypoints[0]
    const R = 6371000
    const wpN = waypoints.map(wp => (wp.lat - origin.lat) * Math.PI / 180 * R)
    const wpE = waypoints.map(wp => (wp.lon - origin.lon) * Math.PI / 180 * R * Math.cos(origin.lat * Math.PI / 180))
    trackTraces.push({
      x: wpE, y: wpN,
      mode: 'markers+lines',
      name: 'Waypoints',
      marker: { size: 10, color: '#FFA500', symbol: 'diamond' },
      line: { color: '#FFA500', dash: 'dot', width: 1 },
    })
  }
  Plotly.react(trackPlot.value, trackTraces, {
    ...darkLayout,
    title: 'XY Track (NED)',
    xaxis: { ...darkLayout.xaxis, title: 'East [m]', scaleanchor: 'y' },
    yaxis: { ...darkLayout.yaxis, title: 'North [m]' },
  }, { responsive: true })

  // --- Heading ---
  const headingTraces = []
  results.forEach((r, i) => {
    headingTraces.push({
      x: r.time, y: r.psi.map(v => v * RAD2DEG),
      mode: 'lines', name: `Actual ${r.profile_id}`,
      line: { color: COLORS[i % COLORS.length], width: 2 },
    })
    headingTraces.push({
      x: r.time, y: r.psi_d.map(v => v * RAD2DEG),
      mode: 'lines', name: `Desired ${r.profile_id}`,
      line: { color: COLORS[i % COLORS.length], width: 1, dash: 'dash' },
    })
  })
  Plotly.react(headingPlot.value, headingTraces, {
    ...darkLayout,
    title: 'Heading',
    xaxis: { ...darkLayout.xaxis, title: 'Time [s]' },
    yaxis: { ...darkLayout.yaxis, title: 'Heading [deg]' },
  }, { responsive: true })

  // --- CTE ---
  const cteTraces = results.map((r, i) => ({
    x: r.time, y: r.cte,
    mode: 'lines', name: `Profile ${r.profile_id}`,
    line: { color: COLORS[i % COLORS.length], width: 2 },
  }))
  Plotly.react(ctePlot.value, cteTraces, {
    ...darkLayout,
    title: 'Cross-Track Error',
    xaxis: { ...darkLayout.xaxis, title: 'Time [s]' },
    yaxis: { ...darkLayout.yaxis, title: 'CTE [m]' },
  }, { responsive: true })

  // --- Speed ---
  const speedTraces = results.map((r, i) => ({
    x: r.time, y: r.speed,
    mode: 'lines', name: `Profile ${r.profile_id}`,
    line: { color: COLORS[i % COLORS.length], width: 2 },
  }))
  Plotly.react(speedPlot.value, speedTraces, {
    ...darkLayout,
    title: 'Speed',
    xaxis: { ...darkLayout.xaxis, title: 'Time [s]' },
    yaxis: { ...darkLayout.yaxis, title: 'Speed [m/s]' },
  }, { responsive: true })

  // --- Heading Error ---
  const errTraces = results.map((r, i) => ({
    x: r.time, y: r.psi_error.map(v => v * RAD2DEG),
    mode: 'lines', name: `Profile ${r.profile_id}`,
    line: { color: COLORS[i % COLORS.length], width: 2 },
  }))
  Plotly.react(headingErrPlot.value, errTraces, {
    ...darkLayout,
    title: 'Heading Error',
    xaxis: { ...darkLayout.xaxis, title: 'Time [s]' },
    yaxis: { ...darkLayout.yaxis, title: 'Error [deg]' },
  }, { responsive: true })

  // --- Motor Commands ---
  const motorTraces = []
  results.forEach((r, i) => {
    motorTraces.push({
      x: r.time, y: r.n1,
      mode: 'lines', name: `n1 P${r.profile_id}`,
      line: { color: COLORS[i % COLORS.length], width: 2 },
    })
    motorTraces.push({
      x: r.time, y: r.n2,
      mode: 'lines', name: `n2 P${r.profile_id}`,
      line: { color: COLORS[i % COLORS.length], width: 1, dash: 'dot' },
    })
  })
  Plotly.react(motorPlot.value, motorTraces, {
    ...darkLayout,
    title: 'Motor Commands',
    xaxis: { ...darkLayout.xaxis, title: 'Time [s]' },
    yaxis: { ...darkLayout.yaxis, title: 'RPM' },
  }, { responsive: true })
}

watch(() => props.results, async (newResults) => {
  if (newResults && newResults.length > 0) {
    await nextTick()
    plotAll(newResults, props.waypoints)
  }
}, { deep: true })

// Cleanup Plotly on unmount
onUnmounted(() => {
  const refs = [trackPlot, headingPlot, ctePlot, speedPlot, headingErrPlot, motorPlot]
  refs.forEach(r => {
    if (r.value) {
      try { Plotly.purge(r.value) } catch {}
    }
  })
})
</script>

<style scoped>
.sim-results {
  padding: 10px 0;
}

.sim-results h3 {
  color: #FFA500;
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
  overflow: hidden;
}

.chart-box.wide {
  grid-column: 1 / -1;
}

.plotly-chart {
  width: 100%;
  height: 300px;
}
</style>
