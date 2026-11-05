import fs from 'node:fs'
import http from 'node:http'
import https from 'node:https'
import path from 'node:path'
import { defineConfig } from 'vite'

const wasmPath = path.resolve('node_modules/laz-perf/lib/web/laz-perf.wasm')

function requestUpstream(target, range, redirectsLeft, res) {
  const lib = target.startsWith('https:') ? https : http
  const headers = { 'user-agent': 'lidar-copc-viewer' }
  if (range) headers.range = range
  const upstream = lib.request(target, { method: 'GET', headers }, (up) => {
    const location = up.headers.location
    if (
      location &&
      [301, 302, 303, 307, 308].includes(up.statusCode) &&
      redirectsLeft > 0
    ) {
      up.resume()
      requestUpstream(new URL(location, target).toString(), range, redirectsLeft - 1, res)
      return
    }
    res.statusCode = up.statusCode || 502
    for (const name of ['content-type', 'content-length', 'content-range', 'accept-ranges']) {
      const value = up.headers[name]
      if (value) res.setHeader(name, value)
    }
    up.pipe(res)
  })
  upstream.on('error', (err) => {
    if (!res.headersSent) res.statusCode = 502
    res.end(err.message)
  })
  upstream.end()
}

function copcDevServer() {
  return {
    name: 'copc-range-proxy',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url || '/', 'http://127.0.0.1')
        if (url.pathname.endsWith('/laz-perf.wasm')) {
          res.setHeader('Content-Type', 'application/wasm')
          fs.createReadStream(wasmPath).pipe(res)
          return
        }
        if (url.pathname !== '/copc-proxy') return next()
        const target = url.searchParams.get('url') || ''
        if (!/^https?:\/\//i.test(target)) {
          res.statusCode = 400
          res.end('url must be an http(s) COPC address')
          return
        }
        requestUpstream(target, req.headers.range, 3, res)
      })
    },
  }
}

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
  optimizeDeps: {
    include: ['copc', 'laz-perf'],
  },
  plugins: [copcDevServer()],
})
