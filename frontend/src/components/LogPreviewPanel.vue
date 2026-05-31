<template>
  <div class="prev-modal" @click.self="$emit('close')">
    <div class="prev-card">
      <header class="prev-head">
        <h3>Live preview — {{ name }}</h3>
        <button class="prev-x" @click="$emit('close')">×</button>
      </header>

      <div v-if="!preview" class="prev-wait">
        Waiting for preview from logger…
      </div>

      <template v-else-if="preview.kind === 'csv'">
        <div class="prev-meta">
          <span><strong>File:</strong> {{ preview.current_file || '—' }}</span>
          <span v-if="preview.paused" class="prev-paused">⚠ {{ preview.paused }}</span>
        </div>
        <div class="prev-tableWrap">
          <table class="prev-table">
            <thead>
              <tr><th v-for="h in preview.headers" :key="h">{{ h }}</th></tr>
            </thead>
            <tbody>
              <tr>
                <td v-for="f in preview.fields" :key="f">
                  {{ formatVal(preview.row[f]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <template v-else-if="preview.kind === 'json'">
        <div class="prev-meta">
          <span><strong>{{ preview.protocol?.toUpperCase() }}</strong>
                {{ preview.host }}:{{ preview.port }}</span>
          <span v-if="preview.error" class="prev-paused">⚠ {{ preview.error }}</span>
        </div>
        <pre class="prev-json">{{ jsonText }}</pre>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'

const props = defineProps({ id: { type: String, required: true }, name: { type: String, default: '' } })
const emit  = defineEmits(['close'])
const store = useTelemetryStore()

const preview = computed(() => store.loggerPreviews[props.id])
const jsonText = computed(() => {
  try { return JSON.stringify(preview.value?.payload ?? {}, null, 2) }
  catch { return '' }
})

function formatVal(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(4)
  return String(v)
}

let interval
onMounted(() => {
  store.startLoggerPreview(props.id)
  // Keep alive: backend auto-stops after 10 s of silence
  interval = setInterval(() => store.startLoggerPreview(props.id), 4000)
})
onBeforeUnmount(() => {
  clearInterval(interval)
  store.stopLoggerPreview(props.id)
})
</script>

<style scoped>
.prev-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 9000; display: flex; align-items: center; justify-content: center; }
.prev-card { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; width: min(900px, 95vw); max-height: 80vh; display: flex; flex-direction: column; }
.prev-head { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem; border-bottom: 1px solid #334155; }
.prev-head h3 { margin: 0; font-size: 1rem; }
.prev-x { background: none; border: none; color: #94a3b8; font-size: 1.4rem; cursor: pointer; }
.prev-wait { padding: 2rem; text-align: center; color: #94a3b8; }
.prev-meta { padding: 0.5rem 1rem; display: flex; justify-content: space-between; font-size: 0.85rem; color: #cbd5e1; border-bottom: 1px solid #334155; }
.prev-paused { color: #fca5a5; }
.prev-tableWrap { overflow: auto; padding: 0.5rem 1rem; }
.prev-table { border-collapse: collapse; font-size: 0.8rem; font-family: monospace; }
.prev-table th, .prev-table td { border: 1px solid #334155; padding: 0.3rem 0.6rem; text-align: left; white-space: nowrap; }
.prev-table th { background: #0f172a; color: #93c5fd; position: sticky; top: 0; }
.prev-json { padding: 0.5rem 1rem; overflow: auto; font-size: 0.8rem; color: #a5f3fc; margin: 0; }
</style>
