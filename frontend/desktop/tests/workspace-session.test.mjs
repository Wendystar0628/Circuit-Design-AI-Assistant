import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

function document(documentId, path, content) {
  return {
    documentId,
    path,
    name: path.slice(path.lastIndexOf('/') + 1),
    viewKind: 'code',
    revision: 1,
    content,
    savedContent: content,
    mimeType: 'text/plain',
    readonly: false,
    dirty: false,
    missing: false,
    cursorLine: 1,
    cursorColumn: 1,
    markdownPreview: true,
  }
}

async function loadWorkspaceRestore() {
  const path = join(
    desktopRoot,
    'src',
    'renderer',
    'src',
    'features',
    'workspace',
    'workspaceRestore.ts',
  )
  const source = await readFile(path, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: path,
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

test('workspace restore keeps tab order and rebinds drafts to fresh document identities', async () => {
  const { restoreWorkspaceDocuments } = await loadWorkspaceRestore()
  const snapshots = [
    { path: 'first.cir', cursorLine: 7, cursorColumn: 4, markdownPreview: false },
    {
      path: 'second.cir',
      unsavedContent: 'restored draft',
      savedContent: 'saved before exit',
      cursorLine: 11,
      cursorColumn: 9,
    },
  ]
  const fresh = [
    document('new-first-id', 'first.cir', 'current first'),
    { ...document('new-second-id', 'second.cir', 'saved before exit'), revision: 1 },
  ]

  const restored = restoreWorkspaceDocuments(snapshots, fresh)

  assert.deepEqual(restored.documents.map((item) => item.path), ['first.cir', 'second.cir'])
  assert.equal(restored.documents[1].documentId, 'new-second-id')
  assert.equal(restored.documents[1].revision, 1)
  assert.equal(restored.documents[1].content, 'restored draft')
  assert.equal(restored.documents[1].savedContent, 'saved before exit')
  assert.equal(restored.documents[1].dirty, true)
  assert.equal(restored.documents[0].cursorLine, 7)
  assert.equal(restored.documents[0].cursorColumn, 4)
  assert.equal(restored.documents[0].markdownPreview, false)
  assert.deepEqual(restored.conflictPaths, [])
})

test('workspace restore preserves the draft and reports when disk content changed', async () => {
  const { restoreWorkspaceDocuments } = await loadWorkspaceRestore()
  const snapshot = {
    path: 'main.cir',
    unsavedContent: 'local draft',
    savedContent: 'old disk content',
  }
  const fresh = { ...document('fresh-id', 'main.cir', 'externally changed'), revision: 3 }

  const restored = restoreWorkspaceDocuments([snapshot], [fresh])

  assert.deepEqual(restored.conflictPaths, ['main.cir'])
  assert.equal(restored.documents[0].documentId, 'fresh-id')
  assert.equal(restored.documents[0].revision, 3)
  assert.equal(restored.documents[0].content, 'local draft')
  assert.equal(restored.documents[0].savedContent, 'externally changed')
  assert.equal(restored.documents[0].dirty, true)
})

test('workspace restore ignores unavailable tabs and resolves the active path against fresh ids', async () => {
  const { restoreWorkspaceDocuments, restoredActiveDocumentId } = await loadWorkspaceRestore()
  const snapshots = [
    { path: 'missing.cir' },
    { path: 'available.cir', cursorLine: -2, cursorColumn: Number.NaN },
  ]
  const restored = restoreWorkspaceDocuments(
    snapshots,
    [null, document('fresh-available', 'available.cir', 'content')],
  )

  assert.deepEqual(restored.documents.map((item) => item.path), ['available.cir'])
  assert.equal(restored.documents[0].cursorLine, 1)
  assert.equal(restored.documents[0].cursorColumn, 1)
  assert.equal(
    restoredActiveDocumentId(restored.documents, 'available.cir'),
    'fresh-available',
  )
  assert.equal(
    restoredActiveDocumentId(restored.documents, 'missing.cir'),
    'fresh-available',
  )
})
