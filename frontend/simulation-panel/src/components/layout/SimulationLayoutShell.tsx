import type { ReactNode } from 'react'

import type { SimulationMainState, SimulationTabId } from '../../types/state'
import { SimulationTabBar } from './SimulationTabBar'

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
  const shouldShowEmptyHint = runtime.is_empty && activeTab !== 'history'
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
                    {state.surface_tabs.has_history ? (
                      <div className="surface-state-actions">
                        <button type="button" className="toolbar-button" onClick={() => onTabSelect('history')}>
                          转到历史结果
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
