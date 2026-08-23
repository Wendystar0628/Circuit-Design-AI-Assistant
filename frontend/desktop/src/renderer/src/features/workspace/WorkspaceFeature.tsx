import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, errorMessage, eventsClient, projectApi, workspaceApi } from './apiPort'
import {
  pathOwns,
  reconcileDocumentsAfterDelete,
  rewriteDocumentsAfterMove,
} from './documentPathChanges'
import { EditorArea } from './EditorArea'
import { WorkspaceDialog, type WorkspaceDialogState } from './WorkspaceDialog'
import { WorkspaceTree, type TreeEntryAction } from './WorkspaceTree'
import {
  documentFromWire,
  projectFromWire,
  treeEntryFromWire,
  type ProjectSummary,
  type WorkspaceDocument,
  type WorkspaceTreeEntry,
} from './types'
import './workspace.css'

export interface WorkspaceFeatureProps {
  active: boolean
  onProjectChange?: (project: { id: string; name: string; root: string } | null) => void
  onActiveDocumentChange?: (document: { documentId: string; path: string; revision: string } | null) => void
  openDocumentRequest?: { path: string; requestId: number } | null
}

type ProjectTransition = 'open' | 'close'

function updateTreeEntry(
  entries: WorkspaceTreeEntry[],
  path: string,
  update: (entry: WorkspaceTreeEntry) => WorkspaceTreeEntry,
): WorkspaceTreeEntry[] {
  return entries.map((entry) => {
    if (entry.path === path) return update(entry)
    if (!entry.children) return entry
    const children = updateTreeEntry(entry.children, path, update)
    return children === entry.children ? entry : { ...entry, children }
  })
}

function parentPath(path: string): string {
  const separator = path.lastIndexOf('/')
  return separator < 0 ? '' : path.slice(0, separator)
}

function joinedPath(parent: string, name: string): string {
  return parent ? `${parent}/${name}` : name
}

function validEntryName(name: string): boolean {
  return Boolean(name)
    && name !== '.'
    && name !== '..'
    && !name.includes('/')
    && !name.includes('\\')
    && !name.includes(':')
    && !name.includes('\0')
}

