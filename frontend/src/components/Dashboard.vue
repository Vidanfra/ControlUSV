<template>
  <div class="dashboard">
    <h3>USV Telemetry</h3>
    <div class="status-indicator" :class="{ connected: isConnected }">
      {{ isConnected ? 'CONNECTED' : 'DISCONNECTED' }}
    </div>

    <!-- RT Sim Banner -->
    <div v-if="store.rtSimActive" class="sim-banner">
      SIM RUNNING &mdash; {{ store.rtSimElapsed.toFixed(1) }}s
    </div>

    <div class="data-grid">
      <!-- Core navigation -->
      <div class="data-item">
        <label :class="{ 'sim-label': store.dataSource === 'sim' }">Lat</label>
        <span :style="{ color: store.fixColor }">{{ lat.toFixed(7) }}</span>
      </div>
      <div class="data-item">
        <label :class="{ 'sim-label': store.dataSource === 'sim' }">Lon</label>
        <span :style="{ color: store.fixColor }">{{ lon.toFixed(7) }}</span>
      </div>
      <div class="data-item">
        <label :class="{ 'sim-label': store.dataSource === 'sim' }">Heading</label>
        <span>{{ store.bestHeading.toFixed(1) }}&deg; <small class="src-tag" :class="{ ins: store.insActive }">{{ store.headingSource }}</small></span>
      </div>
      <div class="data-item">
        <label>Desired Hdg</label>
        <span>{{ (((store.targetHeading * 180 / Math.PI) % 360 + 360) % 360).toFixed(1) }}&deg;</span>
      </div>
      <div class="data-item">
        <label :class="{ 'sim-label': store.dataSource === 'sim' }">SOG</label>
        <span>{{ (store.speed / 0.514444).toFixed(1) }} kn</span>
      </div>

      <!-- Waypoint section (STATION or WP_ROUTE active) -->
      <template v-if="isAutoActive">
        <div class="section-label">Waypoint</div>
        <div class="data-item">
          <label>Target WP</label>
          <span>{{ targetWpLabel }}</span>
        </div>
        <div class="data-item">
          <label>Dist to WP</label>
          <span>{{ store.distToWp.toFixed(1) }} m</span>
        </div>
        <div class="data-item">
          <label>ETT WP</label>
          <span>{{ formatEtt(store.ettNextWp) }}</span>
        </div>
        <div class="data-item">
          <label>ETA WP</label>
          <span>{{ formatEta(store.etaNextWp) }}</span>
        </div>
      </template>

      <!-- Route section (WP_ROUTE only) -->
      <template v-if="isRouteActive">
        <div class="section-label">Route</div>
        <div class="data-item">
          <label>ETT End</label>
          <span>{{ formatEtt(store.ettRouteEnd) }}</span>
        </div>
        <div class="data-item">
          <label>ETA End</label>
          <span>{{ formatEta(store.etaRouteEnd) }}</span>
        </div>
        <div class="data-item">
          <label>KP</label>
          <span>{{ formatKp(store.kpM) }}</span>
        </div>
        <div class="data-item">
          <label>DCC</label>
          <span>{{ store.crossTrackError.toFixed(2) }} m</span>
        </div>
      </template>

      <!-- System -->
      <div class="section-label" v-if="isAutoActive">System</div>
      <div class="data-item">
        <label>Battery</label>
        <span>{{ store.batteryVoltage.toFixed(1) }} V</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { lat, lon, isConnected } = storeToRefs(store)

const isAutoActive  = computed(() => store.stationActive || store.wpRouteActive)
const isRouteActive = computed(() => store.wpRouteActive)

// Target WP label — mirrors GncView computation
const targetWpLabel = computed(() => {
  // Station keeping shows its own label regardless of wp_index
  if (store.stationActive || store.vehicleMode === 'STATION') return 'STATION WP'

  const total = store.missionWaypoints.length
  if (total < 2) return '\u2014'

  // PathFollower.wp_index is the FROM-waypoint index in the backend list.
  // The backend always prepends a bridge WP (current vehicle position), so:
  //   backend list = [bridge, wp[0], wp[1], ..., wp[total-1]]
  // The vehicle is heading TO backend[wp_index + 1] = frontend[wp_index].
  //
  // In reverse the backend receives the waypoints already reversed:
  //   backend list = [bridge, ME, WPN, ..., WP1, MS]
  // So TO-waypoint = frontend[total - 1 - wp_index].
  const wpIdx = store.currentWpIndex || 0
  let frontendIdx
  if (store.wpRouteDirection === 'reverse') {
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

function formatEtt(secs) {
  if (secs < 0) return '\u2014'
  if (secs < 60) return `${Math.round(secs)}s`
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  if (m < 60) return `${m}m ${String(s).padStart(2, '0')}s`
  const h = Math.floor(m / 60)
  return `${h}h ${String(m % 60).padStart(2, '0')}m`
}

function formatEta(ts) {
  if (!ts || ts <= 0) return '\u2014'
  return new Date(ts * 1000).toLocaleTimeString('en-GB', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

function formatKp(m) {
  if (m < 100) return `${Math.round(m)} m`
  return `${(m / 1000).toFixed(3)} km`
}
</script>

<style scoped>
.dashboard {
  background: rgba(30, 30, 30, 0.95);
  color: #fff;
  padding: 12px;
  border-radius: 8px;
  min-width: 195px;
  font-size: 0.82rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
}

h3 {
  margin: 0 0 8px;
  font-size: 1rem;
  color: #FFA500;
  text-align: center;
  border-bottom: 1px solid #444;
  padding-bottom: 6px;
}

.status-indicator {
  font-size: 0.78rem;
  font-weight: bold;
  margin-bottom: 8px;
  padding: 3px;
  border-radius: 4px;
  text-align: center;
  background: #e53935;
  color: #fff;
}

.status-indicator.connected {
  background: #00C851;
}

.data-grid {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.data-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.82rem;
}

.data-item label {
  color: #aaa;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  white-space: nowrap;
  margin-right: 6px;
}

.data-item span {
  font-family: monospace;
  font-weight: bold;
  color: #fff;
  text-align: right;
}

.section-label {
  font-size: 0.58rem;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  border-top: 1px solid #333;
  padding-top: 4px;
  margin-top: 1px;
}

.src-tag {
  font-size: 0.65rem;
  color: #888;
  font-weight: normal;
  margin-left: 3px;
}

.src-tag.ins {
  color: #42d4f4;
  font-weight: 700;
}

/* sim-label: same grey as normal labels — no cyan flash */
.sim-label {
  color: #aaa !important;
}

.sim-banner {
  background: #5a3e00;
  border: 1px solid #FFA500;
  color: #FFA500;
  text-align: center;
  font-weight: bold;
  font-size: 0.78rem;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 6px;
  animation: pulse-sim 1.5s ease-in-out infinite;
}

@keyframes pulse-sim {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.65; }
}
</style>
