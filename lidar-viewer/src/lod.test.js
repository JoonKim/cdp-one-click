import assert from 'node:assert/strict'
import test from 'node:test'
import { selectNodeKeys } from './lod.js'

const cube = [0, 0, 0, 100, 100, 100]
const nodes = { '0-0-0-0': { pointCount: 10 } }
for (const a of [0, 1]) {
  for (const b of [0, 1]) {
    for (const c of [0, 1]) {
      nodes[`${1}-${a}-${b}-${c}`] = { pointCount: 4 }
    }
  }
}

test('a distant camera loads the root octree node only', () => {
  const view = { target: [50, 50, 50], zoom: 0, width: 800, height: 800 }
  assert.deepEqual(selectNodeKeys({ nodes, cube, view }), ['0-0-0-0'])
})

test('zooming in replaces the root with the child nodes in view', () => {
  const view = { target: [50, 50, 50], zoom: 2, width: 800, height: 800 }
  const keys = selectNodeKeys({ nodes, cube, view }).sort()
  assert.equal(keys.length, 8)
  assert.equal(keys.includes('0-0-0-0'), false)
})

test('a view outside the cube fetches no point chunks', () => {
  const view = { target: [1000, 1000, 50], zoom: 2, width: 800, height: 800 }
  assert.deepEqual(selectNodeKeys({ nodes, cube, view }), [])
})
