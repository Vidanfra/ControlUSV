<template>
  <div class="sim-container">
    <!-- Left: Parameters Panel -->
    <div class="params-panel">

      <!-- ========== RT Simulation (primary) ========== -->
      <section class="section rt-section">
        <h2 class="rt-title">Real-Time Simulation</h2>
        <p class="rt-subtitle">
          Drives the live frontend/backend pipeline. PID, ALOS and waypoint
          parameters are taken from the <strong>Settings</strong> tab and the
          active <strong>Mission Plan</strong>. Only physics, environment and
          sensor parameters are configured here.
        </p>

        <div v-if="telemetry.rtSimActive" class="rt-status-banner">
          SIM RUNNING &mdash; {{ telemetry.rtSimElapsed.toFixed(1) }}s
        </div>

        <!-- Default Start Position -->
        <div class="start-pos-section">
          <h3>Default Start Position</h3>
          <div class="start-pos-row">
            <label>Lat <input type="number" v-model.number="telemetry.simDefaultLat" step="0.0001" class="coord-input" /></label>
            <label>Lon <input type="number" v-model.number="telemetry.simDefaultLon" step="0.0001" class="coord-input" /></label>
            <button
              class="btn btn-pick"
              :class="{ active: telemetry.simPickMode }"
              @click="pickFromMap"
            >
              {{ telemetry.simPickMode ? 'Click on map...' : 'Pick on Map' }}
            </button>
          </div>
        </div>

        <!-- Vehicle & environment -->
        <h3>Vehicle &amp; Environment</h3>
        <div class="param-grid">
          <label>Payload [kg]
            <input type="number" v-model.number="rtEnv.payload_kg" step="5" min="0" />
          </label>
          <label>Current Speed [m/s]
            <input type="number" v-model.number="rtEnv.current_speed" step="0.05" min="0" />
          </label>
          <label>Current Dir [&deg;]
            <input type="number" v-model.number="rtEnv.current_dir" step="5" />
          </label>
        </div>

        <!-- Sensors & runtime -->
        <h3>Sensors &amp; Runtime</h3>
        <div class="param-grid">
          <label>GNSS Mode
            <select v-model="rtGnssMode">
              <option value="rtk_fix">RTK Fix (best)</option>
              <option value="dgnss">DGNSS</option>
              <option value="gps">GPS (degraded)</option>
            </select>
          </label>
          <label>Time Step [s]
            <input type="number" v-model.number="rtTimeStep" step="0.01" min="0.01" max="0.2" />
          </label>
        </div>

        <!-- Settings being inherited -->
        <div class="rt-settings-badge" v-if="telemetry.gncConfig">
          Controller (Settings tab):
          &omega;<sub>n</sub>={{ telemetry.gncConfig.wn }},
          &zeta;={{ telemetry.gncConfig.zeta }},
          k<sub>&delta;</sub>={{ telemetry.gncConfig.k_delta }}s,
          &gamma;={{ telemetry.gncConfig.gamma }},
          cruise={{ telemetry.gncConfig.cruise_speed_kn }} kn
        </div>
        <div class="rt-settings-badge">
          Route (WP Route panel):
          direction=<strong>{{ telemetry.wpRouteDirection }}</strong>,
          completion=<strong>{{ telemetry.wpRouteCompletion }}</strong>
        </div>

        <div class="launch-row" style="margin-top: 10px;">
          <button
            class="btn btn-rt-start"
            @click="launchRTSim"
            :disabled="telemetry.rtSimActive || telemetry.missionWaypoints.length < 2"
          >
            Start RT Sim
          </button>
          <button
            class="btn btn-danger"
            @click="telemetry.stopRTSim()"
            :disabled="!telemetry.rtSimActive"
          >
            Stop
          </button>
        </div>
        <div v-if="telemetry.missionWaypoints.length < 2" class="rt-hint">
          Load a mission with &ge; 2 waypoints from the Map / Mission Planner first.
        </div>
      </section>

      <!-- ========== Static Simulation (secondary, collapsed) ========== -->
      <details class="static-section">
        <summary class="static-summary">
          Static Simulation
          <span class="static-summary-hint">model validation &amp; PID tuning &mdash; offline multi-profile compare</span>
        </summary>

        <p class="static-note">
          Static profiles run offline and let you compare up to 6 vehicle /
          controller configurations. These values do <strong>not</strong>
          affect Real-Time simulation.
        </p>

        <!-- Waypoint Source -->
        <section class="section">
          <h3>Waypoints</h3>
          <div class="btn-row">
            <button class="btn" @click="loadCurrentRoute" :disabled="telemetry.missionWaypoints.length === 0">
              Load Current Route ({{ telemetry.missionWaypoints.length }} WP)
            </button>
            <button class="btn btn-accent" @click="telemetry.navigateToMapPlanner()">
              Create New Route
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
              <input
                type="text"
                v-model="p.name"
                class="profile-name-input"
                :placeholder="`Profile ${i + 1}`"
              />
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
                <option value="last_wp">Last Waypoint (Reverse)</option>
                <option value="current_pos">Current USV Position</option>
              </select>
            </label>
            <label>Completion Mode
              <select v-model="completionMode">
                <option value="stop_time">Run Full Time</option>
                <option value="one_way">Stop at Last WP</option>
                <option value="loop">Loop (same dir)</option>
                <option value="loop_reverse">Loop (reverse)</option>
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
        </div>

        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <div v-if="successMsg" class="success-msg">{{ successMsg }}</div>
      </details>
    </div>

    <!-- Right: Results -->
    <div class="results-panel">
      <SimResults
        :results="telemetry.simulationResults"
        :waypoints="waypoints"
      />
      <div v-if="telemetry.simulationResults.length === 0" class="no-results">
        <p>No static simulation results yet.</p>
        <p>Expand <strong>Static Simulation</strong>, configure profiles and click <strong>Launch Simulation</strong>.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import SimResults from '../components/SimResults.vue'

