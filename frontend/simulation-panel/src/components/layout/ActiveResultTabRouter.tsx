import type { ReactNode } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState, SimulationTabId } from '../../types/state'
import { AnalysisInfoTab } from '../tabs/AnalysisInfoTab'
import { ChartTab } from '../tabs/ChartTab'
import { CircuitSelectionTab } from '../tabs/CircuitSelectionTab'
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

type TabRenderContext = {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

type TabRenderer = (ctx: TabRenderContext) => ReactNode

/**
 * Data-driven tab → component table.
 *
 * Using `Record<SimulationTabId, TabRenderer>` (rather than an
 * if / switch chain) makes the TypeScript compiler the gatekeeper of
 * exhaustiveness: if `SimulationTabId` gains a new member the table
 * fails to type-check until an entry is added. No single-tab
 * `if (activeTab === '…')` branch is ever allowed in this router.
 *
 * `schematic` and `raw_data` resolve to `null` because they are
 * persistently mounted one layer up by `SimulationApp` (they need
 * to survive tab switches to preserve canvas / grid state).
 * Keeping them in the map — rather than omitting them from the
 * type — lets the compiler still enforce exhaustiveness while
 * documenting the externally-mounted carve-out in one place.
 */
const TAB_COMPONENT_MAP: Record<SimulationTabId, TabRenderer> = {
  circuit_selection: ({ state, bridge }) => <CircuitSelectionTab state={state} bridge={bridge} />,
  metrics: ({ state, bridge }) => <MetricsTab state={state} bridge={bridge} />,
  schematic: () => null,
  chart: ({ state, bridge }) => <ChartTab state={state} bridge={bridge} />,
  waveform: ({ state, bridge }) => <WaveformTab state={state} bridge={bridge} />,
  analysis_info: ({ state }) => <AnalysisInfoTab state={state} />,
  raw_data: () => null,
  output_log: ({ state, bridge }) => <OutputLogTab state={state} bridge={bridge} />,
  export: ({ state, bridge }) => <ExportTab state={state} bridge={bridge} />,
  history: ({ state, bridge }) => <HistoryResultsTab state={state} bridge={bridge} />,
  op_result: ({ state, bridge }) => <OpResultTab state={state} bridge={bridge} />,
}

export function ActiveResultTabRouter({ activeTab, state, bridge }: ActiveResultTabRouterProps) {
  return <>{TAB_COMPONENT_MAP[activeTab]({ state, bridge })}</>
}
