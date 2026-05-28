<template>
  <div class="app_container">
    <!-- Top Navigation Bar -->
    <nav class="navbar">
      <div class="nav-brand">USV Salpa 1 Dashboard</div>
      <div class="nav-tabs">
        <button 
          v-for="tab in tabs" 
          :key="tab.id"
          :class="{ active: telemetry.currentTab === tab.id }"
          @click="telemetry.currentTab = tab.id"
        >
          {{ tab.name }}
        </button>
      </div>
      <div class="sensor-status-bar">
        <span
          v-for="s in sensors"
          :key="s.key"
          class="sensor-dot"
          :class="{
            'status-ok': telemetry.sensorStatus[s.key].status === 'ok',
            'status-error': telemetry.sensorStatus[s.key].status === 'error',
            'status-disconnected': telemetry.sensorStatus[s.key].status !== 'ok' && telemetry.sensorStatus[s.key].status !== 'error'
          }"
          :title="s.label + ': ' + telemetry.sensorStatus[s.key].status + ' — ' + telemetry.sensorStatus[s.key].message"
        >{{ s.label }}</span>
      </div>
      <div class="nav-status" :class="{ connected: telemetry.isConnected }">
        {{ telemetry.isConnected ? 'Connected' : 'Disconnected' }}
      </div>
    </nav>

    <!-- Main Content Area -->
    <div class="main-content">
      <KeepAlive>
        <component :is="currentComponent" />
      </KeepAlive>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useTelemetryStore } from './stores/telemetry'

// Import Views
import MapView from './views/MapView.vue'
import GncView from './views/GncView.vue'
import GnssView from './views/GnssView.vue'
import PowerView from './views/PowerView.vue'
import ImuView from './views/ImuView.vue'
import SimView from './views/SimView.vue'
import SettingsView from './views/SettingsView.vue'

const telemetry = useTelemetryStore()

// Sensor status indicators
const sensors = [
  { key: 'gnss',  label: 'GNSS' },
  { key: 'imu',   label: 'IMU' },
  { key: 'power', label: 'PWR' },
]

// Tabs Configuration
const tabs = [
  { id: 'map', name: 'Map', component: MapView },
  { id: 'gnss', name: 'GNSS', component: GnssView },
  { id: 'gnc', name: 'Control', component: GncView },
  { id: 'power', name: 'Power', component: PowerView },
  { id: 'imu', name: 'IMU', component: ImuView },
  { id: 'sim', name: 'Simulation', component: SimView },
  { id: 'settings', name: 'Settings', component: SettingsView }
]

const currentComponent = computed(() => {
  return tabs.find(t => t.id === telemetry.currentTab)?.component || MapView
})

onMounted(() => {
  telemetry.connectWebSocket()
})
</script>

<style>
/* Global Reset */
body, html {
  margin: 0;
  padding: 0;
  height: 100%;
  width: 100%;
  overflow: hidden;
  font-family: Arial, sans-serif;
  background-color: #121212;
}

#app {
  width: 100%;
  height: 100%;
}

.app_container {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
}

/* Navbar Styles */
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 50px;
  background-color: #1e1e1e;
  border-bottom: 2px solid #333;
  padding: 0 20px;
  color: white;
  z-index: 2000;
}

.nav-brand {
  font-weight: bold;
  font-size: 1.2rem;
  color: #FFA500;
}

.nav-tabs {
  display: flex;
  gap: 10px;
  height: 100%;
}

.nav-tabs button {
  background: none;
  border: none;
  color: #aaa;
  font-size: 1rem;
  font-weight: bold;
  padding: 0 15px;
  cursor: pointer;
  height: 100%;
  border-bottom: 3px solid transparent;
  transition: all 0.2s;
}

.nav-tabs button:hover {
  color: white;
  background-color: #2a2a2a;
}

.nav-tabs button.active {
  color: #FFA500;
  border-bottom: 3px solid #FFA500;
  background-color: #2a2a2a;
}

.nav-status {
  font-weight: bold;
  color: #e53935;
}

.nav-status.connected {
  color: #00C851;
}

/* Sensor status bar */
.sensor-status-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-right: 15px;
  border-right: 1px solid #444;
  padding-right: 15px;
}

.sensor-dot {
  font-size: 0.75rem;
  font-weight: bold;
  padding: 2px 8px;
  border-radius: 10px;
  cursor: default;
  user-select: none;
}

.sensor-dot.status-ok {
  background-color: #00C851;
  color: #000;
}

.sensor-dot.status-disconnected {
  background-color: #555;
  color: #aaa;
}

.sensor-dot.status-error {
  background-color: #e53935;
  color: #fff;
}

.main-content {
  flex-grow: 1;
  position: relative;
  overflow: hidden;
}
</style>
