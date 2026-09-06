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
const modelsPath = join(dirname(path), 'ModelBindings.tsx')
const models = new Module(modelsPath)
models.filename = modelsPath
models.paths = loaded.paths
models._compile(ts.transpileModule(await readFile(modelsPath, 'utf8'), {fileName: modelsPath, compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}}).outputText, modelsPath)
const originalRequire = loaded.require.bind(loaded)
loaded.require = (name) => name === './ModelBindings' ? models.exports : originalRequire(name)
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

test('captured models show immutable digests and unknown applicability without laundering unmatched declarations', () => {
  const html = render({models:[{name:'Dfast',kind:'model',identity:null,source_path:'models/diode.lib',source_id:'file-1',source:'Vendor declared',version:'v2',definition_digest:'sha256:definition',file_digest:'sha256:file',metadata_origin:'user_declared',binding_status:'unmatched',simplified:null,temperature_range:{min:0,max:85}}]})
  assert.match(html,/sha256:definition/)
  assert.match(html,/sha256:file/)
  assert.match(html,/Metadata binding requires attention/)
  assert.match(html,/Vendor declared/)
  assert.match(html,/user declared/)
  assert.match(html,/0 to 85 °C/)
  assert.match(html,/Unknown \/ not declared/)
})
