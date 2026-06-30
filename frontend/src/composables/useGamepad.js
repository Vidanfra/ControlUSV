import { ref, reactive, computed } from 'vue'

/**
 * Shared (module-singleton) gamepad state for the whole app.
 *
 * Polls `navigator.getGamepads()` in a single requestAnimationFrame loop and
 * exposes reactive refs so any component (top-bar indicator, manual-control
 * loop, settings test panel...) sees the same state.
 *
 * Browser security note: in Chrome / Edge the Gamepad API only exposes pads
 * after the user has interacted with the page AND pressed any button on the
 * controller. The `gamepadconnected` window event fires reliably on that
 * first button press; we still poll because `axes` updates only come via
 * `getGamepads()` (the API has no axis events).
 *
 * Settings persisted in localStorage under `usv.gamepad`:
 *   - deadzone:   0..0.5    (default 0.12)
 *   - expo:       0..1      (default 0.35)  cubic blend, 0 = linear
 *   - invertY:    boolean   (default false) flip throttle direction
 */

const LS_KEY = 'usv.gamepad'
const DEFAULTS = { deadzone: 0.12, expo: 0.35, invertY: false }

function loadSettings() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return { ...DEFAULTS }
    const parsed = JSON.parse(raw)
    return {
      deadzone: clamp(Number(parsed.deadzone ?? DEFAULTS.deadzone), 0, 0.5),
      expo:     clamp(Number(parsed.expo     ?? DEFAULTS.expo),     0, 1),
      invertY:  !!(parsed.invertY ?? DEFAULTS.invertY),
    }
  } catch {
    return { ...DEFAULTS }
  }
}

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)) }

// ── Module-level reactive state (shared across all callers) ────────────
const _connected   = ref(false)
const _name        = ref('')
const _id          = ref('')        // raw gamepad.id (vendor/product)
const _index       = ref(-1)
const _mapping     = ref('')        // 'standard' | '' (browser-dependent)
const _timestamp   = ref(0)         // last gamepad.timestamp seen
const _axes        = reactive([0, 0, 0, 0])
const _buttons     = reactive([])   // array of {pressed, value}
const _settings    = reactive(loadSettings())

let _rafId = null
let _started = false

function persistSettings() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      deadzone: _settings.deadzone,
      expo:     _settings.expo,
      invertY:  _settings.invertY,
    }))
  } catch { /* ignore quota errors */ }
}

function pickGamepad() {
  if (typeof navigator === 'undefined' || !navigator.getGamepads) return null
  const pads = navigator.getGamepads()
  if (!pads) return null
  // Prefer a previously-selected index if still connected.
  if (_index.value >= 0 && pads[_index.value] && pads[_index.value].connected) {
    return pads[_index.value]
  }
  for (const gp of pads) {
    if (gp && gp.connected && gp.axes && gp.axes.length >= 2) return gp
  }
  return null
}

function syncFromPad(gp) {
  if (!gp) {
    if (_connected.value) {
      _connected.value = false
      _name.value = ''
      _id.value = ''
      _index.value = -1
      _mapping.value = ''
      for (let i = 0; i < _axes.length; i++) _axes[i] = 0
      _buttons.splice(0, _buttons.length)
    }
    return
  }
  if (!_connected.value || _index.value !== gp.index) {
    _connected.value = true
    _index.value = gp.index
    _id.value = gp.id || ''
    _name.value = _id.value || 'Gamepad'
    _mapping.value = gp.mapping || ''
  }
  _timestamp.value = gp.timestamp || 0
  // Update axes (Web Gamepad API exposes typically 4: LX, LY, RX, RY)
  for (let i = 0; i < 4; i++) {
    _axes[i] = (gp.axes && gp.axes.length > i) ? (gp.axes[i] ?? 0) : 0
  }
  // Update buttons array length lazily
  const n = gp.buttons ? gp.buttons.length : 0
  if (_buttons.length !== n) {
    _buttons.splice(0, _buttons.length)
    for (let i = 0; i < n; i++) _buttons.push({ pressed: false, value: 0 })
  }
  for (let i = 0; i < n; i++) {
    const b = gp.buttons[i]
    if (b) {
      _buttons[i].pressed = !!b.pressed
      _buttons[i].value   = b.value ?? (b.pressed ? 1 : 0)
    }
  }
}

function pollLoop() {
  syncFromPad(pickGamepad())
  _rafId = requestAnimationFrame(pollLoop)
}

function onGamepadConnected(e) {
  // Force-select the newly arrived pad.
  if (e && e.gamepad) {
    _index.value = e.gamepad.index
  }
  syncFromPad(pickGamepad())
}

function onGamepadDisconnected() {
  syncFromPad(pickGamepad())
}

function startIfNeeded() {
  if (_started || typeof window === 'undefined') return
  _started = true
  window.addEventListener('gamepadconnected', onGamepadConnected)
  window.addEventListener('gamepaddisconnected', onGamepadDisconnected)
  // First probe (will likely be null until the first user gesture).
  syncFromPad(pickGamepad())
  _rafId = requestAnimationFrame(pollLoop)
}

// ── Processing helpers (deadzone + expo) ───────────────────────────────

function applyDeadzone(v, dz) {
  if (Math.abs(v) < dz) return 0
  const sign = v < 0 ? -1 : 1
  const scaled = (Math.abs(v) - dz) / (1 - dz)
  return sign * clamp(scaled, 0, 1)
}

function applyExpo(v, k) {
  return (1 - k) * v + k * v * v * v
}

/**
 * Compute manual-control throttle/steering from the current left stick
 * with the user's deadzone/expo/invert-Y settings applied.
 * Returns { throttle: -1..1, steering: -1..1 }.
 */
function leftStickCommand() {
  if (!_connected.value) return { throttle: 0, steering: 0 }
  const dz = _settings.deadzone
  const ex = _settings.expo
  const lx = applyDeadzone(_axes[0] ?? 0, dz)
  const ly = applyDeadzone(_axes[1] ?? 0, dz)
  // Stick "up" returns a negative Y on the standard mapping, so by default
  // we invert it so up == forward (positive throttle).
  const yDir = _settings.invertY ? 1 : -1
  return {
    throttle: applyExpo(yDir * ly, ex),
    steering: applyExpo(lx, ex),
  }
}

// ── Composable entry point ─────────────────────────────────────────────

export function useGamepad() {
  startIfNeeded()
  return {
    connected:  computed(() => _connected.value),
    name:       computed(() => _name.value),
    id:         computed(() => _id.value),
    index:      computed(() => _index.value),
    mapping:    computed(() => _mapping.value),
    timestamp:  computed(() => _timestamp.value),
    axes:       _axes,
    buttons:    _buttons,
    settings:   _settings,
    setDeadzone(v) { _settings.deadzone = clamp(Number(v) || 0, 0, 0.5); persistSettings() },
    setExpo(v)     { _settings.expo     = clamp(Number(v) || 0, 0, 1);   persistSettings() },
    setInvertY(v)  { _settings.invertY  = !!v;                            persistSettings() },
    resetSettings() {
      _settings.deadzone = DEFAULTS.deadzone
      _settings.expo     = DEFAULTS.expo
      _settings.invertY  = DEFAULTS.invertY
      persistSettings()
    },
    leftStickCommand,
  }
}
