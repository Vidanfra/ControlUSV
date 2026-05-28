<template>
  <div class="thrust-indicator">
    <svg :viewBox="`0 0 ${W} ${H}`" width="100%" xmlns="http://www.w3.org/2000/svg">

      <!-- ====== PORT MOTOR BAR (left) ====== -->
      <rect :x="BAR_L - BAR_W/2" :y="BAR_TOP" :width="BAR_W" :height="BAR_H"
            rx="3" fill="#111" stroke="#444" stroke-width="0.8" />
      <line :x1="BAR_L - BAR_W/2" :y1="BAR_MID" :x2="BAR_L + BAR_W/2" :y2="BAR_MID"
            stroke="#888" stroke-width="0.8" />
      <!-- Fill bar -->
      <rect v-if="portFillH > 0"
            :x="BAR_L - BAR_W/2 + 1.5" :y="portFillY" :width="BAR_W - 3" :height="portFillH"
            :fill="portColor" rx="2" opacity="0.85" />
      <!-- Scale ticks (right side of port bar) -->
      <line v-for="t in barTicks" :key="'pu'+t.pct"
            :x1="BAR_L + BAR_W/2" :y1="t.yUp" :x2="BAR_L + BAR_W/2 + 3" :y2="t.yUp"
            stroke="#555" stroke-width="0.5" />
      <line v-for="t in barTicks" :key="'pd'+t.pct"
            :x1="BAR_L + BAR_W/2" :y1="t.yDown" :x2="BAR_L + BAR_W/2 + 3" :y2="t.yDown"
            stroke="#555" stroke-width="0.5" />
      <!-- Labels -->
      <text :x="BAR_L" :y="BAR_TOP - 6" text-anchor="middle"
            fill="#888" font-size="9" font-weight="600" font-family="sans-serif">PORT</text>
      <text :x="BAR_L" :y="BAR_TOP + BAR_H + 14" text-anchor="middle"
            :fill="portColor" font-size="10" font-family="monospace" font-weight="bold">
        {{ portPct }}%
      </text>

      <!-- ====== STBD MOTOR BAR (right) ====== -->
      <rect :x="BAR_R - BAR_W/2" :y="BAR_TOP" :width="BAR_W" :height="BAR_H"
            rx="3" fill="#111" stroke="#444" stroke-width="0.8" />
      <line :x1="BAR_R - BAR_W/2" :y1="BAR_MID" :x2="BAR_R + BAR_W/2" :y2="BAR_MID"
            stroke="#888" stroke-width="0.8" />
      <rect v-if="stbdFillH > 0"
            :x="BAR_R - BAR_W/2 + 1.5" :y="stbdFillY" :width="BAR_W - 3" :height="stbdFillH"
            :fill="stbdColor" rx="2" opacity="0.85" />
      <!-- Scale ticks (left side of stbd bar) -->
      <line v-for="t in barTicks" :key="'su'+t.pct"
            :x1="BAR_R - BAR_W/2 - 3" :y1="t.yUp" :x2="BAR_R - BAR_W/2" :y2="t.yUp"
            stroke="#555" stroke-width="0.5" />
      <line v-for="t in barTicks" :key="'sd'+t.pct"
            :x1="BAR_R - BAR_W/2 - 3" :y1="t.yDown" :x2="BAR_R - BAR_W/2" :y2="t.yDown"
            stroke="#555" stroke-width="0.5" />
      <text :x="BAR_R" :y="BAR_TOP - 6" text-anchor="middle"
            fill="#888" font-size="9" font-weight="600" font-family="sans-serif">STBD</text>
      <text :x="BAR_R" :y="BAR_TOP + BAR_H + 14" text-anchor="middle"
            :fill="stbdColor" font-size="10" font-family="monospace" font-weight="bold">
        {{ stbdPct }}%
      </text>

      <!-- SIM mode badge — shown above compass when dataSource is 'sim' -->
      <rect v-if="isSim" :x="CX - 22" :y="CY - CR - 24" width="44" height="16"
            rx="3" fill="#FFA500" opacity="0.9" />
      <text v-if="isSim" :x="CX" :y="CY - CR - 13" text-anchor="middle"
            fill="#000" font-size="9" font-weight="700" font-family="sans-serif">SIM</text>

      <!-- ====== COMPASS CIRCLE ====== -->
      <!-- Outer ring -->
      <circle :cx="CX" :cy="CY" :r="CR" fill="rgba(8,8,8,0.55)" stroke="#555" stroke-width="1.2" />

      <!-- Cardinal tick marks & labels — grey -->
      <template v-for="c in cardinalPositions" :key="c.label">
        <line :x1="c.tx1" :y1="c.ty1" :x2="c.tx2" :y2="c.ty2" stroke="#aaa" stroke-width="1.2" />
        <text :x="c.lx" :y="c.ly" text-anchor="middle" dominant-baseline="central"
              fill="#aaa" :font-size="c.label === 'N' ? 12 : 10"
              font-weight="600" font-family="sans-serif">{{ c.label }}</text>
      </template>

      <!-- Minor ticks (every 30°, skip cardinals) -->
      <line v-for="(t, i) in minorTickPositions" :key="'mt'+i"
            :x1="t.x1" :y1="t.y1" :x2="t.x2" :y2="t.y2" stroke="#444" stroke-width="0.5" />

      <!-- Desired heading arrow (dashed orange #FFA500 with arrowhead) -->
      <line :x1="CX" :y1="CY" :x2="desiredLineEnd.x" :y2="desiredLineEnd.y"
            stroke="#FFA500" stroke-width="2" stroke-dasharray="4,3" stroke-linecap="round" />
      <polygon :points="desiredArrowHead" fill="#FFA500" />

      <!-- Actual heading arrow (solid green) -->
      <line :x1="CX" :y1="CY" :x2="actualLineEnd.x" :y2="actualLineEnd.y"
            stroke="#00C851" stroke-width="2.5" stroke-linecap="round" />
      <polygon :points="actualArrowHead" fill="#00C851" />

      <!-- Center crosshairs -->
      <line :x1="CX - 5" :y1="CY" :x2="CX + 5" :y2="CY" stroke="#333" stroke-width="0.5" />
      <line :x1="CX" :y1="CY - 5" :x2="CX" :y2="CY + 5" stroke="#333" stroke-width="0.5" />

      <!-- Joystick ball -->
      <circle :cx="ballX" :cy="ballY" r="12" fill="#333" stroke="#eee" stroke-width="1.5" />
      <circle :cx="ballX" :cy="ballY" r="4" fill="rgba(255,255,255,0.5)" />
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'

const telemetry = useTelemetryStore()

// SIM mode flag — drives color scheme
const isSim = computed(() => telemetry.dataSource === 'sim')

// ── SVG Layout Constants ──
const W = 320
const H = 230
const D2R = Math.PI / 180

// Compass — bigger circle
const CX = 160
const CY = 108
const CR = 80

// Motor bars
const BAR_W = 18
const BAR_L = 24         // port bar center x
const BAR_R = W - 24     // stbd bar center x
const BAR_TOP = 16
const BAR_H = 180
const BAR_MID = BAR_TOP + BAR_H / 2   // 106 — aligned near CY
const BAR_HALF = BAR_H / 2
const MAX_BALL_DISP = CR - 14

// ── Motor values (clamped %) ──
const portPct = computed(() => Math.round(Math.max(-100, Math.min(100, telemetry.motorPort))))
const stbdPct = computed(() => Math.round(Math.max(-100, Math.min(100, telemetry.motorStarboard))))

// ── Heading (degrees) ──
const actualHeadingDeg = computed(() => telemetry.bestHeading)
const desiredHeadingDeg = computed(() => {
  const deg = telemetry.targetHeading * 180 / Math.PI
  return ((deg % 360) + 360) % 360
})

// ── Port bar fill ──
const portFillH = computed(() => Math.abs(portPct.value) / 100 * BAR_HALF)
const portFillY = computed(() => portPct.value >= 0 ? BAR_MID - portFillH.value : BAR_MID)
const portColor = computed(() => {
  if (portPct.value >= 0) return isSim.value ? '#FFA500' : '#00C851'
  return '#e53935'
})

// ── Stbd bar fill ──
const stbdFillH = computed(() => Math.abs(stbdPct.value) / 100 * BAR_HALF)
const stbdFillY = computed(() => stbdPct.value >= 0 ? BAR_MID - stbdFillH.value : BAR_MID)
const stbdColor = computed(() => {
  if (stbdPct.value >= 0) return isSim.value ? '#FFA500' : '#00C851'
  return '#e53935'
})

// ── Bar scale ticks (25%, 50%, 75%, 100%) ──
const barTicks = [25, 50, 75, 100].map(pct => ({
  pct,
  yUp:   BAR_MID - (pct / 100) * BAR_HALF,
  yDown: BAR_MID + (pct / 100) * BAR_HALF,
}))

// ── Joystick ball position ──
const ballX = computed(() => {
  const turnPct = (portPct.value - stbdPct.value) / 2
  return CX + (turnPct / 100) * MAX_BALL_DISP
})
const ballY = computed(() => {
  const fwdPct = (portPct.value + stbdPct.value) / 2
  return CY - (fwdPct / 100) * MAX_BALL_DISP
})

// ── Compass cardinal positions (pre-computed) ──
const cardinalPositions = [
  { label: 'N', deg: 0 },
  { label: 'E', deg: 90 },
  { label: 'S', deg: 180 },
  { label: 'W', deg: 270 },
].map(d => {
  const a = d.deg * D2R
  const s = Math.sin(a)
  const c = Math.cos(a)
  return {
    label: d.label,
    tx1: CX + (CR - 8) * s,
    ty1: CY - (CR - 8) * c,
    tx2: CX + (CR - 2) * s,
    ty2: CY - (CR - 2) * c,
    lx: CX + (CR + 10) * s,
    ly: CY - (CR + 10) * c,
  }
})

// ── Minor tick positions (every 30°, skip cardinals) ──
const minorTickPositions = [30, 60, 120, 150, 210, 240, 300, 330].map(deg => {
  const a = deg * D2R
  return {
    x1: CX + (CR - 5) * Math.sin(a),
    y1: CY - (CR - 5) * Math.cos(a),
    x2: CX + (CR - 1) * Math.sin(a),
    y2: CY - (CR - 1) * Math.cos(a),
  }
})

// ── Helper: build arrowhead polygon points ──
function buildArrow(headingDeg, tipRadius, baseRadius, halfWidth) {
  const a = headingDeg * D2R
  const tipX = CX + tipRadius * Math.sin(a)
  const tipY = CY - tipRadius * Math.cos(a)
  const pa = a + Math.PI / 2
  const b1x = CX + baseRadius * Math.sin(a) + halfWidth * Math.sin(pa)
  const b1y = CY - baseRadius * Math.cos(a) - halfWidth * Math.cos(pa)
  const b2x = CX + baseRadius * Math.sin(a) - halfWidth * Math.sin(pa)
  const b2y = CY - baseRadius * Math.cos(a) + halfWidth * Math.cos(pa)
  return `${tipX.toFixed(1)},${tipY.toFixed(1)} ${b1x.toFixed(1)},${b1y.toFixed(1)} ${b2x.toFixed(1)},${b2y.toFixed(1)}`
}

// ── Actual heading arrow ──
const actualLineEnd = computed(() => {
  const a = actualHeadingDeg.value * D2R
  const r = CR - 22
  return { x: CX + r * Math.sin(a), y: CY - r * Math.cos(a) }
})
const actualArrowHead = computed(() => buildArrow(actualHeadingDeg.value, CR - 10, CR - 22, 5))

// ── Desired heading arrow ──
const desiredLineEnd = computed(() => {
  const a = desiredHeadingDeg.value * D2R
  const r = CR - 22
  return { x: CX + r * Math.sin(a), y: CY - r * Math.cos(a) }
})
const desiredArrowHead = computed(() => buildArrow(desiredHeadingDeg.value, CR - 10, CR - 22, 5))
</script>

<style scoped>
.thrust-indicator {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  width: 330px;
  background: rgba(40, 40, 40, 0.6);
  border: 1px solid rgba(100, 100, 100, 0.5);
  border-radius: 10px;
  padding: 5px 5px 2px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  pointer-events: none;
}
</style>
