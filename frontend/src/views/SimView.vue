<template>
  <div class="sim-container">
    <!-- Left: Parameters Panel -->
    <div class="params-panel">
      <h2>Simulation Setup</h2>

      <!-- Waypoint Source -->
      <section class="section">
        <h3>Waypoints</h3>
        <div class="btn-row">
          <button class="btn" @click="loadCurrentRoute" :disabled="telemetry.missionWaypoints.length === 0">
            Load Current Route ({{ telemetry.missionWaypoints.length }} WP)
          </button>
          <label class="btn btn-secondary file-label">
            Browse CSV
            <input type="file" accept=".csv,.txt" @change="onCsvUpload" hidden />
          </label>
        </div>
        <div v-if="waypoints.length > 0" class="wp-summary">
          {{ waypoints.length }} waypoints loaded
          <button class="btn-sm btn-danger" @click="waypoints = []">Clear</button>
        </div>
        <table v-if="waypoints.length > 0" class="wp-table">
          <thead><tr><th>#</th><th>Lat</th><th>Lon</th><th>Radius</th><th>Speed</th></tr></thead>
          <tbody>
            <tr v-for="(wp, i) in waypoints" :key="i">
              <td>{{ i + 1 }}</td>
              <td>{{ wp.lat.toFixed(6) }}</td>
              <td>{{ wp.lon.toFixed(6) }}</td>
              <td><input type="number" v-model.number="wp.radius" step="1" min="1" class="num-input" /></td>
              <td><input type="number" v-model.number="wp.speed" step="0.1" min="0.1" class="num-input" /></td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Profiles -->
      <section class="section">
        <h3>Profiles 
          <button class="btn-sm" @click="addProfile" :disabled="profiles.length >= 6">+ Add</button>
        </h3>
        <div v-for="(p, i) in profiles" :key="i" class="profile-card">
          <div class="profile-header">
            <span class="profile-dot" :style="{ background: COLORS[i % COLORS.length] }"></span>
            <strong>Profile {{ i }}</strong>
            <button v-if="profiles.length > 1" class="btn-sm btn-danger" @click="profiles.splice(i, 1)">x</button>
          </div>
          <div class="param-grid">
            <label>Payload [kg]<input type="number" v-model.number="p.payload_kg" step="5" min="0" /></label>
            <label>PID &omega;<sub>n</sub><input type="number" v-model.number="p.wn_pid" step="0.5" min="0.1" /></label>
            <label>PID &zeta;<input type="number" v-model.number="p.zeta_pid" step="0.1" min="0.1" /></label>
            <label>Ref &omega;<sub>n</sub><input type="number" v-model.number="p.wn_ref" step="0.1" min="0.1" /></label>
            <label>Ref &zeta;<input type="number" v-model.number="p.zeta_ref" step="0.1" min="0.1" /></label>
            <label>ALOS &delta; [m]<input type="number" v-model.number="p.delta" step="1" min="1" /></label>
            <label>ALOS &gamma;<input type="number" v-model.number="p.gamma" step="0.01" min="0" /></label>
            <label>Current [m/s]<input type="number" v-model.number="p.current_speed" step="0.05" min="0" /></label>
            <label>Curr Dir [&deg;]<input type="number" v-model.number="p.current_dir" step="5" /></label>
            <label>Surge F [N]<input type="number" v-model.number="p.surge_force" step="10" min="0" /></label>
          </div>
        </div>
      </section>

      <!-- Simulation Settings -->
      <section class="section">
        <h3>Settings</h3>
        <div class="param-grid">
          <label>Total Time [s]<input type="number" v-model.number="totalTime" step="50" min="10" /></label>
          <label>Time Step [s]<input type="number" v-model.number="timeStep" step="0.01" min="0.005" /></label>
          <label>Start Position
            <select v-model="startMode">
              <option value="first_wp">First Waypoint</option>
              <option value="current_pos">Current USV Position</option>
            </select>
          </label>
        </div>
      </section>

      <!-- Launch -->
      <div class="launch-row">
        <button 
          class="btn btn-launch" 
          @click="launchSimulation" 
          :disabled="waypoints.length < 2 || telemetry.simulationRunning"
        >
          {{ telemetry.simulationRunning ? 'Running...' : 'Launch Simulation' }}
        </button>
        <button 
          v-if="telemetry.simulationResults.length > 0"
          class="btn btn-secondary"
          @click="telemetry.clearSimulation()"
        >
          Clear Results
        </button>
        <button
          v-if="telemetry.simulationResults.length > 0"
          class="btn btn-secondary"
          @click="telemetry.toggleSimOverlay()"
        >
          {{ telemetry.simulationOverlayVisible ? 'Hide Overlay' : 'Show Overlay' }}
        </button>
      </div>

      <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
    </div>

    <!-- Right: Results -->
    <div class="results-panel">
      <SimResults 
        :results="telemetry.simulationResults" 
        :waypoints="waypoints"
      />
      <div v-if="telemetry.simulationResults.length === 0" class="no-results">
        <p>No simulation results yet.</p>
        <p>Configure waypoints and parameters, then click <strong>Launch Simulation</strong>.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import SimResults from '../components/SimResults.vue'

const telemetry = useTelemetryStore()

const COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']

// --- State ---
const waypoints = ref([])
const totalTime = ref(400)
const timeStep = ref(0.02)
const startMode = ref('first_wp')
const errorMsg = ref('')

