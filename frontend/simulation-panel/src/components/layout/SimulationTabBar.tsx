import type { SimulationTabId } from '../../types/state'
import { getUiText, type UiTextMap } from '../../uiText'

interface SimulationTabBarProps {
  activeTab: SimulationTabId
  availableTabs: SimulationTabId[]
  onTabSelect(tabId: SimulationTabId): void
  uiText: UiTextMap
}

const TAB_LABELS: Record<SimulationTabId, { key: string; fallback: string }> = {
  circuit_selection: { key: 'panel.simulation.tab.circuit_selection', fallback: 'Circuit Selection' },
  metrics: { key: 'panel.simulation.tab.metrics', fallback: 'Metrics' },
  schematic: { key: 'panel.simulation.tab.schematic', fallback: 'Schematic' },
  chart: { key: 'panel.simulation.tab.chart', fallback: 'Chart' },
  waveform: { key: 'panel.simulation.tab.waveform', fallback: 'Waveform' },
  analysis_info: { key: 'panel.simulation.tab.analysis_info', fallback: 'Analysis Info' },
  raw_data: { key: 'panel.simulation.tab.raw_data', fallback: 'Raw Data' },
  output_log: { key: 'panel.simulation.tab.output_log', fallback: 'Output Log' },
  export: { key: 'panel.simulation.tab.export', fallback: 'Export' },
  asc_conversion: { key: 'panel.simulation.tab.asc_conversion', fallback: 'ASC Conversion' },
  op_result: { key: 'panel.simulation.tab.op_result', fallback: 'Operating Point Result' },
}

export function SimulationTabBar({ activeTab, availableTabs, onTabSelect, uiText }: SimulationTabBarProps) {
  return (
    <nav className="simulation-tab-bar-shell" aria-label={getUiText(uiText, 'panel.simulation.tab_navigation', 'Simulation result tabs')}>
      <span className="simulation-tab-bar__title" aria-hidden="true">
        {getUiText(uiText, 'panel.simulation', 'Simulation Panel')}
      </span>
      <div className="simulation-tab-bar" role="tablist" aria-orientation="horizontal">
        {availableTabs.map((tabId) => {
          const active = tabId === activeTab
          const tabLabelEntry = TAB_LABELS[tabId]
          const tabLabel = tabLabelEntry ? getUiText(uiText, tabLabelEntry.key, tabLabelEntry.fallback) : tabId

          if (active) {
            return (
              <button
                key={tabId}
                type="button"
                role="tab"
                aria-selected="true"
                className="simulation-tab-chip simulation-tab-chip--active"
                onClick={() => onTabSelect(tabId)}
              >
                {tabLabel}
              </button>
            )
          }

          return (
            <button
              key={tabId}
              type="button"
              role="tab"
              aria-selected="false"
              className="simulation-tab-chip"
              onClick={() => onTabSelect(tabId)}
            >
              {tabLabel}
            </button>
          )
        })}
      </div>
    </nav>
  )
}
