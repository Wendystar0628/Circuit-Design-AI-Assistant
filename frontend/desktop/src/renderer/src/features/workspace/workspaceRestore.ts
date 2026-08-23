import type { WorkspaceDocument } from './types'

export interface WorkspaceDocumentSnapshot {
  path: string
  unsavedContent?: string | null
  savedContent?: string | null
  cursorLine?: number
  cursorColumn?: number
  markdownPreview?: boolean
}

export interface WorkspaceRestoreResult {
  documents: WorkspaceDocument[]
  conflictPaths: string[]
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
    ? value
    : fallback
}

export function restoreWorkspaceDocuments(
  snapshots: readonly WorkspaceDocumentSnapshot[],
  freshDocuments: readonly (WorkspaceDocument | null)[],
): WorkspaceRestoreResult {
  const documents: WorkspaceDocument[] = []
  const conflictPaths: string[] = []

  snapshots.forEach((snapshot, index) => {
    const fresh = freshDocuments[index]
    if (!fresh || fresh.path !== snapshot.path) return
    const hasDraft = typeof snapshot.unsavedContent === 'string'
      && typeof snapshot.savedContent === 'string'
    if (
      hasDraft
      && snapshot.unsavedContent !== fresh.content
      && fresh.content !== snapshot.savedContent
    ) {
      conflictPaths.push(snapshot.path)
    }
    documents.push({
      ...fresh,
      content: hasDraft ? snapshot.unsavedContent as string : fresh.content,
      savedContent: fresh.content,
      dirty: hasDraft && snapshot.unsavedContent !== fresh.content,
      cursorLine: positiveInteger(snapshot.cursorLine, 1),
      cursorColumn: positiveInteger(snapshot.cursorColumn, 1),
      markdownPreview: snapshot.markdownPreview !== false,
    })
  })

  return { documents, conflictPaths }
}

export function restoredActiveDocumentId(
  documents: readonly WorkspaceDocument[],
  activePath: string | null,
): string | null {
  if (activePath) {
    const active = documents.find((document) => document.path === activePath)
    if (active) return active.documentId
  }
  return documents[0]?.documentId ?? null
}
