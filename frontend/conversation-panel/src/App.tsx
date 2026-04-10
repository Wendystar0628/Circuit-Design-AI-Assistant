import type { ConversationBridge } from './bridge'
import { ConversationComposer } from './components/ConversationComposer'
import { ConversationHeader } from './components/ConversationHeader'
import { ConversationOverlays } from './components/ConversationOverlays'
import { RagPanel } from './components/RagPanel'
import { RightPanelTabs } from './components/RightPanelTabs'
import { ConversationTimeline } from './components/ConversationTimeline'
import type { ConversationAttachmentState, ConversationMainState } from './types'

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

  return (
    <div className="app-shell">
      <RightPanelTabs activeSurface={activeSurface} bridge={bridge} />
      {activeSurface === 'conversation' ? (
        <>
          <ConversationHeader state={state} bridge={bridge} bridgeConnected={bridgeConnected} />
          <div className="app-main">
            {!bridgeConnected ? (
              <div className="bridge-banner">前端桥接尚未连接，消息显示和输入动作可能暂时不可用。</div>
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
            <div className="bridge-banner">前端桥接尚未连接，索引库动作可能暂时不可用。</div>
          ) : null}
          <RagPanel state={state} bridge={bridge} bridgeConnected={bridgeConnected} />
        </div>
      )}
      <ConversationOverlays state={state} bridge={bridge} />
    </div>
  )
}