const telemetry = useTelemetryStore()

const COLORS = ['#e6194b', '#3cb44b', '#4363d8', '#f032e6', '#42d4f4', '#fabed4']

// --- State ---
const waypoints = ref([])
const totalTime = ref(400)
const timeStep = ref(0.02)
const startMode = ref('first_wp')
const completionMode = ref('stop_time')
const errorMsg = ref('')
const successMsg = ref('')

// RT Simulation state
const rtGnssMode = ref('rtk_fix')
const rtTimeStep = ref(0.05)

// RT vehicle / environment parameters (physics only — controller gains,
// cruise speed, route direction and completion come from Settings tab and
// the WP Route panel; waypoints come from the active mission).
const defaultRtEnv = () => ({
  payload_kg: 25,
  current_speed: 0.0,
  current_dir: 0.0,
})
const rtEnv = ref(defaultRtEnv())

const defaultProfile = () => ({
  name: 'Profile 1',
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

// --- Persistence ---
const STORAGE_KEY = 'simSettings'

onMounted(() => {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    try {
      const parsed = JSON.parse(saved)
      if (parsed.waypoints) waypoints.value = parsed.waypoints
      if (parsed.profiles) profiles.value = parsed.profiles
      if (parsed.totalTime !== undefined) totalTime.value = parsed.totalTime
      if (parsed.timeStep !== undefined) timeStep.value = parsed.timeStep
      if (parsed.startMode) startMode.value = parsed.startMode
      if (parsed.completionMode) completionMode.value = parsed.completionMode
      if (parsed.rtGnssMode) rtGnssMode.value = parsed.rtGnssMode
      if (parsed.rtTimeStep !== undefined) rtTimeStep.value = parsed.rtTimeStep
      if (parsed.simDefaultLat !== undefined) telemetry.simDefaultLat = parsed.simDefaultLat
      if (parsed.simDefaultLon !== undefined) telemetry.simDefaultLon = parsed.simDefaultLon
      if (parsed.rtEnv) {
        rtEnv.value = { ...defaultRtEnv(), ...parsed.rtEnv }
      } else if (parsed.profiles && parsed.profiles[0]) {
        // Migrate from legacy schema: seed rtEnv from old profile 0.
        const p0 = parsed.profiles[0]
        rtEnv.value = {
          payload_kg:    p0.payload_kg    ?? 25,
          current_speed: p0.current_speed ?? 0.0,
          current_dir:   p0.current_dir   ?? 0.0,
        }
      }
    } catch (e) {
      console.error('Failed to load sim settings', e)
    }
  }
})

watch(
  [waypoints, profiles, rtEnv, totalTime, timeStep, startMode, completionMode, rtGnssMode, rtTimeStep],
  () => {
    const toSave = {
      waypoints: waypoints.value,
      profiles: profiles.value,
      rtEnv: rtEnv.value,
      totalTime: totalTime.value,
      timeStep: timeStep.value,
      startMode: startMode.value,
      completionMode: completionMode.value,
      rtGnssMode: rtGnssMode.value,
      rtTimeStep: rtTimeStep.value,
      simDefaultLat: telemetry.simDefaultLat,
      simDefaultLon: telemetry.simDefaultLon,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave))
  },
  { deep: true }
)

