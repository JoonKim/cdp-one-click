import { Deck, OrbitView, COORDINATE_SYSTEM } from '@deck.gl/core'
import { PointCloudLayer } from '@deck.gl/layers'
import { Copc } from 'copc'
import { PIXEL_THRESHOLD, pageNeedsDetail, selectNodeKeys } from './lod.js'
import { createRangeGetter } from './range-getter.js'

const viewEl = document.getElementById('view')
const form = document.getElementById('bar')
const urlInput = document.getElementById('url')
const sampleButton = document.getElementById('sample')
const hud = document.getElementById('hud')

const AUTZEN =
  'https://s3.amazonaws.com/hobu-lidar/autzen-classified.copc.laz'

let deck
let generation = 0
let current = null
let refreshTimer = 0

function formatBytes(value) {
  if (value == null) return 'unknown'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(2)} MB`
}

function paintHud(text, data) {
  hud.textContent = text
  for (const [key, value] of Object.entries(data)) hud.dataset[key] = String(value)
}

function showStatus(status, message, extra = {}) {
  paintHud(message, { status, ...extra })
}

function fetchUrl(input) {
  if (import.meta.env.DEV && /^https?:\/\//i.test(input)) {
    return `/copc-proxy?url=${encodeURIComponent(input)}`
  }
  return input
}

function absoluteTarget(viewState, origin) {
  const target = viewState.target || [0, 0, 0]
  return [target[0] + origin[0], target[1] + origin[1], target[2] + origin[2]]
}

function viewFromDeck(viewState, origin) {
  const rect = viewEl.getBoundingClientRect()
  return {
    target: absoluteTarget(viewState, origin),
    zoom: viewState.zoom,
    width: rect.width || 800,
    height: rect.height || 800,
  }
}

function colorFor(classification, z, zMin, zMax) {
  if (classification === 2) return [196, 176, 132, 255]
  if (classification >= 3 && classification <= 5) return [52, 148, 78, 255]
  if (classification === 6) return [188, 86, 74, 255]
  if (classification === 9) return [64, 122, 196, 255]
  const span = zMax - zMin
  const t = span === 0 ? 0.5 : (z - zMin) / span
  return [40 + t * 180, 90 + t * 70, 220 - t * 90, 255]
}

async function hierarchyForView(getter, copc, view) {
  const nodes = {}
  const loaded = new Set()
  const queue = [copc.info.rootHierarchyPage]
  while (queue.length) {
    const page = queue.shift()
    const id = `${page.pageOffset}:${page.pageLength}`
    if (loaded.has(id)) continue
    loaded.add(id)
    const subtree = await Copc.loadHierarchyPage(getter, page)
    Object.assign(nodes, subtree.nodes)
    for (const [key, child] of Object.entries(subtree.pages)) {
      if (pageNeedsDetail({ key, cube: copc.info.cube, view })) queue.push(child)
    }
  }
  return nodes
}

async function mapPool(items, limit, fn) {
  let index = 0
  async function worker() {
    while (index < items.length) {
      const currentIndex = index
      index += 1
      await fn(items[currentIndex])
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => worker()))
}

function pointsFromView(pointView, origin) {
  const count = pointView.pointCount
  const positions = new Float32Array(count * 3)
  const colors = new Uint8Array(count * 4)
  const x = pointView.getter('X')
  const y = pointView.getter('Y')
  const z = pointView.getter('Z')
  const classes = pointView.dimensions.Classification ? pointView.getter('Classification') : null
  let zMin = Infinity
  let zMax = -Infinity
  const zs = new Float32Array(count)
  for (let i = 0; i < count; i += 1) {
    const px = x(i) - origin[0]
    const py = y(i) - origin[1]
    const pz = z(i) - origin[2]
    positions[i * 3] = px
    positions[i * 3 + 1] = py
    positions[i * 3 + 2] = pz
    zs[i] = pz
    if (pz < zMin) zMin = pz
    if (pz > zMax) zMax = pz
  }
  for (let i = 0; i < count; i += 1) {
    const rgba = colorFor(classes ? classes(i) : null, zs[i], zMin, zMax)
    colors.set(rgba, i * 4)
  }
  return { positions, colors, count }
}

function renderCloud(chunks) {
  let count = 0
  for (const chunk of chunks) count += chunk.count
  const positions = new Float32Array(count * 3)
  const colors = new Uint8Array(count * 4)
  let offset = 0
  for (const chunk of chunks) {
    positions.set(chunk.positions, offset * 3)
    colors.set(chunk.colors, offset * 4)
    offset += chunk.count
  }
  deck.setProps({
    layers: [
      new PointCloudLayer({
        id: 'copc-points',
        data: {
          length: count,
          attributes: {
            getPosition: { value: positions, size: 3 },
            getColor: { value: colors, size: 4, normalized: true },
          },
        },
        coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        pointSize: 3,
      }),
    ],
  })
  return count
}

function describe(session, nodeCount, pointCount) {
  const { stats, source } = session
  const partial = stats.fileSize != null && stats.bytes < stats.fileSize
  const percent =
    stats.fileSize > 0 ? `${((100 * stats.bytes) / stats.fileSize).toFixed(1)}% of file` : 'file size unknown'
  const text = [
    source,
    `file size: ${formatBytes(stats.fileSize)}`,
    `fetched: ${formatBytes(stats.bytes)} (${percent})`,
    `range requests: ${stats.requests}`,
    `nodes in view: ${nodeCount}`,
    `points drawn: ${pointCount.toLocaleString()}`,
    partial ? 'partial read: viewpoint chunks only' : 'partial read: this file is small enough to cover',
  ].join('\n')
  paintHud(text, {
    status: 'ready',
    bytes: stats.bytes,
    fileSize: stats.fileSize ?? '',
    ranges: stats.requests,
    nodes: nodeCount,
    points: pointCount,
    partial: partial ? 'true' : 'false',
  })
}

async function refreshView() {
  if (!current) return
  const token = ++generation
  const { getter, copc, origin, cache, viewState, stats, source } = current
  const view = viewFromDeck(viewState, origin)
  const nodes = await hierarchyForView(getter, copc, view)
  if (token !== generation) return
  const keys = selectNodeKeys({ nodes, cube: copc.info.cube, view })
  const signature = keys.slice().sort().join(',')
  if (signature === current.rendered) {
    describe({ stats, source }, keys.length, current.renderedPoints || 0)
    return
  }
  const missing = keys.filter((key) => !cache.has(key))
  await mapPool(missing, 6, async (key) => {
    const node = nodes[key]
    const pointView = await Copc.loadPointDataView(getter, copc, node, {
      include: ['X', 'Y', 'Z', 'Classification'],
    })
    if (token !== generation) return
    cache.set(key, pointsFromView(pointView, origin))
  })
  if (token !== generation) return
  const chunks = keys.map((key) => cache.get(key)).filter(Boolean)
  const pointCount = renderCloud(chunks)
  current.rendered = signature
  current.renderedPoints = pointCount
  describe({ stats, source }, keys.length, pointCount)
}

function viewChanged(prev, next) {
  if (!prev || !next) return true
  if (Math.abs((prev.zoom || 0) - (next.zoom || 0)) > 1e-4) return true
  if (prev.rotationX !== next.rotationX || prev.rotationOrbit !== next.rotationOrbit) return true
  const a = prev.target || [0, 0, 0]
  const b = next.target || [0, 0, 0]
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) > 0.05
}

function scheduleRefresh() {
  window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(() => {
    refreshView().catch((err) => showStatus('error', err.message))
  }, 200)
}

function fitView(cube) {
  const extent = Math.max(cube[3] - cube[0], cube[4] - cube[1])
  const height = viewEl.clientHeight || window.innerHeight || 800
  const zoom = Math.log2((0.85 * height) / extent)
  return {
    target: [0, 0, 40],
    rotationX: 50,
    rotationOrbit: 20,
    zoom,
    minZoom: zoom - 2,
    maxZoom: zoom + 10,
  }
}

async function loadSource(source) {
  const token = ++generation
  window.clearTimeout(refreshTimer)
  current = null
  showStatus('loading', `Loading ${source}`)
  const remote = fetchUrl(source)
  const { getter, stats } = createRangeGetter(remote, () => {
    if (token !== generation || !current) return
    paintHud(hud.textContent, {
      status: 'loading',
      bytes: stats.bytes,
      fileSize: stats.fileSize ?? '',
      ranges: stats.requests,
    })
  })
  const copc = await Copc.create(getter)
  if (token !== generation) return
  const cube = copc.info.cube
  const origin = [(cube[0] + cube[3]) / 2, (cube[1] + cube[4]) / 2, cube[2]]
  const viewState = fitView(cube)
  current = { getter, copc, origin, cache: new Map(), viewState, stats, source }
  mountDeck(viewState)
  await refreshView()
}

function mountDeck(viewState) {
  if (deck) deck.finalize()
  deck = new Deck({
    parent: viewEl,
    glOptions: { preserveDrawingBuffer: true },
    views: new OrbitView({ orbitAxis: 'Z' }),
    controller: { inertia: false, scrollZoom: { speed: 0.01, smooth: false } },
    initialViewState: viewState,
    layers: [],
    onViewStateChange: ({ viewState: next }) => {
      if (current && viewChanged(current.viewState, next)) {
        current.viewState = next
        scheduleRefresh()
      }
      return next
    },
    onError: (error) => showStatus('error', error.message),
  })
}

mountDeck({ target: [0, 0, 0], rotationX: 50, rotationOrbit: 0, zoom: 0 })

form.addEventListener('submit', (event) => {
  event.preventDefault()
  const source = urlInput.value.trim()
  if (!source) return
  loadSource(source).catch((err) => showStatus('error', err.message))
})

sampleButton.addEventListener('click', () => {
  const source = new URL('/sample.copc.laz', window.location.href).toString()
  urlInput.value = source
  loadSource(source).catch((err) => showStatus('error', err.message))
})

const query = new URLSearchParams(window.location.search).get('url')
if (query) {
  urlInput.value = query
  loadSource(query).catch((err) => showStatus('error', err.message))
} else {
  urlInput.placeholder = AUTZEN
}
