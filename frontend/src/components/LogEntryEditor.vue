<template>
  <div class="ed-modal" @click.self="$emit('cancel')">
    <div class="ed-card">
      <header class="ed-head">
        <h3>{{ kind === 'csv' ? 'CSV Logger' : 'JSON Broadcaster' }}
          — {{ editing ? 'Edit' : 'New' }}</h3>
        <button class="ed-x" @click="$emit('cancel')">×</button>
      </header>

      <div class="ed-body">

        <!-- Common: name + frequency -->
        <div class="ed-grid">
          <label>Name
            <input v-model="form.name" placeholder="e.g. full-telemetry" />
          </label>
          <label>Frequency
            <div class="ed-inline">
              <input type="number" min="0" step="any" v-model.number="form.frequency_value" />
              <select v-model="form.frequency_unit">
                <option value="hz">Hz</option>
                <option value="s">s (period)</option>
              </select>
            </div>
          </label>
        </div>

        <!-- CSV-specific -->
        <div v-if="kind === 'csv'" class="ed-grid">
          <label>Rotation (hours)
            <input type="number" min="0.0167" step="any" v-model.number="form.rotation_hours" />
          </label>
          <label>Output folder
            <div class="ed-inline">
              <input v-model="form.output_path" placeholder="/media/usb/logs" />
              <button class="ed-btn" type="button" @click="pickerOpen = true">Browse…</button>
            </div>
          </label>
        </div>

        <!-- Broadcaster-specific -->
        <div v-else class="ed-grid">
          <label>Protocol
            <select v-model="form.protocol">
              <option value="udp">UDP</option>
              <option value="tcp">TCP server</option>
            </select>
          </label>
          <label>Host
            <input v-model="form.host" placeholder="127.0.0.1 or 0.0.0.0" />
          </label>
          <label>Port
            <input type="number" min="1" max="65535" v-model.number="form.port" />
          </label>
        </div>

        <!-- Fields -->
        <div class="ed-sec">
          <div class="ed-secHead">
            <strong>Fields ({{ form.fields.length }} selected)</strong>
            <button class="ed-btn ghost" type="button" @click="form.fields = []">Clear all</button>
          </div>

          <div v-if="!catalog" class="ed-wait">Loading catalog…</div>

          <div v-else class="ed-groups">
            <details v-for="g in catalog.groups" :key="g.id" class="ed-group">
              <summary>
                <span>{{ g.label }}</span>
                <span class="ed-grpCount">{{ selectedInGroup(g) }} / {{ g.fields.length }}</span>
                <button class="ed-mini" type="button" @click.prevent.stop="toggleGroup(g)">
                  {{ allSelectedInGroup(g) ? 'Unselect all' : 'Select all' }}
                </button>
              </summary>
              <div class="ed-fieldList">
                <label v-for="f in g.fields" :key="f.id" class="ed-field">
                  <input type="checkbox"
                         :checked="form.fields.includes(f.id)"
                         @change="toggleField(f.id, $event.target.checked)" />
                  <span class="ed-fname">{{ f.label }}</span>
                  <span v-if="f.unit" class="ed-funit">{{ f.unit }}</span>
                </label>
              </div>
            </details>
          </div>
        </div>
      </div>

      <footer class="ed-foot">
        <label class="ed-enabled">
          <input type="checkbox" v-model="form.enabled" /> Enabled
        </label>
        <div>
          <button class="ed-btn ghost" type="button" @click="$emit('cancel')">Cancel</button>
          <button class="ed-btn primary" type="button" :disabled="!isValid" @click="save">Save</button>
        </div>
      </footer>
    </div>

    <FilePicker v-if="pickerOpen"
                :initial-path="form.output_path"
                @select="onPickerSelect" @cancel="pickerOpen = false" />
  </div>
</template>

<script setup>
import { reactive, computed, onMounted, ref } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import FilePicker from './FilePicker.vue'

const props = defineProps({
  kind: { type: String, required: true },   // 'csv' | 'json'
  entry: { type: Object, default: null },   // existing config or null
})
const emit = defineEmits(['save', 'cancel'])
const store = useTelemetryStore()

const pickerOpen = ref(false)
const editing = computed(() => !!props.entry)

const defaults = props.kind === 'csv'
  ? { id: '', name: '', enabled: true, frequency_value: 1.0, frequency_unit: 'hz',
      rotation_hours: 1.0, output_path: '', fields: [] }
  : { id: '', name: '', enabled: true, frequency_value: 1.0, frequency_unit: 'hz',
      protocol: 'udp', host: '127.0.0.1', port: 9000, fields: [] }

