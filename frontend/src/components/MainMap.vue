<template>
  <div class="map-container">
    <div id="map"></div>
    
    <div class="map-controls">
      <button 
        class="ctrl-btn plan-btn"
        :class="{ active: telemetry.mapPlanMode }"
        @click="telemetry.mapPlanMode = !telemetry.mapPlanMode"
      >
        {{ telemetry.mapPlanMode ? 'EXIT PLAN MODE' : 'PLAN MISSION' }}
      </button>
      <label v-if="telemetry.mapPlanMode" class="ctrl-btn route-btn">
        LOAD ROUTE
        <input type="file" accept=".csv,.txt" @change="loadRouteFromFile" hidden />
      </label>
      <div class="map-type-wrapper">
        <button class="ctrl-btn layer-btn" @click="showMapMenu = !showMapMenu">
          MAP ▾
        </button>
        <div v-if="showMapMenu" class="map-menu">
          <label v-for="t in themeOptions" :key="t.id" class="map-menu-item" :class="{ selected: currentThemeName === t.id }">
            <input type="radio" :value="t.id" v-model="currentThemeName" @change="showMapMenu = false" />
            {{ t.label }}
          </label>
        </div>
      </div>
      <button 
        v-if="telemetry.mapPlanMode && missionWaypoints.length > 0"
        class="ctrl-btn save-btn" 
        @click="saveRouteToFile"
      >
        SAVE ROUTE
      </button>
      <button 
        v-if="telemetry.mapPlanMode && missionWaypoints.length > 0"
        class="ctrl-btn danger-btn" 
        @click="telemetry.clearMission()"
      >
        CLEAR
      </button>
      <button
        v-if="telemetry.simulationResults.length > 0"
        class="ctrl-btn sim-btn"
        :class="{ active: telemetry.simulationOverlayVisible }"
        @click="telemetry.toggleSimOverlay()"
      >
        {{ telemetry.simulationOverlayVisible ? 'HIDE SIM' : 'SHOW SIM' }}
      </button>
    </div>

    <!-- Simulation Legend -->
    <div
      v-if="telemetry.simulationOverlayVisible && telemetry.simulationResults.length > 0"
      class="sim-legend"
    >
      <div class="sim-legend-title">Simulation Profiles</div>
      <div v-for="(r, i) in telemetry.simulationResults" :key="i" class="sim-legend-item">
        <span class="sim-legend-line" :style="{ borderColor: SIM_COLORS[i % SIM_COLORS.length] }"></span>
        <span class="sim-legend-label">Profile {{ r.profile_id }} ({{ r.config?.payload_kg ?? 25 }}kg, δ={{ r.config?.delta ?? 5 }}m)</span>
      </div>
    </div>

    <!-- North reset button (just above follow) -->
    <button
      class="north-btn"
      @click="resetNorth"
      title="Reset North"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 3L12 21" stroke="#333" stroke-width="2.5" stroke-linecap="round"/>
        <path d="M5 10L12 3L19 10" stroke="#333" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>

    <button
      class="follow-btn"
      :class="{ active: followVehicle }"
      @click="followVehicle = !followVehicle"
      title="Follow vehicle"
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="4" :fill="followVehicle ? '#1a73e8' : '#666'" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3" :stroke="followVehicle ? '#1a73e8' : '#666'" stroke-width="2" stroke-linecap="round"/>
        <circle cx="12" cy="12" r="8" :stroke="followVehicle ? '#1a73e8' : '#666'" stroke-width="1.5" fill="none"/>
      </svg>
    </button>

    <ThrustIndicator />

    <!-- Windy overlay (wind / radar) -->
    <iframe
      v-if="isWindyView"
      class="windy-overlay"
      :src="windyUrl"
      frameborder="0"
      allowfullscreen
    ></iframe>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'
import ThrustIndicator from './ThrustIndicator.vue'

const telemetry = useTelemetryStore()
const { lat, lon, missionWaypoints, pathHistory, simulationResults, simulationOverlayVisible } = storeToRefs(telemetry)

