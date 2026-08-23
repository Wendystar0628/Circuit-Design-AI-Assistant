export interface ProjectSummary {
  id: string
  name: string
  root: string
  generation: number
}

export type WorkspaceEntryKind = 'file' | 'directory'
export type WorkspaceViewKind = 'code' | 'markdown' | 'image' | 'pdf' | 'text'

export interface WorkspaceTreeEntry {
  path: string
  name: string
  kind: WorkspaceEntryKind
  hasChildren: boolean
  viewKind: WorkspaceViewKind
  isDirty: boolean
  expanded: boolean
  loading: boolean
  children: WorkspaceTreeEntry[] | null
}

export interface WorkspaceDocument {
  documentId: string
  path: string
  name: string
  viewKind: WorkspaceViewKind
  revision: number
  content: string
  savedContent: string
  mimeType: string
  readonly: boolean
  dirty: boolean
  missing: boolean
}

export interface ProjectWire {
  project_id: string
  root: string
  name: string
  generation: number
}

export interface TreeEntryWire {
  path: string
  name: string
  kind: WorkspaceEntryKind
  has_children: boolean
  view_kind: WorkspaceViewKind
  is_dirty: boolean
}

export interface WorkspaceTreeWire {
  project_id: string
  revision: number
  entries: TreeEntryWire[]
}

export interface WorkspaceDocumentWire {
  project_id: string
  document_id: string
  path: string
  name: string
  view_kind: WorkspaceViewKind
  revision: number
  content?: string
  mime_type: string
  readonly: boolean
}

export interface WorkspaceSaveWire {
  project_id: string
  document_id: string
  path: string
  revision: number
}

export interface WorkspaceEvent {
  type: string
  sequence: number
  occurred_at: string
  project_id: string
  payload: Record<string, unknown>
}

export function projectFromWire(project: ProjectWire): ProjectSummary {
  return {
    id: project.project_id,
    name: project.name,
    root: project.root,
    generation: project.generation,
  }
}

export function treeEntryFromWire(entry: TreeEntryWire): WorkspaceTreeEntry {
  return {
    path: entry.path,
    name: entry.name,
    kind: entry.kind,
    hasChildren: entry.has_children,
    viewKind: entry.view_kind,
    isDirty: entry.is_dirty,
    expanded: false,
    loading: false,
    children: null,
  }
}

export function documentFromWire(document: WorkspaceDocumentWire): WorkspaceDocument {
  const content = document.content ?? ''
  return {
    documentId: document.document_id,
    path: document.path,
    name: document.name,
    viewKind: document.view_kind,
    revision: document.revision,
    content,
    savedContent: content,
    mimeType: document.mime_type,
    readonly: document.readonly,
    dirty: false,
    missing: false,
  }
}
