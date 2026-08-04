<template>
  <div class="planner-panel">
    <!-- ─── Header ──────────────────────────────────────────────── -->
    <h3>Mission Plan</h3>
    <div class="item-count-row">{{ middleItems.length }} items · {{ missionWaypoints.length }} WPs</div>

    <!-- ─── Mission Items List ───────────────────────────────────── -->
    <div class="items-list">

      <!-- Mission Start (fixed) -->
      <div class="item-row item-fixed" :class="{ 'item-picking': store.activeMissionWpId === missionStart?.id }">
        <span class="item-badge badge-start">P</span>
        <div class="item-body">
          <span class="item-label">Mission Start</span>
          <span class="item-coords" v-if="missionStart?.lat">
            {{ missionStart.lat.toFixed(6) }}, {{ missionStart.lon.toFixed(6) }}
          </span>
          <span class="item-coords dim" v-else>Not set</span>
          <div class="wp-params">
            <label>R:<input type="number" v-model.number="missionStart.radius" min="1" max="50" step="1" class="param-input" @change="patchItem(missionStart.id,{radius:missionStart.radius})" :disabled="wpRouteActive" /></label>
            <label>kn:<input type="number" v-model.number="missionStart.speed" min="0.1" max="4.0" step="0.1" class="param-input" @change="patchItem(missionStart.id,{speed:missionStart.speed})" :disabled="wpRouteActive" /></label>
          </div>
        </div>
        <div class="item-actions">
          <button class="act-btn act-pos" title="Use current vehicle position" @click="useCurrentPosition" :disabled="wpRouteActive">⊕</button>
          <button class="act-btn act-map" :class="{ active: store.activeMissionWpId === missionStart?.id }"
            title="Pick on map" @click="pickMissionStart" :disabled="wpRouteActive">📍</button>
        </div>
      </div>

      <!-- Middle items (draggable) -->
      <template v-for="(item, idx) in middleItems" :key="item.id">
        <!-- ── Waypoint item ── -->
        <div v-if="item.type === 'waypoint'"
          class="item-row item-waypoint"
          :class="{
            'item-picking': store.activeMissionWpId === item.id,
            'drag-over': dragOverId === item.id
          }"
          draggable="true"
          @dragstart="onDragStart($event, idx)"
          @dragover.prevent="onDragOver($event, item.id)"
          @dragleave="dragOverId = null"
          @drop="onDrop($event, idx)"
          @dragend="dragOverId = null"
        >
          <span class="drag-handle" title="Drag to reorder">⠿</span>
          <span class="item-badge badge-wp">{{ idx + 1 }}</span>
          <div class="item-body">
            <span class="item-label">Waypoint</span>
            <span class="item-coords" v-if="item.lat">
              {{ item.lat.toFixed(6) }}, {{ item.lon.toFixed(6) }}
            </span>
            <span class="item-coords dim" v-else>Click map to place</span>
            <div class="wp-params">
              <label>R:<input type="number" v-model.number="item.radius" min="1" max="50" step="1" class="param-input" @change="patchItem(item.id,{radius:item.radius})" /></label>
              <label>kn:<input type="number" v-model.number="item.speed" min="0.1" max="4.0" step="0.1" class="param-input" @change="patchItem(item.id,{speed:item.speed})" /></label>
            </div>
          </div>
          <div class="item-actions">
            <button class="act-btn act-map" :class="{ active: store.activeMissionWpId === item.id }"
              title="Pick on map" @click="pickWaypoint(item.id)" :disabled="wpRouteActive">📍</button>
            <button class="act-btn act-del" title="Remove" @click="store.removeMissionItem(item.id)" :disabled="wpRouteActive">✕</button>
          </div>
        </div>

        <!-- ── Survey item ── -->
        <div v-else-if="item.type === 'survey'"
          class="item-row item-survey"
          :class="{
            'item-active-survey': store.activeSurveyId === item.id,
            'drag-over': dragOverId === item.id
          }"
          draggable="true"
          @dragstart="onDragStart($event, idx)"
          @dragover.prevent="onDragOver($event, item.id)"
          @dragleave="dragOverId = null"
          @drop="onDrop($event, idx)"
          @dragend="dragOverId = null"
        >
          <span class="drag-handle">⠿</span>
          <span class="item-badge badge-survey">S</span>
          <div class="item-body">
            <div class="survey-header" @click="toggleSurveyExpand(item.id)">
              <span class="item-label">Survey {{ surveyNumber(item.id) }}</span>
              <span class="survey-info">
                {{ item.polygon.length }} vtx · {{ surveyWpCount(item) }} WPs
              </span>
              <span class="chevron">{{ expandedSurveyId === item.id ? '▲' : '▼' }}</span>
            </div>

            <!-- Expanded survey editor -->
            <div v-if="expandedSurveyId === item.id" class="survey-editor">
              <div class="param-grid">
                <label class="param-row">
                  <span>Angle (°N)</span>
                  <div class="param-input-group">
                    <input type="number" v-model.number="item.lineAngle" min="-180" max="180" step="1"
                      class="param-input wide" @change="patchItem(item.id,{lineAngle:item.lineAngle})" />
                    <span class="param-unit">°</span>
                  </div>
                </label>
                <label class="param-row">
                  <span>Line Spacing</span>
                  <div class="param-input-group">
                    <input type="number" v-model.number="item.lineSpacing" min="5" max="500" step="1"
                      class="param-input wide" @change="patchItem(item.id,{lineSpacing:item.lineSpacing})" />
                    <span class="param-unit">m</span>
                  </div>
                </label>
                <label class="param-row">
                  <span>Turnaround</span>
                  <div class="param-input-group">
                    <input type="number" v-model.number="item.lineExtension" min="0" max="200" step="1"
                      class="param-input wide" @change="patchItem(item.id,{lineExtension:item.lineExtension})" />
                    <span class="param-unit">m</span>
                  </div>
                </label>
                <label class="param-row">
                  <span>Accept. Radius</span>
                  <div class="param-input-group">
                    <input type="number" v-model.number="item.radius" min="1" max="30" step="1"
                      class="param-input wide" @change="patchItem(item.id,{radius:item.radius})" />
                    <span class="param-unit">m</span>
                  </div>
                </label>
                <label class="param-row">
                  <span>Speed</span>
                  <div class="param-input-group">
                    <input type="number" v-model.number="item.speed" min="0.1" max="4.0" step="0.1"
                      class="param-input wide" @change="patchItem(item.id,{speed:item.speed})" />
                    <span class="param-unit">kn</span>
                  </div>
                </label>
                <label class="param-row">
                  <span>Start Corner</span>
                  <div class="toggle-group">
                    <button class="tog-btn" :class="{ active: item.startWP === 0 }" @click="patchItem(item.id,{startWP:0})" :disabled="wpRouteActive">A</button>
                    <button class="tog-btn" :class="{ active: item.startWP === 1 }" @click="patchItem(item.id,{startWP:1})" :disabled="wpRouteActive">B</button>
                  </div>
                </label>
              </div>

              <!-- Polygon tools -->
              <div class="poly-tools">
                <button class="btn btn-poly"
                  :class="{ active: store.activeSurveyId === item.id && store.surveyDrawMode }"
                  @click="toggleDrawPolygon(item.id)"
                  :disabled="wpRouteActive">
                  {{ (store.activeSurveyId === item.id && store.surveyDrawMode) ? '✓ CLOSE POLYGON' : '✏ DRAW POLYGON' }}
                </button>
                <button class="btn btn-poly-edit"
                  v-if="item.polygon.length >= 3 && !store.surveyDrawMode"
                  :class="{ active: store.activeSurveyId === item.id }"
                  @click="toggleEditPolygon(item.id)"
                  :disabled="wpRouteActive">
                  {{ store.activeSurveyId === item.id ? '✓ DONE EDIT' : '⤢ EDIT POLYGON' }}
                </button>
                <button class="btn btn-poly-clear"
                  v-if="item.polygon.length > 0"
                  @click="clearPoly(item.id)"
                  :disabled="wpRouteActive">
                  🗑 CLEAR
                </button>
              </div>
              <div v-if="store.activeSurveyId === item.id && store.surveyDrawMode" class="draw-hint">
                Click map to add vertices. Double-click or press CLOSE POLYGON to finish.
              </div>
            </div>
          </div>
          <div class="item-actions">
            <button class="act-btn act-del" title="Remove" @click="store.removeMissionItem(item.id)" :disabled="wpRouteActive">✕</button>
          </div>
        </div>
      </template>

      <!-- Mission End (fixed, editable) -->
      <div class="item-row item-fixed" :class="{ 'item-picking': store.activeMissionWpId === missionEnd?.id }">
        <span class="item-badge badge-end">F</span>
        <div class="item-body">
          <span class="item-label">Mission End</span>
          <span class="item-coords" v-if="missionEnd?.lat !== null">
            {{ missionEnd.lat.toFixed(6) }}, {{ missionEnd.lon.toFixed(6) }}
          </span>
          <span class="item-coords dim" v-else>Not set</span>
          <div class="wp-params">
            <label>R:<input type="number" v-model.number="missionEnd.radius" min="1" max="50" step="1" class="param-input" @change="patchItem(missionEnd.id,{radius:missionEnd.radius})" :disabled="wpRouteActive" /></label>
            <label>kn:<input type="number" v-model.number="missionEnd.speed" min="0.1" max="4.0" step="0.1" class="param-input" @change="patchItem(missionEnd.id,{speed:missionEnd.speed})" :disabled="wpRouteActive" /></label>
          </div>
        </div>
        <div class="item-actions">
          <button class="act-btn act-pos" title="Use current vehicle position" @click="useCurrentPositionEnd" :disabled="wpRouteActive">⊕</button>
          <button class="act-btn act-map" :class="{ active: store.activeMissionWpId === missionEnd?.id }"
            title="Pick on map" @click="pickMissionEnd" :disabled="wpRouteActive">📍</button>
        </div>
      </div>
    </div><!-- /items-list -->

    <!-- ─── Add Buttons ──────────────────────────────────────────── -->
    <div class="add-row" v-if="!wpRouteActive">
      <button class="btn btn-add-wp" @click="store.addMissionItem('waypoint')">+ Waypoint</button>
      <button class="btn btn-add-survey" @click="addAndExpandSurvey">+ Survey</button>
    </div>

    <!-- ─── Home WP ──────────────────────────────────────────────── -->
    <div class="section-divider"></div>
    <div class="field">
      <label>Home WP</label>
      <div class="home-row">
        <span v-if="homeWaypoint" class="coord">
          {{ homeWaypoint.lat.toFixed(6) }}, {{ homeWaypoint.lon.toFixed(6) }}
        </span>
        <span v-else class="coord dim">Not set</span>
        <button class="btn home-btn" :class="{ active: store.homePickMode }"
          @click="setHome" :disabled="wpRouteActive">
          {{ store.homePickMode ? 'PICKING...' : 'SET HOME' }}
        </button>
      </div>
    </div>

    <!-- ─── Execution Options ────────────────────────────────────── -->
    <div class="field">
      <label>Direction</label>
      <div class="toggle-group">
        <button class="tog-btn" :class="{ active: direction === 'forward' }" @click="direction = 'forward'" :disabled="wpRouteActive">FWD</button>
        <button class="tog-btn" :class="{ active: direction === 'reverse' }" @click="direction = 'reverse'" :disabled="wpRouteActive || missionWaypoints.length <= 1">REV</button>
      </div>
    </div>
    <div class="field">
      <label>On Finish</label>
      <select v-model="completion" :disabled="wpRouteActive || missionWaypoints.length <= 1">
        <option value="stop">Stop</option>
        <option value="loop" :disabled="missionWaypoints.length <= 1">Loop</option>
        <option value="loop_reverse" :disabled="missionWaypoints.length <= 1">Loop &amp; Reverse</option>
      </select>
    </div>

    <!-- ─── Cruise Speed ─────────────────────────────────────────────── -->
    <div class="field surge-field">
      <label>Cruise Speed</label>
      <div class="surge-slider-container">
        <input type="range" v-model.number="cruiseSpeedKn" min="0.1" max="4.0" step="0.1"
          class="surge-slider" />
        <span class="surge-val">{{ cruiseSpeedKn.toFixed(1) }} kn</span>
      </div>
      <div class="surge-metrics">
        <span>Force: {{ surgeForceN.toFixed(1) }} N</span>
        <span>Speed: {{ speedMs.toFixed(2) }} m/s</span>
      </div>
    </div>

    <!-- ─── Route Precalculation ─────────────────────────────────── -->
    <div class="field">
      <div class="precalc-btn-row">
        <button class="btn btn-precalc"
          @click="precalculateRoute"
          :disabled="missionWaypoints.length < 2 || precalcLoading">
          {{ precalcLoading ? 'CALCULATING…' : '⏱ PRECALCULATE ROUTE' }}
        </button>
        <button v-if="store.simulationResults.length > 0" class="btn btn-clear-sim"
          title="Clear simulation from map" @click="clearPrecalc">✕</button>
      </div>
      <div v-if="precalcError" class="alert alert-error">{{ precalcError }}</div>
      <div v-if="precalcResult" class="precalc-box">
        <div class="precalc-row"><span>Distance</span><strong>{{ (precalcResult.distanceM / 1000).toFixed(2) }} km</strong></div>
        <div class="precalc-row"><span>Est. Duration</span><strong>{{ formatDuration(precalcResult.etaS) }}</strong></div>
        <div class="precalc-row"><span>Avg. Speed</span><strong>{{ precalcResult.avgSpeedKn.toFixed(2) }} kn</strong></div>
        <div v-if="!precalcResult.completed" class="precalc-hint">
          Route did not finish inside the simulated window — duration is a lower bound. Track shown on map (SHOW SIM).
        </div>
        <div v-else class="precalc-hint">Simulated track shown on map (SHOW SIM).</div>
      </div>
    </div>

    <!-- ─── Pre-flight alerts ────────────────────────────────────── -->
    <div v-if="startError" class="alert alert-error">{{ startError }}</div>
    <div v-for="w in startWarnings" :key="w" class="alert alert-warning">{{ w }}</div>

    <!-- ─── Start / Stop ─────────────────────────────────────────── -->
    <button v-if="!wpRouteActive" class="btn start-btn"
      @click="start" :disabled="!isConnected || (!isArmed && !rtSimActive) || missionWaypoints.length === 0">
      START MISSION ({{ missionWaypoints.length }} WPs)
    </button>
    <button v-else class="btn stop-btn" @click="stop" :disabled="!isConnected">
      STOP
    </button>

    <!-- ─── File Actions ─────────────────────────────────────────── -->
    <div class="file-row">
      <button class="btn file-btn" @click="saveCsv" :disabled="missionWaypoints.length === 0">SAVE CSV</button>
      <label class="btn file-btn file-label">
        LOAD CSV
        <input ref="fileInput" type="file" accept=".csv,.txt" @change="loadCsv" hidden />
      </label>
      <button class="btn clear-btn" @click="store.clearMissionItems()" :disabled="wpRouteActive">CLEAR</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'
