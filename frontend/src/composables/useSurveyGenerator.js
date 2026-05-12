/**
 * useSurveyGenerator.js
 *
 * Pure math – no Vue reactivity. Generates a boustrophedon (lawn-mower)
 * pattern of waypoints inside a lat/lon polygon.
 *
 * Algorithm
 * ─────────
 * 1. Compute polygon centroid in lat/lon.
 * 2. Project every polygon vertex to local ENU (metres) relative to centroid
 *    using a flat-earth (equirectangular) approximation – good for polygons
 *    up to a few km.
 * 3. Rotate the projected polygon by −lineAngle so scan lines are horizontal
 *    in the rotated frame.
 * 4. Find the axis-aligned bounding box of the rotated polygon.
 * 5. Generate horizontal scan lines at y = yMin, yMin+lineSpacing, … yMax.
 * 6. For each scan line clip the infinite horizontal segment against the
 *    polygon boundary → [xLeft, xRight].
 * 7. Extend each segment endpoint outward by lineExtension metres.
 * 8. Build boustrophedon order (reverse every other line).
 * 9. Choose start corner via startWP (0 = top-left / 1 = top-right in rotated
 *    frame, effectively inverting the starting side).
 * 10. Rotate waypoints back by +lineAngle and convert to lat/lon.
 */

// ── Constants ─────────────────────────────────────────────────────────────────
const DEG2RAD = Math.PI / 180
const RAD2DEG = 180 / Math.PI
const EARTH_R  = 6371000  // metres

// ── Coordinate helpers ────────────────────────────────────────────────────────

/** Convert lat/lon to local ENU metres relative to (lat0, lon0). */
function latLonToEnu(lat, lon, lat0, lon0) {
  const E = (lon - lon0) * DEG2RAD * EARTH_R * Math.cos(lat0 * DEG2RAD)
  const N = (lat - lat0) * DEG2RAD * EARTH_R
  return { E, N }
}

/** Convert local ENU metres back to lat/lon. */
function enuToLatLon(E, N, lat0, lon0) {
  const lat = lat0 + (N / EARTH_R) * RAD2DEG
  const lon = lon0 + (E / (EARTH_R * Math.cos(lat0 * DEG2RAD))) * RAD2DEG
  return { lat, lon }
}

/** 2D rotation: rotate point (x,y) by angle (radians). */
function rotate2d(x, y, angle) {
  const c = Math.cos(angle)
  const s = Math.sin(angle)
  return { x: c * x - s * y, y: s * x + c * y }
}

// ── Polygon clipping ──────────────────────────────────────────────────────────

/**
 * Clip a horizontal scan line y=scanY against a 2-D polygon (array of {x,y}).
 * Returns an array of x-intercept pairs [[x0,x1], …] (one per filled segment).
 *
 * Uses the even-odd scanline rasterisation algorithm.
 */
function scanlineClip(poly, scanY) {
  const xs = []
  const n = poly.length
  for (let i = 0; i < n; i++) {
    const a = poly[i]
    const b = poly[(i + 1) % n]
    const minY = Math.min(a.y, b.y)
    const maxY = Math.max(a.y, b.y)
    if (scanY < minY || scanY > maxY) continue
    if (Math.abs(b.y - a.y) < 1e-10) continue   // horizontal edge – skip
    const t = (scanY - a.y) / (b.y - a.y)
    xs.push(a.x + t * (b.x - a.x))
  }
  xs.sort((a, b) => a - b)

  // Pair up intersections
  const segments = []
  for (let i = 0; i + 1 < xs.length; i += 2) {
    segments.push([xs[i], xs[i + 1]])
  }
  return segments
}

// ── Main export ───────────────────────────────────────────────────────────────

/**
 * generateLawnmower(polygon, lineAngle, lineSpacing, lineExtension, startWP)
 *
 * @param {Array<{lat:number,lon:number}>} polygon  – closed polygon vertices
 * @param {number} lineAngle     – bearing of scan lines from North, degrees CW
 *                                 (0 = lines run N–S, 90 = lines run E–W)
 * @param {number} lineSpacing   – distance between transects in metres
 * @param {number} lineExtension – how far each transect extends beyond the
 *                                  polygon boundary in metres
 * @param {number} startWP       – 0 or 1 — which corner to start from
 * @returns {Array<{lat:number,lon:number}>}
 */
