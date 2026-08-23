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
  onOpenSettings(): void
  onOpenWorkspaceFile(path: string): void
}

export function ConversationFeature({
  active,
  projectId,
  onOpenSettings,
  onOpenWorkspaceFile,
}: ConversationFeatureProps) {
  const { state, actions, availability, errorMessage } = useConversationController(
    projectId,
    active,
    onOpenSettings,
    onOpenWorkspaceFile,
  )
  const activeSurface = state.ui.active_surface === 'rag' ? 'rag' : 'conversation'
  const available = active && availability === 'ready' && Boolean(actions) && Boolean(state.context_id)
  const statusMessage = !projectId
    ? 'Open a project to start a conversation.'
    : availability === 'loading'
      ? 'Loading conversation…'
      : availability === 'error'
        ? errorMessage || 'Conversation service is unavailable.'
        : ''

  return (
    <section
      className="conversation-feature"
      hidden={!active}
      aria-label="Conversation"
    >
      <div className="app-shell">
        <RightPanelTabs
          activeSurface={activeSurface}
          actions={actions}
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
            <ConversationComposer state={state} actions={actions} available={available} />
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
