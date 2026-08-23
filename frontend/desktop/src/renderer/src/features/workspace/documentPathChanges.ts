import type { WorkspaceDocument } from './types'

export function pathOwns(candidate: string, root: string): boolean {
  return candidate === root || candidate.startsWith(`${root}/`)
}

function fileName(path: string): string {
  const separator = path.lastIndexOf('/')
  return separator < 0 ? path : path.slice(separator + 1)
}

export function rewriteDocumentsAfterMove(
  documents: WorkspaceDocument[],
  sourcePath: string,
  destinationPath: string,
): WorkspaceDocument[] {
  if (!sourcePath || !destinationPath || sourcePath === destinationPath) return documents
  let changed = false
  const next = documents.map((document) => {
    if (!pathOwns(document.path, sourcePath)) return document
    changed = true
    const path = `${destinationPath}${document.path.slice(sourcePath.length)}`
    return { ...document, path, name: fileName(path) }
  })
  return changed ? next : documents
}

export interface DeletedDocumentReconciliation {
  documents: WorkspaceDocument[]
  closedDocumentIds: string[]
  retainedDirtyDocumentIds: string[]
}

export function reconcileDocumentsAfterDelete(
  documents: WorkspaceDocument[],
  deletedPath: string,
): DeletedDocumentReconciliation {
  if (!deletedPath) {
    return { documents, closedDocumentIds: [], retainedDirtyDocumentIds: [] }
  }
  const remaining: WorkspaceDocument[] = []
  const closedDocumentIds: string[] = []
  const retainedDirtyDocumentIds: string[] = []
  let affected = false
  for (const document of documents) {
    if (!pathOwns(document.path, deletedPath)) {
      remaining.push(document)
    } else if (document.dirty) {
      affected = true
      retainedDirtyDocumentIds.push(document.documentId)
      remaining.push({ ...document, readonly: true, missing: true })
    } else {
      affected = true
      closedDocumentIds.push(document.documentId)
    }
  }
  return {
    documents: affected ? remaining : documents,
    closedDocumentIds,
    retainedDirtyDocumentIds,
  }
}
