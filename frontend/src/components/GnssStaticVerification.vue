<template>
  <div class="verification-overlay">
    <section class="verification-dialog" role="dialog" aria-modal="true" aria-labelledby="verification-title">
      <header class="verification-header">
        <div>
          <p class="eyebrow">CRP position verification</p>
          <h2 id="verification-title">GNSS Static Verification Test</h2>
        </div>
        <button v-if="phase === 'complete'" class="close-button" type="button" @click="$emit('close')">
          Close
        </button>
      </header>

      <div v-if="phase === 'running'" class="running-view">
        <div class="timer" aria-live="polite">{{ remainingSeconds }}<span>s</span></div>
        <p>Recording synchronized GNSS-only and INS positions at the common reference point (CRP).</p>
        <div class="progress-track" role="progressbar" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100">
          <div class="progress-fill" :style="{ width: `${progressPercent}%` }"></div>
        </div>
        <div class="live-status">
          <span><strong>{{ gnssSamples.length }}</strong> GNSS epochs</span>
          <span><strong>{{ insSamples.length }}</strong> INS epochs</span>
          <span :class="qualityMaintained ? 'quality-good' : 'quality-bad'">
            {{ qualityMaintained ? 'RTK Fix maintained' : 'Automatic fail: fix quality dropped' }}
          </span>
        </div>
      </div>

      <div v-else class="results-view">
        <div class="result-banner" :class="qualityMaintained ? 'quality-good' : 'quality-bad'">
          <strong>{{ qualityMaintained ? 'Quality gate passed' : 'Quality gate failed' }}</strong>
          <span v-if="qualityMaintained">RTK Fix was maintained for the full 120-second test.</span>
          <span v-else>
            GNSS status dropped below RTK Fix during the test. All S-44 evaluations are forced to Fail.
          </span>
        </div>

        <div class="solution-tabs" role="tablist" aria-label="Position solution">
          <button
            v-for="solution in solutions"
            :key="solution.key"
            type="button"
            role="tab"
            :aria-selected="selectedSolution === solution.key"
            :class="{ active: selectedSolution === solution.key }"
            @click="selectedSolution = solution.key"
          >
            {{ solution.label }}
          </button>
        </div>

        <template v-if="activeResult">
          <div class="metric-strip">
            <div><span>Valid epochs</span><strong>{{ activeResult.sampleCount }}</strong></div>
            <div><span>Horizontal P95</span><strong>{{ formatMeters(activeResult.horizontalP95) }}</strong></div>
            <div><span>Vertical P95</span><strong>{{ formatMeters(activeResult.verticalP95) }}</strong></div>
            <div><span>Centroid E / N / U</span><strong>{{ formatCentroid(activeResult) }}</strong></div>
          </div>

          <div class="plots-grid">
            <div class="plot-panel">
              <h3>Horizontal EN Plane</h3>
              <div class="horizontal-chart">
                <Scatter :data="horizontalChartData" :options="horizontalChartOptions" />
              </div>
            </div>
            <div class="plot-panel">
              <h3>Vertical Deviation</h3>
              <div class="vertical-chart">
                <Scatter :data="verticalChartData" :options="verticalChartOptions" />
              </div>
            </div>
          </div>

          <div class="reference-line">
            Shared ENU origin: {{ formatReference(referencePosition) }}
          </div>
        </template>

        <div v-else class="no-data">
          No valid {{ selectedSolution === 'gnss' ? 'GNSS' : 'INS-active' }} CRP positions were recorded.
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>S-44 Order</th>
                <th>H Limit (m)</th>
                <th>V Limit (m)</th>
                <th>Pass/Fail H</th>
                <th>Pass/Fail V</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in evaluationRows" :key="row.order">
                <td>{{ row.order }}</td>
                <td>{{ row.horizontalLimit.toFixed(2) }}</td>
                <td>{{ row.verticalLimit.toFixed(2) }}</td>
                <td :class="`evaluation-${row.horizontal.status}`">{{ row.horizontal.label }}</td>
                <td :class="`evaluation-${row.vertical.status}`">{{ row.vertical.label }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="warning">
          <strong>Hydrographic rigor:</strong> IHO S-44 THU and TVU apply to the sounding on the seafloor.
          This table evaluates the static GNSS against the maximum allowed error for the entire system.
          Passing this test does not guarantee full S-44 compliance for the USV survey.
        </p>
        <p class="classification-key">
          Green = pass; yellow = fail within 20% above the limit; red = fail or automatic quality-gate failure.
          TVU limits use depth <em>d</em> = 0 m.
        </p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Scatter } from 'vue-chartjs'
