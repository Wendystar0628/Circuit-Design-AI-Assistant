import type { SimulationBridge } from '../../bridge/bridge'
import { useElementSize } from '../../hooks/useElementSize'
import type {
  CircuitSelectionItemState,
  SimulationMainState,
} from '../../types/state'
import { getUiText } from '../../uiText'

interface CircuitSelectionTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

const MIN_CARD_COLUMNS = 2
const MAX_CARD_COLUMNS = 4
const TARGET_CARD_WIDTH = 280

function resolveCircuitSelectionColumnCount(width: number): number {
  if (!Number.isFinite(width) || width <= 0) {
    return MIN_CARD_COLUMNS
  }
  return Math.max(
    MIN_CARD_COLUMNS,
    Math.min(
      MAX_CARD_COLUMNS,
      Math.floor(width / TARGET_CARD_WIDTH),
    ),
  )
}

/**
 * "电路选择" tab.
 *
 * A per-circuit card grid derived from
 * ``state.circuit_selection_view`` — the single authoritative
 * by-circuit aggregation produced by the backend serializer. This tab
 * is the sole historical-result entry point in the panel: duplicate
 * peer-tab browsing has been deleted, and persisted-result loading now
 * funnels through the card grid only.
 *
 * Visual language is a full reuse of the shared panel primitives and
 * of the generic ``surface-state-card--empty`` for empty states. No
 * local CSS, no inline ``style``, no bridge method is
 * introduced by this tab: the card click calls the single generic
 * ``bridge.loadResultByPath(result_path)`` entry point, and the
 * backend's post-load snapshot is what flips ``is_current`` on the
 * right card — the tab itself keeps no selection state.
 */
export function CircuitSelectionTab({ state, bridge }: CircuitSelectionTabProps) {
  const runtime = state.simulation_runtime
  const { items } = state.circuit_selection_view
  const uiText = state.ui_text
  const { ref: surfaceRef, width: surfaceWidth } = useElementSize<HTMLDivElement>()
  const columnCount = resolveCircuitSelectionColumnCount(surfaceWidth)
  const gridClassName = [
    'circuit-selection-grid',
    `circuit-selection-grid--cols-${columnCount}`,
  ].join(' ')

  return (
    <div className="tab-surface">
      <div
        ref={surfaceRef}
        className="content-card content-card--scrollable circuit-selection-surface"
      >
        {!runtime.has_project ? (
          <div className="surface-state-card surface-state-card--empty">
            <div className="card-title">{getUiText(uiText, 'simulation.circuit_selection.no_project', 'No project is open yet')}</div>
            <div className="muted-text">{getUiText(uiText, 'simulation.circuit_selection.no_project_hint', 'Open a project and run a simulation before choosing a circuit here.')}</div>
          </div>
        ) : items.length === 0 ? (
          <div className="surface-state-card surface-state-card--empty">
            <div className="card-title">{getUiText(uiText, 'simulation.circuit_selection.no_history', 'No simulation history yet')}</div>
            <div className="muted-text">{getUiText(uiText, 'simulation.circuit_selection.no_history_hint', 'Run a simulation once and results will be grouped by circuit here.')}</div>
          </div>
        ) : (
          <div className={gridClassName}>
            {items.map((item) => (
              <CircuitSelectionCard
                key={item.circuit_absolute_path || item.circuit_file}
                item={item}
                uiText={uiText}
                onSelect={() => {
                  const target = item.latest_result
                  if (!bridge || !target.can_load || !target.result_path) {
                    return
                  }
                  bridge.loadResultByPath(target.result_path)
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
  uiText: Record<string, string>
  onSelect: () => void
}

/**
 * One circuit card.
 *
 * The meta line is assembled from the embedded ``latest_result``
 * ({@link LoadableResultState}) — the backend emits one generic
 * persisted-result load target shape and the card reuses it directly.
 * ``disabled`` mirrors the backend's ``latest_result.can_load``
 * predicate: a card whose newest bundle cannot be loaded (empty /
 * malformed ``result_path``) should not be clickable, without the tab
 * re-deriving that rule itself.
 */
function CircuitSelectionCard({ item, uiText, onSelect }: CircuitSelectionCardProps) {
  const latest = item.latest_result
  const metaParts = [
    latest.analysis_type,
    latest.timestamp,
  ].filter(Boolean)
  const badges = [
    !latest.success ? { label: getUiText(uiText, 'simulation.circuit_selection.latest_failed', 'Latest Failed'), modifier: ' circuit-selection-card__badge--error' } : null,
    item.is_current ? { label: getUiText(uiText, 'common.current', 'Current'), modifier: ' circuit-selection-card__badge--current' } : null,
    !latest.can_load ? { label: getUiText(uiText, 'simulation.circuit_selection.not_loadable', 'Not Loadable'), modifier: '' } : null,
  ].filter((badge): badge is { label: string; modifier: string } => badge !== null)
  const className = [
    'circuit-selection-card',
    item.is_current ? 'circuit-selection-card--active' : '',
    !latest.can_load ? 'circuit-selection-card--disabled' : '',
  ].filter(Boolean).join(' ')
  const displayName = item.circuit_display_name || latest.file_name || getUiText(uiText, 'simulation.circuit_selection.unnamed_circuit', 'Unnamed Circuit')

  return (
    <button
      type="button"
      className={className}
      disabled={!latest.can_load}
      onClick={onSelect}
      title={item.circuit_absolute_path || item.circuit_file}
      {...(item.is_current ? { 'aria-current': 'true' as const } : null)}
    >
      <div className="circuit-selection-card__header">
        <div className="circuit-selection-card__title-block">
          <div className="circuit-selection-card__title">{displayName}</div>
          <div className="circuit-selection-card__meta">
            {metaParts.length
              ? getUiText(uiText, 'simulation.circuit_selection.latest_run', 'Latest: {meta}', { meta: metaParts.join(' · ') })
              : getUiText(uiText, 'simulation.circuit_selection.latest_run_empty', 'Latest: No metadata')}
          </div>
        </div>
        <div className="circuit-selection-card__run-count">{getUiText(uiText, 'simulation.circuit_selection.run_count', '{count} runs', { count: item.run_count })}</div>
      </div>
      <div className="circuit-selection-card__footer">
        <div className="circuit-selection-card__badge-row">
          {badges.map((badge) => (
            <span
              key={badge.label}
              className={`circuit-selection-card__badge${badge.modifier}`}
            >
              {badge.label}
            </span>
          ))}
        </div>
      </div>
    </button>
  )
}
