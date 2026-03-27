<template>
  <div class="wp-route-panel">
    <h3>WP Route</h3>

    <!-- Plan Mission toggle -->
    <button
      class="btn plan-btn"
      :class="{ active: store.mapPlanMode }"
      @click="store.mapPlanMode = !store.mapPlanMode"
      :disabled="wpRouteActive"
    >
      {{ store.mapPlanMode ? 'EXIT PLAN' : 'PLAN MISSION' }}
    </button>

    <!-- Route info -->
    <div class="field">
      <label>Waypoints</label>
      <span class="value">{{ missionWaypoints.length }}</span>
    </div>

    <!-- Route file actions -->
    <div class="route-actions">
      <button 
        class="btn load-btn" 
        @click="triggerFileInput"
        :disabled="wpRouteActive"
      >
        LOAD CSV
      </button>
      <button
        v-if="missionWaypoints.length > 0"
        class="btn save-btn"
        @click="saveRouteToFile"
      >
        SAVE
      </button>
      <button
        v-if="missionWaypoints.length > 0"
        class="btn clear-btn"
        @click="store.clearMission()"
      >
        CLEAR
      </button>
      <input 
        ref="fileInput" 
        type="file" 
        accept=".csv,.txt" 
        @change="loadFromFile" 
        hidden 
      />
    </div>

    <!-- Direction -->
    <div class="field">
      <label>Direction</label>
      <div class="toggle-group">
        <button 
          class="btn toggle-btn"
          :class="{ active: direction === 'forward' }"
          @click="direction = 'forward'"
          :disabled="wpRouteActive"
        >FWD</button>
        <button 
          class="btn toggle-btn"
          :class="{ active: direction === 'reverse' }"
          @click="direction = 'reverse'"
          :disabled="wpRouteActive"
        >REV</button>
      </div>
    </div>

    <!-- Completion -->
    <div class="field">
      <label>On Finish</label>
      <select v-model="completion" :disabled="wpRouteActive">
        <option value="stop">Stop</option>
        <option value="loop">Loop</option>
        <option value="loop_reverse">Loop &amp; Reverse</option>
      </select>
    </div>

    <!-- Home WP -->
    <div class="field">
      <label>Home WP</label>
      <div class="home-row">
        <span v-if="homeWaypoint" class="coord">
          {{ homeWaypoint.lat.toFixed(6) }}, {{ homeWaypoint.lon.toFixed(6) }}
        </span>
        <span v-else class="coord dim">Not set</span>
        <button
          class="btn home-btn"
          @click="setHome"
          :disabled="!isConnected || lat === 0"
        >SET HOME</button>
      </div>
    </div>

    <!-- Surge Force Slider -->
    <div class="field surge-field">
      <label>Nominal Surge Force</label>
      <div class="surge-slider-container">
        <input 
          type="range" 
          v-model.number="surgePct" 
          min="0" 
          max="100" 
          step="1" 
          class="surge-slider"
          :disabled="wpRouteActive"
        />
        <span class="surge-val">{{ surgePct }}%</span>
      </div>
      <div class="surge-metrics">
        <span>Force: {{ surgeForceN.toFixed(1) }} N</span>
        <span>Speed: {{ expectedSpeedMs.toFixed(2) }} m/s ({{ expectedSpeedKnots.toFixed(1) }} kn)</span>
      </div>
    </div>

    <!-- Pre-flight alerts -->
    <div v-if="startError" class="alert alert-error">{{ startError }}</div>
    <div v-for="w in startWarnings" :key="w" class="alert alert-warning">{{ w }}</div>

    <!-- Start / Stop -->
    <button 
      v-if="!wpRouteActive"
      class="btn start-btn"
      @click="start"
      :disabled="!isConnected || !isArmed || missionWaypoints.length === 0"
    >
      START
    </button>
    <button 
      v-else
      class="btn stop-btn"
      @click="stop"
      :disabled="!isConnected"
    >
      STOP
    </button>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { lat, lon, isConnected, isArmed, missionWaypoints, wpRouteActive, homeWaypoint, simMode } = storeToRefs(store)

const direction = ref('forward')
const completion = ref('stop')
const fileInput = ref(null)
const startError = ref('')
const startWarnings = ref([])

// Compute Surge Force and Speed
const surgePct = ref(66) // Default ~ 66% (approx 150N)
const surgeForceN = computed(() => (surgePct.value / 100) * 225.6)
const expectedSpeedMs = computed(() => {
  const p = surgePct.value / 100
  if (p <= 0) return 0
  const Umax = 2.0576 // 4 knots in m/s
  return ((-0.2 + Math.sqrt(0.04 + 3.2 * p)) / 1.6) * Umax
})
const expectedSpeedKnots = computed(() => expectedSpeedMs.value / 0.5144)

const triggerFileInput = () => {
  fileInput.value?.click()
}

