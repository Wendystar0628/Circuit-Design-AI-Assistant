import type { ReactNode } from 'react'

import type { SimulationMainState, SimulationTabId } from '../../types/state'
import { SimulationTabBar } from './SimulationTabBar'

/**
 * Tabs that render their own browsable content even when the
 * simulation runtime is empty — they are *not* downstream consumers
 * of `current_result` and therefore must *not* be occluded by the
 * generic "暂无仿真结果" empty-state hint.
 *
 * This set is the single source of truth for the occlusion rule.
 * Adding a new self-contained tab is a one-line append here; the
 * render predicate must never grow ad-hoc one-off exceptions.
 */
const SELF_CONTAINED_TABS = new Set<SimulationTabId>(['circuit_selection'])

interface SimulationLayoutShellProps {
  state: SimulationMainState
  bridgeConnected: boolean
  children: ReactNode
  onTabSelect(tabId: SimulationTabId): void
}

export function SimulationLayoutShell({
  state,
  bridgeConnected,
  children,
  onTabSelect,
}: SimulationLayoutShellProps) {
  const runtime = state.simulation_runtime
  const activeTab = state.surface_tabs.active_tab
  const availableTabs = state.surface_tabs.available_tabs
  const hasStatusMessage = Boolean(runtime.status_message)
  const hasError = Boolean(runtime.error_message)
  const shouldShowEmptyHint = runtime.is_empty && !SELF_CONTAINED_TABS.has(activeTab)
  const canOpenCircuitSelection = availableTabs.includes('circuit_selection')
  const statusToneClassName = runtime.awaiting_confirmation ? 'surface-state-card--warning' : 'surface-state-card--info'

  return (
    <div className="simulation-shell">
      <header className="simulation-shell__header">
        <SimulationTabBar activeTab={activeTab} availableTabs={availableTabs} onTabSelect={onTabSelect} />
      </header>
      <section className="simulation-shell__body">
        <div className="simulation-active-surface">
          <div className="simulation-active-surface__frame">
            {!bridgeConnected || hasError || hasStatusMessage || shouldShowEmptyHint ? (
              <div className="surface-state-stack">
                {!bridgeConnected ? (
                  <div className="surface-state-card surface-state-card--warning">
                    <div className="card-title">前端桥接未连接</div>
                    <div className="muted-text">局部动作暂时可能不可用，但当前 tab 布局仍保持权威状态壳。</div>
                  </div>
                ) : null}
                {hasError ? (
                  <div className="surface-state-card surface-state-card--error">
                    <div className="card-title">仿真错误</div>
                    <div className="muted-text">{runtime.error_message}</div>
                  </div>
                ) : hasStatusMessage ? (
                  <div className={`surface-state-card ${statusToneClassName}`}>
                    <div className="card-title">运行状态</div>
                    <div className="muted-text">{runtime.status_message}</div>
                  </div>
                ) : null}
                {shouldShowEmptyHint ? (
                  <div className="surface-state-card surface-state-card--empty">
                    <div className="card-title">暂无仿真结果</div>
                    <div className="muted-text">
                      {runtime.has_project ? '运行一次仿真后，当前 tab 会显示对应结果。' : '请先打开项目并运行仿真。'}
                    </div>
                    {canOpenCircuitSelection ? (
                      <div className="surface-state-actions">
                        <button type="button" className="sim-compact-button sim-compact-button--accent" onClick={() => onTabSelect('circuit_selection')}>
                          转到电路选择
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="simulation-active-surface__viewport">
              {children}
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
