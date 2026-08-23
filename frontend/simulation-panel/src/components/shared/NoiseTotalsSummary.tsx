import type { NoiseTotalItemState, NoiseTotalsState } from '../../types/state'
import { getUiText, type UiTextMap } from '../../uiText'
import { formatMeasurementNumber } from './chartValueFormatting'

interface NoiseTotalsSummaryProps {
  noiseTotals: NoiseTotalsState
  uiText: UiTextMap
}

function itemLabel(item: NoiseTotalItemState, uiText: UiTextMap): string {
  if (item.key === 'output_rms') {
    return getUiText(
      uiText,
      'simulation.noise_totals.output_rms',
      'Integrated output noise',
    )
  }
  return getUiText(
    uiText,
    'simulation.noise_totals.input_referred_rms',
    'Input-referred noise',
  )
}

function itemValue(item: NoiseTotalItemState): string {
  return `${formatMeasurementNumber(item.value)} ${item.unit} RMS`
}

export function NoiseTotalsSummary({ noiseTotals, uiText }: NoiseTotalsSummaryProps) {
  if (!noiseTotals.applicable) {
    return null
  }

  return (
    <section className="noise-totals-panel" aria-label={getUiText(uiText, 'simulation.noise_totals.title', 'Integrated Noise Totals')}>
      <div className="noise-totals-panel__header">
        <div className="card-title">
          {getUiText(uiText, 'simulation.noise_totals.title', 'Integrated Noise Totals')}
        </div>
        <div className="noise-totals-panel__note">
          {getUiText(
            uiText,
            'simulation.noise_totals.note',
            'Read-only sweep-band integrated RMS scalars from ngspice (FSTART–FSTOP). They are not .MEASURE rows or V/√Hz / A/√Hz spectral-density samples.',
          )}
        </div>
      </div>
      {noiseTotals.available ? (
        <div className="noise-totals-panel__items">
          {noiseTotals.items.map((item) => (
            <div key={item.key} className="noise-totals-panel__item">
              <span className="noise-totals-panel__label">{itemLabel(item, uiText)}</span>
              <span className="noise-totals-panel__value">{itemValue(item)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="noise-totals-panel__unavailable">
          {getUiText(
            uiText,
            'simulation.noise_totals.unavailable',
            'Integrated totals are unavailable for this noise run; the spectral-density curves may still be available.',
          )}
        </div>
      )}
    </section>
  )
}