// Also watch store default position to persist it when changed from map pick
watch(
  () => [telemetry.simDefaultLat, telemetry.simDefaultLon],
  () => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
      saved.simDefaultLat = telemetry.simDefaultLat
      saved.simDefaultLon = telemetry.simDefaultLon
      localStorage.setItem(STORAGE_KEY, JSON.stringify(saved))
    } catch (e) { /* ignore */ }
  }
)

function addProfile() {
  const p = defaultProfile()
  p.profile_id = profiles.value.length
  p.name = `Profile ${profiles.value.length + 1}`
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
      // Also sync to store so the map shows them
      telemetry.missionWaypoints = data.waypoints.map(wp => ({
        lat: wp.lat, lon: wp.lon, radius: wp.radius || 5.0, speed: wp.speed || 1.0
      }))
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
      completion_mode: completionMode.value,
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
  } else {
    successMsg.value = `Simulation complete — ${result.results.length} profile(s), ${result.results[0]?.time?.length || 0} data points each`
    setTimeout(() => { successMsg.value = '' }, 8000)
  }
}

function launchRTSim() {
  const startLat = telemetry.simStartWaypoint?.lat ?? telemetry.simDefaultLat
  const startLon = telemetry.simStartWaypoint?.lon ?? telemetry.simDefaultLon
  // Backend RT sim ignores controller-tuning, start_mode and completion_mode
  // (they come from Settings / WP Route panel respectively), and surge_force
  // is shadowed by the cruise-speed slider, so only physics/environment and
  // sensor parameters are forwarded here.
  telemetry.startRTSim({
    current_lat:     startLat,
    current_lon:     startLon,
    current_heading: telemetry.heading,
    // Vehicle / environment (physics)
    payload_kg:    rtEnv.value.payload_kg    ?? 25,
    current_speed: rtEnv.value.current_speed ?? 0.0,
    current_dir:   rtEnv.value.current_dir   ?? 0.0,
    // Sensor / runtime
    gnss_mode: rtGnssMode.value,
    time_step: rtTimeStep.value,
  })
}

