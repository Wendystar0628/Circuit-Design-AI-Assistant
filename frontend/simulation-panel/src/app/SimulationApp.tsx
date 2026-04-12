import type { ReactNode } from 'react'

import type { SimulationBridge } from '../bridge/bridge'
import { ActiveResultTabRouter } from '../components/layout/ActiveResultTabRouter'
import { SimulationLayoutShell } from '../components/layout/SimulationLayoutShell'
import type { SimulationMainState, SimulationTabId } from '../types/state'

interface SimulationAppProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
  bridgeConnected: boolean
  onTabSelect(tabId: SimulationTabId): void
}

export function SimulationApp({ state, bridge, bridgeConnected, onTabSelect }: SimulationAppProps) {
  const activeTab = state.surface_tabs.active_tab

  const activeTabNode: ReactNode = (
    <ActiveResultTabRouter activeTab={activeTab} state={state} bridge={bridge} />
  )

  return (
    <SimulationLayoutShell
      state={state}
      bridgeConnected={bridgeConnected}
      onTabSelect={onTabSelect}
    >
      {activeTabNode}
    </SimulationLayoutShell>
  )
}
