import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ModelConfigApp } from './ModelConfigApp'
import {
  setModelConfigBridge,
  type ModelConfigAppApi,
  type ModelConfigBridge,
} from './modelConfigBridge'
import './styles.css'
import './model-config.css'
import {
  emptyModelConfigState,
  normalizeModelConfigState,
  type ModelConfigState,
} from './modelConfigTypes'

let pendingState: ModelConfigState = emptyModelConfigState
let pendingBridge: ModelConfigBridge | null = null
let bridgeConnected = false
let setExternalState: ((nextState: ModelConfigState) => void) | null = null
let setBridgeConnectionState: ((connected: boolean) => void) | null = null
let setBridgeState: ((bridge: ModelConfigBridge | null) => void) | null = null

function Root() {
  const [state, setState] = useState<ModelConfigState>(pendingState)
  const [isBridgeConnected, setIsBridgeConnected] = useState<boolean>(bridgeConnected)
  const [bridge, setBridge] = useState<ModelConfigBridge | null>(pendingBridge)

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

  return <ModelConfigApp state={state} bridgeConnected={isBridgeConnected} bridge={bridge} />
}

window.modelConfigApp = {
  setState(nextState: unknown) {
    pendingState = normalizeModelConfigState(nextState)
    if (setExternalState) {
      setExternalState(pendingState)
    }
  },
} satisfies ModelConfigAppApi

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
    pendingBridge = (channel.objects.modelConfigBridge as ModelConfigBridge | undefined) ?? null
    bridgeConnected = Boolean(pendingBridge)
    setModelConfigBridge(pendingBridge)
    if (setBridgeState) {
      setBridgeState(pendingBridge)
    }
    if (setBridgeConnectionState) {
      setBridgeConnectionState(bridgeConnected)
    }
    pendingBridge?.markReady?.()
  })
}