const loadFromFile = (e) => {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => {
    const text = ev.target.result
    const wps = []
    for (const line of text.trim().split('\n')) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#') || trimmed.toLowerCase().startsWith('lat')) continue
      const parts = trimmed.split(',').map(s => s.trim())
      if (parts.length < 2) continue
      wps.push({
        lat: parseFloat(parts[0]),
        lon: parseFloat(parts[1]),
        radius: parts.length > 2 ? parseFloat(parts[2]) : 5.0,
        speed: parts.length > 3 ? parseFloat(parts[3]) : 1.0,
      })
    }
    if (wps.length > 0) {
      store.missionWaypoints = wps
    }
  }
  reader.readAsText(file)
  e.target.value = ''
}

const setHome = () => {
  store.setHomeWp(lat.value, lon.value)
}

const start = () => {
  startError.value = ''
  startWarnings.value = []

  const wps = missionWaypoints.value

  // Pre-flight checks (skip in SIM mode)
  if (simMode.value === 'REAL') {
    if (!store.canStartAutoMode) {
      startError.value = 'Cannot start: No GNSS fix'
      return
    }
    startWarnings.value = store.autoModeWarnings
  }

  // Decoupled start - sends START_WP_ROUTE regardless of simulation mode
  store.startWpRoute({
    waypoints: wps,
    direction: direction.value,
    completion: completion.value,
    tau_x: surgeForceN.value
  })
}

const stop = () => {
  startError.value = ''
  startWarnings.value = []
  store.wpRouteActive = false
  store.stopWpRoute()
}

const saveRouteToFile = () => {
  const wps = missionWaypoints.value
  if (!wps || wps.length === 0) return
  const header = '# lat,lon,radius,speed'
  const lines = wps.map(wp =>
    `${wp.lat.toFixed(7)},${wp.lon.toFixed(7)},${wp.radius || 5.0},${wp.speed || 1.0}`
  )
  const csv = [header, ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const now = new Date()
  const ts = now.toISOString().replace(/[:.]/g, '-').slice(0, 19)
  a.href = url
  a.download = `route_${ts}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.wp-route-panel {
  background: rgba(30, 30, 30, 0.95);
  color: #fff;
  padding: 16px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 220px;
}

h3 {
  margin: 0;
  font-size: 1rem;
  color: #FFA500;
  text-align: center;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: 0.75rem;
  color: #aaa;
  text-transform: uppercase;
}

.value {
  font-size: 0.9rem;
  font-family: monospace;
}

.route-actions {
  display: flex;
  gap: 6px;
}

.toggle-group {
  display: flex;
  gap: 2px;
  background: #333;
  border-radius: 4px;
  padding: 2px;
}

.toggle-btn {
  flex: 1;
  background: transparent;
  color: #aaa;
  padding: 6px 10px;
  border-radius: 3px;
  font-size: 0.8rem;
}

.toggle-btn.active {
  background: #FFA500;
  color: #000;
}

select {
  background: #333;
  border: 1px solid #555;
  color: #fff;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.85rem;
}

select:disabled {
  opacity: 0.5;
}

.btn {
  padding: 10px;
  border: none;
  border-radius: 4px;
  font-weight: bold;
  cursor: pointer;
  font-size: 0.85rem;
  transition: opacity 0.2s;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.load-btn {
  flex: 1;
  background: #555;
  color: #fff;
}

.save-btn {
  background: #2a7a4a;
  color: #fff;
  padding: 10px 8px;
}

.clear-btn {
  background: #aa3333;
  color: #fff;
  padding: 10px 8px;
}

.plan-btn {
  background: #33b5e5;
  color: white;
}

.plan-btn.active {
  background: #ff8800;
  color: #000;
}

.start-btn {
  background: #00C851;
  color: white;
}

.stop-btn {
  background: #ff4444;
  color: white;
}

.home-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.home-row .coord {
  flex: 1;
  font-size: 0.8rem;
  font-family: monospace;
}

.home-row .coord.dim {
  color: #666;
}

.home-btn {
  background: #8855cc;
  color: white;
  padding: 6px 10px !important;
  font-size: 0.75rem !important;
}

.alert {
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: bold;
}

.alert-error {
  background: #5a1a1a;
  color: #ff4444;
  border: 1px solid #ff4444;
}

.alert-warning {
  background: #4a3a1a;
  color: #ffaa00;
  border: 1px solid #ffaa00;
}

/* Surge slider */
.surge-field {
  background: #252525;
  padding: 8px;
  border-radius: 6px;
  margin-top: 4px;
}

.surge-slider-container {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.surge-slider {
  flex: 1;
  cursor: pointer;
  accent-color: #FFA500;
}

.surge-val {
  font-family: monospace;
  font-size: 0.9rem;
  color: #FFA500;
  min-width: 32px;
  text-align: right;
}

.surge-metrics {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 0.7rem;
  color: #888;
  font-family: monospace;
}
</style>