import { generateLawnmower } from '../composables/useSurveyGenerator.js'

const store = useTelemetryStore()
const { isConnected, isArmed, rtSimActive, missionWaypoints, wpRouteActive, simMode, homeWaypoint } = storeToRefs(store)

// ── Local UI state ────────────────────────────────────────────────────────────
const direction = ref('forward')
const completion = ref('stop')
// Initialise from store (localStorage → first backend heartbeat overwrites it)
const cruiseSpeedKn = ref(store.gncConfig?.cruise_speed_kn ?? 3.2)
// Keep slider in sync when the backend broadcasts a new gnc_config (e.g. after restart)
watch(() => store.gncConfig?.cruise_speed_kn, (val) => {
  if (!wpRouteActive.value && val !== undefined) cruiseSpeedKn.value = val
})
// Push live speed changes to backend while route is active (debounced 300 ms)
let _cruiseSpeedTimer = null
watch(cruiseSpeedKn, (val) => {
  if (!wpRouteActive.value) return
  clearTimeout(_cruiseSpeedTimer)
  _cruiseSpeedTimer = setTimeout(() => {
    store.setGncConfig({ cruise_speed_kn: val })
  }, 300)
})
const fileInput = ref(null)
const startError = ref('')
const startWarnings = ref([])
const expandedSurveyId = ref(null)
const dragSrcIdx = ref(null)
const dragOverId = ref(null)
const precalcLoading = ref(false)
const precalcError = ref('')
const precalcResult = ref(null)

