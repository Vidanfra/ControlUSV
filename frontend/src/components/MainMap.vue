<template>
  <div class="map-container">
    <div id="map"></div>

    <div
      v-if="mapContextMenu.visible"
      class="map-context-menu"
      :style="{ left: `${mapContextMenu.x}px`, top: `${mapContextMenu.y}px` }"
      @contextmenu.prevent
    >
      <button class="context-action" @click="startMeasurement">
        Measure from this point
      </button>
      <button
        v-if="measurementStart"
        class="context-action"
        @click="finishMeasurement"
      >
        Measure to this point
      </button>
      <button
        v-if="measurementStart"
        class="context-action danger"
        @click="clearMeasurement"
      >
        Remove measurement
      </button>
    </div>

    <div class="map-controls">
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
        v-if="telemetry.simulationResults.length > 0"
        class="ctrl-btn sim-btn"
        :class="{ active: telemetry.simulationOverlayVisible }"
        @click="telemetry.toggleSimOverlay()"
      >
        {{ telemetry.simulationOverlayVisible ? 'HIDE SIM' : 'SHOW SIM' }}
      </button>
      <button class="ctrl-btn cache-btn" :class="{ active: showCachePanel }" @click="toggleCachePanel">
        CACHE ▾
      </button>
    </div>

    <!-- Offline tile cache panel -->
    <div v-if="showCachePanel" class="cache-panel">
      <div class="cache-row cache-title">
        <span>Offline Map Cache</span>
        <button class="cache-close" @click="showCachePanel = false">&times;</button>
      </div>
      <div class="cache-row cache-info">
        <span>{{ cachedTileCount }} tiles stored ({{ cachedSizeMB }} MB)</span>
      </div>

      <template v-if="cacheableTheme">
        <div class="cache-row">
          <label class="cache-label">Extra zoom levels</label>
          <input
            type="number"
            class="cache-input"
            min="0"
            max="8"
            v-model.number="dlZoomExtra"
            :disabled="dlBusy"
            @change="updateDownloadEstimate"
          />
        </div>
        <div class="cache-row cache-hint">
          Downloads the current view (~{{ dlEstimate }} tiles).
        </div>

        <div v-if="dlBusy" class="cache-row cache-progress">
          <div class="cache-progbar">
            <div
              class="cache-progfill"
              :style="{ width: dlProgress.total ? (dlProgress.done / dlProgress.total * 100) + '%' : '0%' }"
            ></div>
          </div>
          <span class="cache-progtext">{{ dlProgress.done }}/{{ dlProgress.total }}</span>
        </div>

        <div class="cache-row cache-actions">
          <button
            v-if="!dlBusy"
            class="cache-action dl"
            @mouseenter="updateDownloadEstimate"
            @click="startPredownload"
          >
            Download this area
          </button>
          <button v-else class="cache-action cancel" @click="cancelPredownload">
            Cancel
          </button>
          <button class="cache-action clear" :disabled="dlBusy" @click="onClearCache">
            Clear cache
          </button>
        </div>
      </template>
      <template v-else>
        <div class="cache-row cache-hint">
          The current layer (Windy) can't be cached. Switch to a map layer to download tiles.
        </div>
        <div class="cache-row cache-actions">
          <button class="cache-action clear" :disabled="dlBusy" @click="onClearCache">
            Clear cache
          </button>
        </div>
      </template>
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
import { generateLawnmower, polygonCentroid, angleHandlePosition, spacingHandlePosition } from '../composables/useSurveyGenerator.js'
import {
  tileSourceUrl,
  clearTileCache,
  getCacheStats,
  countPredownloadTiles,
  predownloadTiles,
} from '../composables/useMapTileCache.js'

const telemetry = useTelemetryStore()
const { lat, lon, missionWaypoints, missionItems, pathHistory, gnssCrpHistory, simulationResults, simulationOverlayVisible, stationWaypoint, stationRadius, stationReachingRadius, homeWaypoint, simStartWaypoint } = storeToRefs(telemetry)

// Survey drag-marker state
let polyVertexMarkers = []   // maplibregl.Marker[] — one per polygon vertex
let angleHandleMarker = null // maplibregl.Marker — rotate line-angle
let spacingHandleMarker = null // maplibregl.Marker — adjust line-spacing
let lastActiveSurveyId = null // track which survey had markers

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

