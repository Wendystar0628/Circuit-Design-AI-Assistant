import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'

/**
 * "电路选择" tab — Step 10 scaffold.
 *
 * Renders a placeholder card; the actual per-circuit aggregated card
 * grid is wired up in Step 11 (backend `CircuitSelectionViewState`
 * serialization) and Step 12 (card interactions). Placed in the
 * router now so the type/route/whitelist skeletons line up before
 * data lands.
 */
interface CircuitSelectionTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function CircuitSelectionTab(_props: CircuitSelectionTabProps) {
  return (
    <div className="tab-surface">
      <div className="content-card">
        <div className="card-title">电路选择</div>
        <div className="muted-text">
          按电路聚合的仿真结果卡片将在后续步骤接入，当前仅占位。
        </div>
      </div>
    </div>
  )
}
