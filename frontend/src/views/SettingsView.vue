<template>
  <div class="settings-container">
    <div class="settings-panel">
      <h2>System Settings</h2>

      <!-- Battery / Power Section -->
      <section class="settings-section">
        <h3>Battery & Energy</h3>

        <div class="setting-row">
          <label for="batteryCapacity">Battery Capacity (Wh)</label>
          <div class="input-group">
            <input
              id="batteryCapacity"
              v-model.number="capacityInput"
              type="number"
              min="1"
              max="50000"
              step="10"
              placeholder="500"
            />
            <button class="btn btn-primary" @click="saveCapacity" :disabled="!capacityChanged">
              Save
            </button>
          </div>
          <p class="hint">Total battery capacity used to calculate remaining percentage.</p>
        </div>

        <div class="setting-row">
          <label>Energy Measurement</label>
          <div class="input-group">
            <span class="status-text">
              Running since: <strong>{{ measurementStartStr }}</strong>
              &nbsp;({{ measurementDuration }})
            </span>
            <button class="btn btn-warning" @click="confirmReset">
              Restart Energy Counter
            </button>
          </div>
          <p class="hint">Resets the software energy accumulator and restarts measurement timer. PZEM hardware counter is also reset.</p>
        </div>
      </section>

      <!-- Device Info Section -->
      <section class="settings-section">
        <h3>Device Info</h3>
        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">Voltage</span>
            <span class="info-value">{{ telemetry.batteryVoltage?.toFixed(2) ?? '--' }} V</span>
          </div>
          <div class="info-item">
            <span class="info-label">Current</span>
            <span class="info-value">{{ telemetry.batteryCurrent?.toFixed(2) ?? '--' }} A</span>
          </div>
          <div class="info-item">
            <span class="info-label">Power</span>
            <span class="info-value">{{ telemetry.batteryPower?.toFixed(1) ?? '--' }} W</span>
          </div>
          <div class="info-item">
            <span class="info-label">HW Energy</span>
            <span class="info-value">{{ telemetry.batteryEnergyWh ?? '--' }} Wh</span>
          </div>
          <div class="info-item">
            <span class="info-label">SW Energy</span>
            <span class="info-value">{{ telemetry.batteryAccumulatedWh?.toFixed(2) ?? '--' }} Wh</span>
          </div>
          <div class="info-item">
            <span class="info-label">Battery Level</span>
            <span class="info-value">{{ telemetry.batteryLevelPct?.toFixed(1) ?? '--' }} %</span>
          </div>
        </div>
      </section>

      <!-- GNSS / NTRIP Section -->
      <section class="settings-section">
        <h3>GNSS / NTRIP Configuration</h3>

        <div class="setting-row">
          <label for="gnssSerial">Serial Port</label>
          <div class="input-group">
            <input id="gnssSerial" v-model="gnssForm.serial_port" type="text" class="text-input" placeholder="/dev/gnss" />
          </div>
        </div>

        <div class="setting-row">
          <label for="gnssBaud">Baud Rate</label>
          <div class="input-group">
            <select id="gnssBaud" v-model.number="gnssForm.baud_rate" class="text-input">
              <option :value="9600">9600</option>
              <option :value="38400">38400</option>
              <option :value="57600">57600</option>
              <option :value="115200">115200</option>
              <option :value="230400">230400</option>
              <option :value="460800">460800</option>
            </select>
          </div>
        </div>

        <div class="setting-row">
          <label for="ntripCaster">NTRIP Caster</label>
          <div class="input-group">
            <input id="ntripCaster" v-model="gnssForm.ntrip_caster" type="text" class="text-input" placeholder="e.g. 192.168.1.100" />
          </div>
        </div>

        <div class="setting-row">
          <label for="ntripPort">NTRIP Port</label>
          <div class="input-group">
            <input id="ntripPort" v-model.number="gnssForm.ntrip_port" type="number" min="1" max="65535" class="text-input" placeholder="2101" />
          </div>
        </div>

        <div class="setting-row">
          <label for="ntripMount">Mountpoint</label>
          <div class="input-group">
            <input id="ntripMount" v-model="gnssForm.mountpoint" type="text" class="text-input" placeholder="e.g. VRS3M" />
          </div>
        </div>

        <div class="setting-row">
          <label for="ntripUser">Username</label>
          <div class="input-group">
            <input id="ntripUser" v-model="gnssForm.username" type="text" class="text-input" placeholder="NTRIP username" />
          </div>
        </div>

        <div class="setting-row">
          <label for="ntripPass">Password</label>
          <div class="input-group">
            <input id="ntripPass" v-model="gnssForm.password" type="password" class="text-input" placeholder="NTRIP password" />
          </div>
        </div>

        <div class="setting-row">
          <label for="gnssFreq">Update Frequency (Hz)</label>
          <div class="input-group">
            <input id="gnssFreq" v-model.number="gnssForm.command_freq" type="number" min="0.1" max="20" step="0.5" class="text-input" placeholder="1" />
          </div>
        </div>

        <div class="setting-row">
          <div class="input-group">
            <button class="btn btn-primary" @click="saveGnssConfig" :disabled="!gnssConfigChanged">
              Apply & Reconnect
            </button>
          </div>
          <p class="hint">Sends configuration to the GNSS node. The receiver will reconnect with the new settings.</p>
        </div>
      </section>

      <!-- Fail-Safe (Auto Mode) Section -->
      <section class="settings-section">
        <h3>Fail-Safe (Auto Mode)</h3>

        <div class="setting-row">
          <label for="fsMinBattery">Minimum Battery (%)</label>
          <div class="input-group">
            <input id="fsMinBattery" v-model.number="fsForm.min_battery_pct" type="number" min="0" max="100" step="1" class="text-input" placeholder="25" />
          </div>
          <p class="hint">Auto mode issues a warning below this level.</p>
        </div>

        <div class="setting-row">
          <label for="fsMinGnss">Minimum GNSS Quality</label>
          <div class="input-group">
            <select id="fsMinGnss" v-model.number="fsForm.min_gnss_fix" class="text-input">
              <option :value="1">GPS (1)</option>
              <option :value="2">DGPS (2)</option>
              <option :value="4">RTK Fix (4)</option>
              <option :value="5">RTK Float (5)</option>
            </select>
          </div>
          <p class="hint">Blocks auto mode start below this GNSS fix quality.</p>
        </div>

        <div class="setting-row">
          <label for="fsCommTimeout">Comm Loss Timeout (s)</label>
          <div class="input-group">
            <input id="fsCommTimeout" v-model.number="fsForm.comm_timeout" type="number" min="1" max="120" step="1" class="text-input" placeholder="10" />
          </div>
        </div>

        <div class="setting-row">
          <label for="fsCommAction">Comm Loss Action</label>
          <div class="input-group">
            <select id="fsCommAction" v-model="fsForm.comm_action" class="text-input">
              <option value="station_keeping">Station Keeping</option>
              <option value="return_home">Return Home</option>
            </select>
          </div>
        </div>

        <div class="setting-row">
          <label for="fsInsTimeout">GNSS Loss / INS Timeout (s)</label>
          <div class="input-group">
            <input id="fsInsTimeout" v-model.number="fsForm.ins_timeout" type="number" min="1" max="120" step="1" class="text-input" placeholder="10" />
          </div>
        </div>

        <div class="setting-row">
          <label for="fsInsAction">GNSS Loss Action</label>
          <div class="input-group">
            <select id="fsInsAction" v-model="fsForm.ins_action" class="text-input">
              <option value="emergency_stop">Emergency Stop</option>
              <option value="station_keeping">Station Keeping</option>
            </select>
          </div>
        </div>

        <div class="setting-row">
          <div class="input-group">
            <button class="btn btn-primary" @click="saveFailsafeConfig" :disabled="!fsConfigChanged">
              Save Fail-Safe Config
            </button>
          </div>
          <p class="hint">Updates fail-safe parameters on the vehicle.</p>
        </div>
      </section>

      <!-- GNC Controller Config Section -->
      <section class="settings-section">
        <h3>GNC Controller Settings</h3>
        <p class="hint" style="margin-top:-10px; margin-bottom:15px">
          These settings tune the path-following and heading PID controllers. They apply immediately to both real hardware and the physics simulation drift.
        </p>

        <div class="setting-row">
          <label for="gncWn">Heading PID Natural Frequency (wn)</label>
          <div class="input-group">
            <input id="gncWn" v-model.number="gncForm.wn" type="number" min="0.1" max="20" step="0.1" class="text-input" />
          </div>
          <p class="hint">Higher values make steering faster but more aggressive.</p>
        </div>

        <div class="setting-row">
          <label for="gncZeta">Heading PID Damping (zeta)</label>
          <div class="input-group">
            <input id="gncZeta" v-model.number="gncForm.zeta" type="number" min="0.1" max="5.0" step="0.1" class="text-input" />
          </div>
          <p class="hint">1.0 is critically damped. Lower values allow overshoot.</p>
        </div>

        <div class="setting-row">
          <label for="gncWnRef">Reference Model ω (wn_ref)</label>
          <div class="input-group">
            <input id="gncWnRef" v-model.number="gncForm.wn_ref" type="number" min="0.1" max="20" step="0.1" class="text-input" />
          </div>
          <p class="hint">Natural frequency of the 3rd-order reference model.</p>
        </div>

        <div class="setting-row">
          <label for="gncZetaRef">Reference Model ζ (zeta_ref)</label>
          <div class="input-group">
            <input id="gncZetaRef" v-model.number="gncForm.zeta_ref" type="number" min="0.1" max="5.0" step="0.1" class="text-input" />
          </div>
          <p class="hint">Damping ratio of the 3rd-order reference model.</p>
        </div>

        <div class="setting-row">
          <label for="gncDelta">ALOS Look-ahead Distance (delta)</label>
          <div class="input-group">
            <input id="gncDelta" v-model.number="gncForm.delta" type="number" min="1.0" max="50.0" step="0.5" class="text-input" />
          </div>
          <p class="hint">How far ahead the boat aims on the track (meters).</p>
        </div>

        <div class="setting-row">
          <label for="gncGamma">ALOS Adaptive Gain (gamma)</label>
          <div class="input-group">
            <input id="gncGamma" v-model.number="gncForm.gamma" type="number" min="0.0" max="10.0" step="0.1" class="text-input" />
          </div>
          <p class="hint">Adaptive integral gain for compensating ocean currents.</p>
        </div>

        <div class="setting-row">
          <div class="input-group">
            <button class="btn btn-primary" @click="saveGncConfig" :disabled="!gncConfigChanged">
              Update GNC Settings
            </button>
          </div>
          <p class="hint">Live updates the path-following algorithm parameters.</p>
        </div>
      </section>

      <!-- Reset Confirmation Dialog -->
      <div v-if="showResetConfirm" class="confirm-overlay" @click.self="showResetConfirm = false">
        <div class="confirm-dialog">
          <h4>Reset Energy Counter?</h4>
          <p>This will reset the accumulated energy counter and restart the measurement timer. This action cannot be undone.</p>
          <div class="confirm-actions">
            <button class="btn btn-secondary" @click="showResetConfirm = false">Cancel</button>
            <button class="btn btn-danger" @click="doReset">Reset Now</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'