// Which backend tile providers make up each selectable theme
// (nautical = osm base + seamark overlay). Windy themes are not cacheable.
const THEME_PROVIDERS = {
  satellite: ['satellite'],
  osm: ['osm'],
  dark: ['dark'],
  nautical: ['osm', 'nautical'],
}

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

// --- Offline tile cache management -----------------------------------------
const showCachePanel = ref(false)
const cachedTileCount = ref(0)
const cachedTileBytes = ref(0)
const dlZoomExtra = ref(3)          // download current zoom .. current+extra
const dlBusy = ref(false)
const dlProgress = ref({ done: 0, total: 0, downloaded: 0, skipped: 0, failed: 0 })
const dlEstimate = ref(0)
let dlAbort = null

const cachedSizeMB = computed(() => (cachedTileBytes.value / (1024 * 1024)).toFixed(1))

async function refreshCacheCount() {
  const stats = await getCacheStats()
  cachedTileCount.value = stats.count
  cachedTileBytes.value = stats.bytes
}

// Themes that consist of cacheable raster tiles (Windy views cannot be cached).
const cacheableTheme = computed(() => !!THEME_PROVIDERS[currentThemeName.value])

function currentDownloadPlan() {
  if (!map || !cacheableTheme.value) return null
  const b = map.getBounds()
  const bounds = {
    west: b.getWest(),
    south: b.getSouth(),
    east: b.getEast(),
    north: b.getNorth(),
  }
  const minZoom = Math.max(0, Math.round(map.getZoom()))
  const maxZoom = Math.min(19, minZoom + Math.max(0, Math.round(dlZoomExtra.value)))
  const providers = THEME_PROVIDERS[currentThemeName.value]
  return { bounds, minZoom, maxZoom, providers }
}

function updateDownloadEstimate() {
  const plan = currentDownloadPlan()
  dlEstimate.value = plan
    ? countPredownloadTiles(plan.bounds, plan.minZoom, plan.maxZoom, plan.providers.length)
    : 0
}

async function toggleCachePanel() {
  showCachePanel.value = !showCachePanel.value
  showMapMenu.value = false
  if (showCachePanel.value) {
    await refreshCacheCount()
    updateDownloadEstimate()
  }
}

async function startPredownload() {
  const plan = currentDownloadPlan()
  if (!plan || dlBusy.value) return
  dlBusy.value = true
  dlAbort = new AbortController()
  dlProgress.value = { done: 0, total: 0, downloaded: 0, skipped: 0, failed: 0 }
  try {
    await predownloadTiles({
      bounds: plan.bounds,
      minZoom: plan.minZoom,
      maxZoom: plan.maxZoom,
      providers: plan.providers,
      signal: dlAbort.signal,
      onProgress: (p) => { dlProgress.value = p },
    })
  } finally {
    dlBusy.value = false
    dlAbort = null
    await refreshCacheCount()
  }
}

function cancelPredownload() {
  if (dlAbort) dlAbort.abort()
}

async function onClearCache() {
  if (dlBusy.value) return
  if (!window.confirm('Delete all cached offline map tiles?')) return
  await clearTileCache()
  await refreshCacheCount()
}

const followVehicle = ref(false)
const FOLLOW_ZOOM = 16.5  // ~200m north-south view
const SIM_COLORS = ['#e6194b', '#3cb44b', '#4363d8', '#f032e6', '#42d4f4', '#fabed4']
const measurementStart = ref(null)
const measurementEnd = ref(null)
const mapContextMenu = ref({ visible: false, x: 0, y: 0, lng: 0, lat: 0 })

const measurementDistance = computed(() => {
  if (!measurementStart.value || !measurementEnd.value) return null
  return new maplibregl.LngLat(
    measurementStart.value.lng,
    measurementStart.value.lat
  ).distanceTo(measurementEnd.value)
})

let map = null
let boatMarker = null
let trailInterval = null

function formatDistance(meters) {
  if (meters < 0.01) return `${(meters * 1000).toFixed(2)} mm`
  if (meters < 1) return `${(meters * 100).toFixed(2)} cm`
  if (meters < 1000) return `${meters.toFixed(meters < 10 ? 2 : 1)} m`
  return `${(meters / 1000).toFixed(2)} km`
}

