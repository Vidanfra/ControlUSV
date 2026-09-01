import { defineStore } from 'pinia'
import { generateLawnmower } from '../composables/useSurveyGenerator.js'

// ── Mission item helpers ──────────────────────────────────────────────────────
let _itemIdCounter = 1
function makeId() { return _itemIdCounter++ }

function makeMissionStartItem(lat = 0, lon = 0, radius = 5, speed = 1.0) {
  return { id: makeId(), type: 'mission_start', lat, lon, radius, speed }
}
function makeMissionEndItem(radius = 5, speed = 1.0) {
  return { id: makeId(), type: 'mission_end', lat: null, lon: null, radius, speed }
}
function makeWaypointItem(lat = 0, lon = 0, radius = 5, speed = 1.0) {
  return { id: makeId(), type: 'waypoint', lat, lon, radius, speed }
}
function makeSurveyItem(radius = 3, speed = 1.0) {
  return {
    id: makeId(),
    type: 'survey',
    polygon: [],          // [{lat,lon}]
    lineAngle: 0,         // degrees
    lineSpacing: 30,      // metres between transects
    lineExtension: 10,    // metres overshoot past polygon
    startWP: 0,           // 0 or 1 (which corner to start from)
    radius,               // acceptance radius for generated WPs
    speed,
  }
}

// ── Link-quality bookkeeping ─────────────────────────────────────────────────
// Kept outside the store: high-churn, per-PING data that must not be reactive.
const PING_PERIOD_MS = 500          // keep-alive / RTT probe rate
const PING_TIMEOUT_MS = 3000        // unanswered after this → counted as lost
const LATENCY_HISTORY_LEN = 60      // samples kept for the sparkline (~30 s)
const _pendingPings = new Map()     // seq → send timestamp (performance.now())

// The INS, IMU and GNC streams arrive at 20 Hz. Every push invalidates a
// reactive array that several Chart.js line charts re-render from, so they are
// decimated to 8 Hz before being stored.
const CHART_PUSH_INTERVAL_MS = 125

function resetLinkStats(store) {
  _pendingPings.clear()
  store.latencyMs = 0
  store.latencyAvgMs = 0
  store.latencyJitterMs = 0
  store.latencyLossPct = 0
  store.latencyHistory = []
}

function pushLatencySample(store, rttMs) {
  const h = store.latencyHistory
  h.push(rttMs)                     // null marks a lost probe
  if (h.length > LATENCY_HISTORY_LEN) h.splice(0, h.length - LATENCY_HISTORY_LEN)

  if (rttMs !== null) store.latencyMs = rttMs

  const window = h.slice(-20)
  const ok = window.filter(v => v !== null)
  store.latencyLossPct = window.length ? (100 * (window.length - ok.length)) / window.length : 0
  if (ok.length) {
    store.latencyAvgMs = ok.reduce((a, b) => a + b, 0) / ok.length
    let jit = 0
    for (let i = 1; i < ok.length; i++) jit += Math.abs(ok[i] - ok[i - 1])
    store.latencyJitterMs = ok.length > 1 ? jit / (ok.length - 1) : 0
  }
}

