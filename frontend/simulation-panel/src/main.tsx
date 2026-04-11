import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { SimulationApp } from './app/SimulationApp'
import type { SimulationAppApi, SimulationBridge } from './bridge/bridge'
import { EMPTY_SIMULATION_STATE, normalizeSimulationState, type SimulationMainState, type SimulationTabId } from './types/state'

import './styles/tokens.css'
import './styles/layout.css'

function Root() {
  const [state, setState] = useState<SimulationMainState>(EMPTY_SIMULATION_STATE)
  const [bridge, setBridge] = useState<SimulationBridge | null>(null)
  const [bridgeConnected, setBridgeConnected] = useState(false)

  useEffect(() => {
    const api: SimulationAppApi = {
      setState(nextState) {
        setState(normalizeSimulationState(nextState))
      },
      activateTab(tabId) {
        setState((previous: SimulationMainState) => ({
          ...previous,
          surface_tabs: {
            ...previous.surface_tabs,
            active_tab: tabId,
          },
        }))
      },
    }
    window.simulationApp = api
    return () => {
      delete window.simulationApp
    }
  }, [])

  useEffect(() => {
    if (!window.qt?.webChannelTransport || !window.QWebChannel) {
      return
    }
    let disposed = false
    new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
      if (disposed) {
        return
      }
      const nextBridge = channel.objects.simulationBridge ?? null
      setBridge(nextBridge)
      setBridgeConnected(Boolean(nextBridge))
      nextBridge?.markReady?.()
    })
    return () => {
      disposed = true
      setBridge(null)
      setBridgeConnected(false)
    }
  }, [])

  const handleTabSelect = (tabId: SimulationTabId) => {
    setState((previous: SimulationMainState) => ({
      ...previous,
      surface_tabs: {
        ...previous.surface_tabs,
        active_tab: tabId,
      },
    }))
    bridge?.activateTab(tabId)
  }

  return (
    <SimulationApp
      state={state}
      bridge={bridge}
      bridgeConnected={bridgeConnected}
      onTabSelect={handleTabSelect}
    />
  )
}

const rootElement = document.getElementById('root')
if (rootElement) {
  createRoot(rootElement).render(<Root />)
}
