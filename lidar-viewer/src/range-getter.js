function coveredBytes(spans) {
  const ordered = spans.slice().sort((a, b) => a[0] - b[0])
  let total = 0
  let cursor = 0
  for (const [start, stop] of ordered) {
    const from = Math.max(start, cursor)
    if (stop > from) total += stop - from
    cursor = Math.max(cursor, stop)
  }
  return total
}

export function createRangeGetter(url, onChunk) {
  const spans = []
  const stats = { requests: 0, bytes: 0, fileSize: null }
  const getter = async (begin, end) => {
    if (begin === end) return new Uint8Array()
    if (begin < 0 || end < begin) throw new Error(`Invalid range ${begin}-${end}`)
    const response = await fetch(url, {
      headers: { Range: `bytes=${begin}-${end - 1}` },
    })
    if (response.status !== 206) {
      await response.body?.cancel?.()
      throw new Error(
        `Expected HTTP 206 for bytes ${begin}-${end - 1}, got ${response.status}. The server ignored the Range header.`,
      )
    }
    const match = /bytes (\d+)-(\d+)\/(\d+)/.exec(response.headers.get('content-range') || '')
    if (!match) {
      await response.body?.cancel?.()
      throw new Error(`Range response for bytes ${begin}-${end - 1} had no Content-Range`)
    }
    const start = Number(match[1])
    const endInclusive = Number(match[2])
    stats.fileSize = Number(match[3])
    if (start !== begin || endInclusive < start) {
      await response.body?.cancel?.()
      throw new Error(`Content-Range ${match[0]} does not start at byte ${begin}`)
    }
    const buffer = new Uint8Array(await response.arrayBuffer())
    if (buffer.byteLength !== endInclusive - start + 1) {
      throw new Error(
        `Range ${match[0]} returned ${buffer.byteLength} bytes instead of ${endInclusive - start + 1}`,
      )
    }
    spans.push([start, start + buffer.byteLength])
    stats.requests += 1
    stats.bytes = coveredBytes(spans)
    onChunk?.({ ...stats })
    return buffer
  }
  return { getter, stats }
}
