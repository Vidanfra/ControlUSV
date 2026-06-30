<template>
  <div class="control-panel">
    <!-- Joystick connection indicator (always visible, independent of mode) -->
    <span
      class="gamepad-indicator"
      :class="{ connected: gamepadConnected }"
      :title="gamepadConnected
        ? ('Gamepad connected: ' + gamepadName + ' \u2014 configure in Settings')
        : 'No gamepad detected \u2014 plug in / pair a controller and press any button. Settings \u2192 Manual Control to test.'"
    >
      <span class="gamepad-dot"></span>
      <span class="gamepad-text">{{ gamepadConnected ? 'JOY' : 'NO JOY' }}</span>
    </span>

    <!-- ARM / DISARM Toggle -->
    <button 
      v-if="!isArmed"
      class="btn arm-btn"
      @click="handleArm"
      :disabled="!isConnected || rtSimActive"
      :title="rtSimActive ? 'ARM disabled \u2014 simulation is active' : 'ARM vehicle'"
    >
      ARM
    </button>
    <button 
      v-else
      class="btn disarm-btn"
      @click="handleDisarm"
      :disabled="!isConnected"
    >
      DISARM
    </button>

    <!-- Mode Selector -->
    <div class="mode-selector">
      <button 
        v-for="m in modes" 
        :key="m.value"
        class="btn mode-btn"
        :class="{ active: vehicleMode === m.value }"
        @click="changeMode(m.value)"
        :disabled="!isConnected"
      >
        {{ m.label }}
      </button>
    </div>

    <!-- SIM / REAL Toggle Group -->
    <div class="sim-toggle-group">
      <button
        class="btn sim-opt-btn"
        :class="{ active: simMode === 'REAL' }"
        @click="store.setSimMode('REAL')"
      >REAL</button>
      <button
        class="btn sim-opt-btn sim"
        :class="{ active: simMode === 'SIMULATION' }"
        @click="store.setSimMode('SIMULATION')"
      >SIM</button>
    </div>

    <!-- ARM / DISARM Confirmation Dialog (teleported to body so it
         centers over the viewport regardless of any transformed
         ancestor of the control panel) -->
    <Teleport to="body">
      <div v-if="armConfirm" class="confirm-overlay" @click.self="armConfirm = null">
        <div class="confirm-dialog">
          <h4>{{ armConfirm.title }}</h4>
          <p v-html="armConfirm.body"></p>
          <div class="confirm-actions">
            <button class="btn btn-secondary" @click="armConfirm = null">Cancel</button>
            <button
              class="btn"
              :class="armConfirm.danger ? 'btn-danger' : 'btn-success'"
              @click="confirmArmAction"
            >
              {{ armConfirm.confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'
import { useGamepad } from '../composables/useGamepad'

const store = useTelemetryStore()
const { isArmed, isConnected, vehicleMode, simMode, rtSimActive } = storeToRefs(store)

// Shared gamepad state (singleton across the app)
const { connected: gamepadConnected, name: gamepadName } = useGamepad()

const modes = [
  { value: 'MANUAL', label: 'MANUAL' },
  { value: 'STATION', label: 'STATION' },
  { value: 'WP_ROUTE', label: 'WP ROUTE' },
]

// { title, body, confirmLabel, danger, action }
const armConfirm = ref(null)

const handleArm = () => {
  armConfirm.value = {
    title: 'ARM vehicle?',
    body: 'The motors will be <strong>powered on</strong> and will respond to control commands. Make sure the area around the propellers is clear.',
    confirmLabel: 'ARM',
    danger: false,
    action: () => store.armVehicle(),
  }
}

const handleDisarm = () => {
  armConfirm.value = {
    title: 'DISARM vehicle?',
    body: 'This will <strong>cut motor commands</strong> immediately. Any active mission or station-keeping will stop.',
    confirmLabel: 'DISARM',
    danger: true,
    action: () => store.disarmVehicle(),
  }
}

const confirmArmAction = () => {
  const c = armConfirm.value
  armConfirm.value = null
  if (c && typeof c.action === 'function') c.action()
}

const changeMode = (mode) => {
  store.setVehicleMode(mode)
}
</script>

<style scoped>
.control-panel {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(30, 30, 30, 0.95);
  color: #fff;
  padding: 8px 12px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
}

/* Joystick indicator (left of ARM) */
.gamepad-indicator {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  background: #1e1e1e;
  border: 1px solid #555;
  border-radius: 4px;
  font-size: 0.7rem;
  font-family: monospace;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: #888;
  cursor: default;
  user-select: none;
  transition: color 0.2s, border-color 0.2s, background-color 0.2s;
}

.gamepad-indicator.connected {
  color: #6ee06e;
  border-color: #2a8a3f;
  background: #142a14;
}

.gamepad-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #555;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.4) inset;
}

.gamepad-indicator.connected .gamepad-dot {
  background: #00C851;
  box-shadow: 0 0 6px rgba(0, 200, 81, 0.9);
  animation: gp-pulse 2.2s ease-in-out infinite;
}

@keyframes gp-pulse {
  0%, 100% { box-shadow: 0 0 4px rgba(0, 200, 81, 0.6); }
  50%      { box-shadow: 0 0 10px rgba(0, 200, 81, 1.0); }
}

.btn {
  padding: 8px 14px;
  border: none;
  border-radius: 4px;
  font-weight: bold;
  cursor: pointer;
  transition: opacity 0.2s, transform 0.1s;
  font-size: 0.85rem;
  white-space: nowrap;
}

.btn:active {
  transform: scale(0.95);
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  filter: grayscale(0.8);
}

.arm-btn {
  background-color: #00C851;
  color: white;
  min-width: 70px;
}

.arm-btn:hover:not(:disabled) {
  background-color: #00a543;
}

.disarm-btn {
  background-color: #e53935;
  color: white;
  min-width: 70px;
  animation: pulse-red 1.5s infinite;
}

.disarm-btn:hover:not(:disabled) {
  background-color: #c62828;
}

@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 68, 68, 0.5); }
  50% { box-shadow: 0 0 8px 4px rgba(255, 68, 68, 0.3); }
}