// ── Derived mission item views ────────────────────────────────────────────────
const missionStart = computed(() => store.missionItems.find(i => i.type === 'mission_start'))
const missionEnd   = computed(() => store.missionItems.find(i => i.type === 'mission_end'))
const middleItems  = computed(() => store.missionItems.filter(i => i.type !== 'mission_start' && i.type !== 'mission_end'))

// ── Cruise speed slider (knots, 0.1–4.0 kn) ─────────────────────────────────────
const KN_TO_MS = 0.5144
const speedMs     = computed(() => cruiseSpeedKn.value * KN_TO_MS)
const surgeForceN = computed(() => {
  const v = speedMs.value
  return 21.94 * v + 42.58 * v * v
})

// ── Route precalculation (runs the physics simulation with the current
//    mission waypoints, the Simulation tab's vehicle/environment settings
//    and the live GNC controller gains) ─────────────────────────────────────
function haversineDistance(lat1, lon1, lat2, lon2) {
  const R = 6371000
  const toRad = d => d * Math.PI / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}
function totalRouteDistance(wps) {
  let d = 0
  for (let i = 1; i < wps.length; i++) {
    d += haversineDistance(wps[i - 1].lat, wps[i - 1].lon, wps[i].lat, wps[i].lon)
  }
  return d
}
function getSimEnv() {
  // Vehicle/environment params configured in the Simulation tab ("Vehicle & Environment")
  try {
    const saved = JSON.parse(localStorage.getItem('simSettings') || '{}')
    return {
      payload_kg: saved.rtEnv?.payload_kg ?? 25,
      current_speed: saved.rtEnv?.current_speed ?? 0.0,
      current_dir: saved.rtEnv?.current_dir ?? 0.0,
    }
  } catch {
    return { payload_kg: 25, current_speed: 0.0, current_dir: 0.0 }
  }
}
function formatDuration(s) {
  s = Math.max(0, Math.round(s))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}
