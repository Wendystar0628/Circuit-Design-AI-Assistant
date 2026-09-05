import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import typescript from 'typescript'

class MemoryStorage {
  constructor(initial = {}) {
    this.values = new Map(Object.entries(initial))
  }

  getItem(key) {
    return this.values.get(key) ?? null
  }

  setItem(key, value) {
    this.values.set(key, value)
  }

  removeItem(key) {
    this.values.delete(key)
  }
}

const browserStorage = new MemoryStorage()
Object.defineProperty(globalThis, 'window', {
  configurable: true,
  value: { localStorage: browserStorage },
})

const sourcePath = new URL('../src/renderer/src/lib/workSession.ts', import.meta.url)
const source = await readFile(fileURLToPath(sourcePath), 'utf8')
const compiled = typescript.transpileModule(source, {
  compilerOptions: {
    module: typescript.ModuleKind.ES2022,
    target: typescript.ScriptTarget.ES2022,
  },
  fileName: fileURLToPath(sourcePath),
}).outputText
const workSession = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

function populatedSession() {
  return {
    version: 1,
    projectRoot: 'E:\\Circuit Demo',
    workspace: {
      openDocuments: [{
        path: 'circuits/filter.cir',
        unsavedContent: 'R1 in out 10k\n',
        savedContent: 'R1 in out 1k\n',
        cursorLine: 1,
        cursorColumn: 14,
        markdownPreview: false,
      }],
      activeDocumentPath: 'circuits/filter.cir',
      explorerCollapsed: true,
    },
    simulation: {
      selectedResultPath: 'simulation_results/filter/run/result.json',
      baselineResultPath: 'simulation_results/filter/baseline/result.json',
      activeTab: 'waveforms',
      traces: [
        { signal: 'V(out)', reference: 'V(in)', component: 'db' },
        { signal: 'V(out)', reference: 'V(in)', component: 'db' },
      ],
      cursorA: 1_000,
      cursorB: 10_000,
      cursorTarget: 'b',
      xRange: [100, 100_000],
    },
    conversation: {
      sessionId: 'session-1',
      activeSurface: 'rag',
      draftText: 'Continue from the previous design.',
    },
  }
}

test('normalization preserves experiment state and canonicalizes trace expressions', () => {
  const normalized = workSession.normalizeWorkSession(populatedSession())
  assert.ok(normalized)
  assert.deepEqual(normalized.simulation.traces, [{ signal: 'V(out)', reference: 'V(in)', component: 'db' }])
  assert.equal(normalized.simulation.baselineResultPath, 'simulation_results/filter/baseline/result.json')
  assert.deepEqual(normalized.simulation.xRange, [100, 100_000])
  assert.equal(normalized.workspace.openDocuments[0].unsavedContent, 'R1 in out 10k\n')
  assert.equal(normalized.conversation.activeSurface, 'rag')
})

test('old simulation presentation state migrates without losing workspace or conversation', () => {
  const original = populatedSession()
  for (const [previousTab, nextTab] of Object.entries({ chart: 'waveforms', waveform: 'waveforms', metrics: 'measurements', schematic: 'topology', analysis: 'experiment', export: 'experiment', runs: 'experiment', raw: 'raw', log: 'log' })) {
    const storage = new MemoryStorage({
      [workSession.WORK_SESSION_STORAGE_KEY]: JSON.stringify({
        ...original,
        simulation: {
          selectedResultPath: original.simulation.selectedResultPath,
          activeTab: previousTab, visibleSeriesIds: ['V(out)'],
          cursorA: 1_000, cursorB: 10_000, cursorTarget: 'b',
        },
      }),
    })
    const restored = workSession.loadWorkSession(storage)
    assert.deepEqual(restored.workspace, original.workspace)
    assert.deepEqual(restored.conversation, original.conversation)
    assert.deepEqual(restored.simulation, {
      ...workSession.emptyWorkSession().simulation,
      selectedResultPath: original.simulation.selectedResultPath,
      activeTab: nextTab,
    })
  }
})

