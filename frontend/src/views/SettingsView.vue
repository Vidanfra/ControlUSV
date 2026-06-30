<template>
  <div class="settings-container">
    <div class="settings-panel">
      <h2>System Settings</h2>

      <!-- Manual Control / Joystick (PS4 etc.) -->
      <section class="settings-section">
        <h3>Manual Control — Joystick</h3>
        <p class="hint" style="margin-top:-10px; margin-bottom:15px">
          The web browser reads the gamepad directly from this PC (Web Gamepad
          API). Plug in or pair a PS4 / Xbox controller, then press any button
          to wake it up. The left stick drives <strong>throttle</strong>
          (vertical) and <strong>steering</strong> (horizontal) when the
          vehicle is in <strong>MANUAL</strong> mode and armed.
        </p>

        <div class="setting-row">
          <label>Connected Device</label>
          <div class="input-group">
            <span
              class="gp-status-pill"
              :class="{ connected: gpConnected }"
            >
              <span class="gp-status-dot"></span>
              {{ gpConnected ? 'Connected' : 'Not detected' }}
            </span>
            <span class="status-text" style="font-family: monospace;">
              {{ gpConnected ? (gpName || 'Gamepad') : '—' }}
            </span>
          </div>
          <p v-if="gpConnected" class="hint">
            Mapping: <code>{{ gpMapping || 'non-standard' }}</code>
            &nbsp;·&nbsp;
            Index: <code>{{ gpIndex }}</code>
          </p>
          <p v-else class="hint">
            No controller seen yet. In Chrome / Edge the device only appears
            after you press any button on it inside this tab.
          </p>
        </div>

        <!-- Live left-stick visualization -->
        <div class="setting-row">
          <label>Left Stick (live test)</label>
          <div class="gp-test-grid">
            <div class="gp-stick-box" :class="{ disabled: !gpConnected }">
              <div class="gp-stick-frame">
                <div class="gp-stick-crosshair-h"></div>
                <div class="gp-stick-crosshair-v"></div>
                <div
                  class="gp-stick-dot raw"
                  :style="rawDotStyle"
                  title="Raw stick position"
                ></div>
                <div
                  class="gp-stick-dot processed"
                  :style="procDotStyle"
                  title="After deadzone + expo (sent to vehicle)"
                ></div>
                <div
                  class="gp-stick-deadzone"
                  :style="{ width: (gp.settings.deadzone * 100) + '%', height: (gp.settings.deadzone * 100) + '%' }"
                ></div>
              </div>
              <div class="gp-stick-legend">
                <span><span class="sw-raw"></span> Raw</span>
                <span><span class="sw-proc"></span> Processed</span>
                <span><span class="sw-dz"></span> Deadzone</span>
              </div>
            </div>

            <div class="gp-readouts">
              <div class="gp-readout">
                <span class="gp-readout-label">Throttle (Y→)</span>
                <div class="gp-bar">
                  <div class="gp-bar-fill thr" :style="thrBarStyle"></div>
                </div>
                <span class="gp-readout-val">{{ procThrottle.toFixed(2) }}</span>
              </div>
              <div class="gp-readout">
                <span class="gp-readout-label">Steering (X→)</span>
                <div class="gp-bar">
                  <div class="gp-bar-fill str" :style="strBarStyle"></div>
                </div>
                <span class="gp-readout-val">{{ procSteering.toFixed(2) }}</span>
              </div>
              <div class="gp-readout small">
                <span class="gp-readout-label">Raw axes</span>
                <span class="gp-axes-raw">
                  LX:{{ fmtAxis(gp.axes[0]) }}
                  LY:{{ fmtAxis(gp.axes[1]) }}
                  RX:{{ fmtAxis(gp.axes[2]) }}
                  RY:{{ fmtAxis(gp.axes[3]) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Buttons activity -->
        <div class="setting-row" v-if="gpConnected && gp.buttons.length">
          <label>Buttons</label>
          <div class="gp-buttons-grid">
            <span
              v-for="(b, i) in gp.buttons"
              :key="i"
              class="gp-button"
              :class="{ pressed: b.pressed }"
              :title="'Button ' + i + (b.pressed ? ' (pressed)' : '')"
            >{{ i }}</span>
          </div>
          <p class="hint">Press any button on the controller to confirm input is reaching the browser.</p>
        </div>

        <!-- Tuning -->
        <div class="setting-row">
          <label for="gpDeadzone">Stick Deadzone</label>
          <div class="input-group">
            <input
              id="gpDeadzone"
              type="range" min="0" max="0.5" step="0.01"
              :value="gp.settings.deadzone"
              @input="gp.setDeadzone($event.target.value)"
              class="gp-slider"
            />
            <span class="status-text" style="width:60px; text-align:right;">{{ gp.settings.deadzone.toFixed(2) }}</span>
          </div>
          <p class="hint">Filters out resting drift on the stick. 0.10–0.15 is typical for PS4 controllers.</p>
        </div>

        <div class="setting-row">
          <label for="gpExpo">Expo (low-speed sensitivity)</label>
          <div class="input-group">
            <input
              id="gpExpo"
              type="range" min="0" max="1" step="0.01"
              :value="gp.settings.expo"
              @input="gp.setExpo($event.target.value)"
              class="gp-slider"
            />
            <span class="status-text" style="width:60px; text-align:right;">{{ gp.settings.expo.toFixed(2) }}</span>
          </div>
          <p class="hint">0 = linear (1:1). Higher values give finer control near the centre and full power at the edges.</p>
        </div>

        <div class="setting-row">
          <label>Invert Throttle Axis</label>
          <div class="input-group">
            <label class="toggle-label">
              <input
                type="checkbox"
                class="toggle-checkbox"
                :checked="gp.settings.invertY"
                @change="gp.setInvertY($event.target.checked)"
              />
              <span class="toggle-text">
                {{ gp.settings.invertY
                  ? 'Inverted — stick down = forward'
                  : 'Default — stick up = forward' }}
              </span>
            </label>
          </div>
          <p class="hint">Enable if the throttle direction feels reversed on your controller.</p>
        </div>

        <div class="setting-row">
          <div class="input-group">
            <button class="btn btn-secondary" @click="gp.resetSettings()">
              Reset to Defaults
            </button>
          </div>
          <p class="hint">Settings are stored in this browser only (localStorage).</p>
        </div>
      </section>

      <!-- ESP32 Relays (R1 / R2 / R3) -->
      <section class="settings-section">
        <h3>ESP32 Relays</h3>
        <p class="hint" style="margin-top:-10px; margin-bottom:15px">
          Three latched relays on the ESP32 controller. Their order matches the
          firmware command (R1, R2, R3); only the display names are editable.
          Use <strong>Restart</strong> to power-cycle a subsystem (relay opens
          for 5 s, then re-closes automatically).
        </p>

        <div
          v-for="(name, i) in relayNamesDraft"
          :key="i"
          class="relay-row"
        >
          <div class="relay-index">R{{ i + 1 }}</div>
          <input
            class="relay-name"
            v-model="relayNamesDraft[i]"
            type="text"
            maxlength="32"
            :placeholder="`Relay ${i + 1}`"
          />
          <span
            class="relay-status"
            :class="relayStateLabel(i).cls"
            :title="relayPulseHint(i)"
          >
            {{ relayStateLabel(i).text }}
          </span>
          <button
            class="btn"
            :class="relay.states[i] ? 'btn-danger' : 'btn-success'"
            :disabled="relayBusy(i)"
            @click="askToggleRelay(i)"
          >
            {{ relay.states[i] ? 'Open (OFF)' : 'Close (ON)' }}
          </button>
          <button
            class="btn btn-warning"
            :disabled="relayBusy(i) || !relay.states[i]"
            :title="!relay.states[i] ? 'Relay already open' : 'Open relay for 5 s, then re-close'"
            @click="askRestartRelay(i)"
          >
            Restart
          </button>
        </div>

        <div class="setting-row" style="margin-top:18px">
          <div class="input-group">
            <button
              class="btn btn-primary"
              :disabled="!relayNamesChanged"
              @click="saveRelayNames"
            >
              Save Relay Names
            </button>
            <button
              class="btn btn-secondary"
              :disabled="!relayNamesChanged"
              @click="resetRelayNamesDraft"
            >
              Discard
            </button>
          </div>
          <p class="hint">Names are persisted on the vehicle and survive reboots.</p>
        </div>
      </section>

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
          <label for="gncKDelta">ALOS Look-ahead Time Constant k<sub>δ</sub> (k_delta)</label>
          <div class="input-group">
            <input id="gncKDelta" v-model.number="gncForm.k_delta" type="number" min="1.0" max="60.0" step="0.5" class="text-input" />
            <span class="unit">s</span>
          </div>
          <p class="hint">CTE convergence time constant. Look-ahead Δ = max(delta_min, k_delta × U). τ<sub>ye</sub> = k_delta regardless of speed. Recommended: 15 s (4× autopilot settling time).</p>
        </div>

        <div class="setting-row">
          <label for="gncDeltaMin">ALOS Minimum Look-ahead (delta_min)</label>
          <div class="input-group">
            <input id="gncDeltaMin" v-model.number="gncForm.delta_min" type="number" min="1.0" max="30.0" step="0.5" class="text-input" />
            <span class="unit">m</span>
          </div>
          <p class="hint">Floor for look-ahead distance at very low speeds. 5 m ≈ 2× hull length.</p>
        </div>

        <div class="setting-row">
          <label for="gncGamma">ALOS Adaptive Gain (gamma)</label>
          <div class="input-group">
            <input id="gncGamma" v-model.number="gncForm.gamma" type="number" min="0.0" max="10.0" step="0.1" class="text-input" />
          </div>
          <p class="hint">Adaptive integral gain for compensating ocean currents.</p>
        </div>

        <div class="setting-row">
          <label for="gncAccel">Waypoint Departure Acceleration (accel_ms2)</label>
          <div class="input-group">
            <input id="gncAccel" v-model.number="gncForm.accel_ms2" type="number" min="0.01" max="2.0" step="0.01" class="text-input" />
            <span class="unit">m/s²</span>
          </div>
          <p class="hint">Kinematic acceleration when leaving a waypoint. Ramp-up distance = (v_cruise² − v_wp²) / (2 × a). Does not affect the deceleration profile.</p>
        </div>

        <div class="setting-row">
          <label>Velocity Profiler</label>
          <div class="input-group">
            <label class="toggle-label">
              <input id="gncVelProfiler" type="checkbox" v-model="gncForm.vel_profiler_enabled" class="toggle-checkbox" />
              <span class="toggle-text">{{ gncForm.vel_profiler_enabled ? 'Enabled — trapezoidal ramp active' : 'Disabled — constant cruise force' }}</span>
            </label>
          </div>
          <p class="hint">When disabled the cruise surge force from the speed slider is applied directly (no ramp-up / ramp-down near waypoints).</p>
        </div>

        <div v-if="gncError" class="validation-error">
          <span>&#9888; {{ gncError }}</span>
          <button class="close-error" @click="gncError = null">&#x2715;</button>
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

      <!-- Mission Plan Defaults Section -->
      <section class="settings-section">
        <h3>Mission Plan</h3>
        <p class="hint" style="margin-top:-10px; margin-bottom:15px">
          Default values applied to newly created waypoints and survey patterns. Existing items are not affected.
        </p>

        <div class="setting-row">
          <label for="mpWpRadius">Default Waypoint Acceptance Radius (m)</label>
          <div class="input-group">
            <input id="mpWpRadius" v-model.number="mpForm.wpRadius" type="number" min="1" max="100" step="1" class="text-input" />
          </div>
          <p class="hint">Applied to new waypoints and to the Mission Start / End items on reset.</p>
        </div>

        <div class="setting-row">
          <label for="mpWpSpeed">Default Waypoint Speed (knots)</label>
          <div class="input-group">
            <input id="mpWpSpeed" v-model.number="mpForm.wpSpeed" type="number" min="0.1" max="5" step="0.1" class="text-input" />
          </div>
          <p class="hint">Cross speed for new waypoints.</p>
        </div>

        <div class="setting-row">
          <label for="mpSurveyRadius">Default Survey Acceptance Radius (m)</label>
          <div class="input-group">
            <input id="mpSurveyRadius" v-model.number="mpForm.surveyRadius" type="number" min="1" max="100" step="1" class="text-input" />
          </div>
          <p class="hint">Applied to generated survey transect waypoints.</p>
        </div>

        <div class="setting-row">
          <label for="mpSurveySpeed">Default Survey Speed (knots)</label>
          <div class="input-group">
            <input id="mpSurveySpeed" v-model.number="mpForm.surveySpeed" type="number" min="0.1" max="5" step="0.1" class="text-input" />
          </div>
          <p class="hint">Cross speed for new survey patterns.</p>
        </div>

        <div class="setting-row">
          <div class="input-group">
            <button class="btn btn-primary" @click="saveMissionDefaults" :disabled="!mpChanged">
              Save Mission Defaults
            </button>
          </div>
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

      <!-- Relay Action Confirmation Dialog -->
      <div v-if="relayConfirm" class="confirm-overlay" @click.self="relayConfirm = null">
        <div class="confirm-dialog">
          <h4>{{ relayConfirm.title }}</h4>
          <p v-html="relayConfirm.body"></p>
          <div class="confirm-actions">
            <button class="btn btn-secondary" @click="relayConfirm = null">Cancel</button>
            <button class="btn btn-danger" @click="confirmRelayAction">Confirm</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { useGamepad } from '../composables/useGamepad'

const telemetry = useTelemetryStore()

// ── Joystick / gamepad (shared state) ──────────────────────────────
const gp = useGamepad()
const gpConnected = gp.connected
const gpName      = gp.name
const gpMapping   = gp.mapping
const gpIndex     = gp.index

function fmtAxis(v) {
  const n = Number(v) || 0
  return (n >= 0 ? '+' : '') + n.toFixed(2)
}

// Processed (after deadzone + expo + invert) command preview
const processed = computed(() => gp.leftStickCommand())
const procThrottle = computed(() => processed.value.throttle)
const procSteering = computed(() => processed.value.steering)

// Stick visualization positions (center = 50%/50%, edges = 0%/100%)
function stickPos(axX, axY) {
  const x = Math.min(1, Math.max(-1, Number(axX) || 0))
  const y = Math.min(1, Math.max(-1, Number(axY) || 0))
  return {
    left: `calc(${50 + x * 50}% - 6px)`,
    top:  `calc(${50 + y * 50}% - 6px)`,
  }
}
const rawDotStyle = computed(() => stickPos(gp.axes[0], gp.axes[1]))
const procDotStyle = computed(() => {
  // Map processed throttle/steering back to a stick-space dot. Throttle
  // is positive-up in the vehicle frame, so flip sign for the visualization
  // so it tracks the raw dot.
  const yDir = gp.settings.invertY ? 1 : -1
  return stickPos(procSteering.value, yDir * procThrottle.value)
})

function barStyle(v) {
  const x = Math.min(1, Math.max(-1, Number(v) || 0))
  if (x >= 0) return { left: '50%', width: (x * 50) + '%' }
  return { left: (50 + x * 50) + '%', width: (-x * 50) + '%' }
}
const thrBarStyle = computed(() => barStyle(procThrottle.value))
const strBarStyle = computed(() => barStyle(procSteering.value))

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

// GNC config validation error
const gncError = ref(null)

// GNC config form
const gncForm = ref({
  wn: 4.0,
  zeta: 0.5,
  wn_ref: 1.0,
  zeta_ref: 1.0,
  k_delta: 15.0,
  delta_min: 5.0,
  gamma: 0.0,
  cruise_speed_kn: 3.0,
  accel_ms2: 0.3,
  vel_profiler_enabled: true,
})

// Mission plan defaults form
const mpForm = reactive({
  wpRadius:     5,
  wpSpeed:      1.0,
  surveyRadius: 3,
  surveySpeed:  1.0,
})

// Relay names — local draft so the user can edit then commit with one click.
// Restart pulse end-times are surfaced through a 1 Hz ticker so the
// "X s left" hint counts down in the UI.
const relayNamesDraft = ref(['Relay 1', 'Relay 2', 'Relay 3'])
const relayConfirm    = ref(null)   // { title, body, action: () => void }
const nowTs           = ref(Date.now() / 1000)
let _nowTimer = null

const relay = computed(() => telemetry.relayConfig)
const relayNamesChanged = computed(() => {
  const live = telemetry.relayConfig.names
  return relayNamesDraft.value.some((n, i) => (n ?? '') !== (live[i] ?? ''))
})

function syncRelayNamesDraft() {
  relayNamesDraft.value = (telemetry.relayConfig.names || ['Relay 1','Relay 2','Relay 3']).slice(0, 3)
}
function resetRelayNamesDraft() { syncRelayNamesDraft() }

function relayBusy(i) {
  const until = telemetry.relayConfig.restart_until?.[i] || 0
  return until > nowTs.value
}
function relayStateLabel(i) {
  if (relayBusy(i)) {
    const secs = Math.max(0, Math.ceil(telemetry.relayConfig.restart_until[i] - nowTs.value))
    return { text: `RESTARTING (${secs} s)`, cls: 'state-pulse' }
  }
  return telemetry.relayConfig.states[i]
    ? { text: 'CLOSED (ON)',  cls: 'state-on'  }
    : { text: 'OPEN (OFF)',   cls: 'state-off' }
}
function relayPulseHint(i) {
  return relayBusy(i) ? 'Relay is in a 5 s restart pulse — wait for it to re-close' : ''
}

function askToggleRelay(i) {
  const name = telemetry.relayConfig.names[i] || `R${i+1}`
  const wasOn = !!telemetry.relayConfig.states[i]
  const next = wasOn ? 0 : 1
  relayConfirm.value = {
    title: wasOn ? `Open relay "${name}"?` : `Close relay "${name}"?`,
    body: wasOn
      ? `This will <strong>cut power</strong> to <em>${escapeHtml(name)}</em> (R${i+1}). The subsystem will lose power until you close the relay again.`
      : `This will <strong>restore power</strong> to <em>${escapeHtml(name)}</em> (R${i+1}).`,
    action: () => telemetry.setRelay(i, next),
  }
}
function askRestartRelay(i) {
  const name = telemetry.relayConfig.names[i] || `R${i+1}`
  relayConfirm.value = {
    title: `Restart "${name}"?`,
    body: `This will <strong>open</strong> relay R${i+1} (<em>${escapeHtml(name)}</em>) for <strong>5 seconds</strong> and then re-close it. Use this to power-cycle the connected subsystem.`,
    action: () => telemetry.restartRelay(i),
  }
}
function confirmRelayAction() {
  const c = relayConfirm.value
  relayConfirm.value = null
  if (c && typeof c.action === 'function') c.action()
}
function saveRelayNames() {
  telemetry.setRelayNames(relayNamesDraft.value.map((n, i) => (n || `Relay ${i+1}`).trim()))
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[c])
}

// Keep the draft in sync when backend ships new names (e.g. on first connect)
// — but never clobber unsaved user edits.
watch(() => telemetry.relayConfig.names, () => {
  if (!relayNamesChanged.value) syncRelayNamesDraft()
}, { deep: true })

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
    gncForm.value.wn_ref = telemetry.gncConfig.wn_ref ?? 0.5
    gncForm.value.zeta_ref = telemetry.gncConfig.zeta_ref ?? 1.0
    gncForm.value.k_delta = telemetry.gncConfig.k_delta ?? 15.0
    gncForm.value.delta_min = telemetry.gncConfig.delta_min ?? 5.0
    gncForm.value.gamma = telemetry.gncConfig.gamma
    gncForm.value.tau_x = undefined  // legacy field removed
    gncForm.value.cruise_speed_kn = telemetry.gncConfig.cruise_speed_kn ?? 3.0
    gncForm.value.accel_ms2 = telemetry.gncConfig.accel_ms2 ?? 0.3
    gncForm.value.vel_profiler_enabled = telemetry.gncConfig.vel_profiler_enabled ?? true
  }

  // Load mission plan defaults from store
  mpForm.wpRadius     = telemetry.missionDefaultWpRadius
  mpForm.wpSpeed      = telemetry.missionDefaultWpSpeed
  mpForm.surveyRadius = telemetry.missionDefaultSurveyRadius
  mpForm.surveySpeed  = telemetry.missionDefaultSurveySpeed

  // Seed relay-name draft and start 1 Hz ticker for the restart countdown
  syncRelayNamesDraft()
  _nowTimer = setInterval(() => { nowTs.value = Date.now() / 1000 }, 1000)
})