async function precalculateRoute() {
  precalcError.value = ''
  precalcResult.value = null
  const wps = missionWaypoints.value
  if (wps.length < 2) {
    precalcError.value = 'Need at least 2 waypoints to precalculate.'
    return
  }

  const distanceM = totalRouteDistance(wps)
  const naiveEtaS = speedMs.value > 0.05 ? distanceM / speedMs.value : 0
  // Generous time budget so the sim always has room to finish, no matter how
  // long the route is. The backend breaks out of the loop as soon as the
  // route completes (completion_mode 'one_way'), so a large upper bound here
  // costs nothing for normal routes — it's only a safety ceiling in case the
  // vehicle can never reach the last waypoint.
  const totalTimeBudget = Math.min(Math.max(naiveEtaS * 4 + 300, 120), 14 * 3600)

  const env = getSimEnv()
  const gnc = store.gncConfig || {}

  const request = {
    configs: [{
      profile_id: 0,
      payload_kg: env.payload_kg,
      wn_pid: gnc.wn ?? 1.7,
      zeta_pid: gnc.zeta ?? 0.7,
      wn_ref: gnc.wn_ref ?? 0.7,
      zeta_ref: gnc.zeta_ref ?? 0.9,
      delta: gnc.delta_min ?? 5.0,
      k_delta: gnc.k_delta ?? 15.0,
      gamma: gnc.gamma ?? 0.0,
      current_speed: env.current_speed,
      current_dir: env.current_dir,
      // Derive thrust from the mission cruise speed via the same drag inversion
      // the real vehicle uses (backend reads cruise_speed_kn). surge_force is a
      // fallback only.
      cruise_speed_kn: cruiseSpeedKn.value,
      surge_force: surgeForceN.value,
      e_x_threshold_deg: gnc.e_x_threshold_deg ?? 10.0,
      vel_profiler_enabled: gnc.vel_profiler_enabled ?? true,
      accel_ms2: gnc.accel_ms2 ?? 0.3,
      start_mode: 'first_wp',
      completion_mode: 'one_way',
    }],
    waypoints: wps,
    total_time: totalTimeBudget,
    time_step: 0.05,
    current_lat: store.lat,
    current_lon: store.lon,
    current_heading: store.bestHeading,
  }

  precalcLoading.value = true
  const result = await store.runSimulation(request)
  precalcLoading.value = false

  if (!result.ok) {
    precalcError.value = result.message || 'Precalculation failed'
    return
  }

  const r = result.results[0]
  const completed = r.mission_complete_time !== null && r.mission_complete_time !== undefined
  const etaS = completed ? r.mission_complete_time : (r.time[r.time.length - 1] ?? naiveEtaS)
  const avgSpeedKn = etaS > 0 ? (distanceM / etaS) / KN_TO_MS : 0
  precalcResult.value = { distanceM, etaS, completed, avgSpeedKn }
}

