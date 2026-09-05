import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import Module from 'node:module'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const chartPath = join(desktopRoot, 'src/renderer/src/features/simulation/SeriesChart.tsx')
const source = await readFile(chartPath, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  fileName: chartPath,
}).outputText
const chartModule = new Module(chartPath)
chartModule.filename = chartPath
chartModule.paths = Module._nodeModulePaths(dirname(chartPath))
const nodeRequire = chartModule.require.bind(chartModule)
// Use Node's renderer in this worker; the production browser renderer keeps
// MessageChannel handles alive when imported into a Node test process.
chartModule.require = (specifier) => nodeRequire(specifier === 'react-dom/server.browser' ? 'react-dom/server' : specifier)
chartModule._compile(output, chartPath)
const { SeriesChart, buildPlotSvg } = chartModule.exports
const identity = { projectId: 'project-a', resultId: 'result-a', jobId: 'job-a' }

test('comparison exports retain the complete immutable result identity of every trace', () => {
  const baseline = 'baseline-result-20260906-immutable-identity'
  const svg = buildPlotSvg({x_axis:{label:'Time',unit:'s',scale:'linear'},series:[
    {id:'current:v',label:'Current',unit:'V',x:[0,1],y:[1,2],source_result_id:identity.resultId},
    {id:'baseline:v',label:'Baseline',unit:'V',x:[0,.5,1],y:[1,1.5,3],source_result_id:baseline},
  ]}, identity)
  assert.match(svg,/series_sources/)
  assert.ok(svg.includes(baseline))
})

function data(series, axis = {}) {
  return { x_axis: { label: 'Time', unit: 's', scale: 'linear', ...axis }, series }
}

function trace(id, x, y, unit = 'V') {
  return { id, label: id, unit, x, y }
}

function polylines(svg) {
  return [...svg.matchAll(/<polyline[^>]* points="([^"]+)"/g)].map((match) => match[1].split(' ').map((point) => point.split(',').map(Number)))
}

test('voltage, current and phase occupy separate panels with physical labels and legends', () => {
  const svg = buildPlotSvg(data([
    trace('Output & input <V>', [0, 1], [0, 2]),
    trace('V(in)', [0, 1], [1, 1]),
    trace('I(R1)', [0, 1], [0.001, 0.002], 'A'),
    trace('Phase', [0, 1], [0, 90], 'deg'),
  ]), identity)
  assert.equal((svg.match(/<clipPath /g) ?? []).length, 3)
  for (const unit of ['V', 'A', 'deg']) assert.ok(svg.includes(`>${unit}</text>`))
  assert.match(svg, /Output &amp; input &lt;V&gt;/)
  assert.match(svg, /Time \(s\)/)
  assert.match(svg, /result-a/)
  assert.match(svg, /project-a/)
  assert.match(svg, /<metadata>/)
})

test('null gaps remain disconnected and descending sweep samples keep their supplied order', () => {
  const svg = buildPlotSvg(data([trace('descending', [5, 4, 3, null, 2, 1], [0, 5, -2, null, 8, 0])]), identity)
  const paths = polylines(svg)
  assert.equal(paths.length, 2)
  assert.deepEqual(paths.map((path) => path.length), [3, 2])
  for (const path of paths) for (let index = 1; index < path.length; index += 1) assert.ok(path[index][0] < path[index - 1][0])
})

test('the renderer retains every server-selected sample, including a narrow spike beyond the former client limit', () => {
  const x = Array.from({ length: 5001 }, (_, index) => index)
  const y = x.map((value) => value === 4017 ? 1000 : 0)
  const svg = buildPlotSvg(data([trace('pulse', x, y)]), identity)
  const [points] = polylines(svg)
  assert.equal(points.length, 5001)
  assert.ok(points[4017][1] < points[4016][1])
  assert.ok(points[4017][1] < points[4018][1])
})

test('a logarithmic physical viewport places each decade equally and omits invalid log coordinates', () => {
  const svg = buildPlotSvg(data([trace('gain', [0, 1, 10, 100], [4, 1, 2, 3], 'dB')], { label: 'Frequency', unit: 'Hz', scale: 'log' }), identity, [1, 100])
  const [points] = polylines(svg)
  assert.equal(points.length, 3)
  assert.equal(points[1][0] - points[0][0], points[2][0] - points[1][0])
  assert.match(svg, /Frequency \(Hz\) · log scale/)
  assert.match(svg, />100</)
})

test('operating point and isolated samples are visible as markers', () => {
  const svg = buildPlotSvg(data([trace('V(out)', [0, null, 2], [1, null, 3])]), identity)
  assert.equal((svg.match(/<circle /g) ?? []).length, 2)
  assert.equal(polylines(svg).length, 0)
  assert.doesNotMatch(svg, /NaN|Infinity/)
})

test('screen and SVG export share the exact viewport projection for all units', () => {
  const chartData = data([trace('V(out)', [0, 1, 2], [0, 1, 0]), trace('I(R1)', [0, 1, 2], [0, 0.001, 0], 'A')])
  const props = { data: chartData, identity, range: [0.5, 1.5], cursorA: null, cursorB: null, cursorTarget: 'a', onCursorChange() {}, onRangeChange() {} }
  const screen = renderToStaticMarkup(React.createElement(SeriesChart, props))
  const exported = buildPlotSvg(chartData, identity, props.range)
  assert.deepEqual(polylines(screen), polylines(exported))
  assert.equal((screen.match(/<svg /g) ?? []).length, 2)
  assert.match(screen, /drag to pan; scroll to zoom/)
})
