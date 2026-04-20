import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface AscConversionTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function AscConversionTab({ state, bridge }: AscConversionTabProps) {
  const ascConversionView = state.asc_conversion_view

  return (
    <div className="tab-surface">
      <CompactToolbar title="asc转换" description="选择一个或多个 LTspice .asc 文件后，系统会在当前工作目录生成对应的 .cir 文件。" />
      <div className="content-card content-card--scrollable">
        <div className="table-toolbar-grid">
          <label className="field-row field-row--grow">
            <span className="field-row__label">ASC 文件</span>
            <input
              className="field-input"
              value={ascConversionView.selected_files_summary || '未选择'}
              readOnly
            />
          </label>
          <button
            type="button"
            className="sim-compact-button sim-compact-button--accent"
            disabled={!ascConversionView.can_choose_files}
            onClick={() => bridge?.chooseAscFilesForConversion()}
          >
            选择并转换
          </button>
        </div>
      </div>
    </div>
  )
}
