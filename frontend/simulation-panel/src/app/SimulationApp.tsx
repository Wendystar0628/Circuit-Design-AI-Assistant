import type { SimulationBridge } from '../bridge/bridge'
import { ActiveResultTabRouter } from '../components/layout/ActiveResultTabRouter'
import { SimulationLayoutShell } from '../components/layout/SimulationLayoutShell'
import { RawDataTab } from '../components/tabs/RawDataTab'
import type { RawDataViewState, SimulationMainState, SimulationTabId } from '../types/state'

interface SimulationAppProps {
  state: SimulationMainState
  rawDataView: RawDataViewState
  bridge: SimulationBridge | null
  bridgeConnected: boolean
  onTabSelect(tabId: SimulationTabId): void
}

export function SimulationApp({ state, rawDataView, bridge, bridgeConnected, onTabSelect }: SimulationAppProps) {
  const activeTab = state.surface_tabs.active_tab
  const shouldMountRawDataSurface = activeTab === 'raw_data' || rawDataView.visible_columns.length > 0 || rawDataView.rows.length > 0

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
          <RawDataTab rawDataView={rawDataView} />
        </div>
      ) : null}
    </SimulationLayoutShell>
  )
}
