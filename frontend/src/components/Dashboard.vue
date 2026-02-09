<template>
  <div class="dashboard">
    <h3>USV Telemetry</h3>
    <div class="status-indicator" :class="{ connected: isConnected }">
      {{ isConnected ? 'CONNECTED' : 'DISCONNECTED' }}
    </div>
    
    <div class="data-grid">
      <div class="data-item">
        <label>Latitude</label>
        <span>{{ lat.toFixed(7) }}</span>
      </div>
      <div class="data-item">
        <label>Longitude</label>
        <span>{{ lon.toFixed(7) }}</span>
      </div>
      <div class="data-item">
        <label>Heading</label>
        <span>{{ (heading * 180 / Math.PI).toFixed(1) }}°</span>
      </div>
      <div class="data-item">
        <label>Speed</label>
        <span>{{ speed.toFixed(1) }} m/s</span>
      </div>
      <div class="data-item">
        <label>Battery</label>
        <span>{{ battery.toFixed(1) }} V</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { lat, lon, heading, speed, battery, isConnected } = storeToRefs(store)
</script>

<style scoped>
.dashboard {
  background: rgba(30, 30, 30, 0.9);
  color: #fff;
  padding: 15px;
  border-radius: 8px;
  min-width: 200px;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  box-shadow: 0 4px 6px rgba(0,0,0,0.3);
}

h3 {
  margin-top: 0;
  margin-bottom: 10px;
  font-size: 1.1rem;
  border-bottom: 1px solid #555;
  padding-bottom: 5px;
}

.status-indicator {
  font-size: 0.8rem;
  font-weight: bold;
  margin-bottom: 15px;
  padding: 4px;
  border-radius: 4px;
  text-align: center;
  background: #ff4444; /* Red for disconnected */
}

.status-indicator.connected {
  background: #00C851; /* Green for connected */
}

.data-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.data-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.9rem;
}

.data-item label {
  color: #aaa;
  margin-right: 10px;
}

.data-item span {
  font-family: monospace;
  font-weight: bold;
}
</style>