import {
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  ScatterController,
  Title,
  Tooltip
} from 'chart.js'
import { useTelemetryStore } from '../stores/telemetry'

ChartJS.register(
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  ScatterController,
  Title,
  Tooltip
)

defineEmits(['close'])

const TEST_DURATION_MS = 120_000
const WGS84_A_M = 6_378_137
const WGS84_E2 = 6.69437999014e-3
const S44_ORDERS = [
  { order: 'Exclusive Order', horizontalLimit: 0.5, verticalLimit: 0.15 },
  { order: 'Special Order', horizontalLimit: 2.0, verticalLimit: 0.25 },
  { order: 'Order 1a/1b', horizontalLimit: 5.0, verticalLimit: 0.5 }
]

const telemetry = useTelemetryStore()
const phase = ref('running')
const selectedSolution = ref('gnss')
const startedAtMs = ref(0)
const elapsedMs = ref(0)
const gnssSamples = ref([])
const insSamples = ref([])
const qualityMaintained = ref(true)
const results = ref({ gnss: null, ins: null })
const referencePosition = ref(null)
const offsetsUsed = ref(null)
let lastGnssEpochMs = null
let completionTimer
let progressTimer

const remainingSeconds = computed(() => Math.max(0, Math.ceil((TEST_DURATION_MS - elapsedMs.value) / 1000)))
const progressPercent = computed(() => Math.min(100, Math.round(elapsedMs.value / TEST_DURATION_MS * 100)))
const solutions = computed(() => [
  { key: 'gnss', label: `GNSS Only (${gnssSamples.value.length})` },
  { key: 'ins', label: `INS Mode (${insSamples.value.length})` }
])
const activeResult = computed(() => results.value[selectedSolution.value])

const isValidPosition = (lat, lon, alt) => (
  Number.isFinite(lat) && Number.isFinite(lon) && Number.isFinite(alt) && lat !== 0 && lon !== 0
)

function markQualityFailure(
  rawFixType = telemetry.gnssFixType,
  navFixType = telemetry.navFixType,
  gnssStatus = telemetry.sensorStatus.gnss.status,
  backendConnected = telemetry.isConnected
) {
  if (
    phase.value === 'running' &&
    (rawFixType !== 4 || navFixType !== 4 || gnssStatus !== 'ok' || !backendConnected)
  ) {
    qualityMaintained.value = false
  }
}

function capturePoint(point) {
  if (phase.value !== 'running' || !point || Date.now() > startedAtMs.value + TEST_DURATION_MS) return

  markQualityFailure(point.gnssFixType, telemetry.navFixType)
  if (!Number.isFinite(point.gnssTimeMs) || point.gnssTimeMs === lastGnssEpochMs) return
  lastGnssEpochMs = point.gnssTimeMs

  if (isValidPosition(point.gnssLat, point.gnssLon, point.gnssAlt)) {
    gnssSamples.value.push({
      timeMs: point.gnssTimeMs,
      lat: point.gnssLat,
      lon: point.gnssLon,
      alt: point.gnssAlt,
      gnssFixType: point.gnssFixType,
      navFixType: telemetry.navFixType
    })
  }
  if (point.insActive && isValidPosition(point.insLat, point.insLon, point.insAlt)) {
    insSamples.value.push({
      timeMs: point.gnssTimeMs,
      lat: point.insLat,
      lon: point.insLon,
      alt: point.insAlt,
      gnssFixType: point.gnssFixType,
      navFixType: telemetry.navFixType
    })
  }
}

function percentile(values, percentileValue) {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  const rank = (percentileValue / 100) * (sorted.length - 1)
  const lowerIndex = Math.floor(rank)
  const upperIndex = Math.ceil(rank)
  const fraction = rank - lowerIndex
  return sorted[lowerIndex] + (sorted[upperIndex] - sorted[lowerIndex]) * fraction
}

