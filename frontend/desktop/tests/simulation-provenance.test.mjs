import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import Module from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
const path = join(dirname(fileURLToPath(import.meta.url)), '../src/renderer/src/features/simulation/RunProvenance.tsx')
const output = ts.transpileModule(await readFile(path,'utf8'),{fileName:path,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText
const loaded = new Module(path)
loaded.filename = path
loaded.paths = Module._nodeModulePaths(dirname(path))
loaded._compile(output,path)
const render = (provenance) => renderToStaticMarkup(React.createElement(loaded.exports.RunProvenance,{provenance}))

test('run provenance shows the recorded engine and the exact excluded measurement with its reason', () => {
  const html = render({engine:{name:'ngspice',version:'45.2',platform:'Windows',execution_mode:'isolated_worker'},omitted_measurements:[{source_id:'filters.cir',line_number:12,statement:'.measure tran peak MAX v(out)',reason:'analysis tran does not match ac'}]})
  assert.match(html,/ngspice · 45.2/)
  assert.match(html,/isolated_worker/)
  assert.match(html,/excluded by the selected analysis \(1\)/)
  assert.match(html,/\.measure tran peak MAX v\(out\)/)
  assert.match(html,/analysis tran does not match ac/)
  assert.match(html,/filters.cir:12/)
  assert.match(html,/<details/)
})

test('historical missing engine metadata is explicit and empty omission lists do not create a warning', () => {
  const html = render({engine:null,omitted_measurements:[]})
  assert.match(html,/Not recorded for this result/)
  assert.doesNotMatch(html,/<details/)
})
