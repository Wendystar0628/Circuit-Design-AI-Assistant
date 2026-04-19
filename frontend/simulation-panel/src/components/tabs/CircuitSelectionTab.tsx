
import type { SimulationBridge } from '../../bridge/bridge'
import type {
  CircuitSelectionItemState,
  SimulationMainState,
} from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface CircuitSelectionTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

/**
 * "电路选择" tab.
 *
 * A per-circuit card grid derived from
 * ``state.circuit_selection_view`` — the single authoritative
 * by-circuit aggregation produced by the backend serializer, shared
 * with the flat history-tab view at the field level so the two
 * surfaces cannot drift.
 *
 * Visual language is a full reuse of the existing
 * ``history-item`` primitives (border, radius, spacing tokens, active
 * state) and of the generic ``surface-state-card--empty`` for empty
 * states. No local CSS, no inline ``style``, no bridge method is
 * introduced by this tab: the card click re-enters the exact same
 * ``bridge.loadHistoryResult(result_path)`` path the history tab uses,
 * and the backend's post-load snapshot is what flips ``is_current``
 * on the right card — the tab itself keeps no selection state.
 */
export function CircuitSelectionTab({ state, bridge }: CircuitSelectionTabProps) {
  const runtime = state.simulation_runtime
  const { items } = state.circuit_selection_view

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="电路选择"
        description="按最近活跃时间排序，点击任一电路将加载其最近一次仿真结果为当前权威结果。"
      />
      <div className="content-card content-card--scrollable">
        {!runtime.has_project ? (
          <div className="surface-state-card surface-state-card--empty">
            <div className="card-title">尚未打开项目</div>
            <div className="muted-text">请先打开项目并运行仿真后再在此选择电路。</div>
          </div>
        ) : items.length === 0 ? (
          <div className="surface-state-card surface-state-card--empty">
            <div className="card-title">尚无仿真历史</div>
            <div className="muted-text">请先运行一次仿真，完成后此处会按电路聚合展示。</div>
          </div>
        ) : (
          <div className="history-list">
            {items.map((item) => (
              <CircuitSelectionCard
                key={item.circuit_absolute_path || item.circuit_file}
                item={item}
                onSelect={() => {
                  const target = item.latest_result
                  if (!bridge || !target.can_load || !target.result_path) {
                    return
                  }
                  bridge.loadHistoryResult(target.result_path)
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface CircuitSelectionCardProps {
  item: CircuitSelectionItemState
  onSelect: () => void
}

/**
 * One circuit card.
 *
 * The meta line is assembled from the embedded ``latest_result``
 * ({@link HistoryResultItemState}) — that shape is the same one the
 * history-tab row consumes, so the two surfaces present the bundle's
 * identity identically. ``disabled`` mirrors the backend's
 * ``latest_result.can_load`` predicate: a card whose newest bundle
 * cannot be loaded (empty / malformed ``result_path``) should not be
 * clickable, without the tab re-deriving that rule itself.
 */
function CircuitSelectionCard({ item, onSelect }: CircuitSelectionCardProps) {
  const latest = item.latest_result
  const metaParts = [
    latest.analysis_type,
    latest.timestamp,
    `共 ${item.run_count} 次仿真`,
  ].filter(Boolean)
  const className = [
    'history-item',
    'history-item--button',
    item.is_current ? 'history-item--active' : '',
  ].filter(Boolean).join(' ')
  const displayName = item.circuit_display_name || latest.file_name || '未命名电路'

  return (
    <button
      type="button"
      className={className}
      disabled={!latest.can_load}
      onClick={onSelect}
      title={item.circuit_absolute_path || item.circuit_file}
      {...(item.is_current ? { 'aria-current': 'true' as const } : null)}
    >
      <div>
        <div className="history-item__title">{displayName}</div>
        <div className="history-item__meta">
          {metaParts.length ? `最近一次：${metaParts.join(' · ')}` : '最近一次：无元数据'}
        </div>
      </div>
      <div className="list-button-row">
        {latest.success ? null : <span className="muted-text">最近失败</span>}
        {item.is_current ? <span className="muted-text">当前</span> : null}
      </div>
    </button>
  )
}