const telemetry = useTelemetryStore()

const capacityInput = ref(500)
const showResetConfirm = ref(false)

// Fail-safe config form
const fsForm = ref({
  min_battery_pct: 25.0,
  min_gnss_fix: 1,
  comm_timeout: 10.0,
  comm_action: 'station_keeping',
  ins_timeout: 10.0,
  ins_action: 'emergency_stop',
})

// GNSS config form
const gnssForm = ref({
  serial_port: '/dev/gnss',
  baud_rate: 115200,
  ntrip_caster: '',
  ntrip_port: 2101,
  mountpoint: '',
  username: '',
  password: '',
  command_freq: 1.0
})

// GNC config form
const gncForm = ref({
  wn: 4.0,
  zeta: 0.5,
  wn_ref: 1.0,
  zeta_ref: 1.0,
  delta: 5.0,
  gamma: 0.0,
  tau_x: 150.0 // Kept in state but hidden in UI, as WP/Station panels control it
})

onMounted(() => {
  capacityInput.value = telemetry.batteryCapacityWh || 500
  // Load fail-safe config from store
  fsForm.value.min_battery_pct = telemetry.failsafeMinBattery
  fsForm.value.min_gnss_fix = telemetry.failsafeMinGnssFix
  fsForm.value.comm_timeout = telemetry.failsafeCommTimeout
  fsForm.value.comm_action = telemetry.failsafeCommAction
  fsForm.value.ins_timeout = telemetry.failsafeInsTimeout
  fsForm.value.ins_action = telemetry.failsafeInsAction
  // Load GNSS config from store
  gnssForm.value.serial_port = telemetry.gnssSerialPort || '/dev/gnss'
  gnssForm.value.baud_rate = telemetry.gnssBaudRate || 115200
  gnssForm.value.ntrip_caster = telemetry.gnssNtripCaster || ''
  gnssForm.value.ntrip_port = telemetry.gnssNtripPort || 2101
  gnssForm.value.mountpoint = telemetry.gnssMountpoint || ''
  gnssForm.value.username = telemetry.gnssUsername || ''
  gnssForm.value.password = telemetry.gnssPassword || ''
  gnssForm.value.command_freq = telemetry.gnssCommandFreq || 1.0

  // Load GNC config from store
  if (telemetry.gncConfig) {
    gncForm.value.wn = telemetry.gncConfig.wn
    gncForm.value.zeta = telemetry.gncConfig.zeta
    gncForm.value.wn_ref = telemetry.gncConfig.wn_ref ?? 1.0
    gncForm.value.zeta_ref = telemetry.gncConfig.zeta_ref ?? 1.0
    gncForm.value.delta = telemetry.gncConfig.delta
    gncForm.value.gamma = telemetry.gncConfig.gamma
    gncForm.value.tau_x = telemetry.gncConfig.tau_x
  }
})