function pickFromMap() {
  telemetry.simPickMode = !telemetry.simPickMode
  if (telemetry.simPickMode) {
    telemetry.currentTab = 'map'
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

.btn-accent {
  background: #27ae60;
}
.btn-accent:hover:not(:disabled) { background: #2ecc71; }

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

.btn-danger { background: #c62828; color: white; border-color: #c62828; }
.btn-danger:hover { background: #e53935; }

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

.profile-name-input {
  flex: 1;
  background: #2a2a2a;
  border: 1px solid #555;
  border-radius: 3px;
  color: #eee;
  font-size: 0.85rem;
  font-weight: bold;
  padding: 2px 6px;
  min-width: 0;
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
  color: #e53935;
  font-size: 0.85rem;
  margin-top: 8px;
  padding: 6px 10px;
  background: rgba(180, 0, 0, 0.12);
  border: 1px solid #9a0000;
  border-radius: 4px;
}

.success-msg {
  color: #2ecc71;
  font-size: 0.85rem;
  margin-top: 8px;
  padding: 6px 10px;
  background: #1a2c1a;
  border: 1px solid #2a5a2a;
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

/* RT Simulation Section */
.rt-section {
  border: 1px solid #FFA500;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 18px;
  background: #1a1612;
}

.rt-title {
  color: #FFA500 !important;
  margin: 0 0 6px 0;
  font-size: 1.1rem;
}

.rt-subtitle {
  font-size: 0.75rem;
  color: #999;
  margin: 0 0 12px 0;
  line-height: 1.35;
}

.rt-settings-badge {
  margin-top: 10px;
  padding: 5px 8px;
  background: #14181d;
  border: 1px dashed #3a4250;
  border-radius: 4px;
  color: #8aa;
  font-size: 0.72rem;
  font-family: 'Consolas', monospace;
}

/* Static Simulation collapsible */
.static-section {
  border: 1px solid #333;
  border-radius: 6px;
  padding: 0 12px;
  background: #181818;
}
.static-section[open] {
  padding-bottom: 12px;
}
.static-summary {
  cursor: pointer;
  padding: 10px 0;
  font-size: 0.95rem;
  color: #ccc;
  font-weight: bold;
  list-style: none;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.static-summary::-webkit-details-marker { display: none; }
.static-summary::before {
  content: '\25B6';
  font-size: 0.7rem;
  color: #888;
  transition: transform 0.15s;
}
.static-section[open] .static-summary::before {
  transform: rotate(90deg);
}
.static-summary-hint {
  font-weight: normal;
  font-size: 0.72rem;
  color: #777;
}
.static-note {
  font-size: 0.75rem;
  color: #888;
  margin: 0 0 10px 0;
  line-height: 1.35;
}

.rt-status-banner {
  background: #5a3e00;
  border: 1px solid #FFA500;
  color: #FFA500;
  text-align: center;
  font-weight: bold;
  font-size: 0.82rem;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 10px;
  animation: pulse-rt 1.5s ease-in-out infinite;
}

@keyframes pulse-rt {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.btn-rt-start {
  background: #00C851;
}
.btn-rt-start:hover:not(:disabled) { background: #00a543; }

.rt-hint {
  font-size: 0.75rem;
  color: #888;
  margin-top: 6px;
}

.rt-profile-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.78rem;
  color: #aaa;
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 5px 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.start-pos-section {
  margin-bottom: 10px;
}
.start-pos-section label {
  display: block;
  font-size: 0.82rem;
  color: #ccc;
  margin-bottom: 4px;
}
.start-pos-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.coord-input {
  width: 110px;
  padding: 4px 6px;
  background: #1e1e1e;
  color: #fff;
  border: 1px solid #555;
  border-radius: 4px;
  font-size: 0.8rem;
}
.coord-input:focus {
  border-color: #4fc3f7;
  outline: none;
}
.btn-pick {
  padding: 4px 10px;
  background: #333;
  color: #ccc;
  border: 1px solid #555;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.78rem;
  white-space: nowrap;
}
.btn-pick:hover {
  background: #444;
}
.btn-pick.active {
  background: #4fc3f7;
  color: #000;
  border-color: #4fc3f7;
  animation: pulse-pick 1s infinite;
}
@keyframes pulse-pick {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