function clearPrecalc() {
  store.clearSimulation()
  precalcResult.value = null
  precalcError.value = ''
}

function surveyNumber(id) {
  return store.missionItems.filter(i => i.type === 'survey').findIndex(i => i.id === id) + 1
}
function surveyWpCount(item) {
  if (item.polygon.length < 3) return 0
  return generateLawnmower(item.polygon, item.lineAngle, item.lineSpacing, item.lineExtension, item.startWP).length
}

// ── Mission start placement ───────────────────────────────────────────────────
function useCurrentPosition() {
  const item = missionStart.value
  if (item) store.updateMissionItem(item.id, { lat: store.lat, lon: store.lon })
}
function pickMissionStart() {
  if (!missionStart.value) return
  store.activeMissionWpId = store.activeMissionWpId === missionStart.value.id
    ? null : missionStart.value.id
  if (store.activeMissionWpId) {
    // cancel any survey draw
    store.surveyDrawMode = false
  }
}

// ── Mission end placement ─────────────────────────────────────────────────────
function useCurrentPositionEnd() {
  const item = missionEnd.value
  if (item) store.updateMissionItem(item.id, { lat: store.lat, lon: store.lon })
}
function pickMissionEnd() {
  if (!missionEnd.value) return
  store.activeMissionWpId = store.activeMissionWpId === missionEnd.value.id
    ? null : missionEnd.value.id
  if (store.activeMissionWpId) {
    store.surveyDrawMode = false
  }
}

// ── Waypoint placement ────────────────────────────────────────────────────────
function pickWaypoint(id) {
  store.activeMissionWpId = store.activeMissionWpId === id ? null : id
  if (store.activeMissionWpId) {
    store.surveyDrawMode = false
    store.activeSurveyId = null
  }
}

// ── Survey polygon draw / edit ────────────────────────────────────────────────
function toggleSurveyExpand(id) {
  expandedSurveyId.value = expandedSurveyId.value === id ? null : id
}

function toggleDrawPolygon(id) {
  if (store.activeSurveyId === id && store.surveyDrawMode) {
    // Close polygon
    store.surveyDrawMode = false
  } else {
    store.activeSurveyId = id
    store.surveyDrawMode = true
    store.activeMissionWpId = null
    expandedSurveyId.value = id
  }
}

