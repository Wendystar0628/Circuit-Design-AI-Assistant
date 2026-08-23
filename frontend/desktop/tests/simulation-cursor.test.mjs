import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

async function loadSimulationModel() {
  const path = join(
    desktopRoot,
    'src',
    'renderer',
    'src',
    'features',
    'simulation',
    'simulationModel.ts',
  )
  const source = await readFile(path, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: path,
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

function plotModel(overrides = {}) {
  return {
    analysisType: 'tran',
    title: 'Cursor test',
    xLabel: 'Time',
    xUnit: 's',
    leftLabel: 'V',
    rightLabel: null,
    logX: false,
    logLeftY: false,
    logRightY: false,
    series: [],
    ...overrides,
  }
}

function series(id, x, y, overrides = {}) {
  return {
    id,
    label: id,
    color: '#2563eb',
    axis: 'left',
    component: 'real',
    unit: 'V',
    x,
    y,
    ...overrides,
  }
}

test('cursor samples contain unique visible finite points sorted in display order', async () => {
  const { collectCursorSamples } = await loadSimulationModel()
  const model = plotModel({
    series: [
      series(
        'visible',
        [10, 1, 3, 3, null, 2, Number.POSITIVE_INFINITY],
        [1, 2, 3, null, 4, Number.NaN, 5],
      ),
      series('hidden', [4], [4]),
    ],
  })

  assert.deepEqual(collectCursorSamples(model, new Set(['visible'])), [1, 3, 10])
})

test('logarithmic cursor samples reject non-positive plotted coordinates', async () => {
  const { collectCursorSamples } = await loadSimulationModel()
  const model = plotModel({
    analysisType: 'noise',
    logX: true,
    logLeftY: true,
    series: [series('noise', [100, 0, 1, 10, 5, -1], [1, 2, 3, 4, -2, 5])],
  })

  assert.deepEqual(collectCursorSamples(model, new Set(['noise'])), [1, 10, 100])
})

test('cursor snapping uses linear or logarithmic display distance and clamps to bounds', async () => {
  const { snapCursorValue } = await loadSimulationModel()

  assert.equal(snapCursorValue([0, 10, 20], 6, false), 10)
  assert.equal(snapCursorValue([0, 10, 20], 5, false), 0)
  assert.equal(snapCursorValue([0, 10, 20], -100, false), 0)
  assert.equal(snapCursorValue([0, 10, 20], 100, false), 20)
  assert.equal(snapCursorValue([1, 10], 4, true), 10)
  assert.equal(snapCursorValue([], 4, true), null)
})

test('keyboard cursor stepping handles null, fine, coarse, and boundary movement', async () => {
  const { stepCursorValue } = await loadSimulationModel()
  const samples = Array.from({ length: 15 }, (_, index) => index + 1)

  assert.equal(stepCursorValue(samples, null, 1, false), 1)
  assert.equal(stepCursorValue(samples, null, -1, false), 15)
  assert.equal(stepCursorValue(samples, 5, 1, false), 6)
  assert.equal(stepCursorValue(samples, 5, -1, false), 4)
  assert.equal(stepCursorValue(samples, 5, 1, false, true), 15)
  assert.equal(stepCursorValue(samples, 5, -1, false, true), 1)
  assert.equal(stepCursorValue(samples, 15, 1, false), 15)
  assert.equal(stepCursorValue(samples, 1, -1, false), 1)
  assert.equal(stepCursorValue([1, 10, 100], 4, 1, true), 100)
  assert.equal(stepCursorValue([], null, 1, false), null)
})
