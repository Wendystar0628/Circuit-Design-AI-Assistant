import { useRef, useState } from 'react'

import { ConversationFeature } from '../features/conversation/ConversationFeature'
import { SettingsFeature } from '../features/settings'
import { SimulationFeature } from '../features/simulation/SimulationFeature'
import { WorkspaceFeature } from '../features/workspace'
import {
  useAppState,
  type ActiveSection,
} from '../lib/app-state'
import { FeatureBoundary } from './FeatureBoundary'

export function DesktopLayout() {
  const {
    project,
    document,
    activeSection,
    backend,
    setProject,
    setDocument,
    setActiveSection,
  } = useAppState()
  const previousSection = useRef<Exclude<ActiveSection, 'settings'>>('workspace')
  const openDocumentRequestId = useRef(0)
  const [settingsSection, setSettingsSection] = useState<
    'general' | 'models' | 'about'
  >('general')
  const [openDocumentRequest, setOpenDocumentRequest] = useState<{
    path: string
    requestId: number
  } | null>(null)

  const activate = (section: Exclude<ActiveSection, 'settings'>) => {
    previousSection.current = section
    setActiveSection(section)
  }
  const openSettings = (section: 'general' | 'models' | 'about' = 'general') => {
    if (activeSection !== 'settings') {
      previousSection.current = activeSection
    }
    setSettingsSection(section)
    setActiveSection('settings')
  }
  const closeSettings = () => setActiveSection(previousSection.current)
  const openWorkspaceFile = (path: string) => {
    if (!path) return
    openDocumentRequestId.current += 1
    setOpenDocumentRequest({ path, requestId: openDocumentRequestId.current })
    activate('workspace')
  }
  const featureSurfacesActive = activeSection !== 'settings'

  return (
    <div className="desktop-shell">
      <header className="app-header">
        <div className="app-identity" aria-label="Circuit Design AI">
          <span className="app-identity__mark" aria-hidden="true" />
          <span className="app-identity__name">Circuit Design AI</span>
        </div>

        <div className="header-context" title={project?.root ?? 'No workspace open'}>
          <span className="header-context__label">Project</span>
          <span className="header-context__value">{project?.name ?? 'None'}</span>
        </div>
        <div
          className={`backend-state backend-state--${backend.status}`}
          role="status"
          aria-live="polite"
        >
          <span className="backend-state__dot" aria-hidden="true" />
          {backend.status === 'ready'
            ? `Backend ${backend.apiVersion}`
            : backend.status === 'connecting'
              ? 'Connecting'
              : 'Backend unavailable'}
        </div>
        <button
          type="button"
          className="header-settings-button"
          aria-pressed={activeSection === 'settings'}
          onClick={() => openSettings('general')}
        >
          Settings
        </button>
      </header>

      {backend.status === 'error' ? (
        <div className="backend-error" role="alert">
          <strong>Local backend connection failed.</strong>
          <span>{backend.message}</span>
        </div>
      ) : null}

      <main className="feature-grid" aria-label="Circuit design workspace">
        <section
          className="feature-column feature-column--workspace"
          data-active={activeSection === 'workspace'}
          onPointerDownCapture={() => activate('workspace')}
        >
          <div className="feature-column__header">
            <span>Workspace</span>
            <span>{document ? document.path.split(/[\\/]/).at(-1) : 'No file'}</span>
          </div>
          <div className="feature-column__body">
            <FeatureBoundary name="Workspace">
              <WorkspaceFeature
                active={featureSurfacesActive}
                onProjectChange={setProject}
                onActiveDocumentChange={setDocument}
                openDocumentRequest={openDocumentRequest}
              />
            </FeatureBoundary>
          </div>
        </section>

        <section
          className="feature-column feature-column--simulation"
          data-active={activeSection === 'simulation'}
          onPointerDownCapture={() => activate('simulation')}
        >
          <div className="feature-column__header">
            <span>Simulation</span>
            <span>{project ? 'Project scoped' : 'No project'}</span>
          </div>
          <div className="feature-column__body">
            <FeatureBoundary name="Simulation">
              <SimulationFeature
                active={featureSurfacesActive}
                projectId={project?.id ?? null}
                activeDocumentPath={document?.path ?? null}
              />
            </FeatureBoundary>
          </div>
        </section>

        <section
          className="feature-column feature-column--conversation"
          data-active={activeSection === 'conversation'}
          onPointerDownCapture={() => activate('conversation')}
        >
          <div className="feature-column__header">
            <span>Conversation</span>
            <span>{project ? 'Project context' : 'No project'}</span>
          </div>
          <div className="feature-column__body">
            <FeatureBoundary name="Conversation">
              <ConversationFeature
                active={featureSurfacesActive}
                projectId={project?.id ?? null}
                onOpenSettings={() => openSettings('models')}
                onOpenWorkspaceFile={openWorkspaceFile}
              />
            </FeatureBoundary>
          </div>
        </section>
      </main>

      <footer className="app-statusbar">
        <span>{project?.root ?? 'Open a workspace to begin'}</span>
        <span>{document ? `Revision ${document.revision}` : 'No active document'}</span>
      </footer>

      {activeSection === 'settings' ? (
        <FeatureBoundary name="Settings">
          <SettingsFeature
            active
            initialSection={settingsSection}
            onClose={closeSettings}
          />
        </FeatureBoundary>
      ) : null}
    </div>
  )
}
