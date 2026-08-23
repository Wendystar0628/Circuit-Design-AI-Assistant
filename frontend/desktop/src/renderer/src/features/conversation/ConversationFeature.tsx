import { useCallback, useEffect, useState } from 'react'

import {
  getWorkSession,
  sameProjectRoot,
  updateConversationSession,
  type WorkSessionConversationSurface,
} from '../../lib/workSession'
import { ConversationComposer } from './components/ConversationComposer'
import { ConversationHeader } from './components/ConversationHeader'
import { ConversationOverlays } from './components/ConversationOverlays'
import { ConversationTimeline } from './components/ConversationTimeline'
import { RagPanel } from './components/RagPanel'
import { RightPanelTabs } from './components/RightPanelTabs'
import { useConversationController } from './useConversationController'
import './styles.css'

export interface ConversationFeatureProps {
  active: boolean
  projectId: string | null
  projectRoot: string | null
  onOpenSettings(): void
  onOpenWorkspaceFile(path: string): void
}

interface ConversationUiSession {
  projectRoot: string | null
  sessionId: string | null
  activeSurface: WorkSessionConversationSurface
  draftText: string
  hydrated: boolean
}

const EMPTY_UI_SESSION: ConversationUiSession = {
  projectRoot: null,
  sessionId: null,
  activeSurface: 'conversation',
  draftText: '',
  hydrated: false,
}

export function ConversationFeature({
  active,
  projectId,
  projectRoot,
  onOpenSettings,
  onOpenWorkspaceFile,
}: ConversationFeatureProps) {
  const { state, actions, availability, errorMessage } = useConversationController(
    projectId,
    active,
    onOpenSettings,
    onOpenWorkspaceFile,
  )
  const [uiSession, setUiSession] = useState<ConversationUiSession>(EMPTY_UI_SESSION)
  const sessionId = state.session.id || null
  const uiSessionIsCurrent = Boolean(
    uiSession.hydrated
    && projectRoot
    && sessionId
    && sameProjectRoot(uiSession.projectRoot, projectRoot)
    && uiSession.sessionId === sessionId,
  )
  const activeSurface = uiSessionIsCurrent ? uiSession.activeSurface : 'conversation'
  const draftText = uiSessionIsCurrent ? uiSession.draftText : ''
  const available = active && availability === 'ready' && Boolean(actions) && Boolean(state.context_id)
  const statusMessage = !projectId
    ? 'Open a project to start a conversation.'
    : availability === 'loading'
      ? 'Loading conversation…'
      : availability === 'error'
        ? errorMessage || 'Conversation service is unavailable.'
        : ''

  useEffect(() => {
    if (!projectRoot) {
      setUiSession((current) => current.hydrated ? EMPTY_UI_SESSION : current)
      return
    }
    if (availability !== 'ready' || !sessionId) {
      return
    }

    setUiSession((current) => {
      if (
        current.hydrated
        && sameProjectRoot(current.projectRoot, projectRoot)
        && current.sessionId === sessionId
      ) {
        return current
      }
      const persisted = getWorkSession()
      const canRestore = sameProjectRoot(persisted.projectRoot, projectRoot)
        && persisted.conversation.sessionId === sessionId
      return {
        projectRoot,
        sessionId,
        activeSurface: canRestore ? persisted.conversation.activeSurface : 'conversation',
        draftText: canRestore ? persisted.conversation.draftText : '',
        hydrated: true,
      }
    })
  }, [availability, projectRoot, sessionId])

  useEffect(() => {
    if (
      !uiSession.hydrated
      || !projectRoot
      || !sessionId
      || !sameProjectRoot(uiSession.projectRoot, projectRoot)
      || uiSession.sessionId !== sessionId
    ) {
      return
    }
    updateConversationSession(projectRoot, {
      sessionId,
      activeSurface: uiSession.activeSurface,
      draftText: uiSession.draftText,
    })
  }, [projectRoot, sessionId, uiSession])

  const activateSurface = useCallback((surface: WorkSessionConversationSurface) => {
    setUiSession((current) => current.hydrated
      ? { ...current, activeSurface: surface }
      : current)
  }, [])

  const updateDraftText = useCallback((text: string) => {
    setUiSession((current) => current.hydrated
      ? { ...current, draftText: text }
      : current)
  }, [])

  return (
    <section
      className="conversation-feature"
      hidden={!active}
      aria-label="Conversation"
    >
      <div className="app-shell">
        <RightPanelTabs
          activeSurface={activeSurface}
          onActivateSurface={activateSurface}
          uiText={state.ui_text}
        />
        {activeSurface === 'conversation' ? (
          <>
            <ConversationHeader state={state} actions={actions} available={available} />
            <div className="app-main" aria-busy={availability === 'loading' || state.view_flags.is_busy}>
              {statusMessage ? (
                <div
                  className={`conversation-service-banner${availability === 'error' ? ' conversation-service-banner--error' : ''}`}
                  role="status"
                  aria-live="polite"
                >
                  {statusMessage}
                </div>
              ) : null}
              <ConversationTimeline state={state} actions={actions} />
            </div>
            <ConversationComposer
              state={state}
              actions={actions}
              available={available}
              draftText={draftText}
              onDraftTextChange={updateDraftText}
            />
          </>
        ) : (
          <div className="app-main app-main--single-surface" aria-busy={state.rag.actions.is_indexing}>
            {statusMessage ? (
              <div
                className={`conversation-service-banner${availability === 'error' ? ' conversation-service-banner--error' : ''}`}
                role="status"
                aria-live="polite"
              >
                {statusMessage}
              </div>
            ) : null}
            <RagPanel state={state} actions={actions} available={available} />
          </div>
        )}
        <ConversationOverlays state={state} actions={actions} available={available} />
      </div>
    </section>
  )
}
