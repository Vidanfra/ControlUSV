<template>
  <div class="thrust-indicator">
    <svg :viewBox="`0 0 ${W} ${H}`" width="100%" xmlns="http://www.w3.org/2000/svg">

      <!-- ====== GRADIENT / FILTER DEFS ====== -->
      <defs>
        <radialGradient id="dialOuter" cx="50%" cy="32%" r="75%">
          <stop offset="0%" stop-color="#3a3a3c" />
          <stop offset="100%" stop-color="#161618" />
        </radialGradient>
        <radialGradient id="dialMid" cx="50%" cy="32%" r="75%">
          <stop offset="0%" stop-color="#2c2c2e" />
          <stop offset="100%" stop-color="#101012" />
        </radialGradient>
        <radialGradient id="dialInner" cx="50%" cy="68%" r="85%">
          <stop offset="0%" stop-color="#1d1d1f" />
          <stop offset="100%" stop-color="#070708" />
        </radialGradient>
        <radialGradient id="knobGrad" cx="35%" cy="28%" r="75%">
          <stop offset="0%" stop-color="#d08000" />
          <stop offset="55%" stop-color="#8a4200" />
          <stop offset="100%" stop-color="#2a1200" />
        </radialGradient>
      </defs>

      <!-- ====== LAYER 0: BACKGROUND PANEL ====== -->
      <rect x="22" y="68" width="336" height="182" rx="12"
            fill="rgba(2,10,18,0.70)" stroke="rgba(80,100,120,0.28)" stroke-width="0.8" />

      <!-- ====== CENTRAL DIAL — concentric depth layers ====== -->
      <!-- Outer body -->
      <circle :cx="CX" :cy="CY" :r="CR"
              fill="url(#dialOuter)" stroke="#5a5a5a" stroke-width="1" />
      <!-- Mid ring (axis label zone) -->
      <circle :cx="CX" :cy="CY" :r="CR_MID"
              fill="url(#dialMid)" stroke="#3a3a3a" stroke-width="0.8" />
      <!-- Inner well -->
      <circle :cx="CX" :cy="CY" :r="CR_INNER"
              fill="url(#dialInner)" stroke="#2a2a2a" stroke-width="0.6" />

      <!-- ====== DESIRED HEADING CONCENTRIC RING (rotates with delta) ====== -->
      <!-- Green ring track sitting immediately outside the dial outer body -->
      <circle :cx="CX" :cy="CY" :r="DES_RING_R"
              fill="none" stroke="#003a0f" :stroke-width="DES_RING_W" />
      <!-- Green triangle marker embedded in the ring at deltaDeg bearing -->
      <polygon :points="desiredMarkerPts" fill="#00C851" />


      <!-- ====== ACTUAL HEADING — fixed at 12 o'clock, outside the ring ====== -->
      <!-- Orange upward triangle: always at bearing 0, top-dead-centre -->
      <polygon :points="actualMarkerPts" fill="#FFA500" />
      <!-- Orange label: actual heading, fixed top-right of marker -->
      <text :x="CX + 12" :y="CY - ACT_OUTER_R + 8"
            text-anchor="start" dominant-baseline="central"
            fill="#FFA500" font-size="13" font-weight="700" font-family="sans-serif">
        {{ actualHeadingStr }}
      </text>
      <!-- Green label: desired heading, fixed directly below actual label -->
      <text :x="CX + 12" :y="CY - ACT_OUTER_R + 26"
            text-anchor="start" dominant-baseline="central"
            fill="#00C851" font-size="13" font-weight="700" font-family="sans-serif">
        {{ desiredHeadingStr }}
      </text>

      <!-- ====== AXIS LABELS + OUTWARD CHEVRONS ====== -->
      <g font-family="sans-serif" font-size="10" font-weight="600" fill="#cfcfcf">
        <!-- FWD (top) -->
        <text :x="CX" :y="CY - LABEL_R" text-anchor="middle" dominant-baseline="central">FWD</text>
        <polyline :points="`${CX - 4},${CY - LABEL_R - 10} ${CX},${CY - LABEL_R - 14} ${CX + 4},${CY - LABEL_R - 10}`"
                  fill="none" stroke="#8a8a8a" stroke-width="1.1"
                  stroke-linecap="round" stroke-linejoin="round" />
        <!-- BCK (bottom) -->
        <text :x="CX" :y="CY + LABEL_R" text-anchor="middle" dominant-baseline="central">BCK</text>
        <polyline :points="`${CX - 4},${CY + LABEL_R + 10} ${CX},${CY + LABEL_R + 14} ${CX + 4},${CY + LABEL_R + 10}`"
                  fill="none" stroke="#8a8a8a" stroke-width="1.1"
                  stroke-linecap="round" stroke-linejoin="round" />
        <!-- PORT (left) -->
        <text :x="CX - LABEL_R" :y="CY" text-anchor="middle" dominant-baseline="central">PORT</text>
        <polyline :points="`${CX - LABEL_R - 14},${CY - 4} ${CX - LABEL_R - 18},${CY} ${CX - LABEL_R - 14},${CY + 4}`"
                  fill="none" stroke="#8a8a8a" stroke-width="1.1"
                  stroke-linecap="round" stroke-linejoin="round" />
        <!-- STBD (right) -->
        <text :x="CX + LABEL_R" :y="CY" text-anchor="middle" dominant-baseline="central">STBD</text>
        <polyline :points="`${CX + LABEL_R + 14},${CY - 4} ${CX + LABEL_R + 18},${CY} ${CX + LABEL_R + 14},${CY + 4}`"
                  fill="none" stroke="#8a8a8a" stroke-width="1.1"
                  stroke-linecap="round" stroke-linejoin="round" />
      </g>

      <!-- ====== JOYSTICK KNOB (tactile, no arrows) ====== -->
      <ellipse :cx="ballX" :cy="ballY + 2" :rx="KNOB_R" :ry="KNOB_R * 0.45"
               fill="#000" opacity="0.45" />
      <circle :cx="ballX" :cy="ballY" :r="KNOB_R"
              fill="url(#knobGrad)" stroke="#5a3000" stroke-width="0.8" />
      <ellipse :cx="ballX - 3" :cy="ballY - 5" :rx="KNOB_R * 0.55" :ry="KNOB_R * 0.30"
               fill="#ffffff" opacity="0.10" />

      <!-- ====== LEFT (PORT) CURVED THRUST BAR ====== -->
      <!-- Track -->
      <path :d="leftTrackPath" fill="none" stroke="#1f1f1f"
            :stroke-width="BAR_W" stroke-linecap="round" />
      <!-- Fill (anchored at 0 / horizontal middle) -->
      <path v-if="Math.abs(portPct) > 0.1"
            :d="leftFillPath" fill="none" :stroke="portColor"
            :stroke-width="BAR_W - 2" stroke-linecap="round" />
      <!-- Scale labels -->
      <text :x="leftScale.topX" :y="leftScale.topY" text-anchor="end"
            dominant-baseline="central"
            fill="#888" font-size="9" font-family="monospace">+100</text>
      <text :x="leftScale.midX" :y="leftScale.midY" text-anchor="end"
            dominant-baseline="central"
            fill="#888" font-size="9" font-family="monospace">0</text>
      <text :x="leftScale.botX" :y="leftScale.botY" text-anchor="end"
            dominant-baseline="central"
            fill="#888" font-size="9" font-family="monospace">-100</text>
      <!-- Header -->
      <text :x="leftScale.topX" :y="leftScale.topY - 14"
            text-anchor="end" fill="#aaa"
            font-size="10" font-weight="700" font-family="sans-serif">PORT</text>
      <!-- Telemetry readout -->
      <text :x="leftScale.botX" :y="leftScale.botY + 16"
            text-anchor="end" :fill="portColor"
            font-size="13" font-weight="700" font-family="monospace">
        {{ portPctStr }}
      </text>

      <!-- ====== RIGHT (STBD) CURVED THRUST BAR ====== -->
      <path :d="rightTrackPath" fill="none" stroke="#1f1f1f"
            :stroke-width="BAR_W" stroke-linecap="round" />
      <path v-if="Math.abs(stbdPct) > 0.1"
            :d="rightFillPath" fill="none" :stroke="stbdColor"
            :stroke-width="BAR_W - 2" stroke-linecap="round" />
      <text :x="rightScale.topX" :y="rightScale.topY" text-anchor="start"
            dominant-baseline="central"
            fill="#888" font-size="9" font-family="monospace">+100</text>
      <text :x="rightScale.midX" :y="rightScale.midY" text-anchor="start"
            dominant-baseline="central"
            fill="#888" font-size="9" font-family="monospace">0</text>
      <text :x="rightScale.botX" :y="rightScale.botY" text-anchor="start"
            dominant-baseline="central"
            fill="#888" font-size="9" font-family="monospace">-100</text>
      <text :x="rightScale.topX" :y="rightScale.topY - 14"
            text-anchor="start" fill="#aaa"
            font-size="10" font-weight="700" font-family="sans-serif">STBD</text>
      <text :x="rightScale.botX" :y="rightScale.botY + 16"
            text-anchor="start" :fill="stbdColor"
            font-size="13" font-weight="700" font-family="monospace">
        {{ stbdPctStr }}
      </text>
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useTelemetryStore } from '../stores/telemetry'

