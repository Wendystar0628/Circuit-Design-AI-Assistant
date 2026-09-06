import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import Module from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import ts from 'typescript'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const path = join(root, 'src/renderer/src/features/simulation/simulationApi.ts')
const source = await readFile(path, 'utf8')
const output = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},fileName:path}).outputText
const calls = []
let response = null
const api = {post: async (url, body) => {calls.push({url, body}); return response}, get: async (url) => {calls.push({url}); return response}}
const loaded = new Module(path)
loaded.filename = path
loaded.paths = Module._nodeModulePaths(dirname(path))
loaded.require = (name) => { assert.equal(name, '../../lib/api'); return {api} }
loaded._compile(output, path)
const endpoints = loaded.exports
const traces = [{signal:'v(out)',component:'phase',reference:'v(in)'}]
const shared = {traces,x_min:10,x_max:100,max_points:1800,cursor_a:20,cursor_b:50,offset:100,limit:100}

test('waveform endpoints send only the fields accepted by their distinct backend contracts', async () => {
  response = {x_axis:{kind:'frequency',label:'Frequency',unit:'Hz',scale:'log'},series:[],max_points:1800}
  await endpoints.queryTraces('project 1','result/1',shared)
  assert.deepEqual(calls.pop(),{url:'/api/v1/projects/project%201/simulation-results/result%2F1/traces',body:{traces,x_min:10,x_max:100,max_points:1800}})
  await endpoints.queryTraceMeasurements('p','r',shared)
  assert.deepEqual(calls.pop().body,{traces,x_min:10,x_max:100,cursor_a:20,cursor_b:50})
  await endpoints.queryTraceTable('p','r',shared)
  assert.deepEqual(calls.pop().body,{traces,offset:100,limit:100})
  response = 'sample,value\r\n0,1.2345678901234567'
  const csv = await endpoints.exportTraceCsv('p','r',shared)
  assert.deepEqual(calls.pop().body,{traces,format:'csv'})
  assert.equal(await csv.text(),response)
})

test('whole-range measurement requests use explicit null bounds without rendering controls', async () => {
  response = {}
  await endpoints.queryTraceMeasurements('p','r',{traces,cursor_a:null,cursor_b:null,max_points:1800})
  assert.deepEqual(calls.pop().body,{traces,x_min:null,x_max:null,cursor_a:null,cursor_b:null})
})

test('study calls preserve circuit, project, study and case identities', async () => {
  const study = {study_id:'study/1',kind:'corner',status:'running',cases:[{case_id:'c1',status:'pending'}],summary:{}}
  const request = {circuit_path:'filter.cir',experiment:{acceptance_constraints:[{metric:'vout',unit:'V',lower:0}]},kind:'corner',axes:[{kind:'temperature',values:[-40,25,85]}]}
  response = {project_id:'p',study}
  assert.deepEqual(await endpoints.createSimulationStudy('p',request), study)
  assert.deepEqual(calls.pop(),{url:'/api/v1/projects/p/simulation-studies',body:request})
  await endpoints.cancelSimulationStudy('p','study/1','c1')
  assert.deepEqual(calls.pop(),{url:'/api/v1/projects/p/simulation-studies/study%2F1/cancel',body:{case_id:'c1'}})
  await endpoints.cancelSimulationStudy('p','study/1')
  assert.equal(calls.pop().body.case_id,null)
  response = {project_id:'other',study}
  await assert.rejects(() => endpoints.fetchSimulationStudy('p','study/1'),/another project/)
  response = {project_id:'p',study:{...study,study_id:'other'}}
  await assert.rejects(() => endpoints.fetchSimulationStudy('p','study/1'),/another study/)
  response = {project_id:'p',studies:[study]}
  assert.deepEqual(await endpoints.fetchSimulationStudies('p'),[study])
})
