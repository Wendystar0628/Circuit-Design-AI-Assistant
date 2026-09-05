import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import Module from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const path = join(dirname(fileURLToPath(import.meta.url)), '../src/renderer/src/features/simulation/SimulationOutput.tsx')
const output = ts.transpileModule(await readFile(path,'utf8'),{fileName:path,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText
const loaded = new Module(path)
loaded.filename = path
loaded.paths = Module._nodeModulePaths(dirname(path))
loaded._compile(output,path)
const render = (result) => renderToStaticMarkup(React.createElement(loaded.exports.OutputPanel,{view:{identity:{resultId:'failed-run'},result}}))

test('failed preflight with null simulator output shows its structured error without crashing', () => {
  const html = render({success:false,raw_output:null,error:{code:'SIMULATION_ERROR',message:'Unsupported solver option: invalidoption',recovery_suggestion:'Select a supported solver option.'}})
  assert.match(html,/Unsupported solver option: invalidoption/)
  assert.match(html,/Select a supported solver option/)
  assert.match(html,/role="alert"/)
  assert.match(html,/No simulator output was recorded/)
  assert.match(html,/0 lines/)
})

test('a failed native run retains both its error and original simulator output', () => {
  const html = render({success:false,raw_output:'ngspice started\nconvergence failed',error:{code:'CONVERGENCE',message:'Operating point failed',recovery_suggestion:null}})
  assert.match(html,/Operating point failed/)
  assert.match(html,/ngspice started/)
  assert.match(html,/convergence failed/)
  assert.match(html,/2 lines/)
})