test('trace identity includes transfer reference and rejects invalid transform or viewport state', () => {
  const session = populatedSession()
  session.simulation.traces = [
    { signal: 'V(out)', component: 'db' },
    { signal: 'V(out)', reference: null, component: 'db' },
    { signal: 'V(out)', reference: 'V(in)', component: 'db' },
    { signal: 'V(out)', reference: 'V(in)', component: 'phase' },
  ]
  assert.equal(workSession.normalizeWorkSession(session).simulation.traces.length, 3)
  for (const xRange of [[2, 1], [1, 1], [0, Number.POSITIVE_INFINITY], [0]]) {
    assert.equal(workSession.normalizeWorkSession({ ...session, simulation: { ...session.simulation, xRange } }), null)
  }
  assert.equal(workSession.normalizeWorkSession({ ...session, simulation: { ...session.simulation, traces: [{ signal: 'V(out)', component: 'wrapped-legacy' }] } }), null)
})

test('invalid, corrupt, and unknown-version storage is discarded as an empty v1 session', () => {
  const corrupt = new MemoryStorage({
    [workSession.WORK_SESSION_STORAGE_KEY]: '{not-json',
  })
  assert.deepEqual(workSession.loadWorkSession(corrupt), workSession.emptyWorkSession())
  assert.equal(corrupt.getItem(workSession.WORK_SESSION_STORAGE_KEY), null)

  const unknown = new MemoryStorage({
    [workSession.WORK_SESSION_STORAGE_KEY]: JSON.stringify({ ...populatedSession(), version: 2 }),
  })
  assert.deepEqual(workSession.loadWorkSession(unknown), workSession.emptyWorkSession())
  assert.equal(unknown.getItem(workSession.WORK_SESSION_STORAGE_KEY), null)

  assert.equal(
    workSession.normalizeWorkSession({
      ...populatedSession(),
      simulation: { ...populatedSession().simulation, activeTab: 'legacy-plot' },
    }),
    null,
  )
})

test('pure persistence uses the one work-session key and round-trips the normalized snapshot', () => {
  const storage = new MemoryStorage()
  const persisted = workSession.persistWorkSession(storage, populatedSession())
  assert.deepEqual([...storage.values.keys()], [workSession.WORK_SESSION_STORAGE_KEY])
  assert.deepEqual(workSession.loadWorkSession(storage), persisted)
})

test('singleton project lifecycle preserves the same Windows root and rejects stale slice writes', () => {
  const first = workSession.beginWorkSessionProject('E:\\Circuit Demo\\')
  assert.equal(first.projectRoot, 'E:\\Circuit Demo\\')

  workSession.updateWorkspaceSession('e:/circuit demo', populatedSession().workspace)
  workSession.updateSimulationSession('E:/CIRCUIT DEMO/', populatedSession().simulation)
  workSession.updateConversationSession('e:\\circuit demo', populatedSession().conversation)
  const populated = workSession.getWorkSession()
  assert.equal(populated.workspace.openDocuments.length, 1)
  assert.equal(populated.simulation.activeTab, 'waveforms')
  assert.equal(populated.conversation.draftText, 'Continue from the previous design.')

  const preserved = workSession.beginWorkSessionProject('e:/circuit demo')
  assert.deepEqual(preserved, populated)
  preserved.simulation.traces[0].signal = 'mutated'
  preserved.simulation.xRange[0] = -999
  assert.deepEqual(workSession.getWorkSession().simulation, populated.simulation)

  workSession.updateConversationSession('D:\\stale-project', {
    sessionId: null,
    activeSurface: 'conversation',
    draftText: 'must not replace current project state',
  })
  assert.equal(workSession.getWorkSession().conversation.draftText, populated.conversation.draftText)

  assert.equal(workSession.forgetWorkSessionProject('D:\\stale-project').projectRoot, populated.projectRoot)
  assert.deepEqual(
    workSession.forgetWorkSessionProject('E:\\Circuit Demo'),
    workSession.emptyWorkSession(),
  )
})
