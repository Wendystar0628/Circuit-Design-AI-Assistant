import { api, ApiError } from '../../lib/api'
import type { BackendEvent } from '../../types/desktop'
import type {
  ProjectWire,
  WorkspaceDocumentWire,
  WorkspaceEvent,
  WorkspaceSaveWire,
  WorkspaceTreeWire,
} from './types'

export { ApiError }

function encodedPath(path: string): string {
  return path.split('/').map((segment) => encodeURIComponent(segment)).join('/')
}

export const projectApi = {
  async current(): Promise<ProjectWire | null> {
    const response = await api.get<{ project: ProjectWire | null }>('/api/v1/project')
    return response.project
  },

  async open(path: string): Promise<ProjectWire> {
    const response = await api.post<{ project: ProjectWire }>('/api/v1/project/open', { path })
    return response.project
  },

  close(projectId: string): Promise<void> {
    return api.post<void>('/api/v1/project/close', { project_id: projectId })
  },
}

export const workspaceApi = {
  tree(projectId: string, path = ''): Promise<WorkspaceTreeWire> {
    const query = new URLSearchParams({ path, depth: '1' })
    return api.get<WorkspaceTreeWire>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/workspace/tree?${query.toString()}`,
    )
  },

  document(projectId: string, path: string): Promise<WorkspaceDocumentWire> {
    return api.get<WorkspaceDocumentWire>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodedPath(path)}`,
    )
  },

  saveDocument(
    projectId: string,
    path: string,
    documentId: string,
    baseRevision: number,
    content: string,
  ): Promise<WorkspaceSaveWire> {
    return api.put<WorkspaceSaveWire>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/files/${encodedPath(path)}`,
      {
        document_id: documentId,
        base_revision: baseRevision,
        content,
      },
    )
  },

  createEntry(
    projectId: string,
    parentPath: string,
    name: string,
    kind: 'file' | 'directory',
  ): Promise<void> {
    return api.post<void>(`/api/v1/projects/${encodeURIComponent(projectId)}/workspace/entries`, {
      parent_path: parentPath,
      name,
      kind,
    })
  },

  moveEntry(
    projectId: string,
    sourcePath: string,
    destinationPath: string,
  ): Promise<void> {
    return api.post<void>(`/api/v1/projects/${encodeURIComponent(projectId)}/workspace/moves`, {
      source_path: sourcePath,
      destination_path: destinationPath,
    })
  },

  deleteEntry(projectId: string, path: string): Promise<void> {
    return api.delete<void>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/workspace/entries/${encodedPath(path)}`,
    )
  },

  asset(projectId: string, path: string): Promise<Blob> {
    return api.getBlob(
      `/api/v1/projects/${encodeURIComponent(projectId)}/assets/${encodedPath(path)}`,
    )
  },
}

export const eventsClient = {
  subscribe(projectId: string, onEvent: (event: WorkspaceEvent) => void): () => void {
    return api.subscribe((event: BackendEvent) => {
      const candidate = event as BackendEvent & {
        occurred_at?: unknown
        project_id?: unknown
        payload?: unknown
      }
      if (candidate.project_id !== projectId || typeof candidate.type !== 'string') {
        return
      }
      onEvent({
        type: candidate.type,
        sequence: candidate.sequence,
        occurred_at: typeof candidate.occurred_at === 'string' ? candidate.occurred_at : '',
        project_id: candidate.project_id,
        payload:
          candidate.payload && typeof candidate.payload === 'object' && !Array.isArray(candidate.payload)
            ? candidate.payload as Record<string, unknown>
            : {},
      })
    })
  },
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message
  }
  return 'Unexpected workspace error'
}