export const useTelemetryStore = defineStore('telemetry', {
  state: () => ({
    lat: 0.0,
    lon: 0.0,
    altitude: 0.0,
    heading: 0.0,
    headingStatus: '',
    insActive: false,
    positionSource: 'GNSS',
    navFixType: 0,
    navHorizontalAccuracyM: null,
    navVerticalAccuracyM: null,
    battery: 0.0,
    speed: 0.0,
    isConnected: false,
    socket: null,
    isArmed: false,
    mode: 'MANUAL',

    // Command sequence + ACK + link liveness (B-21/B-16)
    _cmdSeq: 0,
    lastAckSeq: 0,
    linkAlive: false,

    // Set to true after the first system/status heartbeat restores mission
    // state from the backend.  Prevents subsequent heartbeats from overwriting
    // waypoints the operator drew between the first sync and route start.
    _missionSynced: false,

    // Mission plan defaults (persisted to localStorage)
    missionDefaultWpRadius:     JSON.parse(localStorage.getItem('missionPlanDefaults'))?.wpRadius     ?? 5,
    missionDefaultWpSpeed:      JSON.parse(localStorage.getItem('missionPlanDefaults'))?.wpSpeed      ?? 1.0,
    missionDefaultSurveyRadius: JSON.parse(localStorage.getItem('missionPlanDefaults'))?.surveyRadius ?? 3,
    missionDefaultSurveySpeed:  JSON.parse(localStorage.getItem('missionPlanDefaults'))?.surveySpeed  ?? 1.0,

    // ── Mission planner items (source of truth) ──────────────────────────
    // missionItems is the rich list; missionWaypoints (getter) is the flat
    // [{lat,lon,radius,speed}] array consumed by the backend.
    missionItems: (() => {
      const d = JSON.parse(localStorage.getItem('missionPlanDefaults')) || {}
      return [
        makeMissionStartItem(0, 0, d.wpRadius ?? 5, d.wpSpeed ?? 1.0),
        makeMissionEndItem(d.wpRadius ?? 5, d.wpSpeed ?? 1.0),
      ]
    })(),
    // Map interaction state for the mission planner
    activeSurveyId: null,     // id of the survey item currently being edited
    surveyDrawMode: false,    // true = map clicks add polygon vertices
    activeMissionWpId: null,  // id of waypoint item being positioned on map

    // Legacy flat list – kept for SimView (CSV upload / WP planner in sim tab).
    // When the mission planner is in use missionWaypoints is derived from missionItems.
    _legacyWaypoints: [],

    pathHistory: [],
    _lastPathPushTime: 0,
    
    // GNC additions
    targetHeading: 0.0,
    headingError: 0.0,
    crossTrackError: 0.0,
    motorPort: 0.0,
    motorStarboard: 0.0,
    distToWp: 0.0,
    currentWpIndex: 0,
    tauXEff: 0.0,
    refSpeedKn: 0.0,

    // Navigation metrics (ETT / ETA / KP)
    ettNextWp: -1.0,       // seconds to next WP; -1 = unavailable
    etaNextWp: 0.0,        // Unix timestamp; 0 = unavailable
    ettRouteEnd: -1.0,     // seconds to end of route; -1 = not in route mode
    etaRouteEnd: 0.0,      // Unix timestamp
    kpM: 0.0,              // chainage along original forward route [m]

    // Power additions
    batteryVoltage: 0.0,
    batteryCurrent: 0.0,
    batteryPower: 0.0,
    batteryLevelPct: 0.0,
    batteryCapacityWh: 500.0,
    batteryAccumulatedWh: 0.0,
    batteryEnergyWh: 0,
    batteryMeasurementStart: 0,
    batteryHighAlarm: 0,
    batteryLowAlarm: 0,

    // GNSS additions — raw sensor values (NOT EKF-filtered)
    // lat/lon/heading/speed are authoritative only from gnc/ekf_state
    gnssRawLat: 0.0,       // raw GNSS latitude (degrees) — used in GNSS diagnostic tab
    gnssRawLon: 0.0,       // raw GNSS longitude (degrees) — used in GNSS diagnostic tab
    gnssAlt: 0.0,
    gnssFixType: 0,
    gnssNumSats: 0,
    gnssHdop: 99.99,
    gnssVdop: 99.99,
    gnssHorizontalAccuracyM: null,
    gnssVerticalAccuracyM: null,
    gnssHeading: 0.0,
    gnssHeadingStatus: '',
    gnssCog: 0.0,
    gnssSogKnots: 0.0,
    gnssSogKmh: 0.0,
    gnssUtcTime: '',
    gnssUtcDate: '',

    // GNSS settings (sent as commands)
    gnssSerialPort: '/dev/gnss',
    gnssBaudRate: 115200,
    gnssNtripCaster: '',
    gnssNtripPort: 2101,
    gnssMountpoint: '',
    gnssUsername: '',
    gnssPassword: '',
    gnssCommandFreq: 1.0,

    // IMU additions
    imuRoll: 0.0,
    imuPitch: 0.0,
    imuYaw: 0.0,
    imuAx: 0.0,
    imuAy: 0.0,
    imuAz: 0.0,
    imuP: 0.0,
    imuQ: 0.0,
    imuR: 0.0,
    imuMagHeading: 0.0,

    // Sensor connection status
    sensorStatus: {
      gnss:  { status: 'disconnected', message: 'Waiting...', timestamp: 0 },
      imu:   { status: 'disconnected', message: 'Waiting...', timestamp: 0 },
      power: { status: 'disconnected', message: 'Waiting...', timestamp: 0 },
      esp32: { status: 'disconnected', message: 'Waiting...', timestamp: 0 },
    },

    // Zero-value warning: sensor is connected/ok but transmitting all-zero data
    sensorZeroValues: {
      gnss:  false,
      imu:   false,
      power: false,
    },

    // UI navigation state (shared across components)
    currentTab: 'map',            // Active tab id
    mapPlanMode: false,           // Whether the map waypoint planner is active

    // Simulation state
    simulationResults: [],        // Array of result objects from /api/simulate
    simulationOverlayVisible: false,
    simulationWaypoints: [],      // Waypoints used for the last simulation
    simulationRunning: false,

    // RT Simulation state
    rtSimActive: false,
    rtSimElapsed: 0.0,
    rtSimConfig: null,
    dataSource: 'sensor',         // 'sensor' or 'sim'

    // Pre-collected chart histories (2-min window, collected regardless of active tab)
    gnssHistory: [],   // Raw GNSS positions retained for sensor diagnostics.
    gnssCrpHistory: [], // Last ten distinct GNSS measurements translated to CRP.
    _lastGnssCrpTimestamp: 0,
    insComparisonHistory: [], // Synchronized INS, GNSS, compass and COG samples.
    imuHistory: [],    // { timeMs, label, roll, pitch, yaw, ax, ay, az, p, q, r }
    gncHistory: [],    // { timeMs, label, actualHeading, targetHeading, headingError, cte, port, starboard, surgeVel, swayVel, surgeAcc, swayAcc, vCruise, tauXEff }
    powerHistory: [],  // { timeMs, label, voltage, current, power }
    // Decimation clocks for the 20 Hz streams above (see CHART_PUSH_INTERVAL_MS).
    _lastInsPushMs: 0,
    _lastImuPushMs: 0,
    _lastGncPushMs: 0,

    // Vehicle command modes
    vehicleMode: 'MANUAL',        // 'MANUAL', 'STATION', 'WP_ROUTE'
    simMode: 'REAL',              // 'REAL' or 'SIMULATION' (frontend-only toggle for now)

    // Station keeping
    stationWaypoint: null,        // { lat, lon } or null
    stationReachingRadius: JSON.parse(localStorage.getItem('stationReachingRadius')) ?? 3.0,
    stationRadius: JSON.parse(localStorage.getItem('stationRadius')) ?? 10.0,
    stationActive: false,

    // WP Route
    wpRouteActive: false,
    wpRouteDirection: 'forward',  // 'forward' or 'reverse'
    wpRouteCompletion: 'stop',    // 'stop', 'loop', 'loop_reverse'

    // Manual control (keyboard/joystick input state)
    manualThrottle: 0.0,          // -1 to 1
    manualSteering: 0.0,          // -1 to 1

    // Fail-safe configuration
    // Loaded from localStorage so user settings survive page reloads.
    failsafeMinBattery:   JSON.parse(localStorage.getItem('failsafeConfig'))?.min_battery_pct ?? 25.0,
    failsafeMinGnssFix:   JSON.parse(localStorage.getItem('failsafeConfig'))?.min_gnss_fix    ?? 1,
    failsafeCommTimeout:  JSON.parse(localStorage.getItem('failsafeConfig'))?.comm_timeout    ?? 10.0,
    failsafeCommAction:   JSON.parse(localStorage.getItem('failsafeConfig'))?.comm_action     ?? 'station_keeping',
    failsafeInsTimeout:   JSON.parse(localStorage.getItem('failsafeConfig'))?.ins_timeout     ?? 10.0,
    failsafeInsAction:    JSON.parse(localStorage.getItem('failsafeConfig'))?.ins_action      ?? 'emergency_stop',

    // Home waypoint
    homeWaypoint: JSON.parse(localStorage.getItem('homeWaypoint')) || null,

    // Alert banners
    alertBanners: [],             // [{ id, type:'error'|'warning', message, dismissible }]

    // Sim default start position (for manual SIM mode)
    simDefaultLat: 39.4699,
    simDefaultLon: -0.3763,
    simPickMode: false,           // true when user is picking a position on the map
    stationPickMode: false,       // true when picking station WP on map
    homePickMode: false,          // true when picking home WP on map
    
    // Loaded from local storage on store creation
    simStartWaypoint: JSON.parse(localStorage.getItem('simStartWp')) || null,

    // GNC Configuration state
    gncConfig: JSON.parse(localStorage.getItem('gncConfig')) || {
      wn: 1.7,
      zeta: 0.7,
      wn_ref: 0.7,
      zeta_ref: 0.9,
      k_delta: 15.0,
      delta_min: 5.0,
      gamma: 0.0,
      cruise_speed_kn: 3.2,
      e_x_threshold_deg: 10.0,
      accel_ms2: 0.3,
      vel_profiler_enabled: true,
    },

    // Logs feature
    loggingConfig: { csv_loggers: [], json_broadcasters: [] },
    logFieldCatalog: null,        // { groups: [...], os: 'Windows'|'Linux'|... }
    loggerPreviews: {},           // id → latest preview payload

    // Relays (ESP32 R1 / R2 / R3) — order MUST match firmware command order.
    relayConfig: {
      names:  ['Relay 1', 'Relay 2', 'Relay 3'],
      states: [1, 1, 1],
      restart_until: [0, 0, 0],
    },
    // Motor calibration (per-direction dead-zone / saturation, %). Backend is
    // authoritative; this mirrors the system/status heartbeat.
    motorConfig: {
      fwd_deadzone: 0.0,
      fwd_saturation: 100.0,
      bwd_deadzone: 0.0,
      bwd_saturation: 100.0,
    },
    // Sensor lever-arm offsets referenced to the CRP (centre of gravity).
    // Body frame: x forward, y starboard, z down [m]. Backend is authoritative;
    // this mirrors the system/status heartbeat.
    offsetsConfig: {
      imu: {
        x: -0.545, y: 0.135, z: -0.233,
        roll_deg: 180.0, pitch_deg: 0.0, yaw_deg: 90.0,
        mag_declination_deg: 2.5, mag_user_offset_deg: 0.0,
      },
      gnss_bow:   { x: 0.802,  y: 0.0,   z: -0.293 },
      gnss_stern: { x: -0.657, y: 0.0,   z: -0.293 },
    },
    insConfig: {
      enabled: true,
      use_magnetometer: true,
      accel_noise_mps2_sqrt_hz: 0.12,
      gyro_noise_deg_s_sqrt_hz: 0.30,
      accel_bias_noise_mps2_sqrt_hz: 0.01,
      gyro_bias_noise_deg_s_sqrt_hz: 0.02,
      accel_bias_tau_s: 500.0,
      gyro_bias_tau_s: 500.0,
      gravity_aiding_noise: 0.10,
      gravity_gate_mps2: 0.40,
      gravity_max_speed_mps: 2.0,
      attitude_aiding_rate_hz: 2.0,
      gnss_velocity_sigma_mps: 0.15,
      gnss_heading_sigma_deg: 0.5,
      mag_heading_sigma_deg: 10.0,
      rtk_fixed_horizontal_floor_m: 0.10,
      rtk_fixed_vertical_floor_m: 0.15,
      rtk_float_horizontal_sigma_m: 0.5,
      rtk_float_vertical_sigma_m: 1.0,
      dgps_horizontal_sigma_m: 1.5,
      dgps_vertical_sigma_m: 2.5,
      gps_horizontal_sigma_m: 3.0,
      gps_vertical_sigma_m: 5.0,
      innovation_gate_sigma: 5.0,
      gnss_loss_timeout_s: 2.0,
    },
    _pendingInsConfig: null,
    _pendingInsConfigSentAt: 0,
    systemMonitor: {
      timestamp: 0,
      cpu_percent: 0,
      cpu_temp_c: null,
      ram_used_mb: 0, ram_total_mb: 0, ram_percent: 0,
      disk_used_gb: 0, disk_total_gb: 0, disk_percent: 0,
      uptime_s: 0,
      net_rx_kbps: 0, net_tx_kbps: 0,
      hostname: '', os_name: '',
    },

    // ── Link quality (frontend ↔ backend round-trip on the PING/PONG stream) ─
    linkTransport: 'unknown',   // wifi | zerotier | ethernet | vpn | loopback | unknown
    linkIface: '',              // backend NIC that accepted the socket (e.g. wlan0, ztabcdef)
    linkServerIp: '',
    linkClientIp: '',
    latencyMs: 0,               // last measured RTT
    latencyAvgMs: 0,            // mean RTT over the recent window
    latencyJitterMs: 0,         // mean absolute delta between consecutive RTTs
    latencyLossPct: 0,          // unanswered PINGs over the recent window
    latencyHistory: [],         // last LATENCY_HISTORY_LEN RTT samples (null = lost)
  }),

  getters: {
    // ── Link quality ─────────────────────────────────────────────────────
    // Grade the control link from RTT + loss so the operator can tell at a
    // glance whether commands are still going through promptly.
    linkQuality(state) {
      if (!state.isConnected) return { level: 'offline', label: 'OFFLINE', score: 0, color: '#777' }
      if (!state.latencyHistory.length) return { level: 'unknown', label: 'MEASURING', score: 0, color: '#777' }
      const rtt = state.latencyAvgMs
      const loss = state.latencyLossPct
      if (loss >= 40 || rtt >= 1000) return { level: 'bad',       label: 'CRITICAL',  score: 10,  color: '#e53935' }
      if (loss >= 15 || rtt >= 400)  return { level: 'poor',      label: 'POOR',      score: 35,  color: '#ff7043' }
      if (loss >= 5  || rtt >= 150)  return { level: 'fair',      label: 'FAIR',      score: 60,  color: '#FFA500' }
      if (rtt >= 60)                 return { level: 'good',      label: 'GOOD',      score: 80,  color: '#9ccc65' }
      return                                { level: 'excellent', label: 'EXCELLENT', score: 100, color: '#00C851' }
    },

    // Bar fill 0–100 %: full bar = fast link. Logarithmic so the useful
    // 10–1000 ms range spreads across the whole width.
    linkQualityPct(state) {
      if (!state.isConnected || !state.latencyHistory.length) return 0
      const rtt = Math.max(state.latencyAvgMs, 1)
      const pct = 100 * (1 - (Math.log10(rtt) - 1) / 2)   // 10 ms → 100 %, 1000 ms → 0 %
      const lossPenalty = state.latencyLossPct
      return Math.max(0, Math.min(100, pct - lossPenalty))
    },

    // Is the link getting better or worse? Compares the two halves of the
    // recent window; ±15 % dead-band avoids flapping.
    linkTrend(state) {
      const ok = state.latencyHistory.slice(-12).filter(v => v !== null)
      if (ok.length < 6) return 'stable'
      const half = Math.floor(ok.length / 2)
      const mean = a => a.reduce((x, y) => x + y, 0) / a.length
      const older = mean(ok.slice(0, half))
      const recent = mean(ok.slice(half))
      if (recent > older * 1.15 + 3) return 'degrading'
      if (recent < older * 0.85 - 3) return 'improving'
      return 'stable'
    },

    linkTransportLabel(state) {
      switch (state.linkTransport) {
        case 'wifi':      return 'LOCAL WIFI'
        case 'ethernet':  return 'LAN'
        case 'zerotier':  return 'ZEROTIER VPN'
        case 'vpn':       return 'VPN'
        case 'loopback':  return 'LOCALHOST'
        default:          return 'UNKNOWN'
      }
    },

    // ── Flat waypoint list derived from missionItems ──────────────────────
    // This is what the backend receives. If missionItems is empty or has no
    // positioned items the legacy list is returned (used by SimView CSV upload).
    missionWaypoints(state) {
      const items = state.missionItems
      const hasContent = items.some(it =>
        (it.type === 'waypoint' && it.lat !== 0) ||
        (it.type === 'survey'   && it.polygon.length >= 3) ||
        (it.type === 'mission_start' && it.lat !== 0)
      )
      if (!hasContent) return state._legacyWaypoints

      const wps = []
      for (const item of items) {
        if (item.type === 'mission_start') {
          if (item.lat !== 0 || item.lon !== 0) {
            wps.push({ lat: item.lat, lon: item.lon, radius: item.radius ?? 10, speed: item.speed ?? 1.0 })
          }
        } else if (item.type === 'waypoint') {
          if (item.lat !== 0 || item.lon !== 0) {
            wps.push({ lat: item.lat, lon: item.lon, radius: item.radius ?? 5, speed: item.speed ?? 1.0 })
          }
        } else if (item.type === 'survey') {
          if (item.polygon.length >= 3) {
            const pts = generateLawnmower(
              item.polygon, item.lineAngle, item.lineSpacing, item.lineExtension, item.startWP
            )
            pts.forEach(p => wps.push({ lat: p.lat, lon: p.lon, radius: item.radius ?? 3, speed: item.speed ?? 1.0 }))
          }
        } else if (item.type === 'mission_end') {
          // Use the item's own position if set
          if (item.lat !== null && item.lon !== null) {
            wps.push({ lat: item.lat, lon: item.lon, radius: item.radius ?? 5, speed: item.speed ?? 1.0 })
          }
        }
      }
      return wps
    },

    // Navigation owns GNSS/magnetometer heading arbitration. State heading is radians.
    bestHeading(state) {
      if (!Number.isFinite(state.heading)) return 0
      return ((state.heading * 180 / Math.PI) + 360) % 360
    },
    headingSource(state) {
      if (state.insActive) return 'INS'
      return { A: 'GNSS', M: 'MAG', I: 'INS', S: 'SIM' }[state.headingStatus] || 'NONE'
    },
    // Fix quality color. Uses the navigation-effective fix (gnc/ekf_state), which
    // decays to 0 on GNSS loss — the raw sensor/gnss value freezes instead.
    fixColor(state) {
      const f = state.navFixType ?? state.gnssFixType
      if (f === 4) return '#00C851'  // RTK Fixed
      if (f === 5) return '#88cc00'  // RTK Float
      if (f === 3) return '#aacc00'  // PPS
      if (f === 2) return '#ffdd00'  // DGPS
      if (f === 1) return '#FFA500'  // GPS
      return '#e53935'               // No fix
    },
    canStartAutoMode(state) {
      return (state.navFixType ?? state.gnssFixType) >= state.failsafeMinGnssFix
    },
    autoModeWarnings(state) {
      const warnings = []
      if (state.batteryLevelPct > 0 && state.batteryLevelPct < state.failsafeMinBattery) {
        warnings.push(`Battery low: ${state.batteryLevelPct.toFixed(0)}% (min ${state.failsafeMinBattery}%)`)
      }
      if (state.gnssFixType < 4) {
        warnings.push('No RTK fix — reduced position accuracy')
      }
      return warnings
    },
  },

  actions: {
    // ── Legacy flat-waypoint helpers (used by SimView) ────────────────────
    addWaypoint(lat, lon) {
      this._legacyWaypoints.push({ lat, lon, radius: 5, speed: 1.0 })
    },

    clearMission() {
      this._legacyWaypoints = []
      // Also reset mission_start position so the getter's hasContent check
      // returns false and missionWaypoints.length stays 0.
      const start = this.missionItems.find(i => i.type === 'mission_start')
      if (start) { start.lat = 0; start.lon = 0 }
      this.sendCommand('CLEAR_WP_ROUTE', {})
    },

    // ── Mission-item actions ──────────────────────────────────────────────
    setMissionPlanDefaults(config) {
      if (config.wpRadius     !== undefined) this.missionDefaultWpRadius     = config.wpRadius
      if (config.wpSpeed      !== undefined) this.missionDefaultWpSpeed      = config.wpSpeed
      if (config.surveyRadius !== undefined) this.missionDefaultSurveyRadius = config.surveyRadius
      if (config.surveySpeed  !== undefined) this.missionDefaultSurveySpeed  = config.surveySpeed
      localStorage.setItem('missionPlanDefaults', JSON.stringify({
        wpRadius:     this.missionDefaultWpRadius,
        wpSpeed:      this.missionDefaultWpSpeed,
        surveyRadius: this.missionDefaultSurveyRadius,
        surveySpeed:  this.missionDefaultSurveySpeed,
      }))
    },

    addMissionItem(type) {
      const endIdx = this.missionItems.findIndex(i => i.type === 'mission_end')
      let item
      if (type === 'waypoint') item = makeWaypointItem(0, 0, this.missionDefaultWpRadius, this.missionDefaultWpSpeed)
      else if (type === 'survey') item = makeSurveyItem(this.missionDefaultSurveyRadius, this.missionDefaultSurveySpeed)
      else return
      if (endIdx >= 0) {
        this.missionItems.splice(endIdx, 0, item)
      } else {
        this.missionItems.push(item)
      }
      return item.id
    },

    removeMissionItem(id) {
      const idx = this.missionItems.findIndex(i => i.id === id)
      if (idx < 0) return
      const item = this.missionItems[idx]
      if (item.type === 'mission_start' || item.type === 'mission_end') return // immovable
      this.missionItems.splice(idx, 1)
      if (this.activeSurveyId === id) {
        this.activeSurveyId = null
        this.surveyDrawMode = false
      }
      if (this.activeMissionWpId === id) {
        this.activeMissionWpId = null
      }
    },

    updateMissionItem(id, patch) {
      const item = this.missionItems.find(i => i.id === id)
      if (!item) return
      Object.assign(item, patch)
    },

    reorderMissionItems(newMiddleItems) {
      // Replace middle items (between mission_start and mission_end)
      const start = this.missionItems.find(i => i.type === 'mission_start')
      const end   = this.missionItems.find(i => i.type === 'mission_end')
      this.missionItems = [
        ...(start ? [start] : []),
        ...newMiddleItems,
        ...(end   ? [end]   : []),
      ]
    },

    clearMissionItems() {
      // Reset mission_start to lat=0/lon=0 (not current vehicle position).
      // If mission_start kept the vehicle coords, the getter's hasContent check
      // would see lat !== 0 and return a 1-WP list, keeping START enabled.
      this.missionItems = [
        makeMissionStartItem(0, 0, this.missionDefaultWpRadius, this.missionDefaultWpSpeed),
        makeMissionEndItem(this.missionDefaultWpRadius, this.missionDefaultWpSpeed),
      ]
      this._legacyWaypoints = []
      this.activeSurveyId = null
      this.surveyDrawMode = false
      this.activeMissionWpId = null
      this.sendCommand('CLEAR_WP_ROUTE', {})
    },

    setMissionStartPosition(lat, lon) {
      const item = this.missionItems.find(i => i.type === 'mission_start')
      if (item) { item.lat = lat; item.lon = lon }
    },

    // Polygon vertex management for surveys
    addSurveyVertex(id, lat, lon) {
      const item = this.missionItems.find(i => i.id === id && i.type === 'survey')
      if (item) item.polygon.push({ lat, lon })
    },

    updateSurveyVertex(id, index, lat, lon) {
      const item = this.missionItems.find(i => i.id === id && i.type === 'survey')
      if (item && item.polygon[index]) {
        item.polygon[index] = { lat, lon }
      }
    },

    clearSurveyPolygon(id) {
      const item = this.missionItems.find(i => i.id === id && i.type === 'survey')
      if (item) item.polygon = []
    },

    uploadMission() {
      // Convert to backend model structure if needed. 
      // Backend expects MissionPayload: { waypoints: [{lat, lon, radius}], loop: bool }
      const payload = {
        waypoints: this.missionWaypoints.map(wp => ({
          lat: wp.lat,
          lon: wp.lon,
          radius: 2.0
        })),
        loop: false
      }
      this.sendCommand('UPLOAD_MISSION', payload)
    },

    sendCommand(type, payload = {}) {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        console.warn(`Cannot send command '${type}': WebSocket not open (readyState=${this.socket?.readyState})`)
        return false
      }

      // Per-session monotonic sequence number. Backend dedups by (connection,
      // seq) so a TCP-buffered retransmit after a reconnect is dropped.
      this._cmdSeq = (this._cmdSeq || 0) + 1
      const message = {
        type: type,
        timestamp: Date.now() / 1000.0, // Unix timestamp in seconds
        payload: payload,
        seq: this._cmdSeq,
      }

      this.socket.send(JSON.stringify(message))
      if (type !== 'MANUAL_INPUT') console.log("Sent Command:", message)
      return true
    },

    resetEnergy() {
      this.sendCommand('RESET_ENERGY')
    },

    setSimMode(newMode) {
      if (!this.isConnected) return
      if (this.simMode === newMode) return

      this.simMode = newMode
      
      if (newMode === 'SIMULATION') {
        // Safety: disarm before starting simulation so real motors cannot activate.
        if (this.isArmed) {
          this.sendCommand('DISARM', {})
          this.isArmed = false
        }
        // Start RT Simulator continuously
        const lat = this.simStartWaypoint ? this.simStartWaypoint.lat : this.simDefaultLat
        const lon = this.simStartWaypoint ? this.simStartWaypoint.lon : this.simDefaultLon
        const kn = this.gncConfig ? (this.gncConfig.cruise_speed_kn || 3.0) : 3.0
        const _v = kn * 0.5144
        const tauX = 21.94 * _v + 42.58 * _v * _v  // equilibrium surge force [N]
        
        this.sendCommand('START_RT_SIM', {
          current_lat: lat,
          current_lon: lon,
          current_heading: 0.0,
          surge_force: tauX,
        })
      } else {
        // Stop RT Simulator
        this.sendCommand('STOP_RT_SIM', {})
      }
    },

    setBatteryCapacity(capacityWh) {
      this.batteryCapacityWh = capacityWh
      this.sendCommand('SET_BATTERY_CAPACITY', { capacity_wh: capacityWh })
    },

    setGnssConfig(config) {
      // config: { serial_port, baud_rate, ntrip_caster, ntrip_port, mountpoint, username, password, command_freq }
      // Also update local state
      if (config.serial_port !== undefined) this.gnssSerialPort = config.serial_port
      if (config.baud_rate !== undefined) this.gnssBaudRate = config.baud_rate
      if (config.ntrip_caster !== undefined) this.gnssNtripCaster = config.ntrip_caster
      if (config.ntrip_port !== undefined) this.gnssNtripPort = config.ntrip_port
      if (config.mountpoint !== undefined) this.gnssMountpoint = config.mountpoint
      if (config.username !== undefined) this.gnssUsername = config.username
      if (config.password !== undefined) this.gnssPassword = config.password
      if (config.command_freq !== undefined) this.gnssCommandFreq = config.command_freq
      this.sendCommand('SET_GNSS_CONFIG', config)
    },

    setGncConfig(config) {
      this.gncConfig = { ...this.gncConfig, ...config }
      localStorage.setItem('gncConfig', JSON.stringify(this.gncConfig))
      // Always send the full merged config so the backend never resets
      // unrelated parameters (wn, zeta, k_delta, …) to their defaults.
      this.sendCommand('SET_GNC_CONFIG', this.gncConfig)
    },

    // ─── Relay control (ESP32 R1 / R2 / R3) ──────────────────────────
    setRelay(idx, state) {
      this.sendCommand('SET_RELAY', { idx, state: state ? 1 : 0 })
    },
    restartRelay(idx) {
      this.sendCommand('RESTART_RELAY', { idx })
    },
    setRelayNames(names) {
      this.sendCommand('SET_RELAY_NAMES', { names })
    },

    // ─── Motor calibration (ESP32 thrusters) ─────────────────────────
    setMotorConfig(config) {
      this.motorConfig = { ...this.motorConfig, ...config }
      this.sendCommand('SET_MOTOR_CONFIG', this.motorConfig)
    },

    // ─── Sensor lever-arm offsets (CRP compensation) ─────────────────
    setOffsetsConfig(config) {
      this.offsetsConfig = { ...this.offsetsConfig, ...config }
      this.sendCommand('SET_OFFSETS_CONFIG', this.offsetsConfig)
    },

    setInsConfig(config) {
      const nextConfig = { ...this.insConfig, ...config }
      if (!this.sendCommand('SET_INS_CONFIG', nextConfig)) return false
      this.insConfig = nextConfig
      this._pendingInsConfig = { ...nextConfig }
      this._pendingInsConfigSentAt = Date.now()
      return true
    },

    syncInsConfigFromBackend(config, nowMs = Date.now()) {
      const incoming = { ...this.insConfig, ...config }
      if (!this._pendingInsConfig) {
        this.insConfig = incoming
        return
      }

      const confirmed = Object.entries(this._pendingInsConfig).every(
        ([key, value]) => incoming[key] === value
      )
      if (confirmed || nowMs - this._pendingInsConfigSentAt >= 5000) {
        this.insConfig = incoming
        this._pendingInsConfig = null
        this._pendingInsConfigSentAt = 0
      }
    },

    // ─── Logs feature ────────────────────────────────────────────────
    async fetchLogFieldCatalog(force = false) {
      if (this.logFieldCatalog && !force) return this.logFieldCatalog
      try {
        const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`
        const resp = await fetch(`${baseUrl}/api/log-fields`)
        this.logFieldCatalog = await resp.json()
      } catch (e) {
        console.error('fetchLogFieldCatalog failed', e)
      }
      return this.logFieldCatalog
    },

    async fsList(path = '', showHidden = false) {
      const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`
      const resp = await fetch(`${baseUrl}/api/fs/list`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, show_hidden: showHidden }),
      })
      return resp.json()
    },

    async fsMkdir(path) {
      const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`
      const resp = await fetch(`${baseUrl}/api/fs/mkdir`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      })
      return resp.json()
    },

    async fetchAppLog(lines = 50, offset = 0) {
      const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`
      const resp = await fetch(`${baseUrl}/api/app-log?lines=${lines}&offset=${offset}`)
      return resp.json()
    },

    pushLoggingConfig() {
      this.sendCommand('SET_LOGGING_CONFIG', this.loggingConfig)
    },

    upsertCsvLogger(cfg) {
      const arr = [...this.loggingConfig.csv_loggers]
      const idx = arr.findIndex(c => c.id === cfg.id)
      if (idx >= 0) arr[idx] = cfg
      else arr.push(cfg)
      this.loggingConfig = { ...this.loggingConfig, csv_loggers: arr }
      this.pushLoggingConfig()
    },

    upsertJsonBroadcaster(cfg) {
      const arr = [...this.loggingConfig.json_broadcasters]
      const idx = arr.findIndex(c => c.id === cfg.id)
      if (idx >= 0) arr[idx] = cfg
      else arr.push(cfg)
      this.loggingConfig = { ...this.loggingConfig, json_broadcasters: arr }
      this.pushLoggingConfig()
    },

    removeLogger(id) {
      this.loggingConfig = {
        csv_loggers: this.loggingConfig.csv_loggers.filter(c => c.id !== id),
        json_broadcasters: this.loggingConfig.json_broadcasters.filter(c => c.id !== id),
      }
      this.pushLoggingConfig()
    },

    toggleLogger(id, enabled) {
      const apply = (list) => list.map(c => c.id === id ? { ...c, enabled } : c)
      this.loggingConfig = {
        csv_loggers: apply(this.loggingConfig.csv_loggers),
        json_broadcasters: apply(this.loggingConfig.json_broadcasters),
      }
      this.pushLoggingConfig()
    },

    startLoggerPreview(id) { this.sendCommand('LOGGER_START_PREVIEW', { id }) },
    stopLoggerPreview(id)  { this.sendCommand('LOGGER_STOP_PREVIEW',  { id }) },
    
    setSimStartWp(lat, lon) {
      this.simStartWaypoint = { lat, lon }
      localStorage.setItem('simStartWp', JSON.stringify({ lat, lon }))
    },

    // --- Simulation Actions ---
    async runSimulation(request) {
      this.simulationRunning = true
      try {
        const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`
        const resp = await fetch(`${baseUrl}/api/simulate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request),
        })
        const data = await resp.json()
        if (data.status === 'ok') {
          this.simulationResults = data.results
          this.simulationWaypoints = request.waypoints
          this.simulationOverlayVisible = true
          return { ok: true, results: data.results }
        } else {
          return { ok: false, message: data.message }
        }
      } catch (e) {
        console.error('Simulation request failed:', e)
        return { ok: false, message: e.message }
      } finally {
        this.simulationRunning = false
      }
    },

    clearSimulation() {
      this.simulationResults = []
      this.simulationWaypoints = []
      this.simulationOverlayVisible = false
    },

    toggleSimOverlay() {
      this.simulationOverlayVisible = !this.simulationOverlayVisible
    },

    // --- RT Simulation Actions ---
    startRTSim(config) {
      const payload = {
        ...config,
      }
      this.sendCommand('START_RT_SIM', payload)
    },

    stopRTSim() {
      this.sendCommand('STOP_RT_SIM', {})
    },

    navigateToMapPlanner() {
      this.currentTab = 'map'
      this.mapPlanMode = true
    },

    // --- Vehicle Mode Actions ---
    setVehicleMode(mode) {
      if (this.wpRouteActive) {
        this.wpRouteActive = false
        this.sendCommand('STOP_WP_ROUTE', {})
      }
      if (this.stationActive) {
        this.stationActive = false
        this.sendCommand('STOP_STATION', {})
      }
      this.sendCommand('SET_MODE', { mode })
    },

    toggleSimMode() {
      if (this.simMode === 'REAL') {
        const wp = this.simStartWaypoint || { lat: this.simDefaultLat, lon: this.simDefaultLon }
        this.startRTSim({
          current_lat: wp.lat,
          current_lon: wp.lon,
          current_heading: this.heading,
          manual_mode: false, // Backend ignores this anyway now
        })
        this.simMode = 'SIMULATION'
      } else {
        // Stop any active auto modes before switching to REAL
        if (this.wpRouteActive) {
          this.wpRouteActive = false
          this.sendCommand('STOP_WP_ROUTE', {})
        }
        if (this.stationActive) {
          this.stationActive = false
          this.sendCommand('STOP_STATION', {})
        }
        this.stopRTSim()
        this.simMode = 'REAL'
      }
    },

    armVehicle() {
      this.sendCommand('ARM', {})
    },

    disarmVehicle() {
      // Explicitly stop any active auto modes first
      if (this.wpRouteActive) {
        this.wpRouteActive = false
        this.sendCommand('STOP_WP_ROUTE', {})
      }
      if (this.stationActive) {
        this.stationActive = false
        this.sendCommand('STOP_STATION', {})
      }
      this.sendCommand('DISARM', {})
    },

    sendManualInput(throttle, steering) {
      this.manualThrottle = throttle
      this.manualSteering = steering
      this.sendCommand('MANUAL_INPUT', { throttle, steering })
    },

    // --- Station Keeping Actions ---
    setStation(lat, lon, reachingRadius, stationRadius) {
      this.stationWaypoint = { lat, lon }
      this.stationReachingRadius = reachingRadius
      this.stationRadius = stationRadius
      localStorage.setItem('stationReachingRadius', JSON.stringify(reachingRadius))
      localStorage.setItem('stationRadius', JSON.stringify(stationRadius))
      this.sendCommand('SET_STATION', { lat, lon, reaching_radius: reachingRadius, station_radius: stationRadius })
    },

    startStation(cruiseSpeedKn = null) {
      this.stationActive = true
      const payload = {
        lat: this.stationWaypoint?.lat,
        lon: this.stationWaypoint?.lon,
        reaching_radius: this.stationReachingRadius,
        station_radius: this.stationRadius,
      }
      if (cruiseSpeedKn !== null) {
        payload.cruise_speed_kn = cruiseSpeedKn
        // Keep local store in sync so saveGncConfig reads the current speed
        this.gncConfig = { ...this.gncConfig, cruise_speed_kn: cruiseSpeedKn }
        localStorage.setItem('gncConfig', JSON.stringify(this.gncConfig))
      }
      this.sendCommand('START_STATION', payload)
    },

    stopStation() {
      this.stationActive = false
      this.sendCommand('STOP_STATION', {})
    },

    // --- WP Route Actions ---
    startWpRoute(config) {
      this.wpRouteActive = true
      // config: { direction, completion, waypoints, cruise_speed_kn }
      // Persist direction/completion so targetWpLabel can read the current direction
      this.wpRouteDirection = config.direction || this.wpRouteDirection
      this.wpRouteCompletion = config.completion || this.wpRouteCompletion

      const wps = config.waypoints || this.missionWaypoints
      const payload = {
        direction: this.wpRouteDirection,
        completion: this.wpRouteCompletion,
        waypoints: wps.map(wp => ({
          lat: wp.lat,
          lon: wp.lon,
          radius: wp.radius || 5.0,
          speed: wp.speed || 1.0,
        })),
      }
      if (config.cruise_speed_kn !== undefined) {
        payload.cruise_speed_kn = config.cruise_speed_kn
        // Keep local store in sync so saveGncConfig reads the current speed
        this.gncConfig = { ...this.gncConfig, cruise_speed_kn: config.cruise_speed_kn }
        localStorage.setItem('gncConfig', JSON.stringify(this.gncConfig))
      }
      
      this.sendCommand('START_WP_ROUTE', payload)
    },

    stopWpRoute() {
      this.wpRouteActive = false
      this.sendCommand('STOP_WP_ROUTE', {})
    },

    // --- Home WP Actions ---
    setHomeWp(lat, lon) {
      this.homeWaypoint = { lat, lon }
      localStorage.setItem('homeWaypoint', JSON.stringify({ lat, lon }))
      this.sendCommand('SET_HOME_WP', { lat, lon })
    },

    // --- Fail-safe Actions ---
    setFailsafeConfig(config) {
      if (config.min_battery_pct !== undefined) this.failsafeMinBattery = config.min_battery_pct
      if (config.min_gnss_fix !== undefined) this.failsafeMinGnssFix = config.min_gnss_fix
      if (config.comm_timeout !== undefined) this.failsafeCommTimeout = config.comm_timeout
      if (config.comm_action !== undefined) this.failsafeCommAction = config.comm_action
      if (config.ins_timeout !== undefined) this.failsafeInsTimeout = config.ins_timeout
      if (config.ins_action !== undefined) this.failsafeInsAction = config.ins_action
      localStorage.setItem('failsafeConfig', JSON.stringify({
        min_battery_pct: this.failsafeMinBattery,
        min_gnss_fix:    this.failsafeMinGnssFix,
        comm_timeout:    this.failsafeCommTimeout,
        comm_action:     this.failsafeCommAction,
        ins_timeout:     this.failsafeInsTimeout,
        ins_action:      this.failsafeInsAction,
      }))
      this.sendCommand('SET_FAILSAFE_CONFIG', config)
    },

    // --- Alert Banner Actions ---
    addAlert(type, message) {
      const id = Date.now()
      this.alertBanners.push({ id, type, message, dismissible: type === 'warning' })
      if (type === 'warning') {
        setTimeout(() => this.dismissAlert(id), 5000)
      }
    },

    dismissAlert(id) {
      this.alertBanners = this.alertBanners.filter(a => a.id !== id)
    },

    clearAlerts() {
      this.alertBanners = []
    },

    connectWebSocket() {
      // Avoid duplicate connections: block if already open OR still connecting.
      if (this.socket && (
        this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING
      )) {
        return
      }

      // Neutralise any previous socket's event handlers so orphaned sockets
      // can no longer update store state or schedule reconnects.
      if (this.socket) {
        const stale = this.socket
        stale.onopen    = null
        stale.onmessage = null
        stale.onclose   = null
        stale.onerror   = null
        // If still open/connecting, close it cleanly.
        if (stale.readyState === WebSocket.OPEN || stale.readyState === WebSocket.CONNECTING) {
          stale.close()
        }
      }

      console.log('Attempting to connect to WebSocket...')
      const ws = new WebSocket(
        // Use window.location.host (includes port when non-standard) so the
        // WebSocket connects to the same host:port the page was served from.
        // This works both on localhost:8000 and through proxies/tunnels like
        // ngrok that serve on the standard HTTPS port (443).
        `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
      )
      this.socket = ws

      ws.onopen = () => {
        if (this.socket !== ws) return   // superseded by a newer socket
        this.isConnected = true
        // Reset per-session command sequence. Backend's last_seq is also per
        // connection, so the first new command (seq=1) is always accepted.
        this._cmdSeq = 0
        this.lastAckSeq = 0
        this.linkAlive = true   // optimistic; updated by comms/link broadcasts
        // Allow the first system/status heartbeat after reconnect to restore
        // any persisted mission state from the backend.
        this._missionSynced = false
        console.log('WebSocket Connected — waiting for system/status to sync config from backend')
        // Do NOT push localStorage values to the backend here.
        // The backend is authoritative: it persists config to manager_settings.json and
        // reloads it on every restart. Pushing stale localStorage values would silently
        // overwrite any backend-side changes made between sessions (B-09).
        // Config will be received via the first system/status heartbeat below.

        // ── Zombie-connection detector (B-15) ─────────────────────────────────
        // If we are "connected" (onclose has not fired) but no messages have been
        // received for 10 seconds, the WebSocket is in a zombie state:
        //   - The server dropped us from its broadcast list (e.g. after a failed
        //     send_text()) but never sent a close frame.
        //   - Commands still reach the backend (TCP is alive), but the frontend
        //     never receives telemetry updates.
        // Forcing ws.close() here triggers onclose → automatic reconnect.
        let _lastMsgTime = Date.now()
        const _heartbeatTimer = setInterval(() => {
          if (this.socket !== ws) { clearInterval(_heartbeatTimer); return }
          if (this.isConnected && Date.now() - _lastMsgTime > 10000) {
            console.warn('[WS] No data received for 10 s — zombie connection detected, forcing reconnect')
            clearInterval(_heartbeatTimer)
            ws.close()
          }
        }, 2000)

        // Expose updater so onmessage can reset the timer
        ws._updateLastMsgTime = () => { _lastMsgTime = Date.now() }

        // ── Frontend keep-alive PING (2 Hz) ───────────────────────────────────
        // The backend uses these PINGs to populate the `comms/link` topic which
        // gates GNC's comm-loss failsafe. Without this stream, a real 4G or
        // commander disconnect would never trip the failsafe.
        // The echoed PONG also gives us the round-trip latency of the control link.
        let _pingSeq = 0
        resetLinkStats(this)
        const _pingTimer = setInterval(() => {
          if (this.socket !== ws || ws.readyState !== WebSocket.OPEN) {
            clearInterval(_pingTimer)
            return
          }
          // Expire probes that were never answered and count them as lost.
          const nowPerf = performance.now()
          for (const [seq, t0] of _pendingPings) {
            if (nowPerf - t0 > PING_TIMEOUT_MS) {
              _pendingPings.delete(seq)
              pushLatencySample(this, null)
            }
          }
          _pingSeq += 1
          try {
            _pendingPings.set(_pingSeq, performance.now())
            ws.send(JSON.stringify({ type: 'PING', seq: _pingSeq, ts: Date.now() / 1000.0 }))
          } catch (e) {
            clearInterval(_pingTimer)
          }
        }, PING_PERIOD_MS)
        ws._pingTimer = _pingTimer
      }

      ws.onmessage = (event) => {
        if (this.socket !== ws) return   // orphaned socket — discard
        if (ws._updateLastMsgTime) ws._updateLastMsgTime()  // reset zombie-detector timer
        try {
          const payload = JSON.parse(event.data)
          // Payload structure: { topic: "...", data: { ... } }
          const { topic, data } = payload

          // Backend ACKs and PONGs are not telemetry — handle and return early.
          if (topic === 'comms/ack') {
            if (typeof data?.seq === 'number') this.lastAckSeq = data.seq
            if (data?.duplicate) console.warn('[WS] backend reports duplicate command', data)
            return
          }
          if (topic === 'comms/pong') {
            const t0 = _pendingPings.get(data?.seq)
            if (t0 !== undefined) {
              _pendingPings.delete(data.seq)
              pushLatencySample(this, performance.now() - t0)
            }
            return
          }
          if (topic === 'comms/link_info') {
            this.linkTransport = data?.transport || 'unknown'
            this.linkIface     = data?.iface     || ''
            this.linkServerIp  = data?.server_ip || ''
            this.linkClientIp  = data?.client_ip || ''
            return
          }
          if (topic === 'comms/link') {
            this.linkAlive = !!data?.ws_alive
            return
          }

          let newLat = null
          let newLon = null

          if (topic === 'sensor/gnss') {
            // Raw sensor diagnostics only — do NOT write to lat/lon/heading/speed.
            // Those are owned exclusively by gnc/ekf_state (EKF-filtered output).
            this.gnssRawLat = data.lat
            this.gnssRawLon = data.lon
            this.gnssAlt = data.alt
            this.gnssFixType = data.fix_type
            this.gnssNumSats = data.num_satellites
            this.gnssHdop = data.hdop
            this.gnssVdop = data.vdop
            this.gnssHorizontalAccuracyM = data.horizontal_accuracy_m ?? null
            this.gnssVerticalAccuracyM = data.vertical_accuracy_m ?? null
            this.gnssHeading = data.heading          // degrees — dual-antenna true heading
            this.gnssHeadingStatus = data.heading_status
            this.gnssCog = data.cog                  // degrees — course over ground
            this.gnssSogKnots = data.sog_knots        // knots
            this.gnssSogKmh = data.sog_kmh            // km/h
            this.gnssUtcTime = data.utc_time
            this.gnssUtcDate = data.utc_date
            // Append to raw GNSS chart history
            const nowMs = Date.now()
            this.gnssHistory.push({
              timeMs: nowMs,
              label: new Date(nowMs).toISOString().substr(11, 8),
              lat: data.lat, lon: data.lon, alt: data.alt || 0
            })
            const cutoffGnss = nowMs - 300000
            if (this.gnssHistory.length > 0 && this.gnssHistory[0].timeMs < cutoffGnss)
              this.gnssHistory = this.gnssHistory.filter(p => p.timeMs > cutoffGnss)
            // Degraded-quality detection: orange whenever the fix is not RTK Fixed (4).
            // Covers "acquiring fix" (fix_type=0/lat=lon=0), GPS-only, DGPS, and RTK Float.
            this.sensorZeroValues.gnss = (data.fix_type !== 4)
          } 
          else if (topic === 'gnc/imu_state') {
            this.imuRoll = data.roll_crp
            this.imuPitch = data.pitch_crp
            this.imuYaw = data.yaw_crp
            this.imuAx = data.accx_crp
            this.imuAy = data.accy_crp
            this.imuAz = data.accz_crp
            this.imuP = data.wx_crp
            this.imuQ = data.wy_crp
            this.imuR = data.wz_crp
            this.imuMagHeading = data.mag_heading_crp

            const nowMs = Number.isFinite(data.timestamp) ? data.timestamp * 1000 : Date.now()
            if (Date.now() - this._lastImuPushMs >= CHART_PUSH_INTERVAL_MS) {
              this._lastImuPushMs = Date.now()
              this.imuHistory.push({
                timeMs: nowMs,
                label: new Date(nowMs).toISOString().substr(11, 8),
                roll: data.roll_crp ?? 0,
                pitch: data.pitch_crp ?? 0,
                yaw: data.yaw_crp ?? 0,
                ax: data.accx_crp ?? 0,
                ay: data.accy_crp ?? 0,
                az: data.accz_crp ?? 0,
                p: data.wx_crp ?? 0,
                q: data.wy_crp ?? 0,
                r: data.wz_crp ?? 0
              })
              const cutoffImu = nowMs - 120000
              if (this.imuHistory.length > 0 && this.imuHistory[0].timeMs < cutoffImu)
                this.imuHistory = this.imuHistory.filter(point => point.timeMs > cutoffImu)
            }
          }
          else if (topic === 'gnc/ekf_state') {
            this.lat = data.lat
            this.lon = data.lon
            this.altitude = data.altitude
            this.heading = data.heading
            this.headingStatus = data.heading_status || ''
            this.insActive = data.ins_active ?? false
            this.positionSource = data.position_source || 'GNSS'
            this.navFixType = data.fix_type ?? 0
            this.navHorizontalAccuracyM = data.horizontal_accuracy_m ?? null
            this.navVerticalAccuracyM = data.vertical_accuracy_m ?? null
            this.speed = data.speed

            if (
              Number.isFinite(data.gnss_timestamp) &&
              data.gnss_timestamp > 0 &&
              data.gnss_timestamp !== this._lastGnssCrpTimestamp &&
              Number.isFinite(data.gnss_lat_crp) &&
              Number.isFinite(data.gnss_lon_crp)
            ) {
              this._lastGnssCrpTimestamp = data.gnss_timestamp
              this.gnssCrpHistory.push({
                timeMs: data.gnss_timestamp * 1000,
                lat: data.gnss_lat_crp,
                lon: data.gnss_lon_crp,
                alt: data.gnss_altitude_crp ?? 0
              })
              if (this.gnssCrpHistory.length > 10) {
                this.gnssCrpHistory.splice(0, this.gnssCrpHistory.length - 10)
              }
            }

            const nowMs = Number.isFinite(data.timestamp) ? data.timestamp * 1000 : Date.now()
            if (Date.now() - this._lastInsPushMs >= CHART_PUSH_INTERVAL_MS) {
              this._lastInsPushMs = Date.now()
              this.insComparisonHistory.push({
                timeMs: nowMs,
                label: new Date(nowMs).toISOString().substr(11, 8),
                insLat: data.lat,
                insLon: data.lon,
                insAlt: data.altitude ?? 0,
                insHeading: Number.isFinite(data.heading)
                  ? ((data.heading * 180 / Math.PI) + 360) % 360
                  : 0,
                gnssLat: data.gnss_lat_crp ?? this.gnssRawLat,
                gnssLon: data.gnss_lon_crp ?? this.gnssRawLon,
                gnssAlt: data.gnss_altitude_crp ?? this.gnssAlt,
                gnssHeading: this.gnssHeading,
                magHeading: this.imuMagHeading,
                cog: this.gnssCog,
                gnssHorizontalAccuracyM: this.gnssHorizontalAccuracyM,
                gnssVerticalAccuracyM: this.gnssVerticalAccuracyM,
                insHorizontalAccuracyM: data.horizontal_accuracy_m ?? null,
                insVerticalAccuracyM: data.vertical_accuracy_m ?? null,
                insActive: data.ins_active ?? false,
                positionSource: data.position_source || 'GNSS'
              })
              const cutoffIns = nowMs - 300000
              if (
                this.insComparisonHistory.length > 0 &&
                this.insComparisonHistory[0].timeMs < cutoffIns
              ) {
                this.insComparisonHistory = this.insComparisonHistory.filter(
                  point => point.timeMs > cutoffIns
                )
              }
            }
            if (data.source) this.dataSource = data.source
            newLat = data.lat
            newLon = data.lon
          }
          else if (topic === 'sim/status') {
            this.rtSimActive = data.running
            this.rtSimElapsed = data.elapsed_time || 0
            this.rtSimConfig = data || null
            if (data.running) {
              this.dataSource = 'sim'
              // Belt-and-suspenders: keep toggle in sync even if system/status
              // hasn't arrived yet (sim/status runs at 20 Hz vs 10 Hz).
              this.simMode = 'SIMULATION'
            } else {
              this.dataSource = 'sensor'
              this.simMode = 'REAL'
            }
          }
          else if (topic === 'system/status') {
             // ── Watchdog crash alerts ────────────────────────────────────
             if (data.watchdog_alert) {
               const type = data.level === 'critical' ? 'error' : 'warning'
               this.addAlert(type, `[${data.process}] ${data.message}`)
               return
             }
             this.isArmed = data.is_armed
             this.mode = data.mode
             if (data.mode) this.vehicleMode = data.mode
             // simMode is authoritative on the backend (Manager tracks START/STOP_RT_SIM).
             // Always sync so the REAL/SIM toggle stays correct after a page reload.
             // If the Manager says REAL (which it always does on a fresh start) also
             // clear rtSimActive so the "SIM RUNNING" banner disappears even when the
             // backend was killed mid-simulation and never sent a final sim/status
             // { running: false }.
             if (data.sim_mode !== undefined) {
               this.simMode = data.sim_mode
               if (data.sim_mode === 'REAL') {
                 this.rtSimActive = false
                 this.rtSimElapsed = 0
               }
             }
             if (data.station_active !== undefined) this.stationActive = data.station_active
             if (data.station_wp) this.stationWaypoint = data.station_wp
             if (data.station_reaching_radius !== undefined && this.stationActive) this.stationReachingRadius = data.station_reaching_radius
             if (data.station_radius !== undefined && this.stationActive) this.stationRadius = data.station_radius
             if (data.wp_route_active !== undefined) this.wpRouteActive = data.wp_route_active
             // Always keep direction/completion in sync (backend is authoritative).
             if (data.wp_route_direction  !== undefined) this.wpRouteDirection  = data.wp_route_direction
             if (data.wp_route_completion !== undefined) this.wpRouteCompletion = data.wp_route_completion
             // Restore mission waypoints from the backend on the first heartbeat
             // after a page refresh.  This makes the route visible even when the
             // operator reconnects mid-survey.  The flag prevents subsequent
             // heartbeats from overwriting waypoints drawn by the operator.
             if (!this._missionSynced &&
                 Array.isArray(data.wp_route_waypoints) &&
                 data.wp_route_waypoints.length > 0) {
               this._legacyWaypoints = data.wp_route_waypoints
               this._missionSynced = true
             } else if (!this._missionSynced && data.wp_route_waypoints !== undefined) {
               // No persisted waypoints on backend → mark synced so we don't
               // overwrite new operator-drawn items on subsequent heartbeats.
               this._missionSynced = true
             }
             if (data.home_wp) {
               // Backend is authoritative. Always accept home_wp and update localStorage
               // so the next reload starts with the current backend value (fixes B-09).
               this.homeWaypoint = data.home_wp
               localStorage.setItem('homeWaypoint', JSON.stringify(data.home_wp))
             }
             if (data.gnss_fix_type !== undefined) this.gnssFixType = data.gnss_fix_type
             if (data.battery_level_pct !== undefined) this.batteryLevelPct = data.battery_level_pct
             if (data.failsafe_config) {
               // Always sync failsafe config from backend and update localStorage.
               // Backend is authoritative; localStorage is just a display cache (fixes B-09).
               const fs = data.failsafe_config
               if (fs.min_battery_pct !== undefined) this.failsafeMinBattery = fs.min_battery_pct
               if (fs.min_gnss_fix !== undefined) this.failsafeMinGnssFix = fs.min_gnss_fix
               if (fs.comm_timeout !== undefined) this.failsafeCommTimeout = fs.comm_timeout
               if (fs.comm_action !== undefined) this.failsafeCommAction = fs.comm_action
               if (fs.ins_timeout !== undefined) this.failsafeInsTimeout = fs.ins_timeout
               if (fs.ins_action !== undefined) this.failsafeInsAction = fs.ins_action
               localStorage.setItem('failsafeConfig', JSON.stringify({
                 min_battery_pct: this.failsafeMinBattery,
                 min_gnss_fix:    this.failsafeMinGnssFix,
                 comm_timeout:    this.failsafeCommTimeout,
                 comm_action:     this.failsafeCommAction,
                 ins_timeout:     this.failsafeInsTimeout,
                 ins_action:      this.failsafeInsAction,
               }))
             }
             if (data.gnc_config) {
               // Always sync gnc_config from backend and update localStorage (fixes B-09).
               this.gncConfig = data.gnc_config
               localStorage.setItem('gncConfig', JSON.stringify(data.gnc_config))
             }
             if (data.logging_config) {
               // Backend is authoritative for logging config.
               this.loggingConfig = data.logging_config
             }
             if (data.relay_config) {
               // Backend is authoritative for relay state.
               const rc = data.relay_config
               this.relayConfig = {
                 names:  Array.isArray(rc.names)  ? rc.names.slice(0, 3)  : this.relayConfig.names,
                 states: Array.isArray(rc.states) ? rc.states.map(s => s ? 1 : 0) : this.relayConfig.states,
                 restart_until: Array.isArray(rc.restart_until) ? rc.restart_until : [0, 0, 0],
               }
             }
             if (data.motor_config) {
               // Backend is authoritative for motor calibration.
               this.motorConfig = { ...this.motorConfig, ...data.motor_config }
             }
             if (data.offsets_config) {
               // Backend is authoritative for sensor lever-arm offsets.
               this.offsetsConfig = { ...this.offsetsConfig, ...data.offsets_config }
             }
             if (data.ins_config) {
               this.syncInsConfigFromBackend(data.ins_config)
             }
             if (data.gnss_config) {
               // Backend is authoritative for GNSS/NTRIP config — sync so the
               // Settings form reflects the persisted values after a reload.
               const gc = data.gnss_config
               if (gc.serial_port   !== undefined) this.gnssSerialPort   = gc.serial_port
               if (gc.baud_rate     !== undefined) this.gnssBaudRate     = gc.baud_rate
               if (gc.ntrip_caster  !== undefined) this.gnssNtripCaster  = gc.ntrip_caster
               if (gc.ntrip_port    !== undefined) this.gnssNtripPort    = gc.ntrip_port
               if (gc.mountpoint    !== undefined) this.gnssMountpoint   = gc.mountpoint
               if (gc.username      !== undefined) this.gnssUsername    = gc.username
               if (gc.password      !== undefined) this.gnssPassword    = gc.password
               if (gc.command_freq  !== undefined) this.gnssCommandFreq = gc.command_freq
             }
          }
          else if (topic === 'gnc/control_debug') {
             this.targetHeading = data.target_heading
             this.headingError = data.heading_error
             this.crossTrackError = data.cross_track_error
             this.ettNextWp   = data.ett_next_wp   ?? -1
             this.etaNextWp   = data.eta_next_wp   ?? 0
             this.ettRouteEnd = data.ett_route_end ?? -1
             this.etaRouteEnd = data.eta_route_end ?? 0
             this.kpM         = data.kp_m          ?? 0
             // Cache velocity/accel/tau for chart history
             this._lastGncDebug = {
               surgeVel:    data.surge_vel    ?? 0,
               swayVel:     data.sway_vel     ?? 0,
               surgeAcc:    data.surge_acc    ?? 0,
               swayAcc:     data.sway_acc     ?? 0,
               vCruise:     data.v_cruise     ?? 0,
               tauXEff:     data.tau_x_eff    ?? 0,
               distToWp:    data.dist_to_wp   ?? 0,
               wpIndex:     data.wp_index     ?? 0,
               refSpeedKn:  data.ref_speed_kn ?? 0,
             }
             // Update live sidebar state
             this.tauXEff        = data.tau_x_eff    ?? 0
             this.distToWp       = data.dist_to_wp   ?? 0
             this.currentWpIndex = data.wp_index     ?? 0
             this.refSpeedKn     = data.ref_speed_kn ?? 0
          }
          else if (topic === 'gnc/control_output') {
             this.motorPort = data.port_pct
             this.motorStarboard = data.starboard_pct
             // Append to gnc chart history (heading already updated by control_debug)
             const nowMs = Date.now()
             const RAD2DEG = 180 / Math.PI
             const dbg = this._lastGncDebug || {}
             if (nowMs - this._lastGncPushMs >= CHART_PUSH_INTERVAL_MS) {
               this._lastGncPushMs = nowMs
               this.gncHistory.push({
                 timeMs: nowMs,
                 label: new Date(nowMs).toISOString().substr(11, 8),
                 actualHeading: ((this.heading || 0) * RAD2DEG + 360) % 360,
                 targetHeading: ((this.targetHeading || 0) * RAD2DEG + 360) % 360,
                 headingError: (this.headingError || 0) * RAD2DEG,
                 cte: this.crossTrackError || 0,
                 port: data.port_pct || 0,
                 starboard: data.starboard_pct || 0,
                 surgeVel:   dbg.surgeVel   || 0,
                 swayVel:    dbg.swayVel    || 0,
                 surgeAcc:   dbg.surgeAcc   || 0,
                 swayAcc:    dbg.swayAcc    || 0,
                 vCruise:    dbg.vCruise    || 0,
                 tauXEff:    dbg.tauXEff    || 0,
                 distToWp:   dbg.distToWp   || 0,
                 wpIndex:    dbg.wpIndex    || 0,
                 refSpeedKn: dbg.refSpeedKn || 0,
               })
               const cutoffGnc = nowMs - 120000
               if (this.gncHistory.length > 0 && this.gncHistory[0].timeMs < cutoffGnc)
                 this.gncHistory = this.gncHistory.filter(p => p.timeMs > cutoffGnc)
             }
          }
          else if (topic === 'sensor/battery') {
             this.batteryVoltage = data.voltage
             this.batteryCurrent = data.current
             this.batteryPower = data.power
             this.batteryLevelPct = data.level_pct
             this.batteryCapacityWh = data.capacity_wh
             this.batteryAccumulatedWh = data.accumulated_wh
             this.batteryEnergyWh = data.energy_wh
             this.batteryMeasurementStart = data.measurement_start
             this.batteryHighAlarm = data.high_voltage_alarm
             this.batteryLowAlarm = data.low_voltage_alarm
             // Append to power chart history
             const nowPwr = Date.now()
             this.powerHistory.push({
               timeMs: nowPwr,
               label: new Date(nowPwr).toISOString().substr(11, 8),
               voltage: data.voltage || 0,
               current: data.current || 0,
               power: data.power || 0
             })
             const cutoffPwr = nowPwr - 120000
             if (this.powerHistory.length > 0 && this.powerHistory[0].timeMs < cutoffPwr)
               this.powerHistory = this.powerHistory.filter(p => p.timeMs > cutoffPwr)
             // Zero-value detection: warn if voltage is zero while connected
             this.sensorZeroValues.power = (data.voltage === 0)
          }
          else if (topic === 'sensor/imu') {
             // Zero-value detection: warn if all motion values are zero while connected
             this.sensorZeroValues.imu = (
               data.roll_raw === 0 && data.pitch_raw === 0 && data.yaw_raw === 0 &&
               data.ax_raw === 0 && data.ay_raw === 0 && data.az_raw === 0
             )
          }
          else if (topic === 'sensor/status') {
             const sensor = data.sensor  // 'gnss', 'imu', or 'power'
             console.log(`[Telemetry] Received sensor/status: ${sensor} = ${data.status}`)
             if (this.sensorStatus[sensor]) {
               this.sensorStatus[sensor].status = data.status
               this.sensorStatus[sensor].message = data.message || ''
               this.sensorStatus[sensor].timestamp = data.timestamp
               console.log(`[Telemetry] Updated ${sensor} status to:`, this.sensorStatus[sensor])
               // Clear zero-value flag when sensor goes offline
               if (data.status !== 'ok' && this.sensorZeroValues[sensor] !== undefined) {
                 this.sensorZeroValues[sensor] = false
               }
             } else {
               console.warn(`[Telemetry] Unknown sensor: ${sensor}`)
             }
          }
          else if (topic === 'system/monitor') {
             this.systemMonitor = { ...this.systemMonitor, ...data }
          }
          else if (topic === 'logger/preview') {
             if (data && data.id) {
               this.loggerPreviews = { ...this.loggerPreviews, [data.id]: data }
             }
          }

          // Update Path History if we have a new position (throttled to 5 Hz)
          if (newLat !== null && newLon !== null && newLat !== 0 && newLon !== 0) {
              const now = Date.now()
              if (now - this._lastPathPushTime >= 200) {
                this._lastPathPushTime = now
                this.pathHistory.push({
                  lat: newLat,
                  lon: newLon,
                  timestamp: now
                })
                
                // Keep only last 2 minutes (120000 ms)
                const twoMinutesAgo = now - 120000
                if (this.pathHistory.length > 0 && this.pathHistory[0].timestamp < twoMinutesAgo) {
                   this.pathHistory = this.pathHistory.filter(p => p.timestamp > twoMinutesAgo)
                }
              }
          }
        } catch (error) {
          console.error('Error parsing telemetry:', error)
        }
      }

      ws.onclose = () => {
        if (this.socket !== ws) return   // orphaned socket — ignore
        this.isConnected = false
        if (ws._pingTimer) { clearInterval(ws._pingTimer); ws._pingTimer = null }
        resetLinkStats(this)
        console.warn('WebSocket Disconnected. Reconnecting in 3s...')
        setTimeout(() => {
          this.connectWebSocket()
        }, 3000)
      }

      ws.onerror = (error) => {
        if (this.socket !== ws) return   // orphaned socket — ignore
        console.error('WebSocket Error:', error)
        // Close to trigger onclose and reconnect logic
        if (ws.readyState !== WebSocket.CLOSED) {
          ws.close()
        }
      }
    }
  }
})
