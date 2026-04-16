import type { SchematicComponentState, SchematicDocumentState, SchematicEditableFieldState, SchematicWriteResultState } from '../../types/state'
import { isSchematicComponentReadonly } from './symbolRegistry'

interface SchematicPropertyPanelProps {
  component: SchematicComponentState
  schematicDocument: SchematicDocumentState
  schematicWriteResult: SchematicWriteResultState
  fieldDrafts: Record<string, string>
  pendingFieldRequestIds: Record<string, string>
  staleDraftNotice: string
  onDraftChange(fieldKey: string, nextValue: string): void
  onSubmitField(field: SchematicEditableFieldState): void
}

function buildFieldStatusLabel(component: SchematicComponentState, field: SchematicEditableFieldState, writeResult: SchematicWriteResultState, pendingFieldRequestIds: Record<string, string>): string {
  if (pendingFieldRequestIds[field.field_key]) {
    return '提交中'
  }
  if (writeResult.component_id === component.id && writeResult.field_key === field.field_key && writeResult.request_id) {
    if (writeResult.result_type === 'conflict') {
      return '发生冲突'
    }
    return writeResult.success ? '已回写' : '写回失败'
  }
  if (!field.editable) {
    return '只读'
  }
  return '可编辑'
}

function buildFieldStatusClassName(component: SchematicComponentState, field: SchematicEditableFieldState, writeResult: SchematicWriteResultState, pendingFieldRequestIds: Record<string, string>): string {
  if (pendingFieldRequestIds[field.field_key]) {
    return 'schematic-property-panel__status schematic-property-panel__status--pending'
  }
  if (writeResult.component_id === component.id && writeResult.field_key === field.field_key && writeResult.request_id) {
    return writeResult.success
      ? 'schematic-property-panel__status schematic-property-panel__status--success'
      : writeResult.result_type === 'conflict'
        ? 'schematic-property-panel__status schematic-property-panel__status--warning'
        : 'schematic-property-panel__status schematic-property-panel__status--error'
  }
  if (!field.editable) {
    return 'schematic-property-panel__status schematic-property-panel__status--readonly'
  }
  return 'schematic-property-panel__status schematic-property-panel__status--editable'
}

export function SchematicPropertyPanel({ component, schematicDocument, schematicWriteResult, fieldDrafts, pendingFieldRequestIds, staleDraftNotice, onDraftChange, onSubmitField }: SchematicPropertyPanelProps) {
  const readonly = isSchematicComponentReadonly(component)
  const visibleFields = component.editable_fields.filter((field) => field.field_key === 'value')
  const hasPendingWrite = Object.keys(pendingFieldRequestIds).length > 0
  const latestWriteMessage = hasPendingWrite
    ? '正在写回本地源文件，等待后端重新解析并回推最新文档。'
    : schematicWriteResult.component_id === component.id && schematicWriteResult.request_id
      ? schematicWriteResult.result_type === 'conflict'
        ? '检测到源文件已变化，旧 revision 提交已被拒绝，请基于当前权威文档重新修改。'
        : schematicWriteResult.error_message || (schematicWriteResult.success ? '最新写回已完成，当前渲染以后端回推文档为准。' : '')
      : ''

  const latestWriteMessageClassName = hasPendingWrite
    ? 'schematic-property-panel__write-banner schematic-property-panel__write-banner--pending'
    : schematicWriteResult.result_type === 'conflict'
      ? 'schematic-property-panel__write-banner schematic-property-panel__write-banner--warning'
      : `schematic-property-panel__write-banner${schematicWriteResult.success ? '' : ' schematic-property-panel__write-banner--error'}`

  const latestWriteFieldKey = !hasPendingWrite && schematicWriteResult.component_id === component.id ? schematicWriteResult.field_key : ''

  return (
    <div className="content-card schematic-property-panel">
      <div className="schematic-property-panel__section">
        <div className="schematic-property-panel__header">
          <div>
            <div className="card-title">{component.instance_name || component.display_name || component.id}</div>
            <div className="card-subtitle">{component.display_name || component.kind || component.symbol_kind}</div>
          </div>
          <div className={`schematic-property-panel__badge${readonly ? ' schematic-property-panel__badge--readonly' : ''}`}>
            {readonly ? '只读' : '可编辑'}
          </div>
        </div>
        <div className="schematic-property-panel__meta-grid">
          <div className="schematic-property-panel__meta-item">
            <span className="schematic-property-panel__meta-label">器件类型</span>
            <span className="schematic-property-panel__meta-value">{component.kind || component.symbol_kind || '--'}</span>
          </div>
          <div className="schematic-property-panel__meta-item">
            <span className="schematic-property-panel__meta-label">当前值</span>
            <span className="schematic-property-panel__meta-value">{component.display_value || '--'}</span>
          </div>
          <div className="schematic-property-panel__meta-item">
            <span className="schematic-property-panel__meta-label">所在文档</span>
            <span className="schematic-property-panel__meta-value">{schematicDocument.file_name || schematicDocument.title || '--'}</span>
          </div>
          <div className="schematic-property-panel__meta-item">
            <span className="schematic-property-panel__meta-label">源文件</span>
            <span className="schematic-property-panel__meta-value">{component.source_file || schematicDocument.file_path || '--'}</span>
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
        <div className="card-title">可编辑字段</div>
        <div className="schematic-property-panel__field-list">
          {visibleFields.length > 0 ? visibleFields.map((field) => {
            const draftValue = fieldDrafts[field.field_key] ?? field.raw_text
            const isPending = Boolean(pendingFieldRequestIds[field.field_key])
            const isCurrentWriteTarget = latestWriteFieldKey === field.field_key && Boolean(schematicWriteResult.request_id)
            return (
              <div className={`schematic-property-panel__field-card${field.editable ? '' : ' schematic-property-panel__field-card--readonly'}`} key={`${component.id}-${field.field_key}`}>
                <div className="schematic-property-panel__field-header">
                  <div>
                    <div className="schematic-property-panel__field-title">{field.label || field.field_key}</div>
                    <div className="card-subtitle">{field.value_kind || 'text'}</div>
                  </div>
                  <div className={buildFieldStatusClassName(component, field, schematicWriteResult, pendingFieldRequestIds)}>
                    {buildFieldStatusLabel(component, field, schematicWriteResult, pendingFieldRequestIds)}
                  </div>
                </div>
                <label className="schematic-property-panel__field-label">
                  <span className="schematic-property-panel__field-caption">当前文本</span>
                  <input
                    className="schematic-property-panel__input"
                    type="text"
                    value={draftValue}
                    disabled={!field.editable || isPending}
                    onChange={(event) => onDraftChange(field.field_key, event.target.value)}
                  />
                </label>
                <div className="schematic-property-panel__field-footer">
                  <div className="muted-text">
                    {field.editable ? `原始值：${field.raw_text || '--'}` : field.readonly_reason || '当前字段不可编辑'}
                  </div>
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
                    正在请求后端写回源文件，当前显示值仍以后端文档为准。
                  </div>
                ) : null}
                {isCurrentWriteTarget && schematicWriteResult.error_message ? (
                  <div className="schematic-property-panel__write-message schematic-property-panel__write-message--error">
                    {schematicWriteResult.error_message}
                  </div>
                ) : null}
              </div>
            )
          }) : <div className="muted-text">当前器件没有可编辑字段。</div>}
        </div>
      </div>

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