function toEnu(sample, origin) {
  const latitudeRad = origin.lat * Math.PI / 180
  const sinLatitude = Math.sin(latitudeRad)
  const primeVerticalRadius = WGS84_A_M / Math.sqrt(1 - WGS84_E2 * sinLatitude * sinLatitude)
  const meridianRadius = WGS84_A_M * (1 - WGS84_E2) /
    Math.pow(1 - WGS84_E2 * sinLatitude * sinLatitude, 1.5)

  return {
    timeMs: sample.timeMs,
    east: (sample.lon - origin.lon) * Math.PI / 180 * primeVerticalRadius * Math.cos(latitudeRad),
    north: (sample.lat - origin.lat) * Math.PI / 180 * meridianRadius,
    up: sample.alt - origin.alt
  }
}

function calculateResult(samples, origin) {
  if (!origin || samples.length === 0) return null
  const positions = samples.map(sample => toEnu(sample, origin))
  const centroid = positions.reduce(
    (mean, point) => ({
      east: mean.east + point.east / positions.length,
      north: mean.north + point.north / positions.length,
      up: mean.up + point.up / positions.length
    }),
    { east: 0, north: 0, up: 0 }
  )
  const deviations = positions.map(point => ({
    elapsedSeconds: (point.timeMs - positions[0].timeMs) / 1000,
    east: point.east - centroid.east,
    north: point.north - centroid.north,
    up: point.up - centroid.up
  }))
  const radialDistances = deviations.map(point => Math.hypot(point.east, point.north))
  const verticalDistances = deviations.map(point => Math.abs(point.up))

  return {
    sampleCount: positions.length,
    centroid,
    deviations,
    horizontalP95: percentile(radialDistances, 95),
    verticalP95: percentile(verticalDistances, 95)
  }
}

function finishTest() {
  if (phase.value !== 'running') return
  clearInterval(progressTimer)
  elapsedMs.value = TEST_DURATION_MS
  referencePosition.value = gnssSamples.value[0] || insSamples.value[0] || null
  results.value = {
    gnss: calculateResult(gnssSamples.value, referencePosition.value),
    ins: calculateResult(insSamples.value, referencePosition.value)
  }
  phase.value = 'complete'
  downloadReport()
}

function evaluateMetric(value, limit) {
  if (!qualityMaintained.value) return { status: 'fail', label: 'Fail (fix)' }
  if (!Number.isFinite(value)) return { status: 'fail', label: 'Fail (no data)' }
  if (value <= limit) return { status: 'pass', label: `Pass (${value.toFixed(3)} m)` }
  if (value <= limit * 1.2) return { status: 'near', label: `Fail (${value.toFixed(3)} m)` }
  return { status: 'fail', label: `Fail (${value.toFixed(3)} m)` }
}

function reportSection(label, result) {
  const lines = ['', `=== ${label} ===`]
  if (!result) {
    lines.push('Valid epochs: 0', 'Result: FAIL (no valid CRP positions)')
  } else {
    lines.push(
      `Valid epochs: ${result.sampleCount}`,
      `Centroid East: ${result.centroid.east.toFixed(4)} m`,
      `Centroid North: ${result.centroid.north.toFixed(4)} m`,
      `Centroid Up: ${result.centroid.up.toFixed(4)} m`,
      `Horizontal empirical P95: ${result.horizontalP95.toFixed(4)} m`,
      `Vertical empirical P95: ${result.verticalP95.toFixed(4)} m`
    )
  }

  lines.push('', 'S-44 evaluation (TVU at depth d = 0 m):')
  for (const row of S44_ORDERS) {
    const horizontal = evaluateMetric(result?.horizontalP95, row.horizontalLimit)
    const vertical = evaluateMetric(result?.verticalP95, row.verticalLimit)
    lines.push(
      `${row.order} | H limit ${row.horizontalLimit.toFixed(2)} m: ${horizontal.label}` +
      ` | V limit ${row.verticalLimit.toFixed(2)} m: ${vertical.label}`
    )
  }
  return lines
}

