import { defineStore } from 'pinia'

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
    missionWaypoints: [],
    pathHistory: [],
    
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

    // GNSS additions
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
  }),

  getters: {
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
  },

  actions: {
    addWaypoint(lat, lon) {
      this.missionWaypoints.push({ lat, lon })
    },

    clearMission() {
      this.missionWaypoints = []
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
      if (!this.isConnected || !this.socket) {
        console.warn("Cannot send command: WebSocket disconnected")
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

    connectWebSocket() {
      // Avoid multiple connections
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        return
      }

      console.log('Attempting to connect to WebSocket...')
      this.socket = new WebSocket(
        // Dynamically determine protocol (ws or wss) and host
        `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.hostname}:8000/ws`
      )

      this.socket.onopen = () => {
        this.isConnected = true
        console.log('WebSocket Connected')
      }

      this.socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data)
          // Payload structure: { topic: "...", data: { ... } }
          const { topic, data } = payload

          let newLat = null
          let newLon = null

          if (topic === 'sensor/gnss') {
            this.lat = data.lat
            this.lon = data.lon
            this.gnssAlt = data.alt
            this.gnssFixType = data.fix_type
            this.gnssNumSats = data.num_satellites
            this.gnssHdop = data.hdop
            this.gnssVdop = data.vdop
            this.gnssHeading = data.heading
            this.gnssHeadingStatus = data.heading_status
            this.gnssCog = data.cog
            this.gnssSogKnots = data.sog_knots
            this.gnssSogKmh = data.sog_kmh
            this.gnssUtcTime = data.utc_time
            this.gnssUtcDate = data.utc_date
            // Update top-level speed from GNSS SOG (knots -> m/s)
            this.speed = data.sog_knots * 0.514444
            newLat = data.lat
            newLon = data.lon
          } 
          else if (topic === 'gnc/ekf_state') {
            this.lat = data.lat
            this.lon = data.lon
            this.heading = data.heading
            this.speed = data.speed
            this.battery = data.battery_voltage
            newLat = data.lat
            newLon = data.lon
          }
          else if (topic === 'system/status') {
             this.isArmed = data.is_armed
             this.mode = data.mode
          }
          else if (topic === 'gnc/control_debug') {
             this.targetHeading = data.target_heading
             this.headingError = data.heading_error
             this.crossTrackError = data.cross_track_error
          }
          else if (topic === 'gnc/control_output') {
             this.motorPort = data.port_pct
             this.motorStarboard = data.starboard_pct
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

          // Update Path History if we have a new position
          if (newLat !== null && newLon !== null && newLat !== 0 && newLon !== 0) {
              const now = Date.now()
              this.pathHistory.push({
                lat: newLat,
                lon: newLon,
                timestamp: now
              })
              
              // Keep only last 2 minutes (120000 ms)
              const twoMinutesAgo = now - 120000
              // Optimization: Only filter if the oldest point is too old
              if (this.pathHistory.length > 0 && this.pathHistory[0].timestamp < twoMinutesAgo) {
                 this.pathHistory = this.pathHistory.filter(p => p.timestamp > twoMinutesAgo)
              }
          }
        } catch (error) {
          console.error('Error parsing telemetry:', error)
        }
      }

      this.socket.onclose = () => {
        this.isConnected = false
        console.warn('WebSocket Disconnected. Reconnecting in 3s...')
        setTimeout(() => {
          this.connectWebSocket()
        }, 3000)
      }

      this.socket.onerror = (error) => {
        console.error('WebSocket Error:', error)
        // Ensure we close to trigger onclose and reconnect logic
        if (this.socket.readyState !== WebSocket.CLOSED) {
            this.socket.close()
        }
      }
    }
  }
})
