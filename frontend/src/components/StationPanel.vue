<template>
  <div class="station-panel">
    <h3>Station Keeping</h3>

    <div class="field">
      <label>Reaching Radio (m)</label>
      <input 
        type="number" 
        v-model.number="reachingRadius" 
        min="1" 
        max="100" 
        step="1"
        :disabled="stationActive"
      />
    </div>

    <div class="field">
      <label>Station Radio (m)</label>
      <input 
        type="number" 
        v-model.number="stationRadiusLocal" 
        min="1" 
        max="200" 
        step="1"
        :disabled="stationActive"
      />
    </div>

    <div class="field">
      <label>Position</label>
      <span v-if="stationWaypoint" class="coord">
        {{ stationWaypoint.lat.toFixed(7) }}, {{ stationWaypoint.lon.toFixed(7) }}
      </span>
      <span v-else class="coord dim">Not set</span>
    </div>

    <button 
      class="btn set-btn"
      @click="setCurrentPosition"
      :disabled="!isConnected || stationActive || lat === 0"
    >
      ⊕ SET CURRENT POSITION
    </button>

    <button
      class="btn pick-btn"
      :class="{ active: store.stationPickMode }"
      @click="pickFromMap"
      :disabled="stationActive"
    >
      {{ store.stationPickMode ? '📍 PICKING...' : '📍 PICK ON MAP' }}
    </button>

    <!-- Cruise Speed Slider -->
    <div class="field surge-field">
      <label>Cruise Speed</label>
      <div class="surge-slider-container">
        <input 
          type="range" 
          v-model.number="cruiseSpeedKn" 
          min="0.1" 
          max="4.0" 
          step="0.1" 
          class="surge-slider"
        />
        <span class="surge-val">{{ cruiseSpeedKn.toFixed(1) }} kn</span>
      </div>
      <div class="surge-metrics">
        <span>Force: {{ surgeForceN.toFixed(1) }} N</span>
        <span>Speed: {{ speedMs.toFixed(2) }} m/s</span>
      </div>
    </div>

    <!-- Pre-flight alert -->
    <div v-if="startError" class="alert alert-error">{{ startError }}</div>
    <div v-for="w in startWarnings" :key="w" class="alert alert-warning">{{ w }}</div>

    <button 
      v-if="!stationActive"
      class="btn start-btn"
      @click="start"
      :disabled="!isConnected || (!isArmed && !rtSimActive) || !stationWaypoint"
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
import { ref, watch, computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { lat, lon, isConnected, isArmed, rtSimActive, stationWaypoint, stationReachingRadius, stationRadius, stationActive, simMode } = storeToRefs(store)

const stationRadiusLocal = ref(stationRadius.value)
const reachingRadius = ref(stationReachingRadius.value)
const startError = ref('')
const startWarnings = ref([])

// Cruise speed slider (knots, 0.1–4.0 kn)
// Initialise from store (localStorage → first backend heartbeat overwrites it)
const KN_TO_MS = 0.5144
const cruiseSpeedKn = ref(store.gncConfig?.cruise_speed_kn ?? 3.2)
// Keep slider in sync when the backend broadcasts a new gnc_config (e.g. after restart)
watch(() => store.gncConfig?.cruise_speed_kn, (val) => {
  if (!stationActive.value && val !== undefined) cruiseSpeedKn.value = val
})
// Push live speed changes to backend while station keeping is active (debounced 300 ms)
let _cruiseSpeedTimer = null
watch(cruiseSpeedKn, (val) => {
  if (!stationActive.value) return
  clearTimeout(_cruiseSpeedTimer)
  _cruiseSpeedTimer = setTimeout(() => {
    store.setGncConfig({ cruise_speed_kn: val })
  }, 300)
})
const speedMs    = computed(() => cruiseSpeedKn.value * KN_TO_MS)
const surgeForceN = computed(() => {
  // Drag inversion: tau = Xu_lin*v + Xu_quad*v²  (Salpa 1 coefficients)
  const v = speedMs.value
  return 21.94 * v + 42.58 * v * v
})

watch(reachingRadius, (val) => {
  store.stationReachingRadius = val
  localStorage.setItem('stationReachingRadius', JSON.stringify(val))
})

watch(stationRadiusLocal, (val) => {
  store.stationRadius = val
  localStorage.setItem('stationRadius', JSON.stringify(val))
})

const setCurrentPosition = () => {
  store.setStation(lat.value, lon.value, reachingRadius.value, stationRadiusLocal.value)
}

const pickFromMap = () => {
  store.stationPickMode = !store.stationPickMode
  if (store.stationPickMode) {
    store.currentTab = 'map'
  }
}

const start = () => {
  startError.value = ''
  startWarnings.value = []

  // Pre-flight checks (skip in SIM mode)
  if (simMode.value === 'REAL') {
    if (!store.canStartAutoMode) {
      startError.value = 'Cannot start: No GNSS fix'
      return
    }
    startWarnings.value = store.autoModeWarnings
  }

  // Decoupled start
  store.startStation(cruiseSpeedKn.value)
}

const stop = () => {
  startError.value = ''
  startWarnings.value = []
  store.stationActive = false
  store.stopStation()
}
</script>

<style scoped>
.station-panel {
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

.field input {
  background: #333;
  border: 1px solid #555;
  color: #fff;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.9rem;
  width: 100%;
  box-sizing: border-box;
}

.field input:disabled {
  opacity: 0.5;
}

.coord {
  font-size: 0.85rem;
  font-family: monospace;
}

.coord.dim {
  color: #666;
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

.set-btn {
  background: #0d3a5c;
  color: #81d4fa;
  border: 1px solid #1565c0;
}
.set-btn:hover:not(:disabled) {
  background: #1565c0;
  color: #fff;
}

.pick-btn {
  background: #1b5e20;
  color: #a5d6a7;
  border: 1px solid #2e7d32;
}

.pick-btn.active {
  background: #388e3c;
  color: #fff;
  border-color: #43a047;
  animation: pulse-pick 1s infinite;
}

@keyframes pulse-pick {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.start-btn {
  background: #00C851;
  color: white;
}

.start-btn:hover:not(:disabled) {
  background: #00a543;
}

.stop-btn {
  background: #e53935;
  color: white;
}

.stop-btn:hover:not(:disabled) {
  background: #c62828;
}

.alert {
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.78rem;
}

.alert-error {
  background: rgba(180,0,0,0.2);
  color: #ff6b6b;
  border: 1px solid #9a0000;
}

.alert-warning {
  background: rgba(160,100,0,0.2);
  color: #ffcc66;
  border: 1px solid #805000;
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
