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

    <!-- Pre-flight alert -->
    <div v-if="startError" class="alert alert-error">{{ startError }}</div>
    <div v-for="w in startWarnings" :key="w" class="alert alert-warning">{{ w }}</div>

    <button 
      v-if="!stationActive"
      class="btn start-btn"
      @click="start"
      :disabled="!isConnected || !isArmed || !stationWaypoint"
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
import { ref, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { lat, lon, isConnected, isArmed, stationWaypoint, stationReachingRadius, stationRadius, stationActive, simMode } = storeToRefs(store)

const reachingRadius = ref(stationReachingRadius.value)
const stationRadiusLocal = ref(stationRadius.value)
const startError = ref('')
const startWarnings = ref([])

watch(reachingRadius, (val) => {
  store.stationReachingRadius = val
})

watch(stationRadiusLocal, (val) => {
  store.stationRadius = val
})

const setCurrentPosition = () => {
  store.setStation(lat.value, lon.value, reachingRadius.value, stationRadiusLocal.value)
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

  if (simMode.value === 'SIMULATION') {
    // In SIM mode, run RT simulation with single-WP approach
    const wp = stationWaypoint.value
    store.stationActive = true
    store.startRTSim({
      waypoints: [
        { lat: lat.value, lon: lon.value, radius: 5.0, speed: 1.0 },
        { lat: wp.lat, lon: wp.lon, radius: reachingRadius.value, speed: 1.0 },
      ],
      start_mode: 'first_wp',
      completion_mode: 'one_way',
    })
  } else {
    store.startStation()
  }
}

const stop = () => {
  startError.value = ''
  startWarnings.value = []
  store.stationActive = false
  if (simMode.value === 'SIMULATION') {
    store.stopRTSim()
  } else {
    store.stopStation()
  }
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
</style>