const currentThemeName = ref('satellite')
const showMapMenu = ref(false)
const themeOptions = [
  { id: 'satellite', label: 'Satellite' },
  { id: 'osm', label: 'Street Map' },
  { id: 'dark', label: 'Dark' },
  { id: 'nautical', label: 'Nautical' },
  { id: 'wind', label: 'Wind (Windy)' },
  { id: 'radar', label: 'Radar (Windy)' },
]

const isWindyView = computed(() => currentThemeName.value === 'wind' || currentThemeName.value === 'radar')

const windyUrl = computed(() => {
  const overlay = currentThemeName.value === 'radar' ? 'radar' : 'wind'
  const product = currentThemeName.value === 'radar' ? 'radar' : 'ecmwf'
  const la = lat.value || 39.4699
  const lo = lon.value || -0.3763
  return `https://embed.windy.com/embed2.html?lat=${la}&lon=${lo}&detailLat=${la}&detailLon=${lo}&zoom=10&level=surface&overlay=${overlay}&product=${product}&menu=&message=true&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=kt&metricTemp=%C2%B0C&radarRange=-1`
})

function resetNorth() {
  if (map) {
    map.easeTo({ bearing: 0, pitch: 0 })
  }
}

const followVehicle = ref(true)
const FOLLOW_ZOOM = 16.5  // ~200m north-south view
const SIM_COLORS = ['#e6194b', '#3cb44b', '#4363d8', '#f032e6', '#42d4f4', '#fabed4']

let map = null
let boatMarker = null
let trailInterval = null

// Build a GeoJSON Polygon ring approximating a circle on the Earth surface
function geoCircle(lng, lat, radiusMeters, steps = 48) {
  const coords = []
  const R = 6371000
  const latRad = lat * Math.PI / 180
  for (let i = 0; i <= steps; i++) {
    const angle = (2 * Math.PI * i) / steps
    const dLat = (radiusMeters * Math.cos(angle)) / R * (180 / Math.PI)
    const dLng = (radiusMeters * Math.sin(angle)) / (R * Math.cos(latRad)) * (180 / Math.PI)
    coords.push([lng + dLng, lat + dLat])
  }
  return [coords]
}