function updateMeasurementLayer() {
  const source = map?.getSource('measurement')
  if (!source) return

  const points = [measurementStart.value, measurementEnd.value].filter(Boolean)
  const features = points.map(point => ({
    type: 'Feature',
    properties: { role: 'endpoint' },
    geometry: { type: 'Point', coordinates: [point.lng, point.lat] }
  }))
  if (points.length === 2) {
    const midpoint = [
      (points[0].lng + points[1].lng) / 2,
      (points[0].lat + points[1].lat) / 2
    ]
    features.unshift({
      type: 'Feature',
      properties: { role: 'line' },
      geometry: {
        type: 'LineString',
        coordinates: points.map(point => [point.lng, point.lat])
      }
    })
    features.push({
      type: 'Feature',
      properties: {
        role: 'label',
        label: formatDistance(measurementDistance.value)
      },
      geometry: { type: 'Point', coordinates: midpoint }
    })
  }
  source.setData({ type: 'FeatureCollection', features })
}

function startMeasurement() {
  const { lng, lat } = mapContextMenu.value
  measurementStart.value = { lng, lat }
  measurementEnd.value = null
  mapContextMenu.value.visible = false
  updateMeasurementLayer()
}

function finishMeasurement() {
  const { lng, lat } = mapContextMenu.value
  measurementEnd.value = { lng, lat }
  mapContextMenu.value.visible = false
  updateMeasurementLayer()
}

