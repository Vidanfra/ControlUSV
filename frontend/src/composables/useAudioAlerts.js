import { watch } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'

// ── GNSS quality tiers ────────────────────────────────────────────────────────
// Maps a raw GNSS fix_type to a coarse quality level so we can detect
// upgrades / downgrades across the three meaningful bands the operator cares
// about: signal lost → GPS → RTK.
//   0 = signal lost (no fix)
//   1 = GPS         (GPS / DGPS / PPS — has a fix but not RTK)
//   2 = RTK         (RTK float or fixed)
function gnssQuality(fixType) {
  if (fixType >= 4) return 2   // RTK (float=5 / fixed=4)
  if (fixType >= 1) return 1   // GPS / DGPS / PPS
  return 0                     // no fix — signal lost
}

/**
 * Installs acoustic alerts that react to telemetry state transitions.
 *
 * Each event plays a single, distinct sound (never a continuously repeating
 * alarm).  Sounds are synthesised with the Web Audio API so no audio asset
 * files are required and everything works fully offline.
 *
 * Call once from a top-level component's `setup()` (e.g. App.vue).
 */
export function useAudioAlerts() {
  const telemetry = useTelemetryStore()

  // ── Audio context (lazily created, resumed on first user gesture) ──────────
  let audioCtx = null

  function getCtx() {
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext
      if (!AC) return null
      audioCtx = new AC()
    }
    return audioCtx
  }

  // Browsers start an AudioContext in the "suspended" state until the user
  // interacts with the page. Resume it on the first interaction so alerts can
  // play afterwards.
  function resumeOnGesture() {
    const ctx = getCtx()
    if (ctx && ctx.state === 'suspended') ctx.resume()
    window.removeEventListener('pointerdown', resumeOnGesture)
    window.removeEventListener('keydown', resumeOnGesture)
  }
  window.addEventListener('pointerdown', resumeOnGesture)
  window.addEventListener('keydown', resumeOnGesture)

  /**
   * Schedules a sequence of notes on the Web Audio graph.
   * @param {Array<{freq:number, start:number, dur:number, type?:OscillatorType, vol?:number}>} notes
   */
  function playSequence(notes) {
    const ctx = getCtx()
    if (!ctx) return
    if (ctx.state === 'suspended') ctx.resume()
    const t0 = ctx.currentTime
    for (const n of notes) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = n.type || 'sine'
      osc.frequency.value = n.freq
      const start = t0 + n.start
      const end = start + n.dur
      const vol = n.vol ?? 0.25
      // Short attack / release envelope to avoid clicks.
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.exponentialRampToValueAtTime(vol, start + 0.01)
      gain.gain.setValueAtTime(vol, end - 0.03)
      gain.gain.exponentialRampToValueAtTime(0.0001, end)
      osc.connect(gain).connect(ctx.destination)
      osc.start(start)
      osc.stop(end + 0.02)
    }
  }

  // ── Sound definitions ──────────────────────────────────────────────────────
  // Backend connection lost — severe: three harsh descending square beeps.
  function soundConnectionLost() {
    playSequence([
      { freq: 500, start: 0.00, dur: 0.16, type: 'square', vol: 0.30 },
      { freq: 380, start: 0.20, dur: 0.16, type: 'square', vol: 0.30 },
      { freq: 260, start: 0.40, dur: 0.28, type: 'square', vol: 0.30 },
    ])
  }

  // GNSS lost while armed — severe but distinct: fast two-tone siren sweep.
  function soundGnssLostArmed() {
    playSequence([
      { freq: 880, start: 0.00, dur: 0.12, type: 'sawtooth', vol: 0.28 },
      { freq: 587, start: 0.13, dur: 0.12, type: 'sawtooth', vol: 0.28 },
      { freq: 880, start: 0.26, dur: 0.12, type: 'sawtooth', vol: 0.28 },
      { freq: 587, start: 0.39, dur: 0.20, type: 'sawtooth', vol: 0.28 },
    ])
  }

  // GNSS quality upgrade — positive: ascending major arpeggio (C-E-G).
  function soundGnssUpgrade() {
    playSequence([
      { freq: 523.25, start: 0.00, dur: 0.12, type: 'sine', vol: 0.25 },
      { freq: 659.25, start: 0.12, dur: 0.12, type: 'sine', vol: 0.25 },
      { freq: 783.99, start: 0.24, dur: 0.18, type: 'sine', vol: 0.25 },
    ])
  }

  // GNSS quality downgrade — negative/warning: descending two-note tritone.
  function soundGnssDowngrade() {
    playSequence([
      { freq: 587.33, start: 0.00, dur: 0.16, type: 'triangle', vol: 0.28 },
      { freq: 415.30, start: 0.16, dur: 0.24, type: 'triangle', vol: 0.28 },
    ])
  }

  // Vehicle armed — informative: single neutral rising blip.
  function soundArmed() {
    playSequence([
      { freq: 660, start: 0.00, dur: 0.09, type: 'sine', vol: 0.22 },
      { freq: 990, start: 0.10, dur: 0.12, type: 'sine', vol: 0.22 },
    ])
  }

  // Vehicle disarmed — informative: single neutral falling blip (mirror of armed).
  function soundDisarmed() {
    playSequence([
      { freq: 990, start: 0.00, dur: 0.09, type: 'sine', vol: 0.22 },
      { freq: 660, start: 0.10, dur: 0.12, type: 'sine', vol: 0.22 },
    ])
  }

  // ── State-transition watchers ──────────────────────────────────────────────

  // 1. Backend connection lost (true → false). The store starts disconnected,
  //    so the `oldVal` guard prevents a false alert on initial page load.
  watch(
    () => telemetry.isConnected,
    (isConnected, wasConnected) => {
      if (wasConnected && !isConnected) soundConnectionLost()
    }
  )

  // 2. Vehicle armed/disarmed — informative.
  watch(
    () => telemetry.isArmed,
    (isArmed, wasArmed) => {
      if (wasArmed === undefined) return
      if (!wasArmed && isArmed) soundArmed()
      else if (wasArmed && !isArmed) soundDisarmed()
    }
  )

  // 3–5. GNSS quality transitions.
  watch(
    () => gnssQuality(telemetry.gnssFixType),
    (level, prevLevel) => {
      if (prevLevel === undefined || level === prevLevel) return
      if (level > prevLevel) {
        // Upgrade: signal lost → GPS, or GPS → RTK.
        soundGnssUpgrade()
      } else {
        // Downgrade. If we dropped to "signal lost" while armed, this is the
        // severe GNSS-lost-while-armed condition; otherwise a normal warning.
        if (level === 0 && telemetry.isArmed) soundGnssLostArmed()
        else soundGnssDowngrade()
      }
    }
  )
}
