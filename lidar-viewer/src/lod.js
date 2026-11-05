export const PIXEL_THRESHOLD = 220

function step(bounds, [a, b, c]) {
  const [minx, miny, minz, maxx, maxy, maxz] = bounds
  const midx = (minx + maxx) / 2
  const midy = (miny + maxy) / 2
  const midz = (minz + maxz) / 2
  return [
    a ? midx : minx,
    b ? midy : miny,
    c ? midz : minz,
    a ? maxx : midx,
    b ? maxy : midy,
    c ? maxz : midz,
  ]
}

export function nodeBounds(cube, key) {
  const [depth, x, y, z] = String(key).split('-').map(Number)
  let bounds = cube
  for (let i = depth - 1; i >= 0; i -= 1) {
    bounds = step(bounds, [(x >> i) & 1, (y >> i) & 1, (z >> i) & 1])
  }
  return bounds
}

export function childKeys(key) {
  const [depth, x, y, z] = String(key).split('-').map(Number)
  const out = []
  for (const a of [0, 1]) {
    for (const b of [0, 1]) {
      for (const c of [0, 1]) {
        out.push(`${depth + 1}-${x * 2 + a}-${y * 2 + b}-${z * 2 + c}`)
      }
    }
  }
  return out
}

export function visibleBox(view) {
  const { target, zoom, width, height, padding = 0.15 } = view
  const scale = 2 ** zoom
  const halfW = width / scale / 2
  const halfH = height / scale / 2
  return [
    target[0] - halfW * (1 + padding),
    target[1] - halfH * (1 + padding),
    target[0] + halfW * (1 + padding),
    target[1] + halfH * (1 + padding),
  ]
}

function overlapsXY(bounds, box) {
  return bounds[0] <= box[2] && bounds[3] >= box[0] && bounds[1] <= box[3] && bounds[4] >= box[1]
}

export function screenPixels(bounds, zoom) {
  const size = Math.max(bounds[3] - bounds[0], bounds[4] - bounds[1])
  return size * 2 ** zoom
}

export function pageNeedsDetail({ key, cube, view, pixelThreshold = PIXEL_THRESHOLD }) {
  const bounds = nodeBounds(cube, key)
  if (!overlapsXY(bounds, visibleBox(view))) return false
  return screenPixels(bounds, view.zoom) > pixelThreshold
}

export function selectNodeKeys({ nodes, cube, view, pixelThreshold = PIXEL_THRESHOLD }) {
  const box = visibleBox(view)
  const selected = []
  const root = '0-0-0-0'
  if (!nodes[root] || nodes[root].pointCount <= 0) return selected
  const stack = [root]
  const seen = new Set()
  while (stack.length) {
    const key = stack.pop()
    if (seen.has(key)) continue
    seen.add(key)
    const node = nodes[key]
    if (!node || node.pointCount <= 0) continue
    const bounds = nodeBounds(cube, key)
    if (!overlapsXY(bounds, box)) continue
    const kids = childKeys(key).filter((child) => nodes[child] && nodes[child].pointCount > 0)
    if (kids.length && screenPixels(bounds, view.zoom) > pixelThreshold) {
      for (const child of kids) stack.push(child)
    } else {
      selected.push(key)
    }
  }
  return selected
}