function toggleEditPolygon(id) {
  if (store.activeSurveyId === id) {
    store.activeSurveyId = null
  } else {
    store.activeSurveyId = id
    store.surveyDrawMode = false
    store.activeMissionWpId = null
  }
}

function clearPoly(id) {
  store.clearSurveyPolygon(id)
  if (store.activeSurveyId === id) {
    store.activeSurveyId = null
    store.surveyDrawMode = false
  }
}

function addAndExpandSurvey() {
  const id = store.addMissionItem('survey')
  expandedSurveyId.value = id
}

// ── Patch helper ──────────────────────────────────────────────────────────────
function patchItem(id, patch) {
  store.updateMissionItem(id, patch)
}

// ── Drag-to-reorder ───────────────────────────────────────────────────────────
function onDragStart(e, idx) {
  dragSrcIdx.value = idx
  e.dataTransfer.effectAllowed = 'move'
}
function onDragOver(e, id) {
  dragOverId.value = id
}
function onDrop(e, targetIdx) {
  dragOverId.value = null
  if (dragSrcIdx.value === null || dragSrcIdx.value === targetIdx) return
  const items = [...middleItems.value]
  const [moved] = items.splice(dragSrcIdx.value, 1)
  items.splice(targetIdx, 0, moved)
  store.reorderMissionItems(items)
  dragSrcIdx.value = null
}

// ── Home WP ───────────────────────────────────────────────────────────────────
function setHome() {
  store.homePickMode = !store.homePickMode
  if (store.homePickMode) store.currentTab = 'map'
}

// ── Mission start / stop ──────────────────────────────────────────────────────
function start() {
  startError.value = ''
  startWarnings.value = []
  if (simMode.value === 'REAL') {
    if (!store.canStartAutoMode) {
      startError.value = 'Cannot start: No GNSS fix'
      return
    }
    startWarnings.value = store.autoModeWarnings
  }
  // Single-WP mission: vehicle navigates to the one point and stops.
  // Loop/reverse modes make no sense with a single target.
  const effectiveCompletion = missionWaypoints.value.length <= 1 ? 'stop' : completion.value
  store.startWpRoute({
    direction: direction.value,
    completion: effectiveCompletion,
    cruise_speed_kn: cruiseSpeedKn.value,
  })
}
function stop() {
  startError.value = ''
  startWarnings.value = []
  store.stopWpRoute()
}