const telemetry = useTelemetryStore()

// ── SVG layout constants ──
const W = 380
const H = 290
const D2R = Math.PI / 180

// Compass dial geometry
const CX = 190
const CY = 158
const CR = 100          // outer dial radius
const CR_MID = 81       // mid ring radius
const CR_INNER = 58     // inner well radius
const LABEL_R = 67      // radius at which axis labels sit
const KNOB_R = 20       // joystick knob radius
const MAX_BALL_DISP = CR_INNER - KNOB_R - 2

// Desired heading concentric ring (sits between dial edge and thrust bars)
const DES_RING_R = 107   // ring centre radius
const DES_RING_W = 12    // ring stroke width
// Actual heading fixed marker + background track (outside the green ring, bearing 0)
const ACT_OUTER_R = 134  // radial distance from centre
const ACT_TRACK_R = ACT_OUTER_R - 8   // arc centre radius = 126
const ACT_TRACK_W = 28                 // stroke-width covering marker + labels

// Curved thrust bars
const BAR_W = 13
const BAR_R = CR + 23
const BAR_SPAN_DEG = 60               // total angular span (±30° from horizontal)
const BAR_HALF_SPAN = BAR_SPAN_DEG / 2

// ── Helpers ──
// Compass bearing: 0 = up (12 o'clock), CW positive.
function pointAt(bearingDeg, radius) {
  const a = bearingDeg * D2R
  return {
    x: CX + radius * Math.sin(a),
    y: CY - radius * Math.cos(a),
  }
}
function normDeg(d) { return ((d % 360) + 360) % 360 }