function clearMeasurement() {
  measurementStart.value = null
  measurementEnd.value = null
  mapContextMenu.value.visible = false
  updateMeasurementLayer()
}

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
    center: simStartWaypoint.value
      ? [simStartWaypoint.value.lon, simStartWaypoint.value.lat]
      : [telemetry.simDefaultLon, telemetry.simDefaultLat], // Default center
    zoom: 15,
    maxZoom: 29
  })

  map.addControl(new maplibregl.ScaleControl({ maxWidth: 140, unit: 'metric' }), 'bottom-right')
  
  // Add sources and layers once map is loaded
  map.on('load', () => {
      // 1. Add Base Sources
      map.addSource('osm', {
          type: 'raster',
          tiles: [tileSourceUrl('osm')],
          tileSize: 256,
          maxzoom: 19,
          attribution: '&copy; OpenStreetMap Contributors'
      })
      
      map.addSource('satellite', {
          type: 'raster',
          tiles: [tileSourceUrl('satellite')],
          tileSize: 256,
          maxzoom: 19,
          attribution: 'Tiles &copy; Esri'
      })

      map.addSource('dark', {
          type: 'raster',
          tiles: [tileSourceUrl('dark')],
          tileSize: 256,
          maxzoom: 19,
          attribution: '&copy; CARTO'
      })

      map.addSource('nautical', {
          type: 'raster',
          tiles: [tileSourceUrl('nautical')],
          tileSize: 256,
          maxzoom: 19,
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

      map.addSource('measurement', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'measurement-line',
        type: 'line',
        source: 'measurement',
        filter: ['==', '$type', 'LineString'],
        paint: {
          'line-color': '#00e5ff',
          'line-width': 3,
          'line-dasharray': [3, 2]
        }
      })
      map.addLayer({
        id: 'measurement-points',
        type: 'circle',
        source: 'measurement',
        filter: ['==', ['get', 'role'], 'endpoint'],
        paint: {
          'circle-radius': 5,
          'circle-color': '#00e5ff',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2
        }
      })
      map.addLayer({
        id: 'measurement-label',
        type: 'symbol',
        source: 'measurement',
        filter: ['==', ['get', 'role'], 'label'],
        layout: {
          'text-field': ['get', 'label'],
          'text-size': 13,
          'text-anchor': 'bottom',
          'text-offset': [0, -0.6],
          'text-allow-overlap': true
        },
        paint: {
          'text-color': '#ffffff',
          'text-halo-color': '#111111',
          'text-halo-width': 2
        }
      })

          map.addSource('gnss-crp-fixes', {
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
              'line-color': '#e60000',
              'line-width': 3,
              'line-opacity': 0.8
          }
      })

          map.addLayer({
            id: 'gnss-crp-points',
            type: 'circle',
            source: 'gnss-crp-fixes',
            paint: {
              'circle-radius': 5,
              'circle-color': '#ff3030',
              'circle-opacity': 0.9,
              'circle-stroke-color': '#ffffff',
              'circle-stroke-width': 1
            }
          })

          updateGnssFixes()

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
              'line-color': '#FFA500',
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
              'circle-color': '#FFA500',
              'circle-stroke-color': '#FFA500',
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
        paint: { 'fill-color': '#FFA500', 'fill-opacity': 0.06 }
      })
      map.addLayer({
        id: 'wp-radius-stroke',
        type: 'line',
        source: 'wp-radius',
        paint: {
          'line-color': '#FFA500',
          'line-width': 1.5,
          'line-dasharray': [6, 4],
          'line-opacity': 0.45
        }
      })

      // Station keeping circles (outer station radius + inner reaching radius + center marker)
      map.addSource('station-circle', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'station-circle-fill',
        type: 'fill',
        source: 'station-circle',
        paint: { 'fill-color': '#FFA500', 'fill-opacity': 0.06 }
      })
      map.addLayer({
        id: 'station-circle-stroke',
        type: 'line',
        source: 'station-circle',
        paint: {
          'line-color': '#FFA500',
          'line-width': 2,
          'line-dasharray': [4, 3],
          'line-opacity': 0.7
        }
      })
      map.addSource('station-reaching-circle', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'station-reaching-fill',
        type: 'fill',
        source: 'station-reaching-circle',
        paint: { 'fill-color': '#FFA500', 'fill-opacity': 0.12 }
      })
      map.addLayer({
        id: 'station-reaching-stroke',
        type: 'line',
        source: 'station-reaching-circle',
        paint: {
          'line-color': '#FFA500',
          'line-width': 2,
          'line-opacity': 0.8
        }
      })
      map.addSource('station-center', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'station-center-dot',
        type: 'circle',
        source: 'station-center',
        paint: {
          'circle-radius': 6,
          'circle-color': '#FFA500',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff'
        }
      })

      // Home waypoint marker
      map.addSource('home-wp', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'home-wp-dot',
        type: 'circle',
        source: 'home-wp',
        paint: {
          'circle-radius': 8,
          'circle-color': '#1b5e20',
          'circle-stroke-width': 3,
          'circle-stroke-color': '#a5d6a7'
        }
      })

      // SIM Start waypoint marker
      map.addSource('sim-start-wp', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'sim-start-wp-dot',
        type: 'circle',
        source: 'sim-start-wp',
        paint: {
          'circle-radius': 8,
          'circle-color': '#FFD700', // Gold color for SIM
          'circle-stroke-width': 2,
          'circle-stroke-color': '#000'
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

  // ── Survey map sources & layers ───────────────────────────────────────────
  map.on('load', () => {
    // Polygon fill + stroke
    map.addSource('survey-polygon', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    })
    map.addLayer({
      id: 'survey-polygon-fill',
      type: 'fill',
      source: 'survey-polygon',
      paint: { 'fill-color': '#22bb66', 'fill-opacity': 0.18 }
    })
    map.addLayer({
      id: 'survey-polygon-stroke',
      type: 'line',
      source: 'survey-polygon',
      paint: { 'line-color': '#22bb66', 'line-width': 2, 'line-dasharray': [5, 3] }
    })

    // Lawnmower pattern lines
    map.addSource('survey-pattern', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    })
    map.addLayer({
      id: 'survey-pattern-lines',
      type: 'line',
      source: 'survey-pattern',
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': '#FFD700', 'line-width': 1.5, 'line-opacity': 0.9 }
    })

    // All survey polygon outlines (non-active)
    map.addSource('survey-all-polygons', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    })
    map.addLayer({
      id: 'survey-all-polygons-fill',
      type: 'fill',
      source: 'survey-all-polygons',
      paint: { 'fill-color': '#22bb66', 'fill-opacity': 0.08 }
    })
    map.addLayer({
      id: 'survey-all-polygons-stroke',
      type: 'line',
      source: 'survey-all-polygons',
      paint: { 'line-color': '#22bb66', 'line-width': 1.5, 'line-dasharray': [4, 3], 'line-opacity': 0.6 }
    })

    // All survey patterns (non-active, dimmed)
    map.addSource('survey-all-patterns', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    })
    map.addLayer({
      id: 'survey-all-pattern-lines',
      type: 'line',
      source: 'survey-all-patterns',
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': '#FFD700', 'line-width': 1, 'line-opacity': 0.45 }
    })

    // Entry/exit waypoints of active pattern
    map.addSource('survey-entry', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] }
    })
    map.addLayer({
      id: 'survey-entry-points',
      type: 'circle',
      source: 'survey-entry',
      paint: {
        'circle-radius': 5,
        'circle-color': '#FFD700',
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#000',
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
  .setLngLat([-0.3763, 39.4699])
  .addTo(map)
  
  // Click Handler for Planning / Sim Pick / Station Pick / Home Pick / Survey Draw
  map.on('click', (e) => {
      mapContextMenu.value.visible = false
      if (telemetry.surveyDrawMode && telemetry.activeSurveyId !== null) {
          // Add vertex to active survey polygon
          const { lng, lat } = e.lngLat
          telemetry.addSurveyVertex(telemetry.activeSurveyId, lat, lng)
      } else if (telemetry.activeMissionWpId !== null) {
          // Place a mission waypoint (including mission_start)
          const { lng, lat } = e.lngLat
          telemetry.updateMissionItem(telemetry.activeMissionWpId, { lat, lon: lng })
          telemetry.activeMissionWpId = null
      } else if (telemetry.simPickMode) {
          const { lng, lat } = e.lngLat
          telemetry.setSimStartWp(lat, lng)
          telemetry.simPickMode = false
      } else if (telemetry.stationPickMode) {
          const { lng, lat } = e.lngLat
          telemetry.setStation(lat, lng, telemetry.stationReachingRadius, telemetry.stationRadius)
          telemetry.stationPickMode = false
      } else if (telemetry.homePickMode) {
          const { lng, lat } = e.lngLat
          telemetry.setHomeWp(lat, lng)
          telemetry.homePickMode = false
      } else if (telemetry.mapPlanMode) {
          const { lng, lat } = e.lngLat
          telemetry.addWaypoint(lat, lng)
      }
  })

  map.on('contextmenu', (e) => {
      e.preventDefault()
      const menuWidth = 210
      const menuHeight = measurementStart.value ? 120 : 42
      mapContextMenu.value = {
        visible: true,
        x: Math.max(5, Math.min(e.point.x, map.getContainer().clientWidth - menuWidth)),
        y: Math.max(5, Math.min(e.point.y, map.getContainer().clientHeight - menuHeight)),
        lng: e.lngLat.lng,
        lat: e.lngLat.lat
      }
  })

  // Double-click closes the active polygon
  map.on('dblclick', (e) => {
      if (telemetry.surveyDrawMode && telemetry.activeSurveyId !== null) {
          e.preventDefault()
          telemetry.surveyDrawMode = false
      }
  })

  // Disable follow mode when user manually drags/pans the map
  map.on('dragstart', () => {
      followVehicle.value = false
  })

  // Start trail update loop (throttle updates to 5Hz)
  trailInterval = setInterval(updateTrail, 200)
})

onUnmounted(() => {
    if (trailInterval) clearInterval(trailInterval)
    clearSurveyHandleMarkers()
  if (map) map.remove()
  map = null
})

// ── Survey draw cursor ────────────────────────────────────────────────────────
watch(() => telemetry.surveyDrawMode, (drawing) => {
  if (!map) return
  map.getCanvas().style.cursor = drawing ? 'crosshair' : ''
})

watch(() => telemetry.activeMissionWpId, (id) => {
  if (!map) return
  map.getCanvas().style.cursor = id !== null ? 'crosshair' : ''
})

// ── Survey layer update ───────────────────────────────────────────────────────
function buildPatternFeatures(item) {
  if (!item || item.polygon.length < 3) return []
  const pts = generateLawnmower(
    item.polygon, item.lineAngle, item.lineSpacing, item.lineExtension, item.startWP
  )
  if (pts.length < 2) return []
  const lines = []
  for (let i = 0; i + 1 < pts.length; i += 2) {
    lines.push({
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: [[pts[i].lon, pts[i].lat], [pts[i+1].lon, pts[i+1].lat]]
      }
    })
  }
  return lines
}

