import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

function document(documentId, path, dirty = false) {
  return {
    documentId,
    path,
    name: path.slice(path.lastIndexOf('/') + 1),
    viewKind: 'code',
    revision: 1,
    content: dirty ? 'changed' : 'saved',
    savedContent: 'saved',
    mimeType: 'text/plain',
    readonly: false,
    dirty,
    missing: false,
  }
}

async function loadPathChanges() {
  const path = join(
    desktopRoot,
    'src',
    'renderer',
    'src',
    'features',
    'workspace',
    'documentPathChanges.ts',
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

test('workspace move rewrites an open directory subtree without losing edit state', async () => {
  const { rewriteDocumentsAfterMove } = await loadPathChanges()
  const moved = document('moved', 'circuits/stages/amplifier.cir', true)
  const unrelated = document('other', 'notes/readme.md')

  const result = rewriteDocumentsAfterMove(
    [moved, unrelated],
    'circuits',
    'archive/circuits',
  )

  assert.equal(result[0].path, 'archive/circuits/stages/amplifier.cir')
  assert.equal(result[0].name, 'amplifier.cir')
  assert.equal(result[0].documentId, 'moved')
  assert.equal(result[0].dirty, true)
  assert.equal(result[0].content, 'changed')
  assert.strictEqual(result[1], unrelated)
})

test('workspace delete closes clean tabs and retains dirty content fail-closed', async () => {
  const { reconcileDocumentsAfterDelete } = await loadPathChanges()
  const clean = document('clean', 'circuits/clean.cir')
  const dirty = document('dirty', 'circuits/nested/dirty.cir', true)
  const unrelated = document('other', 'notes/readme.md')

  const result = reconcileDocumentsAfterDelete(
    [clean, dirty, unrelated],
    'circuits',
  )

  assert.deepEqual(result.closedDocumentIds, ['clean'])
  assert.deepEqual(result.retainedDirtyDocumentIds, ['dirty'])
  assert.deepEqual(result.documents.map((item) => item.documentId), ['dirty', 'other'])
  assert.equal(result.documents[0].content, 'changed')
  assert.equal(result.documents[0].dirty, true)
  assert.equal(result.documents[0].readonly, true)
  assert.equal(result.documents[0].missing, true)
  assert.strictEqual(result.documents[1], unrelated)
})

test('workspace wires authoritative move and delete events to document reconciliation', async () => {
  const feature = await readFile(
    join(desktopRoot, 'src', 'renderer', 'src', 'features', 'workspace', 'WorkspaceFeature.tsx'),
    'utf8',
  )
  assert.match(feature, /event\.type === 'workspace\.entry_moved'[\s\S]{0,500}applyDocumentMove\(sourcePath, destinationPath\)/)
  assert.match(feature, /event\.type === 'workspace\.entry_deleted'[\s\S]{0,400}applyDocumentDelete\(deletedPath\)/)
  assert.doesNotMatch(feature, /workspace\.entry_modified/)
})
