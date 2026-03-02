<template>
  <div class="map-container">
    <div id="map"></div>
    
    <div class="map-controls">
      <button 
        class="plan-btn"
        :class="{ active: isPlanMode }"
        @click="isPlanMode = !isPlanMode"
      >
        {{ isPlanMode ? 'EXIT PLAN MODE' : 'PLAN MISSION' }}
      </button>
      <button 
        class="layer-btn"
        @click="isSatellite = !isSatellite"
      >
        {{ isSatellite ? 'MAP VIEW' : 'SATELLITE' }}
      </button>
      <button 
        v-if="missionWaypoints.length > 0"
        class="clear-btn" 
        @click="telemetry.clearMission()"
      >
        CLEAR
      </button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useTelemetryStore } from '../stores/telemetry'
import { storeToRefs } from 'pinia'

const telemetry = useTelemetryStore()
const { lat, lon, heading, missionWaypoints, pathHistory } = storeToRefs(telemetry)

const isPlanMode = ref(false)
const isSatellite = ref(false)

let map = null
let boatMarker = null
let trailInterval = null

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
    center: [2.4, 39.5], // Default center (Mallorca roughly)
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

      // 2. Add Base Layers
      // Satellite (hidden by default)
      map.addLayer({
          id: 'satellite',
          type: 'raster',
          source: 'satellite',
          layout: { visibility: 'none' }
      })
      
      // OSM (visible by default)
      map.addLayer({
          id: 'osm',
          type: 'raster',
          source: 'osm',
          layout: { visibility: 'visible' }
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
          layout: {
              'line-join': 'round',
              'line-cap': 'round'
          },
          paint: {
              'line-color': '#FFA500', // Orange path
              'line-width': 4
          }
      })
      
      map.addLayer({
          id: 'mission-points',
          type: 'circle',
          source: 'mission',
          paint: {
              'circle-radius': 6,
              'circle-color': '#ffffff',
              'circle-stroke-color': '#FFA500',
              'circle-stroke-width': 2
          }
      })
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
  .setLngLat([2.4, 39.5])
  .addTo(map)
  
  // Click Handler for Planning
  map.on('click', (e) => {
      if (isPlanMode.value) {
          const { lng, lat } = e.lngLat
          telemetry.addWaypoint(lat, lng)
      }
  })

  // Connect
  
  // Start trail update loop (throttle updates to 5Hz)
  trailInterval = setInterval(updateTrail, 200)
})

onUnmounted(() => {
    if (trailInterval) clearInterval(trailInterval)
  telemetry.connectWebSocket()
})

watch(isSatellite, (val) => {
  if (!map || !map.getLayer('satellite') || !map.getLayer('osm')) return
  if (val) {
    map.setLayoutProperty('satellite', 'visibility', 'visible')
    map.setLayoutProperty('osm', 'visibility', 'none')
  } else {
    map.setLayoutProperty('satellite', 'visibility', 'none')
    map.setLayoutProperty('osm', 'visibility', 'visible')
  }
})

// Watch for changes in telemetry to update marker
watch([lat, lon, heading], ([newLat, newLon, newHeading]) => {
  if (!map || !boatMarker) return
  if (newLat !== 0 && newLon !== 0) {
    boatMarker.setLngLat([newLon, newLat])
  }
  const headingDegrees = newHeading * (180 / Math.PI)
  boatMarker.setRotation(headingDegrees)
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
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 100%; /* Fill parent instead of strict 100vh */
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
    gap: 10px;
    z-index: 10;
}

button {
    padding: 10px 20px;
    border: none;
    border-radius: 4px;
    background: white;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    font-weight: bold;
    cursor: pointer;
}

.plan-btn.active {
    background: #FFD700; /* Gold */
    color: black;
}

.clear-btn {
    background: #ff4444;
    color: white;
}

:deep(.boat-marker) {
  width: 40px;
  height: 40px;
  display: flex;
  justify-content: center;
  align-items: center;
  cursor: pointer;
}
</style>
