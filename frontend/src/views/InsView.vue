<template>
  <div class="ins-workspace">
    <div class="ins-subtabs" role="tablist" aria-label="INS diagnostics">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="ins-subtab"
        :class="{ active: activeTab === tab.id }"
        role="tab"
        :aria-selected="activeTab === tab.id"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="ins-subview">
      <component :is="activeComponent" />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import GnssView from './GnssView.vue'
import ImuView from './ImuView.vue'

const tabs = [
  { id: 'gnss', label: 'GNSS', component: GnssView },
  { id: 'imu', label: 'IMU', component: ImuView },
]

const activeTab = ref('gnss')
const activeComponent = computed(() => (
  tabs.find(tab => tab.id === activeTab.value)?.component || GnssView
))
</script>

<style scoped>
.ins-workspace {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: #121212;
}

.ins-subtabs {
  display: flex;
  flex: 0 0 auto;
  gap: 4px;
  padding: 8px 14px;
  border-bottom: 1px solid #333;
  background: #181818;
}

.ins-subtab {
  min-width: 100px;
  height: 34px;
  padding: 0 18px;
  border: 1px solid #444;
  border-radius: 5px;
  background: #242424;
  color: #aaa;
  font-weight: 700;
  cursor: pointer;
}

.ins-subtab:hover {
  color: #fff;
  border-color: #666;
}

.ins-subtab.active {
  border-color: #FFA500;
  background: #FFA500;
  color: #121212;
}

.ins-subview {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.ins-subview :deep(.gnss-container),
.ins-subview :deep(.imu-container) {
  height: 100%;
}

@media (max-width: 600px) {
  .ins-subtabs {
    padding: 7px 10px;
  }

  .ins-subtab {
    flex: 1;
    min-width: 0;
  }
}
</style>