// ── Motor values ──
const portPct = computed(() =>
  Math.max(-100, Math.min(100, Math.round(telemetry.motorPort)))
)
const stbdPct = computed(() =>
  Math.max(-100, Math.min(100, Math.round(telemetry.motorStarboard)))
)
const portColor = computed(() => (portPct.value >= 0 ? '#00C851' : '#e53935'))
const stbdColor = computed(() => (stbdPct.value >= 0 ? '#00C851' : '#e53935'))
const portPctStr = computed(() => `${portPct.value >= 0 ? '+' : ''}${portPct.value}%`)
const stbdPctStr = computed(() => `${stbdPct.value >= 0 ? '+' : ''}${stbdPct.value}%`)

// ── Headings ──
const actualHeadingDeg = computed(() => normDeg(telemetry.bestHeading || 0))
const desiredHeadingDeg = computed(() =>
  normDeg((telemetry.targetHeading || 0) * 180 / Math.PI)
)
const actualHeadingStr = computed(() => `${Math.round(actualHeadingDeg.value)}°`)
const desiredHeadingStr = computed(() => `${Math.round(desiredHeadingDeg.value)}°`)

// Delta heading in (-180, 180] — drives orbital position
const deltaDeg = computed(() => {
  let d = desiredHeadingDeg.value - actualHeadingDeg.value
  while (d > 180) d -= 360
  while (d <= -180) d += 360
  return d
})

// ── Joystick knob position ──
// Port motor stronger than starboard → vehicle turns right → ball displaces right.
const ballX = computed(() => {
  const turnPct = (portPct.value - stbdPct.value) / 2
  return CX + (turnPct / 100) * MAX_BALL_DISP
})
const ballY = computed(() => {
  const fwdPct = (portPct.value + stbdPct.value) / 2
  return CY - (fwdPct / 100) * MAX_BALL_DISP
})