onBeforeUnmount(() => {
  if (_nowTimer) { clearInterval(_nowTimer); _nowTimer = null }
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
    gncForm.value.wn_ref !== (telemetry.gncConfig.wn_ref ?? 0.5) ||
    gncForm.value.zeta_ref !== (telemetry.gncConfig.zeta_ref ?? 1.0) ||
    gncForm.value.k_delta !== (telemetry.gncConfig.k_delta ?? 15.0) ||
    gncForm.value.delta_min !== (telemetry.gncConfig.delta_min ?? 5.0) ||
    gncForm.value.gamma !== telemetry.gncConfig.gamma ||
    gncForm.value.accel_ms2 !== (telemetry.gncConfig.accel_ms2 ?? 0.3) ||
    gncForm.value.vel_profiler_enabled !== (telemetry.gncConfig.vel_profiler_enabled ?? true)
  )
})

// Clear GNC error whenever the user edits any field
watch(gncForm, () => { gncError.value = null }, { deep: true })

// Sync GNC form from backend heartbeat.
// The system/status handler overwrites telemetry.gncConfig with the authoritative backend
// value. Without this watch, the form would keep its onMounted snapshot (from localStorage)
// even after the backend delivers a different value, making gncConfigChanged incorrect and
// preventing "Update GNC Settings" from being enabled when there actually IS a difference.
// Guard: don't overwrite while the user has unsaved edits (gncConfigChanged would be true).
watch(() => telemetry.gncConfig, (cfg) => {
  if (!cfg || gncConfigChanged.value) return
  gncForm.value.wn               = cfg.wn
  gncForm.value.zeta             = cfg.zeta
  gncForm.value.wn_ref           = cfg.wn_ref           ?? 0.5
  gncForm.value.zeta_ref         = cfg.zeta_ref         ?? 1.0
  gncForm.value.k_delta          = cfg.k_delta          ?? 15.0
  gncForm.value.delta_min        = cfg.delta_min        ?? 5.0
  gncForm.value.gamma            = cfg.gamma
  gncForm.value.cruise_speed_kn  = cfg.cruise_speed_kn  ?? 3.0
  gncForm.value.accel_ms2        = cfg.accel_ms2        ?? 0.3
  gncForm.value.vel_profiler_enabled = cfg.vel_profiler_enabled ?? true
}, { deep: true })

