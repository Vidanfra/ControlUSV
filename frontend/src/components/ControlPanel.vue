<template>
  <div class="control-panel">
    <!-- ARM / DISARM Toggle -->
    <button 
      v-if="!isArmed"
      class="btn arm-btn"
      @click="handleArm"
      :disabled="!isConnected || rtSimActive"
      :title="rtSimActive ? 'ARM disabled — simulation is active' : 'ARM vehicle'"
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
  </div>
</template>

<script setup>
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { isArmed, isConnected, vehicleMode, simMode, rtSimActive } = storeToRefs(store)

const modes = [
  { value: 'MANUAL', label: 'MANUAL' },
  { value: 'STATION', label: 'STATION' },
  { value: 'WP_ROUTE', label: 'WP ROUTE' },
]

const handleArm = () => {
  if (confirm('Are you sure you want to ARM the vehicle? Motors will receive power.')) {
    store.armVehicle()
  }
}

const handleDisarm = () => {
  if (confirm('Are you sure you want to DISARM?')) {
    store.disarmVehicle()
  }
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
</style>
