<template>
  <div class="dashboard">
    <h3>USV Telemetry</h3>
    <div class="status-indicator" :class="{ connected: isConnected }">
      {{ isConnected ? 'CONNECTED' : 'DISCONNECTED' }}
    </div>
    
    <div class="data-grid">
      <div class="data-item">
        <label>Lat</label>
        <span :style="{ color: store.fixColor }">{{ lat.toFixed(7) }}</span>
      </div>
      <div class="data-item">
        <label>Lon</label>
        <span :style="{ color: store.fixColor }">{{ lon.toFixed(7) }}</span>
      </div>
      <div class="data-item">
        <label>Heading</label>
        <span>{{ store.bestHeading.toFixed(1) }}° <small class="src-tag">{{ store.headingSource }}</small></span>
      </div>
      <div class="data-item">
        <label>Speed</label>
        <span>{{ store.gnssSogKnots.toFixed(1) }} kn</span>
      </div>
      <div class="data-item">
        <label>Battery</label>
        <span>{{ store.batteryVoltage.toFixed(1) }} V</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const store = useTelemetryStore()
const { lat, lon, isConnected } = storeToRefs(store)
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
  padding-bottom: 8px;
}

.status-indicator {
  font-size: 0.8rem;
  font-weight: bold;
  margin-bottom: 15px;
  padding: 4px;
  border-radius: 4px;
  text-align: center;
  background: #ff4444;
}

.status-indicator.connected {
  background: #00C851;
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

.src-tag {
  font-size: 0.7rem;
  color: #888;
  font-weight: normal;
  margin-left: 3px;
}
</style>
