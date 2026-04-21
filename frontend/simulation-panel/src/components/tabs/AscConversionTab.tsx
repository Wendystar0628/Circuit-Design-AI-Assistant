import type { SimulationBridge } from '../../bridge/bridge'
import type { SimulationMainState } from '../../types/state'
import { getUiText } from '../../uiText'
import { CompactToolbar } from '../layout/CompactToolbar'

interface AscConversionTabProps {
  state: SimulationMainState
  bridge: SimulationBridge | null
}

export function AscConversionTab({ state, bridge }: AscConversionTabProps) {
  const ascConversionView = state.asc_conversion_view
  const uiText = state.ui_text

  return (
    <div className="tab-surface">
      <CompactToolbar title={getUiText(uiText, 'simulation.asc.title', 'ASC Conversion')} description={getUiText(uiText, 'simulation.asc.description', 'Choose one or more LTspice .asc files and the system will generate the corresponding .cir files in the current workspace directory.')} />
      <div className="content-card content-card--scrollable">
        <div className="table-toolbar-grid">
          <label className="field-row field-row--grow">
            <span className="field-row__label">{getUiText(uiText, 'simulation.asc.files', 'ASC Files')}</span>
            <input
              className="field-input"
              value={ascConversionView.selected_files_summary || getUiText(uiText, 'simulation.asc.not_selected', 'Not Selected')}
              readOnly
            />
          </label>
          <button
            type="button"
            className="sim-compact-button sim-compact-button--accent"
            disabled={!ascConversionView.can_choose_files}
            onClick={() => bridge?.chooseAscFilesForConversion()}
          >
            {getUiText(uiText, 'simulation.asc.choose_and_convert', 'Choose and Convert')}
          </button>
        </div>
      </div>
    </div>
  )
}