function reportOffsetsSection() {
  const offsets = offsetsUsed.value
  const position = (label, value) => value
    ? `${label}: x=${value.x.toFixed(3)} m, y=${value.y.toFixed(3)} m, z=${value.z.toFixed(3)} m`
    : `${label}: unavailable`

  return [
    '',
    '=== SYSTEM OFFSETS USED ===',
    'Body frame: x forward (+bow), y right (+starboard), z down (+below CRP).',
    'CRP (CG): x=0.000 m, y=0.000 m, z=0.000 m',
    position('IMU WT901C', offsets?.imu),
    position('GNSS antenna bow', offsets?.gnss_bow),
    position('GNSS antenna stern (position fix)', offsets?.gnss_stern),
    `IMU mounting rotation: roll=${offsets?.imu?.roll_deg?.toFixed(3) ?? 'unavailable'} deg, ` +
      `pitch=${offsets?.imu?.pitch_deg?.toFixed(3) ?? 'unavailable'} deg, ` +
      `yaw=${offsets?.imu?.yaw_deg?.toFixed(3) ?? 'unavailable'} deg`,
    `Magnetic declination: ${offsets?.imu?.mag_declination_deg?.toFixed(3) ?? 'unavailable'} deg`,
    `Magnetic user heading offset: ${offsets?.imu?.mag_user_offset_deg?.toFixed(3) ?? 'unavailable'} deg`
  ]
}

function reportRawDataSection(label, samples, result, origin) {
  const lines = [
    '',
    `=== RAW ${label} CRP POSITION DATA ===`,
    'Columns are tab-separated. Geodetic values are the original values used by the verification.',
    'epoch\ttimestamp_ms\ttimestamp_utc\telapsed_s\tlatitude_deg\tlongitude_deg\taltitude_m\t' +
      'gnss_fix_type\tnav_fix_type\teast_m\tnorth_m\tup_m\teast_deviation_m\t' +
      'north_deviation_m\tup_deviation_m\tradial_distance_m\tabs_vertical_deviation_m'
  ]
  if (!origin || !result) {
    lines.push('NO VALID DATA')
    return lines
  }

  const firstTimeMs = samples[0].timeMs
  samples.forEach((sample, index) => {
    const enu = toEnu(sample, origin)
    const deviation = result.deviations[index]
    lines.push([
      index + 1,
      sample.timeMs,
      new Date(sample.timeMs).toISOString(),
      ((sample.timeMs - firstTimeMs) / 1000).toFixed(3),
      String(sample.lat),
      String(sample.lon),
      String(sample.alt),
      sample.gnssFixType ?? 'unknown',
      sample.navFixType ?? 'unknown',
      enu.east.toFixed(9),
      enu.north.toFixed(9),
      enu.up.toFixed(9),
      deviation.east.toFixed(9),
      deviation.north.toFixed(9),
      deviation.up.toFixed(9),
      Math.hypot(deviation.east, deviation.north).toFixed(9),
      Math.abs(deviation.up).toFixed(9)
    ].join('\t'))
  })
  return lines
}

function downloadReport() {
  const completedAt = new Date()
  const reference = referencePosition.value
  const lines = [
    'GNSS STATIC VERIFICATION REPORT',
    `Started UTC: ${new Date(startedAtMs.value).toISOString()}`,
    `Completed UTC: ${completedAt.toISOString()}`,
    `Duration: ${TEST_DURATION_MS / 1000} seconds`,
    'Position reference: Common Reference Point (CRP)',
    `Quality gate: ${qualityMaintained.value ? 'PASS - RTK Fix maintained' : 'FAIL - GNSS quality or connection dropped'}`,
    `Shared ENU origin: ${reference
      ? `${reference.lat.toFixed(8)} deg, ${reference.lon.toFixed(8)} deg, ${reference.alt.toFixed(3)} m`
      : 'Unavailable'}`,
    ...reportOffsetsSection(),
    ...reportSection('GNSS ONLY', results.value.gnss),
    ...reportSection('INS MODE', results.value.ins),
    '',
    'Method: centroid is the arithmetic mean of valid ENU positions. Horizontal P95 is the',
    'empirical 95th percentile of radial distance from the centroid. Vertical P95 is the',
    'empirical 95th percentile of absolute Up deviation from the centroid.',
    `ENU conversion constants: WGS84_A_M=${WGS84_A_M}, WGS84_E2=${WGS84_E2}.`,
    'Empirical percentile method: linear interpolation at rank p/100 * (n - 1).',
    ...reportRawDataSection('GNSS ONLY', gnssSamples.value, results.value.gnss, reference),
    ...reportRawDataSection('INS MODE', insSamples.value, results.value.ins, reference),
    '',
    'HYDROGRAPHIC RIGOR WARNING',
    'IHO S-44 THU and TVU apply to the sounding on the seafloor. This report evaluates the',
    'static GNSS against the maximum allowed error for the entire system. Passing this test',
    'does not guarantee full S-44 compliance for the USV survey.',
    ''
  ]
  const timestamp = completedAt.toISOString().slice(0, 19).replace(/[:T]/g, '-')
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `GNSS_verification_${timestamp}.txt`
  link.click()
  URL.revokeObjectURL(url)
}