const capacityChanged = computed(() => {
  return capacityInput.value !== telemetry.batteryCapacityWh && capacityInput.value > 0
})

const gnssConfigChanged = computed(() => {
  return (
    gnssForm.value.serial_port !== telemetry.gnssSerialPort ||
    gnssForm.value.baud_rate !== telemetry.gnssBaudRate ||
    gnssForm.value.ntrip_caster !== telemetry.gnssNtripCaster ||
    gnssForm.value.ntrip_port !== telemetry.gnssNtripPort ||
    gnssForm.value.mountpoint !== telemetry.gnssMountpoint ||
    gnssForm.value.username !== telemetry.gnssUsername ||
    gnssForm.value.password !== telemetry.gnssPassword ||
    gnssForm.value.command_freq !== telemetry.gnssCommandFreq
  )
})

const measurementStartStr = computed(() => {
  const ts = telemetry.batteryMeasurementStart
  if (!ts || ts === 0) return '--'
  return new Date(ts * 1000).toLocaleTimeString()
})

const measurementDuration = computed(() => {
  const ts = telemetry.batteryMeasurementStart
  if (!ts || ts === 0) return '--'
  const elapsed = Math.floor(Date.now() / 1000 - ts)
  if (elapsed < 0) return '--'
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
})

function saveCapacity() {
  telemetry.setBatteryCapacity(capacityInput.value)
}

