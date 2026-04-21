import type { ConversationBridge } from './bridge'
import { ConversationComposer } from './components/ConversationComposer'
import { ConversationHeader } from './components/ConversationHeader'
import { ConversationOverlays } from './components/ConversationOverlays'
import { RagPanel } from './components/RagPanel'
import { RightPanelTabs } from './components/RightPanelTabs'
import { ConversationTimeline } from './components/ConversationTimeline'
import type { ConversationAttachmentState, ConversationMainState } from './types'
import { getUiText } from './uiText'

interface AppProps {
  state: ConversationMainState
  bridgeConnected: boolean
  bridge: ConversationBridge | null
  registerExternalAttachmentSink: ((sink: ((attachments: ConversationAttachmentState[]) => void) | null) => void) | null
  registerClearDraftAttachmentsHandler: ((handler: (() => void) | null) => void) | null
}

export function App({
  state,
  bridgeConnected,
  bridge,
  registerExternalAttachmentSink,
  registerClearDraftAttachmentsHandler,
}: AppProps) {
  const activeSurface = state.ui.active_surface === 'rag' ? 'rag' : 'conversation'
  const conversationBridgeBanner = getUiText(
    state.ui_text,
    'conversation.bridge.disconnected',
    'Frontend bridge is not connected yet. Message display and input actions may be temporarily unavailable.',
  )
  const ragBridgeBanner = getUiText(
    state.ui_text,
    'conversation.bridge.disconnected_rag',
    'Frontend bridge is not connected yet. Index library actions may be temporarily unavailable.',
  )

  return (
    <div className="app-shell">
      <RightPanelTabs activeSurface={activeSurface} bridge={bridge} uiText={state.ui_text} />
      {activeSurface === 'conversation' ? (
        <>
          <ConversationHeader state={state} bridge={bridge} bridgeConnected={bridgeConnected} />
          <div className="app-main">
            {!bridgeConnected ? (
              <div className="bridge-banner">{conversationBridgeBanner}</div>
            ) : null}
            <ConversationTimeline state={state} bridge={bridge} />
          </div>
          <ConversationComposer
            state={state}
            bridge={bridge}
            bridgeConnected={bridgeConnected}
            registerExternalAttachmentSink={registerExternalAttachmentSink}
            registerClearDraftAttachmentsHandler={registerClearDraftAttachmentsHandler}
          />
        </>
      ) : (
        <div className="app-main app-main--single-surface">
          {!bridgeConnected ? (
            <div className="bridge-banner">{ragBridgeBanner}</div>
          ) : null}
          <RagPanel state={state} bridge={bridge} bridgeConnected={bridgeConnected} />
        </div>
      )}
      <ConversationOverlays state={state} bridge={bridge} bridgeConnected={bridgeConnected} />
    </div>
  )
}