// ── CSV save / load ───────────────────────────────────────────────────────────
function saveCsv() {
  const wps = missionWaypoints.value
  if (!wps.length) return
  const lines = ['# lat,lon,radius(m),speed(kn)', ...wps.map(wp =>
    `${wp.lat.toFixed(7)},${wp.lon.toFixed(7)},${wp.radius},${wp.speed}`)]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `mission_${new Date().toISOString().slice(0,19).replace(/[:]/g,'-')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
function loadCsv(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = ev => {
    const wps = []
    for (const line of ev.target.result.trim().split('\n')) {
      const t = line.trim()
      if (!t || t.startsWith('#') || t.toLowerCase().startsWith('lat')) continue
      const parts = t.split(',').map(s => s.trim())
      if (parts.length < 2) continue
      wps.push({
        lat: parseFloat(parts[0]),
        lon: parseFloat(parts[1]),
        radius: parts[2] ? parseFloat(parts[2]) : 5.0,
        speed:  parts[3] ? parseFloat(parts[3]) : 1.0,
      })
    }
    // Build missionItems from flat CSV: start + waypoints + end
    if (wps.length > 0) {
      store.clearMissionItems()
      const startItem = store.missionItems.find(i => i.type === 'mission_start')
      if (startItem) store.updateMissionItem(startItem.id, { lat: wps[0].lat, lon: wps[0].lon })
      for (let i = 1; i < wps.length; i++) {
        const id = store.addMissionItem('waypoint')
        if (id) store.updateMissionItem(id, { lat: wps[i].lat, lon: wps[i].lon, radius: wps[i].radius, speed: wps[i].speed })
      }
    }
  }
  reader.readAsText(file)
  e.target.value = ''
}
</script>

<style scoped>
/* ─── Panel shell ────────────────────────────────────────────────────────── */
.planner-panel {
  background: rgba(30, 30, 30, 0.95);
  color: #fff;
  padding: 16px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 265px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #555 #333;
  font-size: 0.85rem;
}

/* ─── Title ──────────────────────────────────────────────────────────────── */
h3 {
  margin: 0;
  font-size: 1rem;
  color: #FFA500;
  text-align: center;
}
.item-count-row {
  text-align: center;
  font-size: 0.72rem;
  color: #888;
  margin-top: -6px;
}

/* ─── Items list ─────────────────────────────────────────────────────────── */
.items-list { display: flex; flex-direction: column; gap: 4px; }

.item-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px;
  border-radius: 5px;
  background: #2a2a2a;
  border: 1px solid #444;
  transition: border-color 0.15s;
}
.item-row:hover { border-color: #666; }
.item-fixed  { background: #222; }
.item-survey.item-active-survey { border-color: #22bb66; }
.item-picking { border-color: #FFA500 !important; }
.drag-over    { border-color: #FFA500 !important; }

/* ─── Badges ─────────────────────────────────────────────────────────────── */
.item-badge {
  min-width: 20px;
  height: 20px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.badge-start  { background: #2e7d32; color: #fff; }
.badge-end    { background: #c62828; color: #fff; }
.badge-wp     { background: #0288d1; color: #fff; font-size: 0.65rem; }
.badge-survey { background: #2e7d32; color: #fff; }

.drag-handle {
  cursor: grab;
  color: #666;
  font-size: 1rem;
  padding: 1px 2px 0;
  flex-shrink: 0;
  user-select: none;
}

/* ─── Item body ──────────────────────────────────────────────────────────── */
.item-body { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.item-label { font-weight: 600; color: #fff; font-size: 0.8rem; }
.item-coords { font-family: monospace; font-size: 0.7rem; color: #aaa; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-coords.dim { color: #555; font-style: italic; }

/* ─── Waypoint params ────────────────────────────────────────────────────── */
.wp-params { display: flex; gap: 8px; margin-top: 2px; flex-wrap: wrap; }
.wp-params label { display: flex; align-items: center; gap: 3px; color: #aaa; font-size: 0.72rem; }
.wp-params input { background: #333; border: 1px solid #555; color: #fff; border-radius: 4px; padding: 2px 4px; font-size: 0.72rem; width: 48px; }

/* ─── Item actions ───────────────────────────────────────────────────────── */
.item-actions { display: flex; flex-direction: column; gap: 3px; flex-shrink: 0; }
.act-btn {
  background: #333;
  border: 1px solid #555;
  color: #ccc;
  border-radius: 4px;
  width: 24px;
  height: 24px;
  font-size: 0.7rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.act-btn:hover { background: #444; color: #fff; }
.act-btn.active { background: #FFA500; color: #000; border-color: #FFA500; }
/* Semantic tint: ⊕ = use GPS/current position (blue) */
.act-pos { background: #0d3a5c; color: #81d4fa; border-color: #1565c0; }
.act-pos:hover { background: #1565c0; color: #fff; }
/* Semantic tint: 📍 = pick on map (dark green) */
.act-map { background: #1b5e20; color: #a5d6a7; border-color: #2e7d32; }
.act-map:hover { background: #2e7d32; color: #fff; }
.act-map.active { background: #FFA500; color: #000; border-color: #FFA500; }
.act-del:hover  { background: #c62828; color: #fff; border-color: #c62828; }
.act-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ─── Survey editor ──────────────────────────────────────────────────────── */
.survey-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}
.survey-info { color: #888; font-size: 0.7rem; margin-left: auto; }
.chevron { color: #666; font-size: 0.65rem; }

.survey-editor {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid #444;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.param-grid { display: flex; flex-direction: column; gap: 5px; }
.param-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  color: #aaa;
  font-size: 0.78rem;
}
.param-input-group { display: flex; align-items: center; gap: 2px; }
.param-input {
  background: #333;
  border: 1px solid #555;
  color: #fff;
  border-radius: 4px;
  padding: 4px 5px;
  font-size: 0.75rem;
  width: 50px;
}
.param-input.wide { width: 62px; }
.param-unit { color: #888; font-size: 0.7rem; }

.poly-tools { display: flex; flex-wrap: wrap; gap: 4px; }
.btn-poly, .btn-poly-edit, .btn-poly-clear {
  flex: 1;
  padding: 6px;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: bold;
  cursor: pointer;
  border: none;
  transition: background 0.15s;
}
.btn-poly        { background: #1b5e20; color: #a5d6a7; }
.btn-poly.active { background: #388e3c; color: #fff; }
.btn-poly-edit        { background: #1a237e; color: #90caf9; }
.btn-poly-edit.active { background: #303f9f; color: #fff; }
.btn-poly-clear { background: #4e1a1a; color: #ef9a9a; }
.btn-poly-clear:hover { background: #7f1c1c; }
.btn-poly:disabled, .btn-poly-edit:disabled, .btn-poly-clear:disabled { opacity: 0.4; cursor: not-allowed; }

.draw-hint {
  font-size: 0.7rem;
  color: #FFA500;
  font-style: italic;
  background: rgba(255,165,0,0.1);
  border-radius: 4px;
  padding: 4px 6px;
  border-left: 2px solid #FFA500;
}

/* ─── Add row ────────────────────────────────────────────────────────────── */
.add-row { display: flex; gap: 6px; }
.btn-add-wp     { flex: 1; background: #0d3a5c; color: #81d4fa; }
.btn-add-survey { flex: 1; background: #0d3b22; color: #a5d6a7; }

/* ─── Divider ────────────────────────────────────────────────────────────── */
.section-divider { border-top: 1px solid #444; margin: 2px 0; }

/* ─── Fields (label + input rows) ───────────────────────────────────────── */
.field { display: flex; flex-direction: column; gap: 4px; }
.field label {
  font-size: 0.75rem;
  color: #aaa;
  text-transform: uppercase;
}
.field input, .field select {
  background: #333;
  border: 1px solid #555;
  color: #fff;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.85rem;
  width: 100%;
  box-sizing: border-box;
}
.field input:disabled, .field select:disabled { opacity: 0.4; }

/* ─── Home WP row ────────────────────────────────────────────────────────── */
.home-row { display: flex; align-items: center; gap: 6px; }
.coord { font-size: 0.78rem; font-family: monospace; color: #aaa; flex: 1; }
.coord.dim { color: #555; font-style: italic; }
.home-btn {
  background: #1b5e20;
  color: #a5d6a7;
  border: 1px solid #2e7d32;
  border-radius: 4px;
  padding: 5px 10px;
  font-size: 0.75rem;
  font-weight: bold;
  cursor: pointer;
  white-space: nowrap;
}
.home-btn:hover:not(:disabled) { background: #2e7d32; }
.home-btn.active { background: #FFA500; color: #000; animation: pulse-pick 1s infinite; }
.home-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ─── Toggle group ───────────────────────────────────────────────────────── */
.toggle-group {
  display: flex;
  gap: 2px;
  background: #1e1e1e;
  border: 1px solid #555;
  border-radius: 4px;
  padding: 2px;
}
.tog-btn {
  flex: 1;
  background: transparent;
  color: #aaa;
  border: none;
  border-radius: 3px;
  padding: 5px 8px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: background 0.15s;
}
.tog-btn.active { background: #FFA500; color: #000; font-weight: bold; }
.tog-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ─── Surge slider ───────────────────────────────────────────────────────── */
.surge-slider-container { display: flex; align-items: center; gap: 8px; }
.surge-slider { flex: 1; }
.surge-val { font-family: monospace; font-size: 0.85rem; color: #FFA500; min-width: 34px; text-align: right; }
.surge-metrics { font-size: 0.75rem; color: #888; }

/* ─── Alerts ─────────────────────────────────────────────────────────────── */
.alert { padding: 6px 8px; border-radius: 4px; font-size: 0.78rem; }
.alert-error   { background: rgba(180,0,0,0.2); color: #ff6b6b; border: 1px solid #9a0000; }
.alert-warning { background: rgba(160,100,0,0.2); color: #ffcc66; border: 1px solid #805000; }

/* ─── Route precalculation ───────────────────────────────────────────────── */
.precalc-btn-row { display: flex; gap: 6px; }
.btn-precalc {
  flex: 1;
  background: #1a237e;
  color: #90caf9;
}
.btn-precalc:hover:not(:disabled) { background: #283593; }
.btn-clear-sim {
  flex-shrink: 0;
  width: 36px;
  background: #4e1a1a;
  color: #ef9a9a;
  padding: 10px 0;
}
.btn-clear-sim:hover { background: #7f1c1c; }
.precalc-box {
  margin-top: 6px;
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 5px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.precalc-row { display: flex; justify-content: space-between; font-size: 0.8rem; color: #ccc; }
.precalc-row strong { color: #FFA500; }
.precalc-hint { font-size: 0.7rem; color: #888; font-style: italic; margin-top: 2px; }

/* ─── Buttons (base) ─────────────────────────────────────────────────────── */
.btn {
  padding: 10px;
  border: none;
  border-radius: 4px;
  font-weight: bold;
  cursor: pointer;
  font-size: 0.85rem;
  transition: opacity 0.2s;
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.start-btn { background: #00C851; color: #fff; }
.start-btn:hover:not(:disabled) { background: #00a543; }
.stop-btn  { background: #c62828; color: #fff; }
.stop-btn:hover:not(:disabled) { background: #e53935; }

/* ─── File row ───────────────────────────────────────────────────────────── */
.file-row  { display: flex; gap: 6px; }
.file-btn  { flex: 1; background: #2c3e50; color: #90caf9; font-size: 0.75rem; padding: 8px; }
.file-label { text-align: center; cursor: pointer; }
.clear-btn { background: #4e1a1a; color: #ef9a9a; font-size: 0.75rem; padding: 8px; }
</style>

