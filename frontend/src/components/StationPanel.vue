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
      SET CURRENT POSITION
    </button>

    <button
      class="btn pick-btn"
      :class="{ active: store.stationPickMode }"
      @click="pickFromMap"
      :disabled="stationActive"
    >
      {{ store.stationPickMode ? 'PICKING...' : 'PICK ON MAP' }}
    </button>

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
          :disabled="stationActive"
        />
        <span class="surge-val">{{ surgePct }}%</span>
      </div>
      <div class="surge-metrics">
        <span>Force: {{ surgeForceN.toFixed(1) }} N</span>
        <span>Speed: {{ expectedSpeedMs.toFixed(2) }} m/s ({{ expectedSpeedKnots.toFixed(1) }} kn)</span>
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
  store.startStation(surgeForceN.value)
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
  background: #33b5e5;
  color: white;
}

.pick-btn {
  background: #8855cc;
  color: white;
}

.pick-btn.active {
  background: #FFA500;
  color: #000;
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

.stop-btn {
  background: #ff4444;
  color: white;
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
