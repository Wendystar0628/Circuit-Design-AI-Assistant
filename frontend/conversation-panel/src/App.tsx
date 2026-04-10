import type { ConversationBridge } from './bridge'
import { ConversationComposer } from './components/ConversationComposer'
import { ConversationHeader } from './components/ConversationHeader'
import { ConversationOverlays } from './components/ConversationOverlays'
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
  return (
    <div className="app-shell">
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
      <ConversationOverlays state={state} bridge={bridge} />
    </div>
  )
}
