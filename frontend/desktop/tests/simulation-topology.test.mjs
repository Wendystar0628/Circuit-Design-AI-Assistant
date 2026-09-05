import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = join(root, 'src/renderer/src/features/simulation/TopologyInspector.tsx')
const output = ts.transpileModule(await readFile(sourcePath, 'utf8'), {
  fileName: sourcePath,
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const exports = {}
vm.runInNewContext(output, { exports, require: createRequire(sourcePath) })
const { indexTopology, TopologyInspector } = exports

function component(id, source, scope = []) {
  return {
    id, instance_name: 'R1', source_file: source, scope_path: scope,
    kind: 'R', display_name: 'R1', display_value: '1k', primitive_kind: '',
    resolved_model_name: '', subckt_name: '', primitive_source: '', semantic_roles: [],
    node_ids: ['out', '0'], pins: [{ name: '1', node_id: 'out', role: 'positive' }],
    editable_fields: [], pin_roles: {},
  }
}

function document(overrides = {}) {
  return {
    document_id: 'doc', revision: 'revision', file_path: '/test/main.cir', title: 'Amplifier',
    components: [], nets: [], subcircuits: [], parse_errors: [], readonly_reasons: [],
    ...overrides,
  }
}

test('topology preserves authoritative pin connections for repeated device and node names across scopes', () => {
  const top = component('top-r1', '/test/main.cir')
  const nested = component('nested-r1', '/test/model.lib', ['amp'])
  const nets = [
    { id: 'net-top', name: 'out', scope_path: [], source_file: '/test/main.cir', connections: [{ component_id: top.id, instance_name: 'R1', pin_name: '1', pin_role: 'positive' }] },
    { id: 'net-amp', name: 'out', scope_path: ['amp'], source_file: '/test/model.lib', connections: [{ component_id: nested.id, instance_name: 'R1', pin_name: '1', pin_role: 'positive' }] },
  ]
  const index = indexTopology(document({ components: [top, nested], nets }))
  assert.equal(index.pinNets.get(JSON.stringify([top.id, '1'])).id, 'net-top')
  assert.equal(index.pinNets.get(JSON.stringify([nested.id, '1'])).id, 'net-amp')
  assert.equal(index.components.size, 2)
  assert.equal(index.scopes.size, 2)
})

test('network details retain provenance for connections expanded from different source files', () => {
  const top = component('top-r1', '/test/main.cir')
  const included = component('included-r1', '/test/included.cir')
  const schematic = document({
    components: [top, included],
    nets: [{ id: 'shared-out', name: 'out', scope_path: [], source_file: top.source_file, connections: [top, included].map((item) => ({ component_id: item.id, instance_name: item.instance_name, pin_name: '1', pin_role: 'positive' })) }],
  })
  const html = renderToStaticMarkup(React.createElement(TopologyInspector, { schematic }))
  assert.match(html, /Connected component pins/)
  assert.match(html, /\/test\/main\.cir/)
  assert.match(html, /\/test\/included\.cir/)
  assert.match(html, /2 connections/)
})

test('parse issues remain visible when a document contains no components', () => {
  const schematic = document({ parse_errors: [{ message: 'Unsupported device', source_file: '/test/main.cir', line_text: 'Z1 in out model', line_index: 4, column_start: 0, column_end: 2 }] })
  const html = renderToStaticMarkup(React.createElement(TopologyInspector, { schematic }))
  assert.match(html, /connectivity may be incomplete/)
  assert.match(html, /\/test\/main\.cir:5:1/)
  assert.match(html, /Z1 in out model/)
})

test('missing result snapshots display an empty state', () => {
  assert.match(renderToStaticMarkup(React.createElement(TopologyInspector, { schematic: null })), /No result-bound topology snapshot/)
})