function buildPolyFeature(item) {
  if (!item || item.polygon.length < 2) return null
  const coords = item.polygon.map(p => [p.lon, p.lat])
  if (item.polygon.length >= 3) coords.push(coords[0]) // close ring
  return {
    type: 'Feature',
    geometry: { type: item.polygon.length >= 3 ? 'Polygon' : 'LineString',
      coordinates: item.polygon.length >= 3 ? [coords] : coords }
  }
}

function updateSurveyLayers() {
  if (!map || !map.getSource('survey-polygon')) return
  const items = telemetry.missionItems
  const surveys = items.filter(i => i.type === 'survey')
  const activeSurvey = surveys.find(i => i.id === telemetry.activeSurveyId) || null

  // Active polygon and pattern
  if (activeSurvey) {
    const polyFeat = buildPolyFeature(activeSurvey)
    map.getSource('survey-polygon').setData({
      type: 'FeatureCollection',
      features: polyFeat ? [polyFeat] : []
    })
    const patternFeats = buildPatternFeatures(activeSurvey)
    map.getSource('survey-pattern').setData({ type: 'FeatureCollection', features: patternFeats })

    // Entry/exit points
    const pts = activeSurvey.polygon.length >= 3
      ? generateLawnmower(activeSurvey.polygon, activeSurvey.lineAngle, activeSurvey.lineSpacing, activeSurvey.lineExtension, activeSurvey.startWP)
      : []
    const entryFeats = []
    if (pts.length > 0) {
      entryFeats.push({ type:'Feature', geometry:{ type:'Point', coordinates:[pts[0].lon, pts[0].lat] } })
      entryFeats.push({ type:'Feature', geometry:{ type:'Point', coordinates:[pts[pts.length-1].lon, pts[pts.length-1].lat] } })
    }
    map.getSource('survey-entry').setData({ type: 'FeatureCollection', features: entryFeats })
  } else {
    const empty = { type: 'FeatureCollection', features: [] }
    map.getSource('survey-polygon').setData(empty)
    map.getSource('survey-pattern').setData(empty)
    map.getSource('survey-entry').setData(empty)
  }

  // All other surveys (dim overlay)
  const otherSurveys = surveys.filter(i => i.id !== telemetry.activeSurveyId)
  const allPolyFeats = otherSurveys.map(buildPolyFeature).filter(Boolean)
  const allPatFeats  = otherSurveys.flatMap(buildPatternFeatures)
  map.getSource('survey-all-polygons').setData({ type:'FeatureCollection', features: allPolyFeats })
  map.getSource('survey-all-patterns').setData({ type:'FeatureCollection', features: allPatFeats })
}

