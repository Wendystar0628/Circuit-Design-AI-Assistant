import type { ReactNode } from 'react'

import type { SimulationMainState, SimulationTabId } from '../../types/state'
import { SimulationTabBar } from './SimulationTabBar'

interface SimulationLayoutShellProps {
  state: SimulationMainState
  bridgeConnected: boolean
  activeTabContent: ReactNode
  onTabSelect(tabId: SimulationTabId): void
}

export function SimulationLayoutShell({
  state,
  bridgeConnected,
  activeTabContent,
  onTabSelect,
}: SimulationLayoutShellProps) {
  const runtime = state.simulation_runtime
  const hasStatusMessage = Boolean(runtime.status_message)
  const hasError = Boolean(runtime.error_message)

  return (
    <div className="simulation-shell">
      <SimulationTabBar state={state} onTabSelect={onTabSelect} />
      {!bridgeConnected ? (
        <div className="simulation-inline-banner simulation-inline-banner--warning">
          前端桥接尚未完成连接，局部动作可能暂时不可用。
        </div>
      ) : null}
      {hasError ? (
        <div className="simulation-inline-banner simulation-inline-banner--error">{runtime.error_message}</div>
      ) : hasStatusMessage ? (
        <div className="simulation-inline-banner simulation-inline-banner--info">{runtime.status_message}</div>
      ) : null}
      <div className="simulation-active-surface">{activeTabContent}</div>
    </div>
  )
}
