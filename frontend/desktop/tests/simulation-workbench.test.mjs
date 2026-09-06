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

test('acceptance bounds preserve zero, block absent or invalid limits and reuse frozen criteria independently', () => {
  const form = {...model.formFromExperiment({}),acceptance:[{metric:'vout',unit:'V',lower:0,upper:5,conditions:{parameters:{VDD:'5'},temperature:25}}],models:[{name:'Dfast',kind:'model',version:'v1',simplified:true,voltage_range:{min:0,max:10}}]}
  const experiment = model.experimentFromForm(form)
  assert.equal(experiment.acceptance_constraints[0].lower,0)
  form.acceptance[0].lower = 1
  form.models[0].version = 'v2'
  assert.equal(experiment.acceptance_constraints[0].lower,0)
  assert.equal(experiment.model_bindings[0].version,'v1')
  const reused = model.formFromExperiment(experiment)
  reused.acceptance[0].lower = 2
  assert.equal(experiment.acceptance_constraints[0].lower,0)
  const bad = (constraint) => ({...form,acceptance:[{metric:'vout',unit:'V',...constraint}]})
  assert.throws(() => model.experimentFromForm(bad({})),/at least one bound/)
  assert.throws(() => model.experimentFromForm(bad({lower:NaN})),/finite/)
  assert.throws(() => model.experimentFromForm(bad({lower:4,upper:3})),/lower bound/)
  assert.throws(() => model.experimentFromForm(bad({lower:0,unit:''})),/unit/)
  assert.throws(() => model.experimentFromForm(bad({lower:0,conditions:{temperature:Infinity}})),/finite/)
  assert.throws(() => model.experimentFromForm({...form,models:[{name:'Dfast',kind:'model',voltage_range:{min:2,max:1}}]}),/minimum/)
})

test('corner matrix editing preserves SPICE values, requires explicit supply/load parameters and caps Cartesian size', () => {
  const axes = model.cornerAxesFromForm([{kind:'temperature',parameter:'',values:'-40, 0, 85'},{kind:'load',parameter:'Rload',values:'1k 10k'}])
  assert.deepEqual(axes,[{kind:'temperature',values:[-40,0,85]},{kind:'load',parameter:'Rload',values:['1k','10k']}])
  assert.throws(() => model.cornerAxesFromForm([{kind:'supply',parameter:'',values:'3.3,5'}]),/existing .param/)
  assert.throws(() => model.cornerAxesFromForm([{kind:'temperature',parameter:'',values:'NaN'}]),/finite/)
  assert.throws(() => model.cornerAxesFromForm([{kind:'temperature',parameter:'',values:'0 1 2 3 4 5 6 7 8'},{kind:'parameter',parameter:'R',values:'0 1 2 3 4 5 6 7'}]),/64/)
})

test('numerical thresholds never interpret blank as zero or allow a non-refining factor', () => {
  const form = {toleranceFactor:'0.1',timestepFactor:'0.5',metrics:[{name:'vout',unit:'mV',absolute:'0',relative:'0.01'}]}
  assert.deepEqual(model.numericalFromForm(form).metrics,[{name:'vout',unit:'mV',absolute_tolerance:0,relative_tolerance:0.01}])
  assert.throws(() => model.numericalFromForm({...form,timestepFactor:'1'}),/factors/)
  assert.throws(() => model.numericalFromForm({...form,metrics:[{...form.metrics[0],absolute:''}]}),/explicit/)
  assert.throws(() => model.numericalFromForm({...form,metrics:[{...form.metrics[0],relative:'NaN'}]}),/finite/)
  assert.throws(() => model.numericalFromForm({...form,metrics:[{...form.metrics[0],unit:''}]}),/unit/)
})
