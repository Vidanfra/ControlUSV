<template>
  <div class="control-panel">
    <div class="mode-display">
      Mode: <strong>{{ mode || 'UNKNOWN' }}</strong>
    </div>

    <div class="button-group">
      <button 
        class="btn upload-btn"
        @click="uploadMission"
        :disabled="missionWaypoints.length === 0 || !isConnected"
      >
        UPLOAD
      </button>

      <button 
        class="btn arm-btn" 
        @click="sendArm" 
        :disabled="isArmed || !isConnected"
      >
        ARM
      </button>
      
      <button 
        class="btn disarm-btn" 
        @click="sendDisarm" 
        :disabled="!isArmed || !isConnected"
      >
        DISARM
      </button>
    </div>
  </div>
</template>

<script setup>
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { isArmed, isConnected, mode, missionWaypoints } = storeToRefs(store)

const uploadMission = () => {
  store.uploadMission()
}

const sendArm = () => {
  store.sendCommand('ARM', {})
}

const sendDisarm = () => {
  if (confirm("Are you sure you want to DISARM immediately?")) {
    store.sendCommand('DISARM', {})
  }
}
</script>

<style scoped>
.control-panel {
  display: flex;
  align-items: center;
  gap: 20px;
  background: rgba(30, 30, 30, 0.95);
  color: #fff;
  padding: 10px 20px;
  border-radius: 8px;
  box-shadow: 0 -4px 6px rgba(0,0,0,0.3);
  width: 100%;
  max-width: 600px;
  justify-content: space-between;
}

.mode-display {
  font-size: 1rem;
  background: #444;
  padding: 8px 15px;
  border-radius: 4px;
  white-space: nowrap;
}

.button-group {
  display: flex;
  gap: 15px;
  flex: 1;
}

.btn {
  flex: 1;
  padding: 12px 0;
  border: none;
  border-radius: 4px;
  font-weight: bold;
  cursor: pointer;
  transition: opacity 0.2s, transform 0.1s;
  font-size: 1rem;
}

.btn:active {
  transform: scale(0.95);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  filter: grayscale(0.8);
}

.upload-btn {
  background-color: #33b5e5;
  color: white;
}

.arm-btn {
  background-color: #00C851;
  color: white;
}

.disarm-btn {
  background-color: #ff4444;
  color: white;
}
</style>