// ── Survey vertex + handle drag markers ──────────────────────────────────────
function createVertexMarkerEl() {
  const el = document.createElement('div')
  el.style.cssText = 'width:12px;height:12px;background:#22bb66;border:2px solid #fff;border-radius:50%;cursor:grab;'
  return el
}
function createAngleMarkerEl() {
  const el = document.createElement('div')
  el.style.cssText = 'width:14px;height:14px;background:#FF9800;border:2px solid #fff;transform:rotate(45deg);cursor:grab;box-shadow:0 0 4px rgba(0,0,0,0.6);'
  return el
}
function createSpacingMarkerEl() {
  const el = document.createElement('div')
  el.style.cssText = 'width:14px;height:10px;background:#e040fb;border:2px solid #fff;border-radius:3px;cursor:ns-resize;box-shadow:0 0 4px rgba(0,0,0,0.6);'
  return el
}

function clearSurveyHandleMarkers() {
  polyVertexMarkers.forEach(m => m.remove())
  polyVertexMarkers = []
  if (angleHandleMarker)   { angleHandleMarker.remove();   angleHandleMarker = null }
  if (spacingHandleMarker) { spacingHandleMarker.remove(); spacingHandleMarker = null }
  lastActiveSurveyId = null
}

function syncSurveyHandleMarkers() {
  if (!map) return
  const id = telemetry.activeSurveyId
  const item = id !== null ? telemetry.missionItems.find(i => i.id === id) : null

  // If no active survey or draw mode (just adding verts), only show vertex markers
  if (!item) {
    clearSurveyHandleMarkers()
    return
  }

  // Rebuild vertex markers if survey changed or count changed
  const poly = item.polygon
  if (lastActiveSurveyId !== id || polyVertexMarkers.length !== poly.length) {
    polyVertexMarkers.forEach(m => m.remove())
    polyVertexMarkers = []
    poly.forEach((pt, i) => {
      const m = new maplibregl.Marker({ element: createVertexMarkerEl(), draggable: true })
        .setLngLat([pt.lon, pt.lat])
        .addTo(map)
      m.on('drag', () => {
        const ll = m.getLngLat()
        telemetry.updateSurveyVertex(id, i, ll.lat, ll.lng)
      })
      polyVertexMarkers.push(m)
    })
    lastActiveSurveyId = id
  } else {
    // Just update positions
    poly.forEach((pt, i) => {
      if (polyVertexMarkers[i]) polyVertexMarkers[i].setLngLat([pt.lon, pt.lat])
    })
  }

  // Angle handle (only if polygon closed)
  if (poly.length >= 3) {
    const aPos = angleHandlePosition(poly, item.lineAngle)
    if (!angleHandleMarker) {
      angleHandleMarker = new maplibregl.Marker({ element: createAngleMarkerEl(), draggable: true })
        .setLngLat([aPos.lon, aPos.lat])
        .addTo(map)
      angleHandleMarker.on('drag', () => {
        const c = polygonCentroid(item.polygon)
        const ll = angleHandleMarker.getLngLat()
        const R2D = 180 / Math.PI
        const dE = (ll.lng - c.lon) * Math.cos(c.lat * Math.PI / 180) * 111320
        const dN = (ll.lat - c.lat) * 111320
        const angle = Math.atan2(dE, dN) * R2D
        telemetry.updateMissionItem(id, { lineAngle: Math.round(angle) })
      })
    } else {
      angleHandleMarker.setLngLat([aPos.lon, aPos.lat])
    }

    // Spacing handle
    const sPos = spacingHandlePosition(poly, item.lineAngle, item.lineSpacing, item.lineExtension, item.startWP)
    if (!spacingHandleMarker) {
      spacingHandleMarker = new maplibregl.Marker({ element: createSpacingMarkerEl(), draggable: true })
        .setLngLat([sPos.lon, sPos.lat])
        .addTo(map)
      spacingHandleMarker.on('drag', () => {
        const c = polygonCentroid(item.polygon)
        const ll = spacingHandleMarker.getLngLat()
        const bearRad = item.lineAngle * Math.PI / 180
        // lineAngle = bearing from North; perpendicular direction = bearing + 90°
        // perpDist = |dE * cos(bearing) - dN * sin(bearing)|
        const dE = (ll.lng - c.lon) * Math.cos(c.lat * Math.PI / 180) * 111320
        const dN = (ll.lat - c.lat) * 111320
        const perpDist = Math.abs(Math.cos(bearRad) * dE - Math.sin(bearRad) * dN)
        const newSpacing = Math.max(5, Math.round(perpDist * 2))
        telemetry.updateMissionItem(id, { lineSpacing: newSpacing })
      })
    } else {
      spacingHandleMarker.setLngLat([sPos.lon, sPos.lat])
    }
  } else {
    if (angleHandleMarker)   { angleHandleMarker.remove();   angleHandleMarker = null }
    if (spacingHandleMarker) { spacingHandleMarker.remove(); spacingHandleMarker = null }
  }
}

