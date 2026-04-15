import type { SimulationMainState, SimulationTabId } from '../types/state'

export interface SimulationSurfaceViewportInput {
  xMin: number
  xMax: number
  leftYMin: number
  leftYMax: number
  rightYMin?: number | null
  rightYMax?: number | null
}

export interface SimulationBridge {
  markReady(): void
  activateTab(tabId: SimulationTabId): void
  loadHistoryResult(resultPath: string): void
  setChartSeriesVisible(seriesName: string, visible: boolean): void
  clearAllChartSeries(): void
  setChartMeasurementEnabled(enabled: boolean): void
  moveChartMeasurementCursor(cursorId: 'a' | 'b', position: number): void
  setChartMeasurementPointEnabled(enabled: boolean): void
  setChartMeasurementPointTarget(targetId: string): void
  moveChartMeasurementPoint(position: number): void
  setChartViewport(viewport: SimulationSurfaceViewportInput): void
  resetChartViewport(): void
  setSignalVisible(signalName: string, visible: boolean): void
  clearAllSignals(): void
  setCursorVisible(cursorId: 'a' | 'b', visible: boolean): void
  moveCursor(cursorId: 'a' | 'b', position: number): void
  setWaveformViewport(viewport: SimulationSurfaceViewportInput): void
  resetWaveformViewport(): void
  searchOutputLog(keyword: string): void
  filterOutputLog(level: string): void
  setExportTypeSelected(exportType: string, selected: boolean): void
  setAllExportTypesSelected(selected: boolean): void
  chooseExportDirectory(): void
  clearExportDirectory(): void
  requestExport(): void
  addToConversation(target: string): void
}

export interface SimulationAppApi {
  setState(state: SimulationMainState | Record<string, unknown>): void
}

interface QtTransport {
  send(data: unknown): void
}

interface QtChannelObjects {
  simulationBridge?: SimulationBridge
}

interface QtChannel {
  objects: QtChannelObjects
}

interface QtWebChannelConstructor {
  new (transport: QtTransport, callback: (channel: QtChannel) => void): unknown
}

declare global {
  interface Window {
    qt?: {
      webChannelTransport?: QtTransport
    }
    QWebChannel?: QtWebChannelConstructor
    simulationApp?: SimulationAppApi
  }
}