const evaluationRows = computed(() => S44_ORDERS.map(row => ({
  ...row,
  horizontal: evaluateMetric(activeResult.value?.horizontalP95, row.horizontalLimit),
  vertical: evaluateMetric(activeResult.value?.verticalP95, row.verticalLimit)
})))

const horizontalBounds = computed(() => {
  if (!activeResult.value) return { xMin: -0.1, xMax: 0.1, yMin: -0.1, yMax: 0.1 }
  const radius = activeResult.value.horizontalP95
  const eastValues = activeResult.value.deviations.map(point => point.east)
  const northValues = activeResult.value.deviations.map(point => point.north)
  const xMin = Math.min(-radius, ...eastValues)
  const xMax = Math.max(radius, ...eastValues)
  const yMin = Math.min(-radius, ...northValues)
  const yMax = Math.max(radius, ...northValues)
  const range = Math.max(0.2, xMax - xMin, yMax - yMin) * 1.12
  const xCenter = (xMin + xMax) / 2
  const yCenter = (yMin + yMax) / 2
  return {
    xMin: xCenter - range / 2,
    xMax: xCenter + range / 2,
    yMin: yCenter - range / 2,
    yMax: yCenter + range / 2
  }
})

const horizontalChartData = computed(() => {
  const result = activeResult.value
  if (!result) return { datasets: [] }
  const circle = Array.from({ length: 97 }, (_, index) => {
    const angle = index / 96 * Math.PI * 2
    return {
      x: result.horizontalP95 * Math.cos(angle),
      y: result.horizontalP95 * Math.sin(angle)
    }
  })
  return {
    datasets: [
      {
        label: 'Raw epochs',
        data: result.deviations.map(point => ({ x: point.east, y: point.north })),
        backgroundColor: 'rgba(190, 198, 205, 0.55)',
        borderColor: 'rgba(190, 198, 205, 0.55)',
        pointRadius: 2.5,
        order: 3
      },
      {
        label: 'Centroid',
        data: [{ x: 0, y: 0 }],
        backgroundColor: '#ff3b30',
        borderColor: '#ff3b30',
        pointStyle: 'crossRot',
        pointRadius: 9,
        pointBorderWidth: 3,
        order: 0
      },
      {
        label: 'Horizontal P95',
        data: circle,
        borderColor: '#ff3b30',
        backgroundColor: 'transparent',
        pointRadius: 0,
        borderWidth: 2,
        showLine: true,
        order: 1
      }
    ]
  }
})

const horizontalChartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: true,
  aspectRatio: 1,
  animation: false,
  parsing: false,
  plugins: {
    legend: { labels: { color: '#d7dce0', boxWidth: 14 } },
    tooltip: {
      callbacks: {
        label: context => `${context.dataset.label}: E ${context.parsed.x.toFixed(3)} m, N ${context.parsed.y.toFixed(3)} m`
      }
    }
  },
  scales: {
    x: {
      type: 'linear',
      min: horizontalBounds.value.xMin,
      max: horizontalBounds.value.xMax,
      title: { display: true, text: 'East from centroid (m)', color: '#aeb5ba' },
      ticks: { color: '#aeb5ba' },
      grid: { color: '#343a3e' }
    },
    y: {
      type: 'linear',
      min: horizontalBounds.value.yMin,
      max: horizontalBounds.value.yMax,
      title: { display: true, text: 'North from centroid (m)', color: '#aeb5ba' },
      ticks: { color: '#aeb5ba' },
      grid: { color: '#343a3e' }
    }
  }
}))

