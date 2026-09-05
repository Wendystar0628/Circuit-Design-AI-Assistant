import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { Buffer } from 'node:buffer'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import ts from 'typescript'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const path = join(root, 'src/renderer/src/features/simulation/simulationModel.ts')
const source = await readFile(path, 'utf8')
const output = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022},fileName:path}).outputText
const model = await import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)

test('experiment editing preserves SPICE suffixes and validates explicit numeric controls', () => {
  const form = {analysis:'.ac dec 100 10 1Meg',parameters:'Rload=10k\nCfilter=2.2n',solver:'method=gear\nreltol=1e-4',temperature:'27',timeout:'120'}
  const spec = model.experimentFromForm(form)
  assert.deepEqual(spec.parameters, {Rload:'10k',Cfilter:'2.2n'})
  assert.deepEqual(spec.solver_options, {method:'gear',reltol:'1e-4'})
  assert.deepEqual(model.formFromExperiment(spec), form)
  assert.equal(model.experimentFromForm({...form,analysis:'  '}).analysis_command,'')
  assert.throws(() => model.experimentFromForm({...form,timeout:'0'}), /positive/)
  assert.throws(() => model.experimentFromForm({...form,temperature:'NaN'}), /finite/)
  assert.throws(() => model.experimentFromForm({...form,parameters:'Rload=10k\nRload=20k'}), /duplicate/)
  assert.throws(() => model.experimentFromForm({...form,parameters:'Rload 10k'}), /name=value/)
})

test('baseline matching requires a compatible physical axis and available trace references', () => {
  const catalog = {x_axis:{kind:'frequency',label:'Frequency',unit:'Hz',scale:'log'},signals:[
    {name:'v(out)',unit:'V',components:['magnitude','phase','db']},
    {name:'v(in)',unit:'V',components:['magnitude','phase','db']},
    {name:'i(v1)',unit:'A',components:['magnitude','phase','db']},
  ]}
  const transfer = {signal:'v(out)',reference:'v(in)',component:'db'}
  assert.deepEqual(model.supportedTraces([transfer,{...transfer,reference:'missing'},{...transfer,reference:'i(v1)'},{...transfer,component:'real'}],catalog), [transfer])
  assert.equal(model.compatibleCatalogs(catalog,{...catalog,x_axis:{...catalog.x_axis,unit:'s'}}),false)
  assert.equal(model.compatibleCatalogs(catalog,{...catalog,x_axis:{...catalog.x_axis,label:'Other source'}}),false)
  assert.notEqual(model.traceKey(transfer),model.traceKey({...transfer,reference:null}))
  const impedance = {...transfer,reference:'i(v1)',component:'magnitude'}
  assert.deepEqual(model.supportedTraces([impedance],catalog),[impedance])
})

test('decibels and degrees remain directly readable without engineering prefixes', () => {
  assert.equal(model.formatEngineering(.001,'dB'), '0.001 dB')
  assert.equal(model.formatEngineering(1000,'°'), '1000 °')
  assert.equal(model.formatEngineering(.001,'V'), '1 mV')
  assert.equal(model.formatEngineering(null,'V'), '—')
})

test('workbench uses one authority and retains failed measurements and input provenance', () => {
  const result = {success:false,analysis_type:'unknown'}
  const response = {project_id:'p',result_id:'r',job_id:'j',result_path:'r.json',result,catalog:null,metrics:[{name:'gain',status:'FAILED'}],schematic:null,provenance:{available:true,execution_inputs_available:false,files:[]}}
  const view = model.buildResultViewModel(response)
  assert.deepEqual(view.identity,{projectId:'p',resultId:'r',jobId:'j'})
  assert.equal(view.result,result)
  assert.equal(view.metrics[0].status,'FAILED')
  assert.equal(view.provenance.execution_inputs_available,false)
  assert.equal(Object.hasOwn(view,'plot'),false)
  assert.equal(Object.hasOwn(view,'data'),false)
})

test('result switches block stale traces and failed results never provide a waveform request', () => {
  const noiseTrace = {signal:'onoise_spectrum',component:'real'}
  const opTrace = {signal:'v(out)',component:'real'}
  const view = (id,success,names) => ({identity:{resultId:id},result:{success},catalog:{signals:names.map((name) => ({name,unit:'V',components:['real']}))}})
  const noise = view('noise',true,['onoise_spectrum'])
  const op = view('op',true,['v(out)'])
  const failed = view('failed',false,['v(out)'])
  assert.deepEqual(model.tracesForSelectedResult(noise,'noise',[noiseTrace]),[noiseTrace])
  assert.deepEqual(model.tracesForSelectedResult(op,'noise',[noiseTrace]),[])
  assert.deepEqual(model.tracesForSelectedResult(op,'op',[noiseTrace,opTrace]),[opTrace])
  assert.deepEqual(model.tracesForSelectedResult(failed,'op',[opTrace]),[])
  assert.deepEqual(model.tracesForSelectedResult(failed,'failed',[opTrace]),[])
  assert.deepEqual(model.tracesForSelectedResult(null,'op',[opTrace]),[])
})