.mode-selector {
  display: flex;
  gap: 2px;
  background: #1e1e1e;
  border: 1px solid #555;
  border-radius: 4px;
  padding: 2px;
}

.mode-btn {
  background: transparent;
  color: #aaa;
  padding: 7px 12px;
  border-radius: 3px;
  border: none;
}

.mode-btn.active {
  background: #FFA500;
  color: #000;
  font-weight: bold;
}

.mode-btn:not(.active):hover:not(:disabled) {
  background: #444;
  color: #fff;
}

.sim-toggle-group {
  display: flex;
  gap: 2px;
  background: #1e1e1e;
  border: 1px solid #555;
  border-radius: 4px;
  padding: 2px;
}

.sim-opt-btn {
  background: transparent;
  color: #aaa;
  padding: 7px 12px;
  border-radius: 3px;
  min-width: 45px;
  border: none;
}

.sim-opt-btn.active {
  background: #1b5e20;
  color: #a5d6a7;
  font-weight: bold;
}

.sim-opt-btn.sim.active {
  background: #5a3e00;
  color: #FFA500;
  font-weight: bold;
}

.sim-opt-btn:not(.active):hover:not(:disabled) {
  background: #444;
  color: #fff;
}

/* ── Confirmation modal (matches Settings view) ────────────────── */
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}
.confirm-dialog {
  background: #1e1e1e;
  border: 1px solid #444;
  border-radius: 8px;
  padding: 20px 24px;
  max-width: 420px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.6);
  color: #eee;
}
.confirm-dialog h4 {
  margin: 0 0 10px 0;
  color: #FFA500;
  font-size: 1.1em;
}
.confirm-dialog p {
  margin: 0 0 18px 0;
  line-height: 1.45;
  color: #ccc;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.btn-secondary {
  background-color: #444;
  color: #ccc;
}
.btn-secondary:hover { background-color: #555; }
.btn-danger {
  background-color: #cc3333;
  color: white;
}
.btn-danger:hover { background-color: #ee4444; }
.btn-success {
  background-color: #2a8a3f;
  color: white;
}
.btn-success:hover { background-color: #34a64d; }
</style>
