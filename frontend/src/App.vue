<template>
  <div class="app_container">
    <MainMap />
    <div class="floating-dashboard">
      <Dashboard />
    </div>
    <div class="bottom-bar">
      <ControlPanel />
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import MainMap from './components/MainMap.vue'
import Dashboard from './components/Dashboard.vue'
import ControlPanel from './components/ControlPanel.vue'
import { useTelemetryStore } from './stores/telemetry'

const telemetry = useTelemetryStore()

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
}

#app {
  width: 100%;
  height: 100%;
}

.app_container {
  position: relative;
  width: 100vw;
  height: 100vh;
}

.floating-dashboard {
  position: absolute;
  top: 20px;
  right: 20px;
  z-index: 1000;
}

.bottom-bar {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  width: 80%;
  max-width: 600px;
}
</style>
