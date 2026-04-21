import type { ReactNode } from 'react'

import type { SimulationMainState, SimulationTabId } from '../../types/state'
import { getUiText } from '../../uiText'
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
  const uiText = state.ui_text
  const hasStatusMessage = Boolean(runtime.status_message)
  const hasError = Boolean(runtime.error_message)
  const shouldShowEmptyHint = runtime.is_empty && !SELF_CONTAINED_TABS.has(activeTab)
  const canOpenCircuitSelection = availableTabs.includes('circuit_selection')
  const statusToneClassName = runtime.awaiting_confirmation ? 'surface-state-card--warning' : 'surface-state-card--info'

  return (
    <div className="simulation-shell">
      <header className="simulation-shell__header">
        <SimulationTabBar activeTab={activeTab} availableTabs={availableTabs} onTabSelect={onTabSelect} uiText={uiText} />
      </header>
      <section className="simulation-shell__body">
        <div className="simulation-active-surface">
          <div className="simulation-active-surface__frame">
            {!bridgeConnected || hasError || hasStatusMessage || shouldShowEmptyHint ? (
              <div className="surface-state-stack">
                {!bridgeConnected ? (
                  <div className="surface-state-card surface-state-card--warning">
                    <div className="card-title">{getUiText(uiText, 'panel.simulation.bridge_disconnected_title', 'Frontend bridge is disconnected')}</div>
                    <div className="muted-text">{getUiText(uiText, 'panel.simulation.bridge_disconnected_message', 'Some local actions may be temporarily unavailable, but the current tab layout still reflects the authoritative state shell.')}</div>
                  </div>
                ) : null}
                {hasError ? (
                  <div className="surface-state-card surface-state-card--error">
                    <div className="card-title">{getUiText(uiText, 'panel.simulation.error_title', 'Simulation Error')}</div>
                    <div className="muted-text">{runtime.error_message}</div>
                  </div>
                ) : hasStatusMessage ? (
                  <div className={`surface-state-card ${statusToneClassName}`}>
                    <div className="card-title">{getUiText(uiText, 'panel.simulation.status_title', 'Runtime Status')}</div>
                    <div className="muted-text">{runtime.status_message}</div>
                  </div>
                ) : null}
                {shouldShowEmptyHint ? (
                  <div className="surface-state-card surface-state-card--empty">
                    <div className="card-title">{getUiText(uiText, 'panel.simulation.empty_title', 'No Simulation Result Yet')}</div>
                    <div className="muted-text">
                      {runtime.has_project
                        ? getUiText(uiText, 'panel.simulation.empty_with_project', 'Run a simulation once and the current tab will display the corresponding result.')
                        : getUiText(uiText, 'panel.simulation.empty_without_project', 'Open a project and run a simulation first.')}
                    </div>
                    {canOpenCircuitSelection ? (
                      <div className="surface-state-actions">
                        <button type="button" className="sim-compact-button sim-compact-button--accent" onClick={() => onTabSelect('circuit_selection')}>
                          {getUiText(uiText, 'panel.simulation.go_to_circuit_selection', 'Go to Circuit Selection')}
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