function confirmReset() {
  showResetConfirm.value = true
}

function doReset() {
  telemetry.resetEnergy()
  showResetConfirm.value = false
}

function saveGnssConfig() {
  telemetry.setGnssConfig({ ...gnssForm.value })
}

const fsConfigChanged = computed(() => {
  return (
    fsForm.value.min_battery_pct !== telemetry.failsafeMinBattery ||
    fsForm.value.min_gnss_fix !== telemetry.failsafeMinGnssFix ||
    fsForm.value.comm_timeout !== telemetry.failsafeCommTimeout ||
    fsForm.value.comm_action !== telemetry.failsafeCommAction ||
    fsForm.value.ins_timeout !== telemetry.failsafeInsTimeout ||
    fsForm.value.ins_action !== telemetry.failsafeInsAction
  )
})

function saveFailsafeConfig() {
  telemetry.setFailsafeConfig({ ...fsForm.value })
}

const gncConfigChanged = computed(() => {
  if (!telemetry.gncConfig) return false
  return (
    gncForm.value.wn !== telemetry.gncConfig.wn ||
    gncForm.value.zeta !== telemetry.gncConfig.zeta ||
    gncForm.value.wn_ref !== (telemetry.gncConfig.wn_ref ?? 1.0) ||
    gncForm.value.zeta_ref !== (telemetry.gncConfig.zeta_ref ?? 1.0) ||
    gncForm.value.delta !== telemetry.gncConfig.delta ||
    gncForm.value.gamma !== telemetry.gncConfig.gamma
  )
})

