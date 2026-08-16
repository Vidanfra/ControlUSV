<template>
  <div class="view-container">
    <MainMap />

    <!-- Left sidebar: Station or WP Route panel -->
    <div v-if="vehicleMode === 'STATION'" class="left-sidebar">
      <StationPanel />
    </div>
    <div v-else-if="vehicleMode === 'WP_ROUTE'" class="left-sidebar">
      <MissionPlannerPanel />
    </div>

    <!-- Manual mode HUD (throttle/steering indicator) -->
    <div v-if="vehicleMode === 'MANUAL' && (isArmed || rtSimActive)" class="manual-hud">
      <div class="hud-row">
        <span class="hud-label">THR</span>
        <div class="hud-bar">
          <div class="hud-fill thr" :style="thrStyle"></div>
        </div>
        <span class="hud-val">{{ manualThrottle.toFixed(1) }}</span>
      </div>
      <div class="hud-row">
        <span class="hud-label">STR</span>
        <div class="hud-bar">
          <div class="hud-fill str" :style="strStyle"></div>
        </div>
        <span class="hud-val">{{ manualSteering.toFixed(1) }}</span>
      </div>
    </div>

    <div class="floating-dashboard">
      <Dashboard />
      <SignalQualityPanel />
    </div>
    <div class="top-center-bar">
      <ControlPanel />
    </div>

    <!-- Fail-safe / system alert banners -->
    <div v-if="alertBanners.length" class="alert-banner-area">
      <div
        v-for="alert in alertBanners"
        :key="alert.id"
        class="alert-banner"
        :class="'alert-' + alert.type"
      >
        <span class="alert-text">{{ alert.message }}</span>
        <button v-if="alert.type === 'warning'" class="alert-dismiss" @click="store.dismissAlert(alert.id)">&times;</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import MainMap from '../components/MainMap.vue'
import ControlPanel from '../components/ControlPanel.vue'
import Dashboard from '../components/Dashboard.vue'
import StationPanel from '../components/StationPanel.vue'
import WpRoutePanel from '../components/WpRoutePanel.vue'
import MissionPlannerPanel from '../components/MissionPlannerPanel.vue'
import SignalQualityPanel from '../components/SignalQualityPanel.vue'
import { useTelemetryStore } from '../stores/telemetry'
import { useManualControl } from '../composables/useManualControl'

const store = useTelemetryStore()
const { vehicleMode, isArmed, rtSimActive, manualThrottle, manualSteering, alertBanners } = storeToRefs(store)

// Activate manual control keyboard + gamepad (PS4) listeners
useManualControl()

// HUD bar styles (center-origin for bipolar values)
const thrStyle = computed(() => {
  const v = manualThrottle.value
  if (v >= 0) return { left: '50%', width: `${v * 50}%` }
  return { left: `${50 + v * 50}%`, width: `${-v * 50}%` }
})

const strStyle = computed(() => {
  const v = manualSteering.value
  if (v >= 0) return { left: '50%', width: `${v * 50}%` }
  return { left: `${50 + v * 50}%`, width: `${-v * 50}%` }
})
</script>

<style scoped>
.view-container {
  width: 100%;
  height: calc(100vh - 50px);
  position: relative;
}

.left-sidebar {
  position: absolute;
  top: 55px;
  left: 12px;
  z-index: 1000;
}

.manual-hud {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  background: rgba(30, 30, 30, 0.9);
  border-radius: 8px;
  padding: 8px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 180px;
}

.hud-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.hud-label {
  font-size: 0.7rem;
  color: #aaa;
  width: 28px;
  text-align: right;
}

.hud-bar {
  flex: 1;
  height: 10px;
  background: #333;
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}

.hud-fill {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 3px;
}

.hud-fill.thr {
  background: #00C851;
}

.hud-fill.str {
  background: #FFA500;
}

.hud-val {
  font-size: 0.7rem;
  color: #ccc;
  width: 30px;
  font-family: monospace;
  text-align: right;
}

.floating-dashboard {
  position: absolute;
  top: 20px;
  right: 20px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}

.top-center-bar {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  width: auto;
  max-width: 600px;
}

.alert-banner-area {
  position: absolute;
  top: 60px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1100;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: auto;
  min-width: 300px;
  max-width: 520px;
}

.alert-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(0,0,0,0.5);
}

.alert-error {
  background: rgba(180, 30, 30, 0.92);
  color: #fff;
  border: 1px solid #e53935;
}

.alert-warning {
  background: rgba(140, 80, 0, 0.92);
  color: #fff;
  border: 1px solid #FFA500;
}

.alert-text {
  flex: 1;
}

.alert-dismiss {
  background: none;
  border: none;
  color: #fff;
  font-size: 1.2rem;
  cursor: pointer;
  margin-left: 10px;
  padding: 0 4px;
  opacity: 0.7;
}

.alert-dismiss:hover {
  opacity: 1;
}
</style>