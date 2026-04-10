import { StrictMode, useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { setConversationBridge, type ConversationAppApi, type ConversationBridge } from './bridge'
import './styles.css'
import {
  emptyConversationState,
  normalizeAttachmentList,
  normalizeConversationState,
  type ConversationAttachmentState,
  type ConversationMainState,
} from './types'

type AttachmentSink = (attachments: ConversationAttachmentState[]) => void

let pendingState: ConversationMainState = emptyConversationState
let pendingBridge: ConversationBridge | null = null
let bridgeConnected = false
let queuedDraftAttachments: ConversationAttachmentState[] = []
let setExternalState: ((nextState: ConversationMainState) => void) | null = null
let setBridgeConnectionState: ((connected: boolean) => void) | null = null
let setBridgeState: ((bridge: ConversationBridge | null) => void) | null = null
let externalAttachmentSink: AttachmentSink | null = null
let clearDraftAttachmentsHandler: (() => void) | null = null

function Root() {
  const [state, setState] = useState<ConversationMainState>(pendingState)
  const [isBridgeConnected, setIsBridgeConnected] = useState<boolean>(bridgeConnected)
  const [bridge, setBridge] = useState<ConversationBridge | null>(pendingBridge)

  useEffect(() => {
    setExternalState = setState
    setBridgeConnectionState = setIsBridgeConnected
    setBridgeState = setBridge
    setState(pendingState)
    setIsBridgeConnected(bridgeConnected)
    setBridge(pendingBridge)
    return () => {
      setExternalState = null
      setBridgeConnectionState = null
      setBridgeState = null
    }
  }, [])

  const registerExternalAttachmentSink = useCallback((sink: AttachmentSink | null) => {
    externalAttachmentSink = sink
    if (sink && queuedDraftAttachments.length) {
      sink(queuedDraftAttachments)
      queuedDraftAttachments = []
    }
  }, [])

  const registerClearDraftAttachmentsHandler = useCallback((handler: (() => void) | null) => {
    clearDraftAttachmentsHandler = handler
  }, [])

  return (
    <App
      state={state}
      bridgeConnected={isBridgeConnected}
      bridge={bridge}
      registerExternalAttachmentSink={registerExternalAttachmentSink}
      registerClearDraftAttachmentsHandler={registerClearDraftAttachmentsHandler}
    />
  )
}

window.conversationApp = {
  setState(nextState: unknown) {
    pendingState = normalizeConversationState(nextState)
    if (setExternalState) {
      setExternalState(pendingState)
    }
  },
  appendDraftAttachments(nextAttachments: unknown) {
    const normalizedAttachments = normalizeAttachmentList(nextAttachments)
    if (!normalizedAttachments.length) {
      return
    }
    if (externalAttachmentSink) {
      externalAttachmentSink(normalizedAttachments)
      return
    }
    queuedDraftAttachments = queuedDraftAttachments.concat(normalizedAttachments)
  },
  clearDraftAttachments() {
    clearDraftAttachmentsHandler?.()
  },
} satisfies ConversationAppApi

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Missing root element')
}

createRoot(rootElement).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)

if (window.QWebChannel && window.qt?.webChannelTransport) {
  new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
    pendingBridge = (channel.objects.conversationBridge as ConversationBridge | undefined) ?? null
    bridgeConnected = Boolean(pendingBridge)
    setConversationBridge(pendingBridge)
    if (setBridgeState) {
      setBridgeState(pendingBridge)
    }
    if (setBridgeConnectionState) {
      setBridgeConnectionState(bridgeConnected)
    }
    pendingBridge?.markReady?.()
  })
}