function saveGncConfig() {
  // Always include the current explicit tau_x so it doesn't revert unexpectedly
  telemetry.setGncConfig({ ...gncForm.value, tau_x: telemetry.gncConfig.tau_x })
}
</script>

<style scoped>
.settings-container {
  display: flex;
  justify-content: center;
  height: calc(100vh - 50px);
  background-color: #121212;
  color: white;
  overflow-y: auto;
  padding: 30px 20px;
}

.settings-panel {
  width: 100%;
  max-width: 800px;
}

.settings-panel h2 {
  color: #FFA500;
  margin-bottom: 30px;
  font-size: 1.5em;
}

.settings-section {
  background-color: #1e1e1e;
  border-radius: 10px;
  padding: 25px;
  margin-bottom: 25px;
}

.settings-section h3 {
  color: #FFA500;
  margin: 0 0 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid #333;
}

.setting-row {
  margin-bottom: 25px;
}

.setting-row:last-child {
  margin-bottom: 0;
}

.setting-row label {
  display: block;
  color: #ccc;
  font-weight: bold;
  margin-bottom: 8px;
}

.input-group {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.input-group input[type="number"] {
  background-color: #2a2a2a;
  color: white;
  border: 1px solid #555;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 1em;
  width: 150px;
}

.input-group input[type="number"]:focus {
  outline: none;
  border-color: #FFA500;
}

.text-input {
  background-color: #2a2a2a;
  color: white;
  border: 1px solid #555;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 1em;
  width: 280px;
}

.text-input:focus {
  outline: none;
  border-color: #FFA500;
}

select.text-input {
  cursor: pointer;
}

.status-text {
  color: #aaa;
  font-size: 0.95em;
}

.status-text strong {
  color: white;
}

.hint {
  color: #666;
  font-size: 0.85em;
  margin-top: 6px;
}

/* Buttons */
.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  font-weight: bold;
  cursor: pointer;
  font-size: 0.9em;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary {
  background-color: #FFA500;
  color: #121212;
}

.btn-primary:hover:not(:disabled) {
  background-color: #ffb733;
}

.btn-warning {
  background-color: #cc7700;
  color: white;
}

.btn-warning:hover {
  background-color: #e68a00;
}

.btn-secondary {
  background-color: #444;
  color: #ccc;
}

.btn-secondary:hover {
  background-color: #555;
}

.btn-danger {
  background-color: #cc3333;
  color: white;
}

.btn-danger:hover {
  background-color: #ee4444;
}

/* Info Grid */
.info-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.info-item {
  background-color: #252525;
  padding: 12px 15px;
  border-radius: 6px;
  text-align: center;
}

.info-label {
  display: block;
  color: #888;
  font-size: 0.8em;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 4px;
}

.info-value {
  display: block;
  font-size: 1.1em;
  font-weight: bold;
  color: white;
}

/* Confirm Dialog */
.confirm-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.7);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 5000;
}

.confirm-dialog {
  background-color: #2a2a2a;
  border-radius: 10px;
  padding: 30px;
  max-width: 420px;
  width: 90%;
}

.confirm-dialog h4 {
  color: #FFA500;
  margin: 0 0 15px;
}

.confirm-dialog p {
  color: #aaa;
  margin-bottom: 20px;
  line-height: 1.5;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

@media (max-width: 600px) {
  .info-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