const verticalChartData = computed(() => {
  const result = activeResult.value
  if (!result) return { datasets: [] }
  const durationSeconds = Math.max(1, result.deviations.at(-1)?.elapsedSeconds ?? 0)
  const thresholdLine = value => [{ x: 0, y: value }, { x: durationSeconds, y: value }]
  return {
    datasets: [
      {
        label: 'Up deviation',
        data: result.deviations.map(point => ({ x: point.elapsedSeconds, y: point.up })),
        backgroundColor: 'rgba(190, 198, 205, 0.65)',
        borderColor: 'rgba(190, 198, 205, 0.65)',
        pointRadius: 2.5
      },
      {
        label: 'Mean',
        data: thresholdLine(0),
        borderColor: '#f1f3f5',
        pointRadius: 0,
        borderWidth: 1.5,
        showLine: true
      },
      {
        label: '+/- Vertical P95',
        data: thresholdLine(result.verticalP95),
        borderColor: '#ff3b30',
        pointRadius: 0,
        borderWidth: 2,
        borderDash: [7, 5],
        showLine: true
      },
      {
        label: '- Vertical P95',
        data: thresholdLine(-result.verticalP95),
        borderColor: '#ff3b30',
        pointRadius: 0,
        borderWidth: 2,
        borderDash: [7, 5],
        showLine: true
      }
    ]
  }
})

const verticalChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  parsing: false,
  plugins: {
    legend: { labels: { color: '#d7dce0', boxWidth: 14 } },
    tooltip: {
      callbacks: {
        label: context => `${context.dataset.label}: ${context.parsed.y.toFixed(3)} m`
      }
    }
  },
  scales: {
    x: {
      type: 'linear',
      title: { display: true, text: 'Elapsed time (s)', color: '#aeb5ba' },
      ticks: { color: '#aeb5ba' },
      grid: { color: '#343a3e' }
    },
    y: {
      type: 'linear',
      title: { display: true, text: 'Up deviation (m)', color: '#aeb5ba' },
      ticks: { color: '#aeb5ba' },
      grid: { color: '#343a3e' }
    }
  }
}

const formatMeters = value => Number.isFinite(value) ? `${value.toFixed(3)} m` : '--'
const formatCentroid = result => (
  `${result.centroid.east.toFixed(3)} / ${result.centroid.north.toFixed(3)} / ${result.centroid.up.toFixed(3)} m`
)
const formatReference = reference => reference
  ? `${reference.lat.toFixed(8)} deg, ${reference.lon.toFixed(8)} deg, ${reference.alt.toFixed(3)} m`
  : '--'

watch(
  () => telemetry.insComparisonHistory.at(-1),
  capturePoint
)

watch(
  () => [
    telemetry.gnssFixType,
    telemetry.navFixType,
    telemetry.sensorStatus.gnss.status,
    telemetry.isConnected
  ],
  ([rawFixType, navFixType, gnssStatus, backendConnected]) => (
    markQualityFailure(rawFixType, navFixType, gnssStatus, backendConnected)
  )
)

onMounted(() => {
  startedAtMs.value = Date.now()
  offsetsUsed.value = JSON.parse(JSON.stringify(telemetry.offsetsConfig))
  markQualityFailure()
  progressTimer = setInterval(() => {
    elapsedMs.value = Date.now() - startedAtMs.value
  }, 100)
  completionTimer = setTimeout(finishTest, TEST_DURATION_MS)
})

onUnmounted(() => {
  clearInterval(progressTimer)
  clearTimeout(completionTimer)
})
</script>

<style scoped>
.verification-overlay {
  position: fixed;
  inset: 0;
  z-index: 9500;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.78);
}

.verification-dialog {
  width: min(1160px, calc(100vw - 32px));
  max-height: calc(100vh - 32px);
  overflow-y: auto;
  color: #f3f5f6;
  background: #181b1d;
  border: 1px solid #454b4f;
  border-radius: 8px;
  box-shadow: 0 20px 70px rgba(0, 0, 0, 0.55);
}

.verification-header {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 22px;
  background: #202427;
  border-bottom: 1px solid #3b4145;
}

