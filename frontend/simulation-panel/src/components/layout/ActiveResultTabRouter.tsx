import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState, SimulationTabId } from '../../types/state'
import { AnalysisInfoTab } from '../tabs/AnalysisInfoTab'
import { ChartTab } from '../tabs/ChartTab'
import { ExportTab } from '../tabs/ExportTab'
import { HistoryResultsTab } from '../tabs/HistoryResultsTab'
import { MetricsTab } from '../tabs/MetricsTab'
import { OpResultTab } from '../tabs/OpResultTab'
import { OutputLogTab } from '../tabs/OutputLogTab'
import { WaveformTab } from '../tabs/WaveformTab'

interface ActiveResultTabRouterProps {
  activeTab: SimulationTabId
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function ActiveResultTabRouter({ activeTab, state, bridge }: ActiveResultTabRouterProps) {
  if (activeTab === 'chart') {
    return <ChartTab state={state} bridge={bridge} />
  }
  if (activeTab === 'waveform') {
    return <WaveformTab state={state} bridge={bridge} />
  }
  if (activeTab === 'analysis_info') {
    return <AnalysisInfoTab state={state} />
  }
  if (activeTab === 'output_log') {
    return <OutputLogTab state={state} bridge={bridge} />
  }
  if (activeTab === 'export') {
    return <ExportTab state={state} bridge={bridge} />
  }
  if (activeTab === 'history') {
    return <HistoryResultsTab state={state} bridge={bridge} />
  }
  if (activeTab === 'op_result') {
    return <OpResultTab state={state} bridge={bridge} />
  }
  return <MetricsTab state={state} bridge={bridge} />
}
