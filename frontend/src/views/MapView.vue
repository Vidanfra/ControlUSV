<template>
  <div class="view-container">
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
import MainMap from '../components/MainMap.vue'
import ControlPanel from '../components/ControlPanel.vue'
import Dashboard from '../components/Dashboard.vue'
</script>

<style scoped>
.view-container {
  width: 100%;
  height: calc(100vh - 50px); /* Adjust for navbar */
  position: relative;
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