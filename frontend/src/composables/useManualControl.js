import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

/**
 * Composable for arcade-style manual control (keyboard).
 * Active when vehicleMode === 'MANUAL' and isArmed.
 * Keyboard input works even when the user switches tabs (e.g. to view plots).
 * Sends throttle/steering at ~10 Hz via the telemetry store.
 */
export function useManualControl() {
  const store = useTelemetryStore()
  const { vehicleMode, isArmed } = storeToRefs(store)

  const throttle = ref(0)
  const steering = ref(0)

  const keysPressed = new Set()
  let sendInterval = null

  const updateFromKeys = () => {
    let t = 0
    let s = 0
    if (keysPressed.has('ArrowUp') || keysPressed.has('w')) t += 1
    if (keysPressed.has('ArrowDown') || keysPressed.has('s')) t -= 1
    if (keysPressed.has('ArrowLeft') || keysPressed.has('a')) s -= 1
    if (keysPressed.has('ArrowRight') || keysPressed.has('d')) s += 1
    throttle.value = t
    steering.value = s
  }

  const onKeyDown = (e) => {
    if (vehicleMode.value !== 'MANUAL') return
    const key = e.key
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'w', 'a', 's', 'd'].includes(key)) {
      e.preventDefault()
      keysPressed.add(key)
      updateFromKeys()
    }
  }

  const onKeyUp = (e) => {
    const key = e.key
    if (keysPressed.has(key)) {
      keysPressed.delete(key)
      updateFromKeys()
    }
  }

  const startSending = () => {
    if (sendInterval) return
    sendInterval = setInterval(() => {
      if (vehicleMode.value === 'MANUAL' && isArmed.value) {
        store.sendManualInput(throttle.value, steering.value)
        store.manualThrottle = throttle.value
        store.manualSteering = steering.value
      }
    }, 100) // 10 Hz
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
