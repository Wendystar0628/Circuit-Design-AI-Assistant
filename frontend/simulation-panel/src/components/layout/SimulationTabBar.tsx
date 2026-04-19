import type { SimulationTabId } from '../../types/state'

interface SimulationTabBarProps {
  activeTab: SimulationTabId
  availableTabs: SimulationTabId[]
  onTabSelect(tabId: SimulationTabId): void
}

const TAB_LABELS: Record<SimulationTabId, string> = {
  circuit_selection: '电路选择',
  metrics: '指标',
  schematic: '电路',
  chart: '图表',
  waveform: '波形',
  analysis_info: '分析信息',
  raw_data: '原始数据',
  output_log: '输出日志',
  export: '导出',
  history: '历史结果',
  op_result: '工作点结果',
}

export function SimulationTabBar({ activeTab, availableTabs, onTabSelect }: SimulationTabBarProps) {
  return (
    <nav className="simulation-tab-bar-shell" aria-label="Simulation Result Tabs">
      <span className="simulation-tab-bar__title" aria-hidden="true">
        仿真面板
      </span>
      <div className="simulation-tab-bar" role="tablist" aria-orientation="horizontal">
        {availableTabs.map((tabId) => {
          const active = tabId === activeTab
          const tabLabel = TAB_LABELS[tabId] ?? tabId

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
