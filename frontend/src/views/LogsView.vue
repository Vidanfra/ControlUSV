<template>
  <div class="logs-view">
    <header class="logs-head">
      <h2>Logs &amp; Broadcasters</h2>
      <p class="logs-sub">
        CSV files are written to the configured folder (e.g. SD card / USB).
        JSON broadcasters push selected fields to the network for other vehicle devices.
      </p>
    </header>

    <!-- System monitor strip -->
    <section class="sys-strip">
      <div class="sys-cell"><div class="sys-k">CPU</div><div class="sys-v">{{ fmt(sys.cpu_percent, '%') }}</div></div>
      <div class="sys-cell"><div class="sys-k">CPU Temp</div><div class="sys-v">{{ fmt(sys.cpu_temp_c, '°C') }}</div></div>
      <div class="sys-cell"><div class="sys-k">RAM</div><div class="sys-v">{{ fmt(sys.ram_percent, '%') }} <small>({{ Math.round(sys.ram_used_mb) }}/{{ Math.round(sys.ram_total_mb) }} MB)</small></div></div>
      <div class="sys-cell"><div class="sys-k">Disk</div><div class="sys-v">{{ fmt(sys.disk_percent, '%') }} <small>({{ fmt(sys.disk_used_gb, 'GB') }}/{{ fmt(sys.disk_total_gb, 'GB') }})</small></div></div>
      <div class="sys-cell"><div class="sys-k">Net rx/tx</div><div class="sys-v">{{ fmt(sys.net_rx_kbps, 'kbps') }} / {{ fmt(sys.net_tx_kbps, 'kbps') }}</div></div>
      <div class="sys-cell"><div class="sys-k">Uptime</div><div class="sys-v">{{ uptimeStr }}</div></div>
      <div class="sys-cell"><div class="sys-k">Host</div><div class="sys-v">{{ sys.hostname || '—' }} <small>({{ sys.os_name }})</small></div></div>
    </section>

    <div class="logs-grid">

      <!-- CSV LOGGERS -->
      <section class="logs-panel">
        <header class="panel-head">
          <h3>CSV Loggers</h3>
          <button class="btn primary" @click="openEditor('csv', null)">+ Add CSV Logger</button>
        </header>

        <div v-if="csvLoggers.length === 0" class="empty">No CSV loggers configured.</div>
        <div v-else class="rows">
          <div v-for="c in csvLoggers" :key="c.id" class="row">
            <div class="row-main">
              <div class="row-name">
                <span class="dot" :class="c.enabled ? 'on' : 'off'"></span>
                {{ c.name }}
              </div>
              <div class="row-meta">
                <span>{{ c.frequency_value }} {{ c.frequency_unit }}</span> ·
                <span>{{ c.rotation_hours }} h rotation</span> ·
                <span class="path" :title="c.output_path">📁 {{ c.output_path || '—' }}</span> ·
                <span>{{ c.fields.length }} fields</span>
              </div>
            </div>
            <div class="row-acts">
              <button class="btn ghost" @click="store.toggleLogger(c.id, !c.enabled)">
                {{ c.enabled ? 'Stop' : 'Start' }}
              </button>
              <button class="btn ghost" @click="openPreview(c)">Preview</button>
              <button class="btn ghost" @click="openEditor('csv', c)">Edit</button>
              <button class="btn danger" @click="confirmRemove(c)">Delete</button>
            </div>
          </div>
        </div>
      </section>

      <!-- JSON BROADCASTERS -->
      <section class="logs-panel">
        <header class="panel-head">
          <h3>JSON Broadcasters</h3>
          <button class="btn primary" @click="openEditor('json', null)">+ Add Broadcaster</button>
        </header>

        <div v-if="jsonBroadcasters.length === 0" class="empty">No broadcasters configured.</div>
        <div v-else class="rows">
          <div v-for="c in jsonBroadcasters" :key="c.id" class="row">
            <div class="row-main">
              <div class="row-name">
                <span class="dot" :class="c.enabled ? 'on' : 'off'"></span>
                {{ c.name }}
              </div>
              <div class="row-meta">
                <span>{{ c.frequency_value }} {{ c.frequency_unit }}</span> ·
                <span class="proto">{{ c.protocol.toUpperCase() }}</span>
                <span>{{ c.host }}:{{ c.port }}</span> ·
                <span>{{ c.fields.length }} fields</span>
              </div>
            </div>
            <div class="row-acts">
              <button class="btn ghost" @click="store.toggleLogger(c.id, !c.enabled)">
                {{ c.enabled ? 'Stop' : 'Start' }}
              </button>
              <button class="btn ghost" @click="openPreview(c)">Preview</button>
              <button class="btn ghost" @click="openEditor('json', c)">Edit</button>
              <button class="btn danger" @click="confirmRemove(c)">Delete</button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <AppLogViewer />

    <LogEntryEditor v-if="editorOpen"
                    :kind="editorKind"
                    :entry="editorEntry"
                    @save="onEditorSave"
                    @cancel="editorOpen = false" />

    <LogPreviewPanel v-if="previewId"
                     :id="previewId"
                     :name="previewName"
                     @close="previewId = null" />
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import LogEntryEditor from '../components/LogEntryEditor.vue'
import LogPreviewPanel from '../components/LogPreviewPanel.vue'
import AppLogViewer from '../components/AppLogViewer.vue'

