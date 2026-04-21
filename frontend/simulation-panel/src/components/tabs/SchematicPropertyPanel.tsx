import type { SchematicComponentState, SchematicEditableFieldState, SchematicWriteResultState } from '../../types/state'
import { getUiText, type UiTextMap } from '../../uiText'
import { getSchematicComponentDisplayName } from './schematicComponentName'
import { getSchematicComponentTypeLabel } from './symbolRegistry'

interface SchematicPropertyPanelProps {
  component: SchematicComponentState | null
  schematicWriteResult: SchematicWriteResultState
  fieldDrafts: Record<string, string>
  pendingFieldRequestIds: Record<string, string>
  staleDraftNotice: string
  uiText: UiTextMap
  onDraftChange(fieldKey: string, nextValue: string): void
  onSubmitField(field: SchematicEditableFieldState): void
}

export function SchematicPropertyPanel({ component, schematicWriteResult, fieldDrafts, pendingFieldRequestIds, staleDraftNotice, uiText, onDraftChange, onSubmitField }: SchematicPropertyPanelProps) {
  const visibleFields = component ? component.editable_fields.filter((field) => field.field_key === 'value') : []
  const hasPendingWrite = component !== null && Object.keys(pendingFieldRequestIds).length > 0
  const componentTypeLabel = component ? getSchematicComponentTypeLabel(component, uiText) : '--'
  const currentComponentName = getSchematicComponentDisplayName(component) || '--'
  const latestWriteMessage = component === null
    ? ''
    : hasPendingWrite
      ? getUiText(uiText, 'simulation.schematic.write_pending_banner', 'Submitting changes and waiting for the backend to re-parse and refresh.')
      : schematicWriteResult.component_id === component.id && schematicWriteResult.request_id
        ? schematicWriteResult.result_type === 'conflict'
          ? getUiText(uiText, 'simulation.schematic.write_conflict_banner', 'The document changed. The submission for the old revision was rejected. Please edit again based on the current content.')
          : schematicWriteResult.error_message || (schematicWriteResult.success ? getUiText(uiText, 'simulation.schematic.write_success_banner', 'Changes were submitted. The current display follows the refreshed backend result.') : '')
        : ''

  const latestWriteMessageClassName = hasPendingWrite
    ? 'schematic-property-panel__write-banner schematic-property-panel__write-banner--pending'
    : schematicWriteResult.result_type === 'conflict'
      ? 'schematic-property-panel__write-banner schematic-property-panel__write-banner--warning'
      : `schematic-property-panel__write-banner${schematicWriteResult.success ? '' : ' schematic-property-panel__write-banner--error'}`

  const latestWriteFieldKey = component !== null && !hasPendingWrite && schematicWriteResult.component_id === component.id ? schematicWriteResult.field_key : ''

  return (
    <div className="content-card schematic-property-panel">
      {component ? (
        <>
          <div className="schematic-property-panel__section">
            <div className="schematic-property-panel__meta-grid">
              <div className="schematic-property-panel__meta-item">
                <span className="schematic-property-panel__meta-label">{getUiText(uiText, 'simulation.schematic.component_type', 'Component Type')}</span>
                <span className="schematic-property-panel__meta-value">{componentTypeLabel}</span>
              </div>
              <div className="schematic-property-panel__meta-item">
                <span className="schematic-property-panel__meta-label">{getUiText(uiText, 'simulation.schematic.component_name', 'Current Component Name')}</span>
                <span className="schematic-property-panel__meta-value">{currentComponentName}</span>
              </div>
            </div>
          </div>

          <div className="schematic-property-panel__section">
            <div className="card-title">{getUiText(uiText, 'simulation.schematic.connected_nodes', 'Connected Nodes')}</div>
            <div className="schematic-property-panel__pin-list">
              {component.pins.length > 0 ? component.pins.map((pin) => (
                <div className="schematic-property-panel__pin-item" key={`${component.id}-${pin.name}`}>
                  <span className="schematic-property-panel__pin-name">{pin.name}</span>
                  <span className="schematic-property-panel__pin-node">{pin.node_id || '--'}</span>
                </div>
              )) : <div className="muted-text">{getUiText(uiText, 'simulation.schematic.no_pins', 'This component has no pins to display.')}</div>}
            </div>
          </div>

          <div className="schematic-property-panel__section schematic-property-panel__section--grow">
            <div className="card-title">{getUiText(uiText, 'simulation.schematic.component_value', 'Component Value')}</div>
            <div className="schematic-property-panel__field-list">
              {visibleFields.length > 0 ? visibleFields.map((field) => {
                const draftValue = fieldDrafts[field.field_key] ?? field.raw_text
                const isPending = Boolean(pendingFieldRequestIds[field.field_key])
                const isCurrentWriteTarget = latestWriteFieldKey === field.field_key && Boolean(schematicWriteResult.request_id)
                const currentValue = field.raw_text || component.display_value || ''
                return (
                  <div className={`schematic-property-panel__field-card${field.editable ? '' : ' schematic-property-panel__field-card--readonly'}`} key={`${component.id}-${field.field_key}`}>
                    <div className="schematic-property-panel__meta-grid">
                      <label className="schematic-property-panel__field-label">
                        <span className="schematic-property-panel__field-caption">{getUiText(uiText, 'simulation.schematic.current_value', 'Current Value')}</span>
                        <input
                          className="schematic-property-panel__input"
                          type="text"
                          value={currentValue}
                          readOnly
                        />
                      </label>
                      <label className="schematic-property-panel__field-label">
                        <span className="schematic-property-panel__field-caption">{getUiText(uiText, 'simulation.schematic.replacement_value', 'Replacement Value')}</span>
                        <input
                          className="schematic-property-panel__input"
                          type="text"
                          value={draftValue}
                          disabled={!field.editable || isPending}
                          onChange={(event) => onDraftChange(field.field_key, event.target.value)}
                        />
                      </label>
                    </div>
                    {!field.editable ? <div className="muted-text">{field.readonly_reason || getUiText(uiText, 'simulation.schematic.value_not_editable', 'The current component value cannot be edited.')}</div> : null}
                    <div className="schematic-property-panel__field-footer">
                      <div className="muted-text">{isPending ? getUiText(uiText, 'simulation.schematic.pending_write', 'Submitting changes...') : ''}</div>
                      <button
                        type="button"
                        className="sim-compact-button sim-compact-button--accent"
                        disabled={!field.editable || draftValue === field.raw_text || isPending}
                        onClick={() => onSubmitField(field)}
                      >
                        {isPending ? getUiText(uiText, 'common.submitting', 'Submitting...') : getUiText(uiText, 'common.submit', 'Submit')}
                      </button>
                    </div>
                    {isPending ? (
                      <div className="schematic-property-panel__write-message schematic-property-panel__write-message--pending">
                        {getUiText(uiText, 'simulation.schematic.pending_write_hint', 'Requesting backend write-back. The current display follows the refreshed backend result.')}
                      </div>
                    ) : null}
                    {isCurrentWriteTarget && schematicWriteResult.error_message ? (
                      <div className="schematic-property-panel__write-message schematic-property-panel__write-message--error">
                        {schematicWriteResult.error_message}
                      </div>
                    ) : null}
                  </div>
                )
              }) : <div className="muted-text">{getUiText(uiText, 'simulation.schematic.no_editable_value', 'This component has no editable value.')}</div>}
            </div>
          </div>
        </>
      ) : (
        <div className="schematic-property-panel__section schematic-property-panel__section--grow">
          <div className="card-title">{getUiText(uiText, 'simulation.schematic.component_details', 'Component Details')}</div>
          <div className="muted-text">{getUiText(uiText, 'simulation.schematic.component_details_hint', 'Select a component to inspect its type, connected nodes, and component value.')}</div>
        </div>
      )}

      {latestWriteMessage ? (
        <div className={latestWriteMessageClassName}>
          {latestWriteMessage}
        </div>
      ) : null}
      {staleDraftNotice ? (
        <div className="schematic-property-panel__write-banner schematic-property-panel__write-banner--warning">
          {staleDraftNotice}
        </div>
      ) : null}
    </div>
  )
}
