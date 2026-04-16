import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface SchematicTabProps {
  state: SimulationMainState
}

export function SchematicTab({ state }: SchematicTabProps) {
  const currentResult = state.simulation_runtime.current_result
  const sourceFilePath = currentResult.file_path
  const hasSourceFile = Boolean(sourceFilePath)

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="电路"
        description="当前结果对应的本地 SPICE 文件是唯一入口"
      />
      <div className="content-card content-card--canvas">
        <div className="surface-state-stack">
          {hasSourceFile ? (
            <div className="surface-state-card surface-state-card--info">
              <div className="card-title">已锁定当前源电路文件</div>
              <div className="muted-text">后续电路图将严格基于这个本地 SPICE 文件生成，不额外猜测其它文件。</div>
              <div className="muted-text">{sourceFilePath}</div>
            </div>
          ) : (
            <div className="surface-state-card surface-state-card--empty">
              <div className="card-title">暂无可用电路文件</div>
              <div className="muted-text">当前结果缺少有效 `file_path`，电路页不会猜路径，也不会推断其它文件。</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