function saveGncConfig() {
  const f = gncForm.value
  const errors = []
  if (!Number.isFinite(f.wn)        || f.wn        <= 0) errors.push('wn debe ser > 0')
  if (!Number.isFinite(f.zeta)      || f.zeta      <= 0) errors.push('zeta debe ser > 0')
  if (!Number.isFinite(f.wn_ref)    || f.wn_ref    <= 0) errors.push('wn_ref debe ser > 0')
  if (!Number.isFinite(f.zeta_ref)  || f.zeta_ref  <= 0) errors.push('zeta_ref debe ser > 0')
  if (!Number.isFinite(f.k_delta)   || f.k_delta   <= 0) errors.push('k_delta debe ser > 0')
  if (!Number.isFinite(f.delta_min) || f.delta_min <= 0) errors.push('delta_min debe ser > 0')
  if (!Number.isFinite(f.gamma)     || f.gamma     <  0) errors.push('gamma debe ser ≥ 0')
  if (!Number.isFinite(f.accel_ms2) || f.accel_ms2 <= 0) errors.push('accel_ms2 debe ser > 0')
  if (errors.length > 0) {
    gncError.value = 'Valores no válidos: ' + errors.join('; ') + '.'
    return
  }
  gncError.value = null
  // Always forward cruise_speed_kn so the profiler doesn't reset to default
  telemetry.setGncConfig({ ...f, cruise_speed_kn: telemetry.gncConfig.cruise_speed_kn ?? 3.0 })
}

