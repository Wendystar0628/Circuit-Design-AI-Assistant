import type { SchematicComponentState, SchematicEditableFieldState, SchematicWriteResultState } from '../../types/state'
import { getSchematicComponentTypeLabel } from './symbolRegistry'

interface SchematicPropertyPanelProps {
  component: SchematicComponentState | null
  schematicWriteResult: SchematicWriteResultState
  fieldDrafts: Record<string, string>
  pendingFieldRequestIds: Record<string, string>
  staleDraftNotice: string
  canFit: boolean
  onFit(): void
  onDraftChange(fieldKey: string, nextValue: string): void
  onSubmitField(field: SchematicEditableFieldState): void
}

export function SchematicPropertyPanel({ component, schematicWriteResult, fieldDrafts, pendingFieldRequestIds, staleDraftNotice, canFit, onFit, onDraftChange, onSubmitField }: SchematicPropertyPanelProps) {
  const visibleFields = component ? component.editable_fields.filter((field) => field.field_key === 'value') : []
  const hasPendingWrite = component !== null && Object.keys(pendingFieldRequestIds).length > 0
  const componentTypeLabel = component ? getSchematicComponentTypeLabel(component) : '--'
  const currentComponentName = component?.instance_name || component?.display_name || component?.id || '--'
  const latestWriteMessage = component === null
    ? ''
    : hasPendingWrite
      ? '正在提交修改，等待后端重新解析并刷新。'
      : schematicWriteResult.component_id === component.id && schematicWriteResult.request_id
        ? schematicWriteResult.result_type === 'conflict'
          ? '检测到文档已变化，旧 revision 的提交已被拒绝，请基于当前内容重新修改。'
          : schematicWriteResult.error_message || (schematicWriteResult.success ? '修改已提交，当前显示以后端刷新结果为准。' : '')
        : ''

  const latestWriteMessageClassName = hasPendingWrite
    ? 'schematic-property-panel__write-banner schematic-property-panel__write-banner--pending'
    : schematicWriteResult.result_type === 'conflict'
      ? 'schematic-property-panel__write-banner schematic-property-panel__write-banner--warning'
      : `schematic-property-panel__write-banner${schematicWriteResult.success ? '' : ' schematic-property-panel__write-banner--error'}`

  const latestWriteFieldKey = component !== null && !hasPendingWrite && schematicWriteResult.component_id === component.id ? schematicWriteResult.field_key : ''

  return (
    <div className="content-card schematic-property-panel">
      <div className="schematic-property-panel__section">
        <div className="schematic-property-panel__toolbar">
          <button
            type="button"
            className="toolbar-button schematic-property-panel__toolbar-button"
            disabled={!canFit}
            onClick={onFit}
          >
            Fit
          </button>
        </div>
      </div>

      {component ? (
        <>
          <div className="schematic-property-panel__section">
            <div className="schematic-property-panel__meta-grid">
              <div className="schematic-property-panel__meta-item">
                <span className="schematic-property-panel__meta-label">元件类型</span>
                <span className="schematic-property-panel__meta-value">{componentTypeLabel}</span>
              </div>
              <div className="schematic-property-panel__meta-item">
                <span className="schematic-property-panel__meta-label">当前元件名称</span>
                <span className="schematic-property-panel__meta-value">{currentComponentName}</span>
              </div>
            </div>
          </div>

          <div className="schematic-property-panel__section">
            <div className="card-title">连接节点</div>
            <div className="schematic-property-panel__pin-list">
              {component.pins.length > 0 ? component.pins.map((pin) => (
                <div className="schematic-property-panel__pin-item" key={`${component.id}-${pin.name}`}>
                  <span className="schematic-property-panel__pin-name">{pin.name}</span>
                  <span className="schematic-property-panel__pin-node">{pin.node_id || '--'}</span>
                </div>
              )) : <div className="muted-text">当前器件没有可展示的引脚。</div>}
            </div>
          </div>

          <div className="schematic-property-panel__section schematic-property-panel__section--grow">
            <div className="card-title">元件数值</div>
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
                        <span className="schematic-property-panel__field-caption">当前值</span>
                        <input
                          className="schematic-property-panel__input"
                          type="text"
                          value={currentValue}
                          readOnly
                        />
                      </label>
                      <label className="schematic-property-panel__field-label">
                        <span className="schematic-property-panel__field-caption">替换值</span>
                        <input
                          className="schematic-property-panel__input"
                          type="text"
                          value={draftValue}
                          disabled={!field.editable || isPending}
                          onChange={(event) => onDraftChange(field.field_key, event.target.value)}
                        />
                      </label>
                    </div>
                    {!field.editable ? <div className="muted-text">{field.readonly_reason || '当前元件数值不可修改'}</div> : null}
                    <div className="schematic-property-panel__field-footer">
                      <div className="muted-text">{isPending ? '正在提交修改...' : ''}</div>
                      <button
                        type="button"
                        className="toolbar-button"
                        disabled={!field.editable || draftValue === field.raw_text || isPending}
                        onClick={() => onSubmitField(field)}
                      >
                        {isPending ? '提交中...' : '提交'}
                      </button>
                    </div>
                    {isPending ? (
                      <div className="schematic-property-panel__write-message schematic-property-panel__write-message--pending">
                        正在请求后端写回，当前显示以后端刷新结果为准。
                      </div>
                    ) : null}
                    {isCurrentWriteTarget && schematicWriteResult.error_message ? (
                      <div className="schematic-property-panel__write-message schematic-property-panel__write-message--error">
                        {schematicWriteResult.error_message}
                      </div>
                    ) : null}
                  </div>
                )
              }) : <div className="muted-text">当前元件没有可修改的数值。</div>}
            </div>
          </div>
        </>
      ) : (
        <div className="schematic-property-panel__section schematic-property-panel__section--grow">
          <div className="card-title">元件详情</div>
          <div className="muted-text">选择一个元件查看类型、连接节点和元件数值。</div>
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