const defaultProfile = () => ({
  profile_id: 0,
  payload_kg: 25,
  wn_pid: 4.0,
  zeta_pid: 0.5,
  wn_ref: 1.0,
  zeta_ref: 1.0,
  delta: 5.0,
  gamma: 0.0,
  current_speed: 0.0,
  current_dir: 0.0,
  surge_force: 150,
  start_mode: 'first_wp',
})

const profiles = ref([defaultProfile()])

function addProfile() {
  const p = defaultProfile()
  p.profile_id = profiles.value.length
  profiles.value.push(p)
}

function loadCurrentRoute() {
  waypoints.value = telemetry.missionWaypoints.map(wp => ({
    lat: wp.lat,
    lon: wp.lon,
    radius: wp.radius || 5.0,
    speed: wp.speed || 1.0,
  }))
}

async function onCsvUpload(e) {
  const file = e.target.files[0]
  if (!file) return
  const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`
  const formData = new FormData()
  formData.append('file', file)
  try {
    const resp = await fetch(`${baseUrl}/api/upload-waypoints`, {
      method: 'POST',
      body: formData,
    })
    const data = await resp.json()
    if (data.status === 'ok') {
      waypoints.value = data.waypoints
      errorMsg.value = ''
    } else {
      errorMsg.value = data.message || 'CSV parse failed'
    }
  } catch (err) {
    errorMsg.value = err.message
  }
  // Reset file input
  e.target.value = ''
}

async function launchSimulation() {
  if (waypoints.value.length < 2) {
    errorMsg.value = 'Need at least 2 waypoints'
    return
  }
  errorMsg.value = ''

  const request = {
    configs: profiles.value.map((p, i) => ({
      ...p,
      profile_id: i,
      start_mode: startMode.value,
    })),
    waypoints: waypoints.value,
    total_time: totalTime.value,
    time_step: timeStep.value,
    current_lat: telemetry.lat,
    current_lon: telemetry.lon,
    current_heading: telemetry.bestHeading,
  }

  const result = await telemetry.runSimulation(request)
  if (!result.ok) {
    errorMsg.value = result.message || 'Simulation failed'
  }
}
</script>

<style scoped>
.sim-container {
  display: flex;
  height: calc(100vh - 50px);
  background: #121212;
  color: #ddd;
  overflow: hidden;
}

.params-panel {
  width: 400px;
  min-width: 340px;
  padding: 15px;
  overflow-y: auto;
  border-right: 2px solid #333;
  flex-shrink: 0;
}

.results-panel {
  flex: 1;
  padding: 15px;
  overflow-y: auto;
}

h2 {
  color: #FFA500;
  margin: 0 0 15px 0;
  font-size: 1.2rem;
}

h3 {
  color: #ccc;
  font-size: 0.95rem;
  margin: 12px 0 8px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section {
  margin-bottom: 15px;
  padding-bottom: 12px;
  border-bottom: 1px solid #333;
}

/* Buttons */
.btn-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.btn {
  padding: 6px 14px;
  border: none;
  border-radius: 4px;
  background: #2a6caa;
  color: white;
  font-weight: bold;
  font-size: 0.8rem;
  cursor: pointer;
  transition: background 0.2s;
}
.btn:hover:not(:disabled) { background: #3580c4; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-secondary {
  background: #444;
}
.btn-secondary:hover:not(:disabled) { background: #555; }

.btn-launch {
  background: #e67e22;
  font-size: 0.95rem;
  padding: 10px 24px;
}
.btn-launch:hover:not(:disabled) { background: #f39c12; }

.btn-sm {
  padding: 2px 8px;
  font-size: 0.7rem;
  border: 1px solid #555;
  border-radius: 3px;
  background: #333;
  color: #ccc;
  cursor: pointer;
}
.btn-sm:hover { background: #444; }

.btn-danger { background: #c0392b; color: white; border-color: #c0392b; }
.btn-danger:hover { background: #e74c3c; }

.file-label {
  display: inline-block;
  text-align: center;
}

/* Waypoint table */
.wp-summary {
  font-size: 0.8rem;
  margin: 6px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.wp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
  margin-top: 6px;
}
.wp-table th {
  background: #222;
  padding: 4px 6px;
  text-align: left;
  color: #aaa;
  border-bottom: 1px solid #444;
}
.wp-table td {
  padding: 3px 6px;
  border-bottom: 1px solid #2a2a2a;
}

.num-input {
  width: 55px;
  background: #1a1a1a;
  border: 1px solid #444;
  color: #ddd;
  padding: 2px 4px;
  border-radius: 3px;
  font-size: 0.75rem;
}

/* Profile cards */
.profile-card {
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
}

.profile-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 0.85rem;
}

.profile-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.param-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 10px;
}

.param-grid label {
  font-size: 0.75rem;
  color: #aaa;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.param-grid input, .param-grid select {
  background: #1a1a1a;
  border: 1px solid #444;
  color: #ddd;
  padding: 4px 6px;
  border-radius: 3px;
  font-size: 0.8rem;
}

.launch-row {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.error-msg {
  color: #e74c3c;
  font-size: 0.85rem;
  margin-top: 8px;
  padding: 6px 10px;
  background: #2c1a1a;
  border: 1px solid #5a2a2a;
  border-radius: 4px;
}

.no-results {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 300px;
  color: #666;
  text-align: center;
}
.no-results p {
  margin: 4px 0;
}
</style>