const mpChanged = computed(() => {
  return (
    mpForm.wpRadius     !== telemetry.missionDefaultWpRadius     ||
    mpForm.wpSpeed      !== telemetry.missionDefaultWpSpeed      ||
    mpForm.surveyRadius !== telemetry.missionDefaultSurveyRadius ||
    mpForm.surveySpeed  !== telemetry.missionDefaultSurveySpeed
  )
})

function saveMissionDefaults() {
  telemetry.setMissionPlanDefaults({ ...mpForm })
}
</script>

<style scoped>
.settings-container {
  display: flex;
  justify-content: center;
  align-items: flex-start;
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

.validation-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #3d1515;
  border: 1px solid #cc3333;
  border-radius: 6px;
  color: #ff6b6b;
  padding: 10px 14px;
  margin-bottom: 18px;
  font-size: 0.9em;
  gap: 10px;
}

.close-error {
  background: none;
  border: none;
  color: #ff6b6b;
  cursor: pointer;
  font-size: 1em;
  padding: 0 4px;
  line-height: 1;
  flex-shrink: 0;
}

.close-error:hover {
  color: #ff9999;
}

.unit {
  color: #888;
  font-size: 0.9em;
  white-space: nowrap;
}

/* ── Joystick / gamepad test panel ─────────────────────────────────── */
.gp-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 14px;
  border: 1px solid #555;
  background: #2a2a2a;
  color: #aaa;
  font-weight: 600;
  font-size: 0.85em;
}
.gp-status-pill.connected {
  border-color: #2a8a3f;
  background: #142a14;
  color: #6ee06e;
}
.gp-status-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #555;
}
.gp-status-pill.connected .gp-status-dot {
  background: #00C851;
  box-shadow: 0 0 6px rgba(0, 200, 81, 0.9);
}