// Watch missionItems for survey layer updates
watch(missionItems, () => {
  updateSurveyLayers()
  syncSurveyHandleMarkers()
}, { deep: true })

watch(() => telemetry.activeSurveyId, () => {
  updateSurveyLayers()
  syncSurveyHandleMarkers()
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
// When follow button is activated, zoom in once
watch(followVehicle, (newVal) => {
  if (newVal && map && lat.value && lon.value && lat.value !== 0 && lon.value !== 0) {
    // User just pressed follow - zoom and center once
    map.easeTo({
      center: [lon.value, lat.value],
      zoom: FOLLOW_ZOOM,
      duration: 500
    })
  }
})

// Track vehicle position and center map while following (zoom only changed via follow watch)
watch([lat, lon, () => telemetry.bestHeading], ([newLat, newLon, newHeading]) => {
  if (!map || !boatMarker) return
  if (newLat !== 0 && newLon !== 0) {
    boatMarker.setLngLat([newLon, newLat])
    if (followVehicle.value) {
      // Only center map - preserve zoom level set by user or initial follow activation
      map.setCenter([newLon, newLat])
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

// Watch station waypoint/radii to update map circles (outer + inner + center)
watch([stationWaypoint, stationRadius, stationReachingRadius], () => {
  if (!map) return
  const wp = stationWaypoint.value
  const rOuter = stationRadius.value
  const rInner = stationReachingRadius.value
  const outerSrc = map.getSource('station-circle')
  const innerSrc = map.getSource('station-reaching-circle')
  const centerSrc = map.getSource('station-center')
  if (!outerSrc || !innerSrc || !centerSrc) return

  const empty = { type: 'FeatureCollection', features: [] }
  if (!wp) {
    outerSrc.setData(empty)
    innerSrc.setData(empty)
    centerSrc.setData(empty)
    return
  }

  outerSrc.setData({
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: geoCircle(wp.lon, wp.lat, rOuter) } }]
  })
  innerSrc.setData({
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: geoCircle(wp.lon, wp.lat, rInner) } }]
  })
  centerSrc.setData({
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [wp.lon, wp.lat] } }]
  })
}, { deep: true })