onMounted(() => {
  // Initialize Map with a basic background style first
  map = new maplibregl.Map({
    container: 'map',
    style: {
      version: 8,
      sources: {},
      layers: [
        {
          id: 'background',
          type: 'background',
          paint: {
            'background-color': '#021c2b' // Dark Blue Sea Color
          }
        }
      ]
    },
    center: [-0.3763, 39.4699], // Default center (Valencia, Spain)
    zoom: 15
  })
  
  // Add sources and layers once map is loaded
  map.on('load', () => {
      // 1. Add Base Sources
      map.addSource('osm', {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '&copy; OpenStreetMap Contributors'
      })
      
      map.addSource('satellite', {
          type: 'raster',
          tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
          tileSize: 256,
          attribution: 'Tiles &copy; Esri'
      })

      map.addSource('dark', {
          type: 'raster',
          tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '&copy; CARTO'
      })

      map.addSource('nautical', {
          type: 'raster',
          tiles: ['https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: 'Map data &copy; OpenSeaMap contributors'
      })

      // 2. Add Base Layers
      // Satellite (visible by default)
      map.addLayer({
          id: 'satellite',
          type: 'raster',
          source: 'satellite',
          layout: { visibility: 'visible' }
      })
      
      // OSM (hidden by default)
      map.addLayer({
          id: 'osm',
          type: 'raster',
          source: 'osm',
          layout: { visibility: 'none' }
      })

      // Dark (hidden by default)
      map.addLayer({
          id: 'dark',
          type: 'raster',
          source: 'dark',
          layout: { visibility: 'none' }
      })

      // Nautical (hidden by default)
      map.addLayer({
          id: 'nautical',
          type: 'raster',
          source: 'nautical',
          layout: { visibility: 'none' }
      })

      // 3. Add Mission Source
      map.addSource('mission', {
          type: 'geojson',
          data: {
              type: 'FeatureCollection',
              features: []
          }
      })
      
      // Add Trail Source
      map.addSource('trail', {
          type: 'geojson',
          data: {
              type: 'FeatureCollection',
              features: []
          }
      })

      // 4. Add Mission Layers (on top of map)
      // Trail Layer
      map.addLayer({
          id: 'trail-line',
          type: 'line',
          source: 'trail',
          layout: {
              'line-join': 'round',
              'line-cap': 'round'
          },
          paint: {
              'line-color': '#FF0000', // Red path
              'line-width': 3,
              'line-opacity': 0.8
          }
      })

      map.addLayer({
          id: 'mission-line',
          type: 'line',
          source: 'mission',
          filter: ['==', '$type', 'LineString'],
          layout: {
              'line-join': 'round',
              'line-cap': 'round'
          },
          paint: {
              'line-color': '#00E5FF',
              'line-width': 4
          }
      })
      
      map.addLayer({
          id: 'mission-points',
          type: 'circle',
          source: 'mission',
          filter: ['==', '$type', 'Point'],
          paint: {
              'circle-radius': 6,
              'circle-color': '#00E5FF',
              'circle-stroke-color': '#00E5FF',
              'circle-stroke-width': 2
          }
      })

      // Waypoint acceptance-radius circles
      map.addSource('wp-radius', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'wp-radius-fill',
        type: 'fill',
        source: 'wp-radius',
        paint: { 'fill-color': '#00E5FF', 'fill-opacity': 0.08 }
      })
      map.addLayer({
        id: 'wp-radius-stroke',
        type: 'line',
        source: 'wp-radius',
        paint: {
          'line-color': '#00E5FF',
          'line-width': 1.5,
          'line-dasharray': [6, 4],
          'line-opacity': 0.45
        }
      })

      // 5. Simulation overlay sources/layers (up to 6 profiles)
      for (let i = 0; i < 6; i++) {
        map.addSource(`sim-track-${i}`, {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] }
        })
        map.addLayer({
          id: `sim-track-line-${i}`,
          type: 'line',
          source: `sim-track-${i}`,
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: {
            'line-color': SIM_COLORS[i],
            'line-width': 3,
            'line-dasharray': [4, 3],
            'line-opacity': 0.85
          }
        })
      }
  })

  // Create Custom Boat Marker Element
  const el = document.createElement('div')
  el.className = 'boat-marker'
  el.innerHTML = `
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 2L2 22L12 18L22 22L12 2Z" fill="#ff0000" stroke="white" stroke-width="2"/>
    </svg>
  `

  boatMarker = new maplibregl.Marker({
    element: el,
    rotationAlignment: 'map'
  })
  .setLngLat([-0.3763, 39.4699])
  .addTo(map)
  
  // Click Handler for Planning
  map.on('click', (e) => {
      if (telemetry.mapPlanMode) {
          const { lng, lat } = e.lngLat
          telemetry.addWaypoint(lat, lng)
      }
  })

  // Disable follow mode when user manually drags/pans the map
  map.on('dragstart', () => {
      followVehicle.value = false
  })

  // Connect
  
  // Start trail update loop (throttle updates to 5Hz)
  trailInterval = setInterval(updateTrail, 200)
})

onUnmounted(() => {
    if (trailInterval) clearInterval(trailInterval)
  telemetry.connectWebSocket()
})

watch(currentThemeName, (val) => {
  if (!map || !map.getLayer('satellite') || !map.getLayer('osm')) return
  
  // Hide all tile layers
  map.setLayoutProperty('satellite', 'visibility', 'none')
  map.setLayoutProperty('osm', 'visibility', 'none')
  if (map.getLayer('dark')) map.setLayoutProperty('dark', 'visibility', 'none')
  if (map.getLayer('nautical')) map.setLayoutProperty('nautical', 'visibility', 'none')

  // For Windy views, keep map layers hidden (iframe overlays the map)
  if (val === 'wind' || val === 'radar') return

  if (val === 'satellite') {
    map.setLayoutProperty('satellite', 'visibility', 'visible')
  } else if (val === 'osm') {
    map.setLayoutProperty('osm', 'visibility', 'visible')
  } else if (val === 'dark') {
    if (map.getLayer('dark')) map.setLayoutProperty('dark', 'visibility', 'visible')
  } else if (val === 'nautical') {
    map.setLayoutProperty('osm', 'visibility', 'visible')
    if (map.getLayer('nautical')) map.setLayoutProperty('nautical', 'visibility', 'visible')
  }
})

