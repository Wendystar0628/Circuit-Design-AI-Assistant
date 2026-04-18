import { useEffect, useMemo, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { MetricItemState, SimulationMainState } from '../../types/state'

interface MetricsTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

// Build a short string that uniquely identifies the server-side
// metrics view so edits get reset whenever the metric list changes
// identity (new simulation run, target refreshed from service, etc.)
// but not when a re-render delivers the very same payload.
function buildMetricsSignature(items: MetricItemState[], sourceFilePath: string): string {
  const parts = items.map((item) => `${item.name}\u0001${item.target}`)
  return `${sourceFilePath}\u0002${parts.join('\u0003')}`
}

function buildInitialDrafts(items: MetricItemState[]): Record<string, string> {
  const drafts: Record<string, string> = {}
  for (const item of items) {
    drafts[item.name] = item.target
  }
  return drafts
}

function areDraftsDirty(items: MetricItemState[], drafts: Record<string, string>): boolean {
  for (const item of items) {
    const draft = drafts[item.name] ?? ''
    if (draft.trim() !== item.target.trim()) {
      return true
    }
  }
  return false
}

export function MetricsTab({ state, bridge }: MetricsTabProps) {
  const metrics = state.metrics_view.items
  const sourceFilePath = state.metrics_view.source_file_path
  const canAddToConversation = state.metrics_view.can_add_to_conversation

  const signature = useMemo(() => buildMetricsSignature(metrics, sourceFilePath), [metrics, sourceFilePath])
  const [drafts, setDrafts] = useState<Record<string, string>>(() => buildInitialDrafts(metrics))

  // Re-seed the edit buffer whenever the authoritative metrics
  // signature changes. We purposefully blow away any in-flight edits
  // here: the only way the signature mutates is either a fresh
  // simulation result landing (which invalidates stale drafts) or
  // MetricTargetService flushing back a confirmed save (which should
  // synchronise the inputs with the persisted values).
  useEffect(() => {
    setDrafts(buildInitialDrafts(metrics))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature])

  const isDirty = useMemo(() => areDraftsDirty(metrics, drafts), [metrics, drafts])
  const canConfirm = isDirty && bridge !== null && sourceFilePath.length > 0

  const handleDraftChange = (name: string, nextValue: string) => {
    setDrafts((current) => ({ ...current, [name]: nextValue }))
  }

  const handleConfirm = () => {
    if (!canConfirm || bridge === null) {
      return
    }
    const payloadTargets: Record<string, string> = {}
    for (const item of metrics) {
      const draft = (drafts[item.name] ?? '').trim()
      if (draft) {
        payloadTargets[item.name] = draft
      } else {
        // Pass empty strings explicitly so the backend can evict
        // targets the user cleared; `MetricTargetService` drops empty
        // entries during persistence.
        payloadTargets[item.name] = ''
      }
    }
    bridge.updateMetricTargets({
      sourceFilePath,
      targets: payloadTargets,
    })
  }

  const handleAddToConversation = () => {
    if (!canAddToConversation) {
      return
    }
    bridge?.addToConversation('metrics')
  }

  return (
    <div className="tab-surface tab-surface--metrics">
      <div className="metrics-overlay">
        <button
          type="button"
          className="sim-compact-button"
          disabled={!canConfirm}
          onClick={handleConfirm}
        >
          确认修改
        </button>
        <button
          type="button"
          className="sim-compact-button sim-compact-button--accent"
          disabled={!canAddToConversation}
          onClick={handleAddToConversation}
        >
          添加至对话
        </button>
      </div>
      {metrics.length ? (
        <div className="metrics-matrix-scroll">
          <table className="metrics-matrix">
            <thead>
              <tr>
                <th className="metrics-matrix__corner" aria-hidden="true" />
                {metrics.map((metric) => (
                  <th key={metric.name} className="metrics-matrix__col-head" scope="col">
                    <span className="metrics-matrix__metric-name">{metric.display_name || metric.name}</span>
                    {metric.unit ? (
                      <span className="metrics-matrix__metric-unit">{metric.unit}</span>
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th className="metrics-matrix__row-head" scope="row">
                  当前值
                </th>
                {metrics.map((metric) => (
                  <td key={metric.name} className="metrics-matrix__current">
                    {metric.value || '--'}
                  </td>
                ))}
              </tr>
              <tr>
                <th className="metrics-matrix__row-head" scope="row">
                  目标值
                </th>
                {metrics.map((metric) => (
                  <td key={metric.name} className="metrics-matrix__target">
                    <input
                      type="text"
                      className="metrics-matrix__target-input"
                      value={drafts[metric.name] ?? ''}
                      placeholder="例: ≥ 20 dB"
                      spellCheck={false}
                      autoComplete="off"
                      onChange={(event) => handleDraftChange(metric.name, event.target.value)}
                    />
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <div className="metrics-matrix-empty">
          <div className="metrics-matrix-empty__title">暂无指标</div>
          <div className="metrics-matrix-empty__hint">
            在 SPICE 文件中添加 <code>.MEASURE</code> 语句后运行仿真即可生成指标。
          </div>
        </div>
      )}
    </div>
  )
}
