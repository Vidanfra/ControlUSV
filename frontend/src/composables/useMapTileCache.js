// Offline map-tile caching (server-side, disk-backed).
//
// Tile requests are routed through the backend proxy endpoint
// `/tiles/{provider}/{z}/{x}/{y}`. The server stores every fetched tile on
// disk, so the offline cache is persistent across browser reloads AND server
// restarts, and is shared by every connected client device. When there is no
// internet, previously cached tiles are still served from the server's disk.
//
// The backend is reached the same way as the rest of the REST API in this app
// (host:8000), which works both in dev (Vite on :5173) and in the production
// build served by FastAPI.

function backendBase() {
  return `${window.location.protocol}//${window.location.hostname}:8000`
}

/**
 * MapLibre raster tile URL template for a provider, pointing at the backend
 * disk-cache proxy. Providers: 'osm', 'satellite', 'dark', 'nautical'.
 */
export function tileSourceUrl(provider) {
  return `${backendBase()}/tiles/${provider}/{z}/{x}/{y}`
}

/** Delete every cached tile from the server's disk. Returns count removed. */
export async function clearTileCache() {
  try {
    const resp = await fetch(`${backendBase()}/tiles/clear`, { method: 'POST' })
    const j = await resp.json()
    return j.removed || 0
  } catch {
    return 0
  }
}

/** Number of tiles stored on the server and their total size in bytes. */
export async function getCacheStats() {
  try {
    const resp = await fetch(`${backendBase()}/tiles/stats`)
    if (!resp.ok) return { count: 0, bytes: 0 }
    const j = await resp.json()
    return { count: j.count || 0, bytes: j.bytes || 0 }
  } catch {
    return { count: 0, bytes: 0 }
  }
}

// --- Web Mercator tile math -------------------------------------------------

function lngToTileX(lng, z) {
  return Math.floor(((lng + 180) / 360) * Math.pow(2, z))
}

function latToTileY(lat, z) {
  const rad = (lat * Math.PI) / 180
  return Math.floor(
    ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * Math.pow(2, z)
  )
}

/**
 * Enumerate every {z,x,y} tile covering the given bounds across a zoom range.
 * `bounds` is { west, south, east, north } in degrees.
 */
export function enumerateTiles(bounds, minZoom, maxZoom) {
  const tiles = []
  const maxIndex = (z) => Math.pow(2, z) - 1
  const clamp = (v, hi) => Math.max(0, Math.min(hi, v))
  for (let z = minZoom; z <= maxZoom; z++) {
    const hi = maxIndex(z)
    const xMin = clamp(lngToTileX(bounds.west, z), hi)
    const xMax = clamp(lngToTileX(bounds.east, z), hi)
    // Note: tile Y increases southward, so north maps to the smaller index.
    const yMin = clamp(latToTileY(bounds.north, z), hi)
    const yMax = clamp(latToTileY(bounds.south, z), hi)
    for (let x = Math.min(xMin, xMax); x <= Math.max(xMin, xMax); x++) {
      for (let y = Math.min(yMin, yMax); y <= Math.max(yMin, yMax); y++) {
        tiles.push({ z, x, y })
      }
    }
  }
  return tiles
}

function buildTileUrl(template, { z, x, y }) {
  return template
    .replace('{z}', z)
    .replace('{x}', x)
    .replace('{y}', y)
}

/** Count how many tiles a pre-download would involve (per provider). */
export function countPredownloadTiles(bounds, minZoom, maxZoom, providerCount = 1) {
  return enumerateTiles(bounds, minZoom, maxZoom).length * providerCount
}

/**
 * Pre-download and cache (on the server) all tiles covering `bounds` for the
 * given zoom range and providers (e.g. ['osm'] or ['osm', 'nautical']).
 * Tiles already on disk are reported as skipped via the backend's
 * X-Tile-Cache header. Progress is reported via
 * `onProgress({ done, total, downloaded, skipped, failed })`. Pass an
 * AbortSignal to allow cancellation.
 *
 * Returns a summary { total, downloaded, skipped, failed }.
 */
export async function predownloadTiles({
  bounds,
  minZoom,
  maxZoom,
  providers,
  onProgress,
  signal,
  concurrency = 6,
}) {
  const coords = enumerateTiles(bounds, minZoom, maxZoom)
  const base = backendBase()
  const jobs = []
  for (const provider of providers) {
    for (const c of coords) {
      jobs.push(`${base}/tiles/${provider}/${c.z}/${c.x}/${c.y}`)
    }
  }

  const total = jobs.length
  let done = 0
  let downloaded = 0
  let skipped = 0
  let failed = 0

  const report = () => {
    if (onProgress) onProgress({ done, total, downloaded, skipped, failed })
  }
  report()

  let index = 0
  const worker = async () => {
    while (index < jobs.length) {
      if (signal && signal.aborted) return
      const url = jobs[index++]
      try {
        const resp = await fetch(url, { signal })
        if (!resp.ok) throw new Error(String(resp.status))
        await resp.arrayBuffer() // drain body so the connection is released
        if (resp.headers.get('X-Tile-Cache') === 'HIT') skipped++
        else downloaded++
      } catch (e) {
        if (signal && signal.aborted) return
        failed++
      } finally {
        done++
        report()
      }
    }
  }

  const pool = []
  for (let i = 0; i < Math.max(1, concurrency); i++) pool.push(worker())
  await Promise.all(pool)

  return { total, downloaded, skipped, failed }
}