.gp-test-grid {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 24px;
  align-items: start;
}

.gp-stick-box.disabled { opacity: 0.45; }
.gp-stick-frame {
  position: relative;
  width: 200px;
  height: 200px;
  border-radius: 50%;
  background: #161616;
  border: 1px solid #444;
  box-shadow: inset 0 0 12px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}
.gp-stick-crosshair-h,
.gp-stick-crosshair-v {
  position: absolute;
  background: #2a2a2a;
}
.gp-stick-crosshair-h { left: 0; right: 0; top: 50%; height: 1px; }
.gp-stick-crosshair-v { top: 0; bottom: 0; left: 50%; width: 1px; }
.gp-stick-deadzone {
  position: absolute;
  left: 50%; top: 50%;
  transform: translate(-50%, -50%);
  border: 1px dashed #555;
  border-radius: 50%;
  pointer-events: none;
}
.gp-stick-dot {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  transition: left 0.04s linear, top 0.04s linear;
}
.gp-stick-dot.raw {
  background: rgba(255, 165, 0, 0.55);
  border: 1px solid #FFA500;
}
.gp-stick-dot.processed {
  background: #00C851;
  border: 1px solid #00C851;
  box-shadow: 0 0 6px rgba(0, 200, 81, 0.8);
}
.gp-stick-legend {
  display: flex;
  gap: 12px;
  margin-top: 8px;
  font-size: 0.75em;
  color: #888;
  justify-content: center;
  flex-wrap: wrap;
}
.gp-stick-legend > span { display: inline-flex; align-items: center; gap: 5px; }
.gp-stick-legend .sw-raw,
.gp-stick-legend .sw-proc,
.gp-stick-legend .sw-dz {
  display: inline-block;
  width: 10px; height: 10px; border-radius: 50%;
}
.gp-stick-legend .sw-raw  { background: rgba(255,165,0,0.55); border: 1px solid #FFA500; }
.gp-stick-legend .sw-proc { background: #00C851; }
.gp-stick-legend .sw-dz   { background: transparent; border: 1px dashed #777; }

.gp-readouts {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.gp-readout {
  display: grid;
  grid-template-columns: 110px 1fr 60px;
  gap: 10px;
  align-items: center;
}
.gp-readout.small {
  grid-template-columns: 110px 1fr;
}
.gp-readout-label {
  color: #aaa;
  font-size: 0.85em;
}
.gp-readout-val {
  font-family: monospace;
  color: #eee;
  text-align: right;
  font-size: 0.9em;
}
.gp-bar {
  position: relative;
  height: 12px;
  background: #222;
  border: 1px solid #333;
  border-radius: 3px;
  overflow: hidden;
}
.gp-bar::before {
  content: '';
  position: absolute;
  left: 50%; top: 0; bottom: 0;
  width: 1px;
  background: #555;
}
.gp-bar-fill {
  position: absolute;
  top: 0; bottom: 0;
  border-radius: 2px;
}
.gp-bar-fill.thr { background: #00C851; }
.gp-bar-fill.str { background: #FFA500; }
.gp-axes-raw {
  font-family: monospace;
  color: #aaa;
  font-size: 0.85em;
  letter-spacing: 0.5px;
}

.gp-buttons-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.gp-button {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  min-width: 28px;
  height: 28px;
  padding: 0 6px;
  border-radius: 4px;
  background: #2a2a2a;
  border: 1px solid #444;
  color: #888;
  font-family: monospace;
  font-size: 0.8em;
  transition: background 0.08s, color 0.08s, border-color 0.08s;
}
.gp-button.pressed {
  background: #00C851;
  border-color: #00C851;
  color: #0c2a14;
  font-weight: 700;
  box-shadow: 0 0 6px rgba(0, 200, 81, 0.6);
}

.gp-slider {
  flex: 1;
  min-width: 200px;
  accent-color: #FFA500;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.toggle-checkbox {
  width: 18px;
  height: 18px;
  accent-color: #FFA500;
  cursor: pointer;
  flex-shrink: 0;
}

.toggle-text {
  color: #ccc;
  font-size: 0.95em;
}

/* ── Relay control ───────────────────────────────────────────────── */
.btn-success {
  background-color: #2a8a3f;
  color: white;
}
.btn-success:hover:not(:disabled) {
  background-color: #34a64d;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.relay-row {
  display: grid;
  grid-template-columns: 36px 1fr 170px 130px 110px;
  gap: 10px;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #2a2a2a;
}
.relay-row:last-child { border-bottom: none; }

.relay-index {
  font-weight: 700;
  font-size: 1.05em;
  color: #FFA500;
  text-align: center;
}

.relay-name {
  background: #1a1a1a;
  border: 1px solid #333;
  color: #eee;
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 0.95em;
}
.relay-name:focus {
  outline: none;
  border-color: #FFA500;
}

.relay-status {
  display: inline-block;
  text-align: center;
  padding: 6px 10px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 0.9em;
  letter-spacing: 0.5px;
}
.state-on    { background: #1d3a1d; color: #6ee06e; border: 1px solid #2a8a3f; }
.state-off   { background: #3a1d1d; color: #ff8a8a; border: 1px solid #cc3333; }
.state-pulse { background: #3a2f1d; color: #ffd166; border: 1px solid #cc7700; }

/* Confirmation dialog (relay variant reuses .confirm-overlay/.confirm-dialog) */
.confirm-dialog p em { color: #FFA500; font-style: normal; }
</style>
