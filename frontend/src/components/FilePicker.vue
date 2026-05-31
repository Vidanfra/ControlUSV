<template>
  <div class="fp-modal" @click.self="$emit('cancel')">
    <div class="fp-card">
      <header class="fp-head">
        <h3>Select folder</h3>
        <button class="fp-x" @click="$emit('cancel')">×</button>
      </header>

      <div class="fp-bar">
        <button class="fp-btn" :disabled="!current" @click="goUp">↑ Up</button>
        <input class="fp-path" v-model="manualPath" @keyup.enter="loadPath(manualPath)" placeholder="Type a path and Enter" />
        <button class="fp-btn" @click="loadPath(manualPath)">Go</button>
        <button class="fp-btn ghost"
                :disabled="!current"
                :title="!current ? 'Navigate into a drive/folder first' : 'Create a folder inside the current path'"
                @click="askNewFolder">+ New folder</button>
      </div>

      <div v-if="error" class="fp-err">{{ error }}</div>

      <div class="fp-list">
        <div
          v-for="e in dirEntries"
          :key="e.name"
          class="fp-row"
          @dblclick="enter(e)"
          @click="selected = e.name"
          :class="{ sel: selected === e.name }"
        >
          <span class="fp-ic">📁</span>
          <span class="fp-nm">{{ e.name }}</span>
        </div>
        <div v-if="dirEntries.length === 0" class="fp-empty">No subfolders</div>
      </div>

      <footer class="fp-foot">
        <span class="fp-cur" :title="current">{{ current || '(root)' }}</span>
        <div>
          <button class="fp-btn ghost" @click="$emit('cancel')">Cancel</button>
          <button class="fp-btn primary" :disabled="!current" @click="$emit('select', current)">Select this folder</button>
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'

const props = defineProps({ initialPath: { type: String, default: '' } })
const emit = defineEmits(['select', 'cancel'])

const store = useTelemetryStore()
const current = ref('')
const parent  = ref('')
const entries = ref([])
const os      = ref('')
const error   = ref('')
const manualPath = ref('')
const selected   = ref('')

const dirEntries = computed(() => entries.value.filter(e => e.is_dir))

async function loadPath(path) {
  error.value = ''
  try {
    const r = await store.fsList(path || '')
    if (r.status === 'error') { error.value = r.message; return }
    current.value = r.path
    parent.value  = r.parent
    entries.value = r.entries || []
    os.value      = r.os
    manualPath.value = r.path
    selected.value = ''
  } catch (e) {
    error.value = e.message
  }
}

function enter(e) {
  // On Windows root, e.name is "C:\" — use directly. Otherwise join.
  const sep = os.value === 'Windows' ? '\\' : '/'
  if (!current.value) loadPath(e.name)
  else loadPath(current.value.endsWith(sep) ? current.value + e.name : current.value + sep + e.name)
}

function goUp() { loadPath(parent.value || '') }

async function askNewFolder() {
  if (!current.value) {
    error.value = 'Navigate into a drive/folder first before creating a subfolder.'
    return
  }
  const name = prompt('New folder name:')
  if (!name) return
  const trimmed = name.trim()
  if (!trimmed) return
  if (/[\\/:*?"<>|]/.test(trimmed)) {
    error.value = `Invalid folder name: "${trimmed}"`
    return
  }
  const sep = os.value === 'Windows' ? '\\' : '/'
  const base = current.value.endsWith(sep) ? current.value : current.value + sep
  const target = base + trimmed
  error.value = ''
  try {
    const r = await store.fsMkdir(target)
    if (r && r.status === 'ok') {
      // Reload current dir then navigate into the freshly created folder
      await loadPath(current.value)
      selected.value = trimmed
      // Auto-enter so the user can immediately "Select this folder"
      await loadPath(r.path || target)
    } else {
      error.value = (r && r.message) || 'mkdir failed (no response)'
      alert(`Could not create folder:\n${error.value}`)
    }
  } catch (e) {
    error.value = e.message || String(e)
    alert(`Could not create folder:\n${error.value}`)
  }
}

onMounted(() => loadPath(props.initialPath || ''))
</script>

<style scoped>
.fp-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 9000; display: flex; align-items: center; justify-content: center; }
.fp-card { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; width: min(640px, 90vw); max-height: 80vh; display: flex; flex-direction: column; }
.fp-head { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem; border-bottom: 1px solid #334155; }
.fp-head h3 { margin: 0; font-size: 1rem; }
.fp-x { background: none; border: none; color: #94a3b8; font-size: 1.4rem; cursor: pointer; }
.fp-bar { display: flex; gap: 0.4rem; padding: 0.5rem 1rem; border-bottom: 1px solid #334155; }
.fp-path { flex: 1; background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 0.35rem 0.5rem; font-family: monospace; font-size: 0.85rem; }
.fp-btn { background: #334155; color: #e2e8f0; border: none; padding: 0.35rem 0.7rem; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
.fp-btn:hover:not(:disabled) { background: #475569; }
.fp-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.fp-btn.ghost { background: transparent; border: 1px solid #475569; }
.fp-btn.primary { background: #10b981; }
.fp-btn.primary:hover { background: #059669; }
.fp-err { padding: 0.4rem 1rem; color: #fca5a5; font-size: 0.85rem; }
.fp-list { flex: 1; overflow: auto; padding: 0.4rem 0.5rem; }
.fp-row { display: flex; gap: 0.5rem; align-items: center; padding: 0.3rem 0.5rem; border-radius: 4px; cursor: pointer; }
.fp-row:hover { background: #334155; }
.fp-row.sel { background: #1e40af; }
.fp-empty { padding: 1rem; text-align: center; color: #64748b; font-size: 0.85rem; }
.fp-foot { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 1rem; border-top: 1px solid #334155; gap: 0.5rem; }
.fp-cur { font-family: monospace; font-size: 0.8rem; color: #cbd5e1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
</style>
