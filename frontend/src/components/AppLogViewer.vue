<template>
  <section class="al-panel">
    <header class="al-head">
      <h3>Application Log <small>(logs/usv_control.log)</small></h3>
      <div class="al-acts">
        <label class="al-auto">
          <input type="checkbox" v-model="autoRefresh" /> Auto-refresh (3 s)
        </label>
        <label class="al-filter">
          Level:
          <select v-model="levelFilter">
            <option value="">All</option>
            <option>DEBUG</option>
            <option>INFO</option>
            <option>WARNING</option>
            <option>ERROR</option>
            <option>CRITICAL</option>
          </select>
        </label>
        <button class="al-btn" @click="refresh">Refresh</button>
        <button class="al-btn ghost" :disabled="!hasMore || loading" @click="loadMore">
          Load 50 more
        </button>
        <button class="al-btn ghost" @click="copyAll" :title="'Copy visible lines'">Copy</button>
      </div>
    </header>

    <div class="al-meta" v-if="meta">
      <span>File: <code>{{ meta.path }}</code></span>
      <span>· {{ fmtSize(meta.size_bytes) }}</span>
      <span>· Showing <strong>{{ filteredLines.length }}</strong> / loaded {{ allLines.length }} lines</span>
      <span v-if="!hasMore">· (top of buffer)</span>
    </div>

    <div v-if="error" class="al-err">{{ error }}</div>

    <pre ref="logEl" class="al-pre">
      <span v-for="(ln, idx) in filteredLines" :key="idx"
            class="al-line" :class="lineLevel(ln)">{{ ln }}
</span>
    </pre>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'

const store = useTelemetryStore()

const PAGE = 50
const allLines    = ref([])    // chronological (oldest first)
const meta        = ref(null)
const hasMore     = ref(false)
const loading     = ref(false)
const error       = ref('')
const autoRefresh = ref(false)
const levelFilter = ref('')
const logEl       = ref(null)

const filteredLines = computed(() => {
  if (!levelFilter.value) return allLines.value
  const pat = new RegExp(`\\| *${levelFilter.value}\\b`)
  return allLines.value.filter(l => pat.test(l))
})

function lineLevel(l) {
  if (/\|\s*ERROR\s*\|/.test(l))    return 'lv-err'
  if (/\|\s*WARNING\s*\|/.test(l))  return 'lv-warn'
  if (/\|\s*CRITICAL\s*\|/.test(l)) return 'lv-crit'
  if (/\|\s*DEBUG\s*\|/.test(l))    return 'lv-dbg'
  return ''
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const r = await store.fetchAppLog(PAGE, 0)
    if (r.status === 'ok') {
      allLines.value = r.lines
      meta.value = r
      hasMore.value = r.has_more
      await nextTick()
      if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
    } else {
      error.value = r.message || 'unknown error'
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  loading.value = true
  error.value = ''
  try {
    // Skip the lines already shown to walk back PAGE more from there
    const offset = allLines.value.length
    const r = await store.fetchAppLog(PAGE, offset)
    if (r.status === 'ok') {
      // Prepend older lines (preserve scroll position relative to bottom)
      const prevScrollHeight = logEl.value ? logEl.value.scrollHeight : 0
      allLines.value = [...r.lines, ...allLines.value]
      meta.value = { ...r, returned_lines: allLines.value.length }
      hasMore.value = r.has_more
      await nextTick()
      if (logEl.value) {
        logEl.value.scrollTop = logEl.value.scrollHeight - prevScrollHeight
      }
    } else {
      error.value = r.message || 'unknown error'
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function copyAll() {
  navigator.clipboard?.writeText(filteredLines.value.join('\n'))
    .catch(() => {})
}

function fmtSize(b) {
  if (!b && b !== 0) return ''
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} kB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

let timer
watch(autoRefresh, (on) => {
  clearInterval(timer)
  if (on) timer = setInterval(refresh, 3000)
})

onMounted(refresh)
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.al-panel { background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 0.6rem 0.8rem; margin-top: 1rem; }
.al-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.4rem; }
.al-head h3 { margin: 0; font-size: 0.95rem; }
.al-head small { color: #64748b; font-weight: normal; font-family: monospace; }
.al-acts { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
.al-auto, .al-filter { font-size: 0.8rem; color: #cbd5e1; display: flex; gap: 0.3rem; align-items: center; }
.al-filter select { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 0.15rem 0.4rem; font-size: 0.8rem; }
.al-btn { background: #334155; color: #e2e8f0; border: none; padding: 0.3rem 0.7rem; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
.al-btn:hover:not(:disabled) { background: #475569; }
.al-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.al-btn.ghost { background: transparent; border: 1px solid #475569; }
.al-meta { font-size: 0.75rem; color: #94a3b8; margin: 0.4rem 0; display: flex; flex-wrap: wrap; gap: 0.3rem; }
.al-meta code { color: #cbd5e1; font-family: monospace; }
.al-err { color: #fca5a5; padding: 0.4rem; font-size: 0.85rem; }
.al-pre { background: #0b1220; color: #cbd5e1; border: 1px solid #1f2937; border-radius: 4px; padding: 0.4rem 0.6rem; max-height: 360px; overflow: auto; font-family: 'Consolas', monospace; font-size: 0.75rem; margin: 0; white-space: pre; }
.al-line.lv-err  { color: #fca5a5; }
.al-line.lv-warn { color: #fcd34d; }
.al-line.lv-crit { color: #f87171; font-weight: bold; }
.al-line.lv-dbg  { color: #64748b; }
</style>