// Watch for changes in telemetry to update marker
watch([lat, lon, () => telemetry.bestHeading], ([newLat, newLon, newHeading]) => {
  if (!map || !boatMarker) return
  if (newLat !== 0 && newLon !== 0) {
    boatMarker.setLngLat([newLon, newLat])
    if (followVehicle.value) {
      map.setCenter([newLon, newLat])
      if (Math.abs(map.getZoom() - FOLLOW_ZOOM) > 1) {
        map.setZoom(FOLLOW_ZOOM)
      }
    }
  }
  boatMarker.setRotation(newHeading)
})

// Watch for changes in waypoints to update map drawing
watch(missionWaypoints, (newPoints) => {
    if (!map || !map.getSource('mission')) return;
    
    // Create LineString feature
    const lineString = {
        type: 'Feature',
        geometry: {
            type: 'LineString',
            coordinates: newPoints.map(p => [p.lon, p.lat])
        }
    }
    
    // Create Points features
    const points = newPoints.map(p => ({
        type: 'Feature',
        geometry: {
            type: 'Point',
            coordinates: [p.lon, p.lat]
        }
    }))
    
    map.getSource('mission').setData({
        type: 'FeatureCollection',
        features: [lineString, ...points]
    })

    // Update acceptance-radius circles
    const radiusSrc = map.getSource('wp-radius')
    if (radiusSrc) {
      const circles = newPoints.map(wp => ({
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: geoCircle(wp.lon, wp.lat, wp.radius || 5)
        }
      }))
      radiusSrc.setData({ type: 'FeatureCollection', features: circles })
    }
}, { deep: true })

// Optimized Trail Update Function (Polling instead of Watcher)
const updateTrail = () => {
    if (!map || !map.getSource('trail')) return;
    
    // Access raw value to avoid some overhead
    const newHistory = pathHistory.value
    
    if (newHistory.length < 2) {
       map.getSource('trail').setData({
         type: 'FeatureCollection',
         features: []
       })
       return
    }

    const lineString = {
        type: 'Feature',
        geometry: {
            type: 'LineString',
            coordinates: newHistory.map(p => [p.lon, p.lat])
        }
    }
    
    map.getSource('trail').setData({
        type: 'FeatureCollection',
        features: [lineString]
    })
}

// --- Load Route from File ---
function loadRouteFromFile(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => {
    const text = ev.target.result
    const wps = []
    for (const line of text.trim().split('\n')) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#') || trimmed.toLowerCase().startsWith('lat')) continue
      const parts = trimmed.split(',').map(s => s.trim())
      if (parts.length < 2) continue
      wps.push({
        lat: parseFloat(parts[0]),
        lon: parseFloat(parts[1]),
        radius: parts.length > 2 ? parseFloat(parts[2]) : 5.0,
        speed: parts.length > 3 ? parseFloat(parts[3]) : 1.0,
      })
    }
    if (wps.length > 0) {
      telemetry.missionWaypoints = wps
      // Fly to the route
      if (map && wps.length >= 1) {
        followVehicle.value = false
        const bounds = new maplibregl.LngLatBounds()
        wps.forEach(wp => bounds.extend([wp.lon, wp.lat]))
        map.fitBounds(bounds, { padding: 60, maxZoom: 17 })
      }
    }
  }
  reader.readAsText(file)
  e.target.value = ''
}

