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
      activeTab: 'chart',
      visibleSeriesIds: ['V(out)', 'V(out)'],
      cursorA: 1_000,
      cursorB: 10_000,
      cursorTarget: 'b',
    },
    conversation: {
      sessionId: 'session-1',
      activeSurface: 'rag',
      draftText: 'Continue from the previous design.',
    },
  }
}

test('normalization accepts the v1 contract and canonicalizes series identities', () => {
  const normalized = workSession.normalizeWorkSession(populatedSession())
  assert.ok(normalized)
  assert.deepEqual(normalized.simulation.visibleSeriesIds, ['V(out)'])
  assert.equal(normalized.workspace.openDocuments[0].unsavedContent, 'R1 in out 10k\n')
  assert.equal(normalized.conversation.activeSurface, 'rag')
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
  assert.equal(populated.simulation.activeTab, 'chart')
  assert.equal(populated.conversation.draftText, 'Continue from the previous design.')

  const preserved = workSession.beginWorkSessionProject('e:/circuit demo')
  assert.deepEqual(preserved, populated)

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