.eyebrow {
  margin: 0 0 3px;
  color: #ffb02e;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

h2,
h3,
p {
  margin-top: 0;
}

h2 {
  margin-bottom: 0;
  font-size: 1.25rem;
}

.close-button,
.solution-tabs button {
  color: #f3f5f6;
  background: #30363a;
  border: 1px solid #545c61;
  border-radius: 5px;
  cursor: pointer;
}

.close-button {
  padding: 8px 14px;
}

.running-view {
  min-height: 430px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}

.timer {
  color: #ffb02e;
  font-size: 6rem;
  font-weight: 800;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.timer span {
  margin-left: 7px;
  color: #aeb5ba;
  font-size: 1.4rem;
}

.running-view p {
  margin: 18px 0 28px;
  color: #c3c8cb;
}

.progress-track {
  width: min(620px, 100%);
  height: 10px;
  overflow: hidden;
  background: #30363a;
  border-radius: 5px;
}

.progress-fill {
  height: 100%;
  background: #ffb02e;
  transition: width 0.1s linear;
}

.live-status {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 20px;
  margin-top: 22px;
  color: #aeb5ba;
  font-size: 0.85rem;
}

.quality-good {
  color: #43c875;
}

.quality-bad {
  color: #ff6058;
}

.results-view {
  padding: 20px 22px 24px;
}

.result-banner {
  display: flex;
  gap: 12px;
  padding: 11px 14px;
  background: #22272a;
  border-left: 4px solid currentColor;
}

.solution-tabs {
  display: flex;
  gap: 6px;
  margin: 18px 0 12px;
}

.solution-tabs button {
  min-width: 170px;
  padding: 9px 14px;
  font-weight: 700;
}

.solution-tabs button.active {
  color: #17191a;
  background: #ffb02e;
  border-color: #ffb02e;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid #3b4145;
  border-bottom: 1px solid #3b4145;
}

.metric-strip div {
  min-width: 0;
  padding: 13px 15px;
  border-right: 1px solid #3b4145;
}

.metric-strip div:last-child {
  border-right: 0;
}

.metric-strip span {
  display: block;
  margin-bottom: 5px;
  color: #9fa7ac;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.metric-strip strong {
  font-size: 0.95rem;
  overflow-wrap: anywhere;
}

.plots-grid {
  display: grid;
  grid-template-columns: minmax(300px, 0.85fr) minmax(420px, 1.15fr);
  gap: 14px;
  margin-top: 14px;
}

.plot-panel {
  min-width: 0;
  padding: 12px;
  background: #202427;
  border: 1px solid #353b3f;
  border-radius: 6px;
}

.plot-panel h3 {
  margin-bottom: 8px;
  color: #c9ced1;
  font-size: 0.82rem;
  text-align: center;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.horizontal-chart {
  width: min(100%, 400px);
  margin: 0 auto;
  aspect-ratio: 1;
}

.vertical-chart {
  height: 400px;
}

.reference-line,
.classification-key {
  color: #929ba0;
  font-size: 0.76rem;
}

.reference-line {
  margin-top: 8px;
  text-align: right;
}

.table-wrap {
  margin-top: 16px;
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}

th,
td {
  padding: 10px 12px;
  border: 1px solid #3b4145;
  text-align: left;
  white-space: nowrap;
}

th {
  color: #aeb5ba;
  background: #252a2d;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.evaluation-pass {
  color: #55d989;
  background: rgba(45, 151, 88, 0.16);
  font-weight: 800;
}

.evaluation-near {
  color: #ffd15c;
  background: rgba(204, 151, 24, 0.17);
  font-weight: 800;
}

.evaluation-fail {
  color: #ff736c;
  background: rgba(196, 57, 50, 0.18);
  font-weight: 800;
}

.warning {
  margin: 16px 0 7px;
  padding: 12px 14px;
  color: #f0d497;
  background: #29261e;
  border: 1px solid #5a4b2d;
  border-radius: 5px;
  font-size: 0.82rem;
  line-height: 1.45;
}

.classification-key,
.no-data {
  margin-bottom: 0;
}

.no-data {
  padding: 70px 20px;
  color: #ff736c;
  text-align: center;
  border: 1px solid #3b4145;
}

@media (max-width: 820px) {
  .plots-grid,
  .metric-strip {
    grid-template-columns: 1fr;
  }

  .metric-strip div,
  .metric-strip div:last-child {
    border-right: 0;
    border-bottom: 1px solid #3b4145;
  }

  .metric-strip div:last-child {
    border-bottom: 0;
  }

  .result-banner,
  .solution-tabs {
    flex-direction: column;
  }

  .solution-tabs button {
    width: 100%;
  }

  .vertical-chart {
    height: 320px;
  }
}
</style>