// --- Save Route to File ---
function saveRouteToFile() {
  const wps = missionWaypoints.value
  if (!wps || wps.length === 0) return
  const header = '# lat,lon,radius,speed'
  const lines = wps.map(wp =>
    `${wp.lat.toFixed(7)},${wp.lon.toFixed(7)},${wp.radius || 5.0},${wp.speed || 1.0}`
  )
  const csv = [header, ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const now = new Date()
  const ts = now.toISOString().replace(/[:.]/g, '-').slice(0, 19)
  a.href = url
  a.download = `route_${ts}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// --- Simulation Overlay ---
function updateSimOverlay() {
  if (!map) return
  const results = simulationResults.value
  const visible = simulationOverlayVisible.value

  for (let i = 0; i < 6; i++) {
    const src = map.getSource(`sim-track-${i}`)
    if (!src) continue
    
    if (!visible || !results || i >= results.length) {
      src.setData({ type: 'FeatureCollection', features: [] })
      continue
    }
    
    const r = results[i]
    const coords = r.lat.map((lat, j) => [r.lon[j], lat])
    src.setData({
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: coords }
      }]
    })
  }
}

watch([simulationResults, simulationOverlayVisible], () => {
  updateSimOverlay()
}, { deep: true })
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  position: relative;
}

#map {
  width: 100%;
  height: 100%;
}

.map-controls {
  position: absolute;
  top: 20px;
  left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 10;
}

/* ── Unified button base ── */
.ctrl-btn {
  padding: 7px 16px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0,0,0,0.25);
  transition: opacity 0.15s, background 0.2s;
  text-align: center;
  color: white;
  background: #444;
}
.ctrl-btn:hover { opacity: 0.85; }

/* Plan mode toggle */
.plan-btn { background: #555; color: #eee; }
.plan-btn.active { background: #FFD700; color: #111; }

/* Layer toggle */
.layer-btn { background: rgba(50,50,50,0.85); color: #ddd; }

/* Route (load) */
.route-btn { background: #2ecc71; color: white; }

/* Save */
.save-btn { background: #3498db; color: white; }

/* Clear / danger */
.danger-btn { background: #e74c3c; color: white; }

/* Sim overlay */
.sim-btn { background: #333; color: #ccc; }
.sim-btn.active { background: #1f77b4; color: white; }

:deep(.boat-marker) {
  width: 40px;
  height: 40px;
  display: flex;
  justify-content: center;
  align-items: center;
  cursor: pointer;
}

.sim-legend {
  position: absolute;
  bottom: 60px;
  left: 20px;
  z-index: 10;
  background: rgba(30, 30, 30, 0.9);
  border: 1px solid #555;
  border-radius: 6px;
  padding: 8px 12px;
  min-width: 180px;
}
.sim-legend-title {
  color: #00E5FF;
  font-weight: bold;
  font-size: 12px;
  margin-bottom: 6px;
}
.sim-legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}
.sim-legend-line {
  display: inline-block;
  width: 24px;
  height: 0;
  border-bottom: 3px dashed;
  flex-shrink: 0;
}
.sim-legend-label {
  color: #ddd;
  font-size: 11px;
}

.follow-btn {
  position: absolute;
  bottom: 20px;
  left: 20px;
  z-index: 10;
  width: 36px;
  height: 36px;
  padding: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 6px;
  background: white;
  box-shadow: 0 2px 4px rgba(0,0,0,0.3);
  cursor: pointer;
  transition: background 0.2s;
}

.follow-btn.active {
  background: #e8f0fe;
  box-shadow: 0 2px 6px rgba(26,115,232,0.4);
}

.north-btn {
  position: absolute;
  bottom: 62px;
  left: 20px;
  z-index: 10;
  width: 36px;
  height: 36px;
  padding: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 6px;
  background: white;
  box-shadow: 0 2px 4px rgba(0,0,0,0.3);
  cursor: pointer;
  transition: background 0.2s;
}
.north-btn:hover {
  background: #f0f0f0;
}

/* ── Map Type Selector ── */
.map-type-wrapper {
  position: relative;
}
.map-menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: rgba(40, 40, 40, 0.95);
  border: 1px solid #555;
  border-radius: 6px;
  padding: 6px 0;
  min-width: 170px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  z-index: 20;
}
.map-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 14px;
  color: #ccc;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.map-menu-item:hover {
  background: rgba(255, 255, 255, 0.1);
}
.map-menu-item.selected {
  color: #00E5FF;
}
.map-menu-item input[type="radio"] {
  accent-color: #00E5FF;
  margin: 0;
}

/* ── Windy Overlay ── */
.windy-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 5;
  border: none;
}
</style>