// ── Desired heading ring: rotating marker + label ──
const desiredMarkerPts = computed(() => {
  const d = deltaDeg.value
  const a = d * D2R
  const rx = Math.sin(a)        // radial unit vector (outward)
  const ry = -Math.cos(a)
  const tx = Math.cos(a)        // tangential unit vector (CW = "right" on ring)
  const ty = Math.sin(a)
  const tipR  = DES_RING_R + DES_RING_W / 2 - 1   // near outer edge
  const baseR = DES_RING_R - DES_RING_W / 2 + 1   // near inner edge
  const hw    = 6                                   // half-base-width
  const tipX  = CX + tipR  * rx
  const tipY  = CY + tipR  * ry
  const b1x   = CX + baseR * rx + hw * tx
  const b1y   = CY + baseR * ry + hw * ty
  const b2x   = CX + baseR * rx - hw * tx
  const b2y   = CY + baseR * ry - hw * ty
  return `${tipX.toFixed(1)},${tipY.toFixed(1)} ${b1x.toFixed(1)},${b1y.toFixed(1)} ${b2x.toFixed(1)},${b2y.toFixed(1)}`
})
// Actual heading: static marker string (bearing 0, pointing outward = upward)
const actualMarkerPts =
  `${CX},${CY - ACT_OUTER_R + 2} ${CX - 6},${CY - ACT_OUTER_R + 13} ${CX + 6},${CY - ACT_OUTER_R + 13}`

// ── Curved thrust bar paths ──
// Left bar: bearings 270° ± BAR_HALF_SPAN (top of bar = 270 - half = upper-left)
// Right bar: bearings 90°  ± BAR_HALF_SPAN (top of bar = 90  - half = upper-right)
function arcPath(b1, b2, r) {
  if (Math.abs(b2 - b1) < 0.05) return ''
  const p1 = pointAt(b1, r)
  const p2 = pointAt(b2, r)
  const sweep = b2 > b1 ? 1 : 0   // increasing bearing = clockwise on screen
  const span = Math.abs(b2 - b1)
  const largeArc = span > 180 ? 1 : 0
  return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} ` +
         `A ${r} ${r} 0 ${largeArc} ${sweep} ` +
         `${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`
}

// Static dark arc track behind the actual heading elements (top ±75° = 150° span)
const actualTrackPath = arcPath(-75, 75, ACT_TRACK_R)

const leftTrackPath = computed(() =>
  arcPath(270 - BAR_HALF_SPAN, 270 + BAR_HALF_SPAN, BAR_R)
)
const rightTrackPath = computed(() =>
  arcPath(90 - BAR_HALF_SPAN, 90 + BAR_HALF_SPAN, BAR_R)
)

// Fill paths anchored at center (0% mark = horizontal middle of bar)
// On the LEFT side of the circle, bearing 270+offset goes UPWARD on screen
// (bearing 300 = upper-left), while 270-offset goes DOWNWARD (bearing 240 = lower-left).
// On the RIGHT side, bearing 90-offset goes upward (bearing 60 = upper-right).
const leftFillPath = computed(() => {
  const pct = portPct.value
  const off = (Math.abs(pct) / 100) * BAR_HALF_SPAN
  // Left side: positive grows upward → bearing INCREASES from 270 (toward 300 = upper-left).
  if (pct >= 0) return arcPath(270, 270 + off, BAR_R)
  return arcPath(270, 270 - off, BAR_R)
})
const rightFillPath = computed(() => {
  const pct = stbdPct.value
  const off = (Math.abs(pct) / 100) * BAR_HALF_SPAN
  // Right side: positive grows upward → bearing decreases from 90.
  if (pct >= 0) return arcPath(90, 90 - off, BAR_R)
  return arcPath(90, 90 + off, BAR_R)
})

// Scale label positions (just outside each bar)
// Left bar: bearing 270+half = 300 = upper-left (screen top), bearing 270-half = 240 = lower-left (screen bottom)
const leftScale = computed(() => {
  const top = pointAt(270 + BAR_HALF_SPAN, BAR_R)  // upper-left (bearing 300)
  const mid = pointAt(270, BAR_R)                  // direct left
  const bot = pointAt(270 - BAR_HALF_SPAN, BAR_R)  // lower-left (bearing 240)
  const off = 12
  return {
    topX: top.x - off, topY: top.y,
    midX: mid.x - off, midY: mid.y,
    botX: bot.x - off, botY: bot.y,
  }
})
const rightScale = computed(() => {
  const top = pointAt(90 - BAR_HALF_SPAN, BAR_R)   // upper-right
  const mid = pointAt(90, BAR_R)                   // direct right
  const bot = pointAt(90 + BAR_HALF_SPAN, BAR_R)   // lower-right
  const off = 12
  return {
    topX: top.x + off, topY: top.y,
    midX: mid.x + off, midY: mid.y,
    botX: bot.x + off, botY: bot.y,
  }
})
</script>

<style scoped>
.thrust-indicator {
  position: absolute;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  width: 360px;
  pointer-events: none;
}
</style>
