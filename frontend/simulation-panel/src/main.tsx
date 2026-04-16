import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { SimulationApp } from './app/SimulationApp'
import type { SimulationAppApi, SimulationBridge } from './bridge/bridge'
import {
  EMPTY_RAW_DATA_COPY_RESULT,
  EMPTY_RAW_DATA_DOCUMENT,
  EMPTY_RAW_DATA_VIEWPORT,
  EMPTY_SCHEMATIC_DOCUMENT,
  EMPTY_SCHEMATIC_WRITE_RESULT,
  EMPTY_SIMULATION_STATE,
  normalizeRawDataCopyResult,
  normalizeRawDataDocument,
  normalizeRawDataViewport,
  normalizeSchematicDocument,
  normalizeSchematicWriteResult,
  normalizeSimulationState,
  type RawDataCopyResultState,
  type RawDataDocumentState,
  type RawDataViewportState,
  type SchematicDocumentState,
  type SchematicWriteResultState,
  type SimulationMainState,
  type SimulationTabId,
} from './types/state'

import './styles/tokens.css'
import './styles/layout.css'

function Root() {
  const [state, setState] = useState<SimulationMainState>(EMPTY_SIMULATION_STATE)
  const [rawDataCopyResult, setRawDataCopyResult] = useState<RawDataCopyResultState>(EMPTY_RAW_DATA_COPY_RESULT)
  const [rawDataDocument, setRawDataDocument] = useState<RawDataDocumentState>(EMPTY_RAW_DATA_DOCUMENT)
  const [rawDataViewport, setRawDataViewport] = useState<RawDataViewportState>(EMPTY_RAW_DATA_VIEWPORT)
  const [schematicDocument, setSchematicDocument] = useState<SchematicDocumentState>(EMPTY_SCHEMATIC_DOCUMENT)
  const [schematicWriteResult, setSchematicWriteResult] = useState<SchematicWriteResultState>(EMPTY_SCHEMATIC_WRITE_RESULT)
  const [bridge, setBridge] = useState<SimulationBridge | null>(null)
  const [bridgeConnected, setBridgeConnected] = useState(false)

  useEffect(() => {
    const api: SimulationAppApi = {
      setState(nextState) {
        setState(normalizeSimulationState(nextState))
      },
      setSchematicDocument(nextState) {
        setSchematicDocument(normalizeSchematicDocument(nextState))
      },
      finishSchematicWrite(nextState) {
        setSchematicWriteResult(normalizeSchematicWriteResult(nextState))
      },
      setRawDataDocument(nextState) {
        setRawDataDocument(normalizeRawDataDocument(nextState))
      },
      setRawDataViewport(nextState) {
        setRawDataViewport(normalizeRawDataViewport(nextState))
      },
      finishRawDataCopy(nextState) {
        setRawDataCopyResult(normalizeRawDataCopyResult(nextState))
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
    bridge?.activateTab(tabId)
  }

  return (
    <SimulationApp
      state={state}
      schematicDocument={schematicDocument}
      schematicWriteResult={schematicWriteResult}
      rawDataCopyResult={rawDataCopyResult}
      rawDataDocument={rawDataDocument}
      rawDataViewport={rawDataViewport}
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
