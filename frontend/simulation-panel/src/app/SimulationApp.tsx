import type { SimulationBridge } from '../bridge/bridge'
import { ActiveResultTabRouter } from '../components/layout/ActiveResultTabRouter'
import { SimulationLayoutShell } from '../components/layout/SimulationLayoutShell'
import { RawDataTab } from '../components/tabs/RawDataTab'
import type { RawDataCopyResultState, RawDataDocumentState, RawDataViewportState, SimulationMainState, SimulationTabId } from '../types/state'

interface SimulationAppProps {
  state: SimulationMainState
  rawDataCopyResult: RawDataCopyResultState
  rawDataDocument: RawDataDocumentState
  rawDataViewport: RawDataViewportState
  bridge: SimulationBridge | null
  bridgeConnected: boolean
  onTabSelect(tabId: SimulationTabId): void
}

export function SimulationApp({ state, rawDataCopyResult, rawDataDocument, rawDataViewport, bridge, bridgeConnected, onTabSelect }: SimulationAppProps) {
  const activeTab = state.surface_tabs.active_tab
  const shouldMountRawDataSurface = activeTab === 'raw_data' || rawDataDocument.has_data

  return (
    <SimulationLayoutShell
      state={state}
      bridgeConnected={bridgeConnected}
      onTabSelect={onTabSelect}
    >
      {activeTab === 'raw_data' ? null : (
        <div className="tab-surface-shell">
          <ActiveResultTabRouter activeTab={activeTab} state={state} bridge={bridge} />
        </div>
      )}
      {shouldMountRawDataSurface ? (
        <div className={activeTab === 'raw_data' ? 'tab-surface-shell' : 'tab-surface-shell tab-surface-shell--hidden'}>
          <RawDataTab rawDataCopyResult={rawDataCopyResult} rawDataDocument={rawDataDocument} rawDataViewport={rawDataViewport} bridge={bridge} />
        </div>
      ) : null}
    </SimulationLayoutShell>
  )
}
