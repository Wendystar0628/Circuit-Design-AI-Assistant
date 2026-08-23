import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react'

import { api } from './api'
import type {
  BackendConnectionConfig,
  DesktopProject,
} from '../types/desktop'

export type ActiveSection =
  | 'workspace'
  | 'simulation'
  | 'conversation'
  | 'settings'

export interface ActiveDocument {
  documentId: string
  path: string
  revision: string
}

export type BackendConnectionState =
  | { status: 'connecting' }
  | { status: 'ready'; apiVersion: 'v1'; origin: string }
  | { status: 'error'; message: string }

interface AppStateValue {
  project: DesktopProject | null
  document: ActiveDocument | null
  activeSection: ActiveSection
  backend: BackendConnectionState
  setProject(project: DesktopProject | null): void
  setDocument(document: ActiveDocument | null): void
  setActiveSection(section: ActiveSection): void
}

const AppStateContext = createContext<AppStateValue | null>(null)

function backendOrigin(config: BackendConnectionConfig): string {
  return new URL(config.baseUrl).origin
}

export function AppStateProvider({ children }: PropsWithChildren) {
  const [project, setProjectState] = useState<DesktopProject | null>(null)
  const [document, setDocument] = useState<ActiveDocument | null>(null)
  const [activeSection, setActiveSection] = useState<ActiveSection>('workspace')
  const [backend, setBackend] = useState<BackendConnectionState>({
    status: 'connecting',
  })
  const projectId = useRef<string | null>(null)

  useEffect(() => {
    let active = true
    void window.circuitDesktop
      .getBackendConfig()
      .then(async (config) => {
        const state = await api.get<{
          api_version: unknown
          ready: unknown
        }>('/api/v1/app/state')
        if (state.api_version !== 'v1' || state.ready !== true) {
          throw new Error('Local backend returned an invalid readiness response')
        }
        if (active) {
          setBackend({
            status: 'ready',
            apiVersion: config.apiVersion,
            origin: backendOrigin(config),
          })
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setBackend({
            status: 'error',
            message: error instanceof Error ? error.message : String(error),
          })
        }
      })
    return () => {
      active = false
    }
  }, [])

  const setProject = useCallback((nextProject: DesktopProject | null) => {
    const nextProjectId = nextProject?.id ?? null
    if (projectId.current !== nextProjectId) {
      projectId.current = nextProjectId
      setDocument(null)
    }
    setProjectState(nextProject)
  }, [])

  const value = useMemo<AppStateValue>(
    () => ({
      project,
      document,
      activeSection,
      backend,
      setProject,
      setDocument,
      setActiveSection,
    }),
    [project, document, activeSection, backend, setProject],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState(): AppStateValue {
  const value = useContext(AppStateContext)
  if (!value) {
    throw new Error('useAppState must be used inside AppStateProvider')
  }
  return value
}

export function useApi() {
  return api
}