export function WorkspaceFeature({
  active,
  onProjectChange,
  onActiveDocumentChange,
  openDocumentRequest,
}: WorkspaceFeatureProps) {
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [tree, setTree] = useState<WorkspaceTreeEntry[]>([])
  const [documents, setDocuments] = useState<WorkspaceDocument[]>([])
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null)
  const [treeLoading, setTreeLoading] = useState(false)
  const [projectBusy, setProjectBusy] = useState(false)
  const [savingDocumentIds, setSavingDocumentIds] = useState<ReadonlySet<string>>(new Set())
  const [explorerCollapsed, setExplorerCollapsed] = useState(false)
  const [dialog, setDialog] = useState<WorkspaceDialogState | null>(null)
  const [dialogBusy, setDialogBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [cursor, setCursor] = useState({ line: 1, column: 1 })

  const projectRef = useRef<ProjectSummary | null>(null)
  const documentsRef = useRef<WorkspaceDocument[]>([])
  const activeDocumentIdRef = useRef<string | null>(null)
  const onProjectChangeRef = useRef(onProjectChange)
  const onActiveDocumentChangeRef = useRef(onActiveDocumentChange)
  const projectEpochRef = useRef(0)
  const rootTreeRequestRef = useRef(0)
  const subtreeRequestRef = useRef(new Map<string, number>())
  const openDocumentRequestRef = useRef(0)
  const handledExternalOpenRequestRef = useRef<number | null>(null)
  const documentReloadRequestRef = useRef(new Map<string, number>())
  const saveRequestRef = useRef(new Map<string, number>())
  const saveRequestNonceRef = useRef(0)
  const savesInFlightRef = useRef(new Set<string>())
  const lastEventSequenceRef = useRef(0)
  const pendingProjectTransitionRef = useRef<ProjectTransition | null>(null)

  onProjectChangeRef.current = onProjectChange
  onActiveDocumentChangeRef.current = onActiveDocumentChange

  const replaceDocuments = useCallback((update: (documents: WorkspaceDocument[]) => WorkspaceDocument[]) => {
    const next = update(documentsRef.current)
    documentsRef.current = next
    setDocuments(next)
  }, [])

  const activateDocument = useCallback((documentId: string | null) => {
    activeDocumentIdRef.current = documentId
    setActiveDocumentId(documentId)
    setCursor({ line: 1, column: 1 })
  }, [])

  const replaceProject = useCallback((nextProject: ProjectSummary | null) => {
    projectRef.current = nextProject
    setProject(nextProject)
    setTree([])
    documentsRef.current = []
    setDocuments([])
    activateDocument(null)
    subtreeRequestRef.current.clear()
    documentReloadRequestRef.current.clear()
    saveRequestRef.current.clear()
    savesInFlightRef.current.clear()
    setSavingDocumentIds(new Set())
    lastEventSequenceRef.current = 0
    onProjectChangeRef.current?.(
      nextProject
        ? { id: nextProject.id, name: nextProject.name, root: nextProject.root }
        : null,
    )
  }, [activateDocument])

  const refreshTreeFor = useCallback(async (
    expectedProject: ProjectSummary,
    expectedEpoch: number,
    showLoading = true,
  ) => {
    const requestId = rootTreeRequestRef.current + 1
    rootTreeRequestRef.current = requestId
    if (showLoading) setTreeLoading(true)
    try {
      const response = await workspaceApi.tree(expectedProject.id)
      if (
        projectEpochRef.current !== expectedEpoch
        || projectRef.current?.id !== expectedProject.id
        || rootTreeRequestRef.current !== requestId
        || response.project_id !== expectedProject.id
      ) return
      const incoming = response.entries.map(treeEntryFromWire)
      setTree(incoming)
      subtreeRequestRef.current.clear()
    } catch (error) {
      if (projectEpochRef.current === expectedEpoch && projectRef.current?.id === expectedProject.id) {
        setNotice(errorMessage(error))
      }
    } finally {
      if (rootTreeRequestRef.current === requestId) setTreeLoading(false)
    }
  }, [])

  useEffect(() => {
    let disposed = false
    const epoch = projectEpochRef.current + 1
    projectEpochRef.current = epoch
    setProjectBusy(true)
    projectApi.current()
      .then((wire) => {
        if (disposed || projectEpochRef.current !== epoch) return
        const current = wire ? projectFromWire(wire) : null
        replaceProject(current)
        if (current) void refreshTreeFor(current, epoch)
      })
      .catch((error) => {
        if (!disposed && projectEpochRef.current === epoch) setNotice(errorMessage(error))
      })
      .finally(() => {
        if (!disposed && projectEpochRef.current === epoch) setProjectBusy(false)
      })
    return () => {
      disposed = true
    }
  }, [refreshTreeFor, replaceProject])

  const activeDocument = documents.find((document) => document.documentId === activeDocumentId) ?? null

  useEffect(() => {
    onActiveDocumentChangeRef.current?.(
      activeDocument && !activeDocument.missing
        ? {
            documentId: activeDocument.documentId,
            path: activeDocument.path,
            revision: String(activeDocument.revision),
          }
        : null,
    )
  }, [activeDocument?.documentId, activeDocument?.missing, activeDocument?.path, activeDocument?.revision])

  const openDocumentPath = useCallback(async (path: string) => {
    const currentProject = projectRef.current
    if (!currentProject || !path) return
    const existing = documentsRef.current.find((document) => document.path === path)
    openDocumentRequestRef.current += 1
    if (existing) {
      activateDocument(existing.documentId)
      return
    }
    const requestId = openDocumentRequestRef.current
    const expectedEpoch = projectEpochRef.current
    try {
      const response = await workspaceApi.document(currentProject.id, path)
      if (
        projectEpochRef.current !== expectedEpoch
        || projectRef.current?.id !== currentProject.id
        || openDocumentRequestRef.current !== requestId
        || response.project_id !== currentProject.id
        || response.path !== path
      ) return
      const document = documentFromWire(response)
      replaceDocuments((current) => {
        const withoutExisting = current.filter((candidate) => candidate.documentId !== document.documentId)
        return [...withoutExisting, document]
      })
      activateDocument(document.documentId)
    } catch (error) {
      if (projectEpochRef.current === expectedEpoch) setNotice(errorMessage(error))
    }
  }, [activateDocument, replaceDocuments])

  useEffect(() => {
    if (
      !project
      || !openDocumentRequest
      || !openDocumentRequest.path
      || handledExternalOpenRequestRef.current === openDocumentRequest.requestId
    ) return
    handledExternalOpenRequestRef.current = openDocumentRequest.requestId
    void openDocumentPath(openDocumentRequest.path)
  }, [openDocumentPath, openDocumentRequest, project])

  const toggleDirectory = useCallback(async (entry: WorkspaceTreeEntry) => {
    const currentProject = projectRef.current
    if (!currentProject || entry.kind !== 'directory') return
    if (entry.expanded) {
      subtreeRequestRef.current.set(
        entry.path,
        (subtreeRequestRef.current.get(entry.path) ?? 0) + 1,
      )
      setTree((current) => updateTreeEntry(current, entry.path, (item) => ({
        ...item,
        expanded: false,
        loading: false,
      })))
      return
    }
    if (entry.children) {
      setTree((current) => updateTreeEntry(current, entry.path, (item) => ({ ...item, expanded: true })))
      return
    }
    const expectedEpoch = projectEpochRef.current
    const requestId = (subtreeRequestRef.current.get(entry.path) ?? 0) + 1
    subtreeRequestRef.current.set(entry.path, requestId)
    setTree((current) => updateTreeEntry(current, entry.path, (item) => ({ ...item, expanded: true, loading: true })))
    try {
      const response = await workspaceApi.tree(currentProject.id, entry.path)
      if (
        projectEpochRef.current !== expectedEpoch
        || projectRef.current?.id !== currentProject.id
        || subtreeRequestRef.current.get(entry.path) !== requestId
        || response.project_id !== currentProject.id
      ) return
      const children = response.entries.map(treeEntryFromWire)
      setTree((current) => updateTreeEntry(current, entry.path, (item) => ({
        ...item,
        expanded: true,
        loading: false,
        children,
      })))
    } catch (error) {
      if (projectEpochRef.current === expectedEpoch) {
        setTree((current) => updateTreeEntry(current, entry.path, (item) => ({ ...item, loading: false })))
        setNotice(errorMessage(error))
      }
    }
  }, [])

  const changeContent = useCallback((documentId: string, content: string) => {
    replaceDocuments((current) => current.map((document) => (
      document.documentId === documentId && !document.readonly
        ? { ...document, content, dirty: content !== document.savedContent }
        : document
    )))
  }, [replaceDocuments])

  const saveDocument = useCallback(async (documentId: string): Promise<boolean> => {
    const currentProject = projectRef.current
    const document = documentsRef.current.find((candidate) => candidate.documentId === documentId)
    if (!currentProject || !document) return false
    if (document.missing) {
      setNotice(`${document.name} was deleted on disk. Copy its contents or discard the tab.`)
      return false
    }
    if (document.readonly) return !document.dirty
    if (!document.dirty) return true
    if (savesInFlightRef.current.has(documentId)) return false
    savesInFlightRef.current.add(documentId)
    const requestId = saveRequestNonceRef.current + 1
    saveRequestNonceRef.current = requestId
    saveRequestRef.current.set(documentId, requestId)
    const expectedEpoch = projectEpochRef.current
    const savedContent = document.content
    setSavingDocumentIds((current) => new Set(current).add(documentId))
    try {
      const response = await workspaceApi.saveDocument(
        currentProject.id,
        document.path,
        document.documentId,
        document.revision,
        savedContent,
      )
      if (
        projectEpochRef.current !== expectedEpoch
        || projectRef.current?.id !== currentProject.id
        || saveRequestRef.current.get(documentId) !== requestId
        || response.project_id !== currentProject.id
        || response.document_id !== documentId
        || response.path !== document.path
      ) return false
      const latest = documentsRef.current.find((candidate) => candidate.documentId === documentId)
      if (!latest || latest.revision !== document.revision) return false
      replaceDocuments((current) => current.map((candidate) => (
        candidate.documentId === documentId && candidate.revision === document.revision
          ? {
              ...candidate,
              revision: response.revision,
              savedContent,
              dirty: candidate.content !== savedContent,
            }
          : candidate
      )))
      return true
    } catch (error) {
      if (projectEpochRef.current === expectedEpoch) {
        setNotice(error instanceof ApiError && error.status === 409
          ? 'The file changed on disk. Reload it before saving again.'
          : errorMessage(error))
      }
      return false
    } finally {
      if (saveRequestRef.current.get(documentId) === requestId) {
        savesInFlightRef.current.delete(documentId)
        setSavingDocumentIds((current) => {
          const next = new Set(current)
          next.delete(documentId)
          return next
        })
      }
    }
  }, [replaceDocuments])

  const closeDocumentNow = useCallback((documentId: string) => {
    const current = documentsRef.current
    const index = current.findIndex((document) => document.documentId === documentId)
    if (index < 0) return
    const next = current.filter((document) => document.documentId !== documentId)
    documentsRef.current = next
    setDocuments(next)
    if (activeDocumentIdRef.current === documentId) {
      activateDocument(next[Math.min(index, next.length - 1)]?.documentId ?? null)
    }
  }, [activateDocument])

  const applyDocumentMove = useCallback((sourcePath: string, destinationPath: string) => {
    replaceDocuments((current) => rewriteDocumentsAfterMove(current, sourcePath, destinationPath))
  }, [replaceDocuments])

  const applyDocumentDelete = useCallback((deletedPath: string) => {
    const current = documentsRef.current
    const result = reconcileDocumentsAfterDelete(current, deletedPath)
    if (result.documents === current) return
    const activeId = activeDocumentIdRef.current
    const activeIndex = activeId
      ? current.findIndex((document) => document.documentId === activeId)
      : -1
    documentsRef.current = result.documents
    setDocuments(result.documents)
    if (activeId && result.closedDocumentIds.includes(activeId)) {
      activateDocument(result.documents[Math.min(activeIndex, result.documents.length - 1)]?.documentId ?? null)
    }
    if (result.retainedDirtyDocumentIds.length) {
      setNotice('A changed document was deleted on disk. Its contents remain available read-only until you copy or discard them.')
    }
  }, [activateDocument])

  const requestCloseDocument = useCallback((documentId: string) => {
    const document = documentsRef.current.find((candidate) => candidate.documentId === documentId)
    if (!document) return
    if (document.dirty) setDialog({ kind: 'dirty-document', documentId })
    else closeDocumentNow(documentId)
  }, [closeDocumentNow])

  const beginOpenProject = useCallback(async () => {
    setProjectBusy(true)
    try {
      const path = await window.circuitDesktop.selectDirectory()
      if (!path) return
      const epoch = projectEpochRef.current + 1
      projectEpochRef.current = epoch
      const response = await projectApi.open(path)
      if (projectEpochRef.current !== epoch) return
      const nextProject = projectFromWire(response)
      replaceProject(nextProject)
      await refreshTreeFor(nextProject, epoch)
    } catch (error) {
      setNotice(errorMessage(error))
    } finally {
      setProjectBusy(false)
    }
  }, [refreshTreeFor, replaceProject])

  const requestOpenProject = useCallback(() => {
    if (documentsRef.current.some((document) => document.dirty)) {
      pendingProjectTransitionRef.current = 'open'
      setDialog({ kind: 'dirty-project' })
      return
    }
    void beginOpenProject()
  }, [beginOpenProject])

  const closeProjectNow = useCallback(async () => {
    const currentProject = projectRef.current
    if (!currentProject) return
    setProjectBusy(true)
    const epoch = projectEpochRef.current + 1
    projectEpochRef.current = epoch
    try {
      await projectApi.close(currentProject.id)
      if (projectEpochRef.current === epoch && projectRef.current?.id === currentProject.id) {
        replaceProject(null)
      }
    } catch (error) {
      if (projectEpochRef.current === epoch) setNotice(errorMessage(error))
    } finally {
      setProjectBusy(false)
    }
  }, [replaceProject])

  const requestCloseProject = useCallback(() => {
    if (!projectRef.current) return
    if (documentsRef.current.some((document) => document.dirty)) {
      pendingProjectTransitionRef.current = 'close'
      setDialog({ kind: 'dirty-project' })
      return
    }
    void closeProjectNow()
  }, [closeProjectNow])

  const requestEntryAction = useCallback((action: TreeEntryAction, entry: WorkspaceTreeEntry | null) => {
    if (!projectRef.current) return
    if ((action === 'rename' || action === 'delete') && entry) {
      const hasDirtyOwner = documentsRef.current.some(
        (document) => document.dirty && pathOwns(document.path, entry.path),
      )
      if (hasDirtyOwner) {
        setNotice('Save or close changed documents before renaming or deleting this entry.')
        return
      }
    }
    setDialog({ kind: action, entry })
  }, [])

  const confirmEntryAction = useCallback(async (name: string) => {
    const currentProject = projectRef.current
    const currentDialog = dialog
    if (!currentProject || !currentDialog || currentDialog.kind.startsWith('dirty')) return
    if (currentDialog.kind !== 'delete' && !validEntryName(name)) {
      setNotice('Use a single file or folder name without path separators.')
      return
    }
    const expectedEpoch = projectEpochRef.current
    let movedEntry: { sourcePath: string; destinationPath: string } | null = null
    let deletedPath = ''
    setDialogBusy(true)
    try {
      if (currentDialog.kind === 'create-file' || currentDialog.kind === 'create-directory') {
        const parent = currentDialog.entry?.kind === 'directory' ? currentDialog.entry.path : ''
        await workspaceApi.createEntry(
          currentProject.id,
          parent,
          name,
          currentDialog.kind === 'create-file' ? 'file' : 'directory',
        )
      } else if (currentDialog.kind === 'rename' && currentDialog.entry) {
        const destination = joinedPath(parentPath(currentDialog.entry.path), name)
        await workspaceApi.moveEntry(currentProject.id, currentDialog.entry.path, destination)
        movedEntry = { sourcePath: currentDialog.entry.path, destinationPath: destination }
      } else if (currentDialog.kind === 'delete' && currentDialog.entry) {
        await workspaceApi.deleteEntry(currentProject.id, currentDialog.entry.path)
        deletedPath = currentDialog.entry.path
      }
      if (projectEpochRef.current !== expectedEpoch || projectRef.current?.id !== currentProject.id) return
      if (movedEntry) applyDocumentMove(movedEntry.sourcePath, movedEntry.destinationPath)
      if (deletedPath) applyDocumentDelete(deletedPath)
      setDialog(null)
      await refreshTreeFor(currentProject, expectedEpoch, false)
    } catch (error) {
      if (projectEpochRef.current === expectedEpoch) setNotice(errorMessage(error))
    } finally {
      setDialogBusy(false)
    }
  }, [applyDocumentDelete, applyDocumentMove, dialog, refreshTreeFor])

  const resolveDirtyDialog = useCallback(async (action: 'save' | 'discard') => {
    const currentDialog = dialog
    if (!currentDialog || (currentDialog.kind !== 'dirty-document' && currentDialog.kind !== 'dirty-project')) return
    setDialogBusy(true)
    try {
      if (action === 'save') {
        const targets = currentDialog.kind === 'dirty-document'
          ? documentsRef.current.filter((document) => document.documentId === currentDialog.documentId && document.dirty)
          : documentsRef.current.filter((document) => document.dirty)
        for (const document of targets) {
          if (!await saveDocument(document.documentId)) return
        }
      }
      setDialog(null)
      if (currentDialog.kind === 'dirty-document') {
        closeDocumentNow(currentDialog.documentId)
        return
      }
      const transition = pendingProjectTransitionRef.current
      pendingProjectTransitionRef.current = null
      if (transition === 'open') await beginOpenProject()
      else if (transition === 'close') await closeProjectNow()
    } finally {
      setDialogBusy(false)
    }
  }, [beginOpenProject, closeDocumentNow, closeProjectNow, dialog, saveDocument])

  const reloadCleanDocument = useCallback(async (projectId: string, documentId: string, path: string) => {
    const current = documentsRef.current.find((document) => document.documentId === documentId)
    if (!current) return
    if (current.dirty) {
      setNotice(`${current.name} changed on disk while it has unsaved edits.`)
      return
    }
    const requestId = (documentReloadRequestRef.current.get(documentId) ?? 0) + 1
    documentReloadRequestRef.current.set(documentId, requestId)
    const expectedEpoch = projectEpochRef.current
    try {
      const response = await workspaceApi.document(projectId, path)
      if (
        projectEpochRef.current !== expectedEpoch
        || projectRef.current?.id !== projectId
        || documentReloadRequestRef.current.get(documentId) !== requestId
        || response.project_id !== projectId
        || response.document_id !== documentId
      ) return
      const refreshed = documentFromWire(response)
      replaceDocuments((documents) => documents.map((document) => (
        document.documentId === documentId
        && !document.dirty
        && refreshed.revision >= document.revision
          ? refreshed
          : document
      )))
    } catch (error) {
      if (projectEpochRef.current === expectedEpoch) setNotice(errorMessage(error))
    }
  }, [replaceDocuments])

  useEffect(() => {
    if (!active || !project) return undefined
    let refreshTimer = 0
    const unsubscribe = eventsClient.subscribe(project.id, (event) => {
      if (projectRef.current?.id !== project.id || event.sequence <= lastEventSequenceRef.current) return
      lastEventSequenceRef.current = event.sequence
      if (
        event.type === 'workspace.entry_created'
        || event.type === 'workspace.entry_deleted'
        || event.type === 'workspace.entry_moved'
      ) {
        window.clearTimeout(refreshTimer)
        refreshTimer = window.setTimeout(() => {
          if (projectRef.current?.id === project.id) {
            void refreshTreeFor(project, projectEpochRef.current, false)
          }
        }, 80)
      }
      if (event.type === 'workspace.entry_moved') {
        const sourcePath = typeof event.payload.source_path === 'string' ? event.payload.source_path : ''
        const destinationPath = typeof event.payload.destination_path === 'string' ? event.payload.destination_path : ''
        applyDocumentMove(sourcePath, destinationPath)
      }
      if (event.type === 'workspace.entry_deleted') {
        const deletedPath = typeof event.payload.path === 'string' ? event.payload.path : ''
        applyDocumentDelete(deletedPath)
      }
      if (event.type === 'workspace.entry_updated') {
        const path = typeof event.payload.path === 'string' ? event.payload.path : ''
        const document = documentsRef.current.find((candidate) => candidate.path === path)
        if (document && !savesInFlightRef.current.has(document.documentId)) {
          void reloadCleanDocument(project.id, document.documentId, path)
        }
      }
    })
    return () => {
      window.clearTimeout(refreshTimer)
      unsubscribe()
    }
  }, [active, applyDocumentDelete, applyDocumentMove, project, refreshTreeFor, reloadCleanDocument])

  return (
    <section className={`workspace-feature${explorerCollapsed ? ' workspace-feature--collapsed' : ''}`} hidden={!active}>
      <WorkspaceTree
        project={project}
        entries={tree}
        loading={treeLoading || projectBusy}
        busy={projectBusy}
        collapsed={explorerCollapsed}
        onToggleCollapsed={() => setExplorerCollapsed((collapsed) => !collapsed)}
        onOpenProject={requestOpenProject}
        onCloseProject={requestCloseProject}
        onRefresh={() => project && void refreshTreeFor(project, projectEpochRef.current)}
        onToggleDirectory={toggleDirectory}
        onOpenFile={(entry) => { void openDocumentPath(entry.path) }}
        onEntryAction={requestEntryAction}
      />
      <EditorArea
        projectId={project?.id ?? null}
        documents={documents}
        activeDocumentId={activeDocumentId}
        savingDocumentIds={savingDocumentIds}
        onActivate={activateDocument}
        onClose={requestCloseDocument}
        onContentChange={changeContent}
        onSave={(documentId) => { void saveDocument(documentId) }}
        onCursorChange={(line, column) => setCursor({ line, column })}
      />
      <footer className="workspace-status" aria-live="polite">
        <span className="workspace-status__path" title={activeDocument?.path || project?.root}>
          {activeDocument?.path || project?.root || 'No project open'}
        </span>
        <span className="workspace-status__meta">
          {activeDocument && activeDocument.viewKind !== 'image' && activeDocument.viewKind !== 'pdf' ? (
            <span>Ln {cursor.line}, Col {cursor.column}</span>
          ) : null}
          {activeDocument?.mimeType ? <span>{activeDocument.mimeType}</span> : null}
          {activeDocument?.missing ? <span>Deleted on disk</span> : activeDocument?.readonly ? <span>Read only</span> : null}
        </span>
      </footer>
      {notice ? (
        <div className="workspace-notice" role="alert">
          <span>{notice}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setNotice('')}>×</button>
        </div>
      ) : null}
      {dialog ? (
        <WorkspaceDialog
          key={dialog.kind === 'dirty-document' ? `${dialog.kind}-${dialog.documentId}` : dialog.kind}
          dialog={dialog}
          documents={documents}
          busy={dialogBusy}
          onCancel={() => {
            pendingProjectTransitionRef.current = null
            setDialog(null)
          }}
          onEntryConfirm={(name) => { void confirmEntryAction(name) }}
          onDirtyAction={(action) => { void resolveDirtyDialog(action) }}
        />
      ) : null}
    </section>
  )
}