const store = useTelemetryStore()

const csvLoggers       = computed(() => store.loggingConfig.csv_loggers       || [])
const jsonBroadcasters = computed(() => store.loggingConfig.json_broadcasters || [])
const sys = computed(() => store.systemMonitor)

const editorOpen  = ref(false)
const editorKind  = ref('csv')
const editorEntry = ref(null)
const previewId   = ref(null)
const previewName = ref('')

function openEditor(kind, entry) {
  editorKind.value = kind
  editorEntry.value = entry
  editorOpen.value = true
}
function onEditorSave(cfg) {
  if (editorKind.value === 'csv') store.upsertCsvLogger(cfg)
  else store.upsertJsonBroadcaster(cfg)
  editorOpen.value = false
}
function openPreview(c) {
  previewId.value = c.id
  previewName.value = c.name
}
function confirmRemove(c) {
  if (confirm(`Delete logger "${c.name}"?`)) store.removeLogger(c.id)
}

function fmt(v, suffix='') {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) + (suffix ? ' ' + suffix : '')
  return v + (suffix ? ' ' + suffix : '')
}

const uptimeStr = computed(() => {
  const s = sys.value.uptime_s || 0
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`
})

onMounted(() => store.fetchLogFieldCatalog())
</script>

<style scoped>
.logs-view { padding: 1rem 1.5rem; color: #e2e8f0; height: 100%; overflow: auto; }
.logs-head h2 { margin: 0 0 0.2rem; }
.logs-sub { margin: 0 0 1rem; color: #94a3b8; font-size: 0.85rem; }
.sys-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.5rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 0.6rem; margin-bottom: 1rem; }
.sys-cell { background: #1e293b; border-radius: 4px; padding: 0.4rem 0.6rem; }
.sys-k { color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px; }
.sys-v { font-size: 0.95rem; font-family: monospace; color: #93c5fd; margin-top: 0.15rem; }
.sys-v small { color: #64748b; font-size: 0.7rem; font-family: monospace; }
.logs-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 1100px) { .logs-grid { grid-template-columns: 1fr; } }
.logs-panel { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 0.6rem 0.8rem; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem; }
.panel-head h3 { margin: 0; font-size: 0.95rem; }
.btn { background: #334155; color: #e2e8f0; border: none; padding: 0.3rem 0.7rem; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
.btn:hover { background: #475569; }
.btn.primary { background: #10b981; }
.btn.primary:hover { background: #059669; }
.btn.ghost { background: transparent; border: 1px solid #475569; }
.btn.danger { background: #b91c1c; }
.btn.danger:hover { background: #991b1b; }
.empty { padding: 1rem; text-align: center; color: #64748b; font-size: 0.85rem; }
.rows { display: flex; flex-direction: column; gap: 0.4rem; }
.row { background: #0f172a; border: 1px solid #334155; border-radius: 4px; padding: 0.5rem 0.7rem; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.row-main { min-width: 0; flex: 1; }
.row-name { display: flex; gap: 0.4rem; align-items: center; font-weight: 600; font-size: 0.9rem; }
.row-meta { font-size: 0.75rem; color: #94a3b8; margin-top: 0.2rem; font-family: monospace; display: flex; gap: 0.3rem; flex-wrap: wrap; }
.row-meta .path { color: #cbd5e1; }
.row-meta .proto { color: #fcd34d; font-weight: 700; }
.row-acts { display: flex; gap: 0.3rem; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.on { background: #10b981; box-shadow: 0 0 6px #10b981; }
.dot.off { background: #64748b; }
</style>