export function generateLawnmower(polygon, lineAngle, lineSpacing, lineExtension, startWP) {
  if (!polygon || polygon.length < 3) return []
  if (lineSpacing <= 0) return []

  // 1. Centroid
  const lat0 = polygon.reduce((s, p) => s + p.lat, 0) / polygon.length
  const lon0 = polygon.reduce((s, p) => s + p.lon, 0) / polygon.length

  // 2. Project to ENU
  const enu = polygon.map(p => latLonToEnu(p.lat, p.lon, lat0, lon0))

  // 3. Rotate by -(90° - bearing) so scan lines (bearing from North) are horizontal
  // bearing 0° = N-S lines → rotate by -90°; bearing 90° = E-W → rotate by 0°
  const angleRad = (90 - lineAngle) * DEG2RAD
  const rotated = enu.map(({ E, N }) => rotate2d(E, N, -angleRad))

  // 4. Bounding box
  const xs = rotated.map(p => p.x)
  const ys = rotated.map(p => p.y)
  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const yMin = Math.min(...ys)
  const yMax = Math.max(...ys)

  // 5 & 6. Generate scan lines and clip against polygon
  const waypoints2d = []  // [{x,y}] in rotated frame
  let lineIndex = 0

  for (let scanY = yMin; scanY <= yMax + 1e-6; scanY += lineSpacing) {
    const segs = scanlineClip(rotated, scanY)
    if (segs.length === 0) { lineIndex++; continue }

    // Use outermost segment (xMin → xMax of all hits)
    const xLeft  = Math.min(...segs.flat()) - lineExtension
    const xRight = Math.max(...segs.flat()) + lineExtension

    // 8. Boustrophedon: reverse alternate lines
    const forward = (lineIndex % 2 === 0) !== (startWP === 1)
    if (forward) {
      waypoints2d.push({ x: xLeft,  y: scanY })
      waypoints2d.push({ x: xRight, y: scanY })
    } else {
      waypoints2d.push({ x: xRight, y: scanY })
      waypoints2d.push({ x: xLeft,  y: scanY })
    }
    lineIndex++
  }

  if (waypoints2d.length === 0) return []

  // 10. Rotate back by +(90° - bearing) and convert to lat/lon
  return waypoints2d.map(({ x, y }) => {
    const unrot = rotate2d(x, y, angleRad)
    return enuToLatLon(unrot.x, unrot.y, lat0, lon0)
  })
}

/**
 * Utility: compute the centroid of a polygon in lat/lon.
 */
export function polygonCentroid(polygon) {
  if (!polygon || polygon.length === 0) return { lat: 0, lon: 0 }
  return {
    lat: polygon.reduce((s, p) => s + p.lat, 0) / polygon.length,
    lon: polygon.reduce((s, p) => s + p.lon, 0) / polygon.length,
  }
}

/**
 * Compute the angle handle position: 50 m from centroid in the direction of
 * lineAngle (perpendicular to the scan lines — i.e. the "row direction").
 */
export function angleHandlePosition(polygon, lineAngle) {
  const c = polygonCentroid(polygon)
  // lineAngle is bearing from North (CW). Scan line direction unit vector:
  //   E = sin(bearing), N = cos(bearing)
  const bearingRad = lineAngle * DEG2RAD
  const E = 50 * Math.sin(bearingRad)
  const N = 50 * Math.cos(bearingRad)
  return enuToLatLon(E, N, c.lat, c.lon)
}

/**
 * Compute the spacing handle position: placed between the first two scan
 * lines, at their midpoint x position.
 */
export function spacingHandlePosition(polygon, lineAngle, lineSpacing, lineExtension, startWP) {
  if (!polygon || polygon.length < 3 || lineSpacing <= 0) {
    return polygonCentroid(polygon)
  }
  const c = polygonCentroid(polygon)
  const enu = polygon.map(p => latLonToEnu(p.lat, p.lon, c.lat, c.lon))
  const angleRad = (90 - lineAngle) * DEG2RAD
  const rotated = enu.map(({ E, N }) => rotate2d(E, N, -angleRad))
  const ys = rotated.map(p => p.y)
  const xs = rotated.map(p => p.x)
  const yMin = Math.min(...ys)
  const xMid = (Math.min(...xs) + Math.max(...xs)) / 2
  // Place handle at midpoint between first and second scan line
  const handleY = yMin + lineSpacing * 0.5
  const unrot = rotate2d(xMid, handleY, angleRad)
  return enuToLatLon(unrot.x, unrot.y, c.lat, c.lon)
}
