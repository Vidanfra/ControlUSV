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
    pathHistory: []
  }),

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