const form = reactive({ ...defaults, ...(props.entry || {}) })
if (!form.id) form.id = `${props.kind}-${Date.now()}-${Math.floor(Math.random()*1000)}`
if (!Array.isArray(form.fields)) form.fields = []

const catalog = computed(() => store.logFieldCatalog)

onMounted(() => store.fetchLogFieldCatalog())

function toggleField(id, checked) {
  if (checked) {
    if (!form.fields.includes(id)) form.fields.push(id)
  } else {
    form.fields = form.fields.filter(x => x !== id)
  }
}
function selectedInGroup(g) {
  return g.fields.filter(f => form.fields.includes(f.id)).length
}
function allSelectedInGroup(g) {
  return g.fields.every(f => form.fields.includes(f.id))
}
function toggleGroup(g) {
  const all = allSelectedInGroup(g)
  const ids = g.fields.map(f => f.id)
  if (all) form.fields = form.fields.filter(x => !ids.includes(x))
  else {
    const set = new Set(form.fields)
    ids.forEach(i => set.add(i))
    form.fields = [...set]
  }
}
function onPickerSelect(p) { form.output_path = p; pickerOpen.value = false }

const isValid = computed(() => {
  if (!form.name || form.fields.length === 0) return false
  if (!(form.frequency_value > 0)) return false
  if (props.kind === 'csv') return !!form.output_path && form.rotation_hours > 0
  return !!form.host && form.port >= 1 && form.port <= 65535
})

function save() {
  if (!isValid.value) return
  emit('save', { ...form })
}
</script>

<style scoped>
.ed-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 8500; display: flex; align-items: center; justify-content: center; }
.ed-card { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px; width: min(760px, 95vw); max-height: 90vh; display: flex; flex-direction: column; }
.ed-head { display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 1rem; border-bottom: 1px solid #334155; }
.ed-head h3 { margin: 0; font-size: 1rem; }
.ed-x { background: none; border: none; color: #94a3b8; font-size: 1.4rem; cursor: pointer; }
.ed-body { flex: 1; overflow: auto; padding: 1rem; display: flex; flex-direction: column; gap: 1rem; }
.ed-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; }
.ed-grid label { display: flex; flex-direction: column; font-size: 0.8rem; color: #cbd5e1; gap: 0.25rem; }
.ed-grid input, .ed-grid select { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 0.35rem 0.5rem; font-size: 0.9rem; }
.ed-inline { display: flex; gap: 0.3rem; }
.ed-inline input, .ed-inline select { flex: 1; }
.ed-btn { background: #334155; color: #e2e8f0; border: none; padding: 0.35rem 0.7rem; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
.ed-btn:hover:not(:disabled) { background: #475569; }
.ed-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ed-btn.ghost { background: transparent; border: 1px solid #475569; }
.ed-btn.primary { background: #10b981; }
.ed-btn.primary:hover:not(:disabled) { background: #059669; }
.ed-mini { background: #334155; color: #cbd5e1; border: none; padding: 0.1rem 0.5rem; border-radius: 3px; cursor: pointer; font-size: 0.7rem; }
.ed-sec { border: 1px solid #334155; border-radius: 6px; padding: 0.5rem; }
.ed-secHead { display: flex; justify-content: space-between; align-items: center; padding: 0.2rem 0.4rem 0.6rem; }
.ed-wait { padding: 1rem; text-align: center; color: #64748b; font-size: 0.85rem; }
.ed-groups { display: flex; flex-direction: column; gap: 0.3rem; max-height: 360px; overflow: auto; }
.ed-group summary { cursor: pointer; padding: 0.4rem 0.5rem; background: #0f172a; border-radius: 4px; display: flex; gap: 0.5rem; align-items: center; font-size: 0.85rem; list-style: none; }
.ed-group summary::-webkit-details-marker { display: none; }
.ed-group summary > span:first-child { flex: 1; }
.ed-grpCount { font-family: monospace; color: #94a3b8; font-size: 0.75rem; }
.ed-fieldList { display: grid; grid-template-columns: 1fr 1fr; gap: 0.2rem; padding: 0.4rem 0.8rem; }
.ed-field { display: flex; gap: 0.4rem; align-items: center; font-size: 0.8rem; }
.ed-fname { flex: 1; }
.ed-funit { color: #64748b; font-family: monospace; font-size: 0.7rem; }
.ed-foot { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 1rem; border-top: 1px solid #334155; gap: 0.5rem; }
.ed-enabled { display: flex; gap: 0.3rem; align-items: center; font-size: 0.85rem; }
</style>
