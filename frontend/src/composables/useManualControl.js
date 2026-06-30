import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'
import { useGamepad } from './useGamepad'

/**
 * Composable for arcade-style manual control (keyboard + gamepad).
 *
 * Active when vehicleMode === 'MANUAL' and (isArmed || rtSimActive).
 *
 * Inputs supported:
 *  - Keyboard: arrow keys / WASD (digital, ±1).
 *  - Gamepad (Web Gamepad API, e.g. PS4 / DualShock 4 / DualSense, Xbox):
 *      * Left stick X axis → steering
 *      * Left stick Y axis → throttle (up = forward, by default)
 *
 * Gamepad polling and settings (deadzone/expo/invert-Y) live in the shared
 * `useGamepad` composable so the rest of the UI (top-bar indicator,
 * Settings test panel) sees the exact same state regardless of mode.
 *
 * Keyboard and gamepad inputs are combined per-axis: whichever has the
 * larger magnitude wins (so the analog stick is not "flattened" by a
 * digital key press, and vice versa). Result is clamped to [-1, 1].
 *
 * Commands are sent at ~20 Hz via the telemetry store while in MANUAL.
 */
export function useManualControl() {
  const store = useTelemetryStore()
  const { vehicleMode, isArmed } = storeToRefs(store)
  const gamepad = useGamepad()

  const throttle = ref(0)
  const steering = ref(0)

  const keysPressed = new Set()
  let sendInterval = null

  // Send rate: 20 Hz gives smoother analog response than the original 10 Hz.
  const SEND_PERIOD_MS = 50

  // --- Keyboard handling --------------------------------------------------

  const readKeyboard = () => {
    let t = 0
    let s = 0
    if (keysPressed.has('ArrowUp') || keysPressed.has('w')) t += 1
    if (keysPressed.has('ArrowDown') || keysPressed.has('s')) t -= 1
    if (keysPressed.has('ArrowLeft') || keysPressed.has('a')) s -= 1
    if (keysPressed.has('ArrowRight') || keysPressed.has('d')) s += 1
    return { t, s }
  }

  const onKeyDown = (e) => {
    if (vehicleMode.value !== 'MANUAL') return
    const key = e.key
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'w', 'a', 's', 'd'].includes(key)) {
      e.preventDefault()
      keysPressed.add(key)
    }
  }

  const onKeyUp = (e) => {
    const key = e.key
    if (keysPressed.has(key)) {
      keysPressed.delete(key)
    }
  }

  // --- Combine inputs and send -------------------------------------------

  const clamp = (v) => Math.min(1, Math.max(-1, v))
  // Pick the input with larger magnitude per-axis so the analog stick is
  // not "flattened" by simultaneous keyboard input and vice versa.
  const pickLarger = (a, b) => (Math.abs(a) >= Math.abs(b) ? a : b)

  const updateInputs = () => {
    const kb = readKeyboard()
    const gp = gamepad.leftStickCommand()
    throttle.value = clamp(pickLarger(kb.t, gp.throttle))
    steering.value = clamp(pickLarger(kb.s, gp.steering))
  }

  const startSending = () => {
    if (sendInterval) return
    sendInterval = setInterval(() => {
      updateInputs()
      if (vehicleMode.value === 'MANUAL' && (isArmed.value || store.rtSimActive)) {
        store.sendManualInput(throttle.value, steering.value)
        store.manualThrottle = throttle.value
        store.manualSteering = steering.value
      }
    }, SEND_PERIOD_MS)
  }

  const stopSending = () => {
    if (sendInterval) {
      clearInterval(sendInterval)
      sendInterval = null
    }
    throttle.value = 0
    steering.value = 0
    keysPressed.clear()
    store.manualThrottle = 0
    store.manualSteering = 0
  }

  // Start/stop based on mode only (NOT tab)
  watch(vehicleMode, (mode) => {
    if (mode === 'MANUAL') {
      startSending()
    } else {
      stopSending()
    }
  }, { immediate: true })

  onMounted(() => {
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', onKeyDown)
    window.removeEventListener('keyup', onKeyUp)
    stopSending()
  })

  return { throttle, steering }
}
