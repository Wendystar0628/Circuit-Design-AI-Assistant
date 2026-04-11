import type { SimulationMainState, SimulationTabId } from '../../types/state'

interface SimulationTabBarProps {
  state: SimulationMainState
  onTabSelect(tabId: SimulationTabId): void
}

const TAB_LABELS: Record<SimulationTabId, string> = {
  metrics: '指标',
  chart: '图表',
  waveform: '波形',
  analysis_info: '分析信息',
  raw_data: '原始数据',
  output_log: '输出日志',
  export: '导出',
  history: '历史结果',
  op_result: '工作点结果',
}

export function SimulationTabBar({ state, onTabSelect }: SimulationTabBarProps) {
  const activeTab = state.surface_tabs.active_tab
  const availableTabs = state.surface_tabs.available_tabs

  return (
    <div className="simulation-tab-bar" aria-label="Simulation Result Tabs">
      {availableTabs.map((tabId) => {
        const active = tabId === activeTab
        return (
          <button
            key={tabId}
            type="button"
            className={active ? 'simulation-tab-chip simulation-tab-chip--active' : 'simulation-tab-chip'}
            onClick={() => onTabSelect(tabId)}
          >
            {TAB_LABELS[tabId] ?? tabId}
          </button>
        )
      })}
    </div>
  )
}
