import { useRef, useState, type CSSProperties } from 'react'

import { SplitHandle } from '../components/SplitHandle'
import { usePanelSplit, type PanelSplitOptions } from '../components/usePanelSplit'
import { ConversationFeature } from '../features/conversation/ConversationFeature'
import { SettingsFeature } from '../features/settings'
import { SimulationFeature } from '../features/simulation/SimulationFeature'
import type { SimulationRunControlState } from '../features/simulation/types'
import { WorkspaceFeature } from '../features/workspace'
import {
  useAppState,
  type ActiveSection,
} from '../lib/app-state'
import { FeatureBoundary } from './FeatureBoundary'

const WORKBENCH_SPLIT: PanelSplitOptions = {
  storageKey: 'circuit-design-ai.layout.workbench.v1',
  dimension: 'width',
  defaultPercent: 70,
  minPercent: 55,
  maxPercent: 80,
  minPrimaryPixels: 600,
  minSecondaryPixels: 300,
}

const SIMULATION_SPLIT: PanelSplitOptions = {
  storageKey: 'circuit-design-ai.layout.simulation.v1',
  dimension: 'height',
  defaultPercent: 78,
  minPercent: 55,
  maxPercent: 85,
  minPrimaryPixels: 320,
  minSecondaryPixels: 120,
}

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
  const featureGridRef = useRef<HTMLElement | null>(null)
  const featureStackRef = useRef<HTMLDivElement | null>(null)
  const [settingsSection, setSettingsSection] = useState<
    'general' | 'models' | 'about'
  >('general')
  const [openDocumentRequest, setOpenDocumentRequest] = useState<{
    path: string
    requestId: number
  } | null>(null)
  const [simulationRunRequestId, setSimulationRunRequestId] = useState(0)
  const [simulationRunControl, setSimulationRunControl] = useState<SimulationRunControlState>({
    canRun: false,
    busy: false,
    title: 'Select a SPICE circuit to run.',
  })
  const workbenchSplit = usePanelSplit(featureGridRef, WORKBENCH_SPLIT)
  const simulationSplit = usePanelSplit(featureStackRef, SIMULATION_SPLIT)

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

      <div className="desktop-body">
        {backend.status === 'error' ? (
          <div className="backend-error" role="alert">
            <strong>Local backend connection failed.</strong>
            <span>{backend.message}</span>
          </div>
        ) : null}

        <main
          ref={featureGridRef}
          className="feature-grid"
          aria-label="Circuit design workspace"
          style={{ '--workbench-size': `${workbenchSplit.percent}%` } as CSSProperties}
        >
          <div
            ref={featureStackRef}
            className="feature-stack"
            aria-label="Workspace and simulation panes"
            style={{ '--workspace-size': `${simulationSplit.percent}%` } as CSSProperties}
          >
            <section
              className="feature-pane feature-pane--workspace"
              data-active={activeSection === 'workspace'}
              data-layout-region="workspace"
              aria-label="Workspace pane"
              onPointerDownCapture={() => activate('workspace')}
            >
              <FeatureBoundary name="Workspace">
                <WorkspaceFeature
                  active={featureSurfacesActive}
                  simulationRunControl={simulationRunControl}
                  onRunSimulation={() => setSimulationRunRequestId((requestId) => requestId + 1)}
                  onProjectChange={setProject}
                  onActiveDocumentChange={setDocument}
                  openDocumentRequest={openDocumentRequest}
                />
              </FeatureBoundary>
            </section>

            <SplitHandle
              name="workspace-simulation"
              orientation="horizontal"
              label="Resize workspace and simulation panels"
              percent={simulationSplit.percent}
              minPercent={simulationSplit.minPercent}
              maxPercent={simulationSplit.maxPercent}
              defaultPercent={SIMULATION_SPLIT.defaultPercent}
              onPointerPosition={simulationSplit.percentFromPointer}
              onChange={simulationSplit.setPercent}
            />

            <section
              className="feature-pane feature-pane--simulation"
              data-active={activeSection === 'simulation'}
              data-layout-region="simulation"
              aria-label="Simulation pane"
              onPointerDownCapture={() => activate('simulation')}
            >
              <FeatureBoundary name="Simulation">
                <SimulationFeature
                  active={featureSurfacesActive}
                  projectId={project?.id ?? null}
                  projectRoot={project?.root ?? null}
                  activeDocumentPath={document?.path ?? null}
                  runRequestId={simulationRunRequestId}
                  onRunControlChange={setSimulationRunControl}
                />
              </FeatureBoundary>
            </section>
          </div>

          <SplitHandle
            name="workbench-conversation"
            orientation="vertical"
            label="Resize workbench and conversation panels"
            percent={workbenchSplit.percent}
            minPercent={workbenchSplit.minPercent}
            maxPercent={workbenchSplit.maxPercent}
            defaultPercent={WORKBENCH_SPLIT.defaultPercent}
            onPointerPosition={workbenchSplit.percentFromPointer}
            onChange={workbenchSplit.setPercent}
          />

          <section
            className="feature-pane feature-pane--conversation"
            data-active={activeSection === 'conversation'}
            data-layout-region="conversation"
            aria-label="Conversation pane"
            onPointerDownCapture={() => activate('conversation')}
          >
            <FeatureBoundary name="Conversation">
              <ConversationFeature
                active={featureSurfacesActive}
                projectId={project?.id ?? null}
                projectRoot={project?.root ?? null}
                onOpenSettings={() => openSettings('models')}
                onOpenWorkspaceFile={openWorkspaceFile}
              />
            </FeatureBoundary>
          </section>
        </main>
      </div>

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
