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

export const useTelemetryStore = defineStore('telemetry', {
  state: () => ({
    lat: 0.0,
    lon: 0.0,
    heading: 0.0,
    battery: 0.0,
    speed: 0.0,
    isConnected: false,
    socket: null,
    isArmed: false,
    mode: 'MANUAL',

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
    gnssHistory: [],   // { timeMs, label, lat, lon, alt }
    imuHistory: [],    // { timeMs, label, roll, pitch, yaw, ax, ay, az, p, q, r }
    gncHistory: [],    // { timeMs, label, actualHeading, targetHeading, headingError, cte, port, starboard }
    powerHistory: [],  // { timeMs, label, voltage, current, power }

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
      wn: 4.0,
      zeta: 0.5,
      wn_ref: 1.0,
      zeta_ref: 1.0,
      delta: 5.0,
      gamma: 0.0,
      tau_x: 150.0
    },
  }),

  getters: {
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

    // Best heading: prefer GNSS dual-antenna heading if available, fallback to magnetic
    bestHeading(state) {
      if (state.gnssHeadingStatus === 'A' && state.gnssHeading !== 0) {
        return state.gnssHeading
      }
      return state.imuMagHeading
    },
    headingSource(state) {
      if (state.gnssHeadingStatus === 'A' && state.gnssHeading !== 0) {
        return 'GNSS'
      }
      return 'MAG'
    },
    // Fix quality color: green for RTK fixed (4), yellow-green for float (5), 
    // yellow for DGPS (2), orange for GPS only (1), red for no fix (0)
    fixColor(state) {
      const f = state.gnssFixType
      if (f >= 4) return '#00cc00'   // RTK Fixed
      if (f === 3) return '#88cc00'  // PPS
      if (f === 2) return '#aacc00'  // DGPS
      if (f === 1) return '#FFA500'  // GPS
      return '#ff4444'               // No fix
    },
    canStartAutoMode(state) {
      return state.gnssFixType >= state.failsafeMinGnssFix
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
      this.missionItems = [
        makeMissionStartItem(this.lat, this.lon, this.missionDefaultWpRadius, this.missionDefaultWpSpeed),
        makeMissionEndItem(this.missionDefaultWpRadius, this.missionDefaultWpSpeed),
      ]
      this.activeSurveyId = null
      this.surveyDrawMode = false
      this.activeMissionWpId = null
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
        return
      }
      
      const message = {
        type: type,
        timestamp: Date.now() / 1000.0, // Unix timestamp in seconds
        payload: payload
      }
      
      this.socket.send(JSON.stringify(message))
      console.log("Sent Command:", message)
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
        const tauX = this.gncConfig ? this.gncConfig.tau_x : 150.0
        
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
      this.sendCommand('SET_GNC_CONFIG', config)
    },
    
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

    startStation(tauX = null) {
      this.stationActive = true
      const payload = {
        lat: this.stationWaypoint?.lat,
        lon: this.stationWaypoint?.lon,
        reaching_radius: this.stationReachingRadius,
        station_radius: this.stationRadius,
      }
      if (tauX !== null) payload.tau_x = tauX
      this.sendCommand('START_STATION', payload)
    },

    stopStation() {
      this.stationActive = false
      this.sendCommand('STOP_STATION', {})
    },

    // --- WP Route Actions ---
    startWpRoute(config) {
      this.wpRouteActive = true
      // config: { direction, completion, waypoints, tau_x }
      const wps = config.waypoints || this.missionWaypoints
      const payload = {
        direction: config.direction || this.wpRouteDirection,
        completion: config.completion || this.wpRouteCompletion,
        waypoints: wps.map(wp => ({
          lat: wp.lat,
          lon: wp.lon,
          radius: wp.radius || 5.0,
          speed: wp.speed || 1.0,
        })),
      }
      if (config.tau_x !== undefined) payload.tau_x = config.tau_x
      
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
        // Dynamically determine protocol (ws or wss) and host
        `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.hostname}:8000/ws`
      )
      this.socket = ws

      ws.onopen = () => {
        if (this.socket !== ws) return   // superseded by a newer socket
        this.isConnected = true
        console.log('WebSocket Connected')
        // Sync all persisted user settings to backend on every connect.
        // This ensures the backend always reflects the user's last-saved values,
        // regardless of whether the backend was restarted.
        if (localStorage.getItem('gncConfig')) {
          this.sendCommand('SET_GNC_CONFIG', this.gncConfig)
        }
        if (localStorage.getItem('failsafeConfig')) {
          this.sendCommand('SET_FAILSAFE_CONFIG', {
            min_battery_pct: this.failsafeMinBattery,
            min_gnss_fix:    this.failsafeMinGnssFix,
            comm_timeout:    this.failsafeCommTimeout,
            comm_action:     this.failsafeCommAction,
            ins_timeout:     this.failsafeInsTimeout,
            ins_action:      this.failsafeInsAction,
          })
        }
        if (this.homeWaypoint) {
          this.sendCommand('SET_HOME_WP', this.homeWaypoint)
        }
      }

      ws.onmessage = (event) => {
        if (this.socket !== ws) return   // orphaned socket — discard
        try {
          const payload = JSON.parse(event.data)
          // Payload structure: { topic: "...", data: { ... } }
          const { topic, data } = payload

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
            const cutoffGnss = nowMs - 120000
            if (this.gnssHistory.length > 0 && this.gnssHistory[0].timeMs < cutoffGnss)
              this.gnssHistory = this.gnssHistory.filter(p => p.timeMs > cutoffGnss)
          } 
          else if (topic === 'gnc/ekf_state') {
            this.lat = data.lat
            this.lon = data.lon
            this.heading = data.heading
            this.speed = data.speed
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
            } else {
              this.dataSource = 'sensor'
            }
          }
          else if (topic === 'system/status') {
             this.isArmed = data.is_armed
             this.mode = data.mode
             if (data.mode) this.vehicleMode = data.mode
             // simMode is frontend-only — do NOT overwrite from backend
             if (data.station_active !== undefined) this.stationActive = data.station_active
             if (data.station_wp) this.stationWaypoint = data.station_wp
             if (data.station_reaching_radius !== undefined && this.stationActive) this.stationReachingRadius = data.station_reaching_radius
             if (data.station_radius !== undefined && this.stationActive) this.stationRadius = data.station_radius
             if (data.wp_route_active !== undefined) this.wpRouteActive = data.wp_route_active
             if (data.home_wp) {
               // Only accept home_wp from backend if user has not set one locally.
               // User-set value (persisted in localStorage) always takes priority.
               if (!localStorage.getItem('homeWaypoint')) this.homeWaypoint = data.home_wp
             }
             if (data.gnss_fix_type !== undefined) this.gnssFixType = data.gnss_fix_type
             if (data.battery_level_pct !== undefined) this.batteryLevelPct = data.battery_level_pct
             if (data.failsafe_config) {
               // Only sync failsafe config from backend if user has no locally-persisted values.
               if (!localStorage.getItem('failsafeConfig')) {
                 const fs = data.failsafe_config
                 if (fs.min_battery_pct !== undefined) this.failsafeMinBattery = fs.min_battery_pct
                 if (fs.min_gnss_fix !== undefined) this.failsafeMinGnssFix = fs.min_gnss_fix
                 if (fs.comm_timeout !== undefined) this.failsafeCommTimeout = fs.comm_timeout
                 if (fs.comm_action !== undefined) this.failsafeCommAction = fs.comm_action
                 if (fs.ins_timeout !== undefined) this.failsafeInsTimeout = fs.ins_timeout
                 if (fs.ins_action !== undefined) this.failsafeInsAction = fs.ins_action
               }
             }
             if (data.gnc_config) {
               // Only sync gnc_config from backend if user has no locally-persisted values.
               if (!localStorage.getItem('gncConfig')) this.gncConfig = data.gnc_config
             }
          }
          else if (topic === 'gnc/control_debug') {
             this.targetHeading = data.target_heading
             this.headingError = data.heading_error
             this.crossTrackError = data.cross_track_error
          }
          else if (topic === 'gnc/control_output') {
             this.motorPort = data.port_pct
             this.motorStarboard = data.starboard_pct
             // Append to gnc chart history (heading already updated by control_debug)
             const nowMs = Date.now()
             const RAD2DEG = 180 / Math.PI
             this.gncHistory.push({
               timeMs: nowMs,
               label: new Date(nowMs).toISOString().substr(11, 8),
               actualHeading: ((this.heading || 0) * RAD2DEG + 360) % 360,
               targetHeading: ((this.targetHeading || 0) * RAD2DEG + 360) % 360,
               headingError: (this.headingError || 0) * RAD2DEG,
               cte: this.crossTrackError || 0,
               port: data.port_pct || 0,
               starboard: data.starboard_pct || 0
             })
             const cutoffGnc = nowMs - 120000
             if (this.gncHistory.length > 0 && this.gncHistory[0].timeMs < cutoffGnc)
               this.gncHistory = this.gncHistory.filter(p => p.timeMs > cutoffGnc)
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
          }
          else if (topic === 'sensor/imu') {
             this.imuRoll = data.roll
             this.imuPitch = data.pitch
             this.imuYaw = data.yaw
             this.imuAx = data.ax
             this.imuAy = data.ay
             this.imuAz = data.az
             this.imuP = data.wx
             this.imuQ = data.wy
             this.imuR = data.wz
             this.imuMagHeading = data.mag_heading ?? 0.0
             // Append to chart history
             const nowMs = Date.now()
             this.imuHistory.push({
               timeMs: nowMs,
               label: new Date(nowMs).toISOString().substr(11, 8),
               roll: data.roll || 0, pitch: data.pitch || 0, yaw: data.yaw || 0,
               ax: data.ax || 0, ay: data.ay || 0, az: data.az || 0,
               p: data.wx || 0, q: data.wy || 0, r: data.wz || 0
             })
             const cutoffImu = nowMs - 120000
             if (this.imuHistory.length > 0 && this.imuHistory[0].timeMs < cutoffImu)
               this.imuHistory = this.imuHistory.filter(p => p.timeMs > cutoffImu)
          }
          else if (topic === 'sensor/status') {
             const sensor = data.sensor  // 'gnss', 'imu', or 'power'
             console.log(`[Telemetry] Received sensor/status: ${sensor} = ${data.status}`)
             if (this.sensorStatus[sensor]) {
               this.sensorStatus[sensor].status = data.status
               this.sensorStatus[sensor].message = data.message || ''
               this.sensorStatus[sensor].timestamp = data.timestamp
               console.log(`[Telemetry] Updated ${sensor} status to:`, this.sensorStatus[sensor])
             } else {
               console.warn(`[Telemetry] Unknown sensor: ${sensor}`)
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