// Watch home waypoint to update map marker
watch(homeWaypoint, (hw) => {
  if (!map) return
  const src = map.getSource('home-wp')
  if (!src) return
  if (!hw) {
    src.setData({ type: 'FeatureCollection', features: [] })
    return
  }
  src.setData({
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [hw.lon, hw.lat] } }]
  })
}, { deep: true })

// Watch SIM Start waypoint to update map marker
watch(simStartWaypoint, (sw) => {
  if (!map) return
  const src = map.getSource('sim-start-wp')
  if (!src) return
  if (!sw) {
    src.setData({ type: 'FeatureCollection', features: [] })
    return
  }
  src.setData({
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [sw.lon, sw.lat] } }]
  })
}, { deep: true, immediate: true })
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

const updateGnssFixes = () => {
  const source = map?.getSource('gnss-crp-fixes')
  if (!source) return

  const features = gnssCrpHistory.value
    .filter(point => point.lat !== 0 && point.lon !== 0)
    .slice(-10)
    .map((point, index, points) => ({
      type: 'Feature',
      properties: { sequence: index + 1, latest: index === points.length - 1 },
      geometry: { type: 'Point', coordinates: [point.lon, point.lat] }
    }))

  source.setData({ type: 'FeatureCollection', features })
}

watch(gnssCrpHistory, updateGnssFixes, { deep: true })

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

.map-context-menu {
  position: absolute;
  z-index: 2000;
  width: 200px;
  padding: 5px;
  background: rgba(35, 35, 35, 0.97);
  border: 1px solid #666;
  border-radius: 6px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.5);
}

.context-action {
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: #eee;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.context-action:hover {
  background: rgba(255, 255, 255, 0.12);
}

.context-action.danger {
  color: #ff7770;
}

:deep(.maplibregl-ctrl-scale) {
  border-color: #222;
  background: rgba(255, 255, 255, 0.88);
  color: #111;
  font-size: 11px;
}

.map-controls {
  position: absolute;
  top: 20px;
  left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 1010;
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
.danger-btn { background: #e53935; color: white; }

/* Sim overlay */
.sim-btn { background: #333; color: #ccc; }
.sim-btn.active { background: #1f77b4; color: white; }

/* Offline tile cache */
.cache-btn { background: rgba(50,50,50,0.85); color: #ddd; }
.cache-btn.active { background: #2ecc71; color: #fff; }

.cache-panel {
  position: absolute;
  top: 20px;
  left: 130px;
  width: 240px;
  background: rgba(40, 40, 40, 0.96);
  border: 1px solid #555;
  border-radius: 8px;
  padding: 10px 12px;
  z-index: 1015;
  box-shadow: 0 4px 14px rgba(0,0,0,0.45);
  color: #ddd;
  font-size: 12px;
}
.cache-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.cache-row:last-child { margin-bottom: 0; }
.cache-title {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: #fff;
  font-size: 12px;
}
.cache-close {
  background: none;
  border: none;
  color: #bbb;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}
.cache-close:hover { color: #fff; }
.cache-info { color: #9ad; }
.cache-hint {
  color: #999;
  font-size: 11px;
  line-height: 1.35;
  display: block;
}
.cache-label { color: #ccc; }
.cache-input {
  width: 54px;
  padding: 3px 6px;
  background: #2a2a2a;
  border: 1px solid #555;
  border-radius: 4px;
  color: #eee;
  font-size: 12px;
  text-align: center;
}
.cache-progress { gap: 8px; }
.cache-progbar {
  flex: 1;
  height: 8px;
  background: #333;
  border-radius: 4px;
  overflow: hidden;
}
.cache-progfill {
  height: 100%;
  background: #2ecc71;
  transition: width 0.15s;
}
.cache-progtext {
  font-family: monospace;
  font-size: 11px;
  color: #bbb;
  min-width: 64px;
  text-align: right;
}
.cache-actions { gap: 8px; }
.cache-action {
  flex: 1;
  padding: 6px 8px;
  border: none;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.cache-action:hover { opacity: 0.85; }
.cache-action:disabled { opacity: 0.4; cursor: not-allowed; }
.cache-action.dl { background: #2ecc71; color: #fff; }
.cache-action.cancel { background: #e08a00; color: #fff; }
.cache-action.clear { background: #e53935; color: #fff; }

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
  color: #FFA500;
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
  color: #FFA500;
}
.map-menu-item input[type="radio"] {
  accent-color: #FFA500;
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
