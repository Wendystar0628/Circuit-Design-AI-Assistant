import type { SchematicDocumentState, SchematicWriteResultState, SimulationMainState } from '../../types/state'
import { CompactToolbar } from '../layout/CompactToolbar'

interface SchematicTabProps {
  state: SimulationMainState
  schematicDocument: SchematicDocumentState
  schematicWriteResult: SchematicWriteResultState
}

export function SchematicTab({ state, schematicDocument, schematicWriteResult }: SchematicTabProps) {
  const currentResult = state.simulation_runtime.current_result
  const sourceFilePath = currentResult.file_path
  const hasSourceFile = Boolean(sourceFilePath)
  const hasSchematic = schematicDocument.has_schematic
  const latestWriteFailed = Boolean(schematicWriteResult.request_id) && !schematicWriteResult.success && Boolean(schematicWriteResult.error_message)

  return (
    <div className="tab-surface">
      <CompactToolbar
        title="电路"
        description="前端只消费后端权威 schematic_document，不重建第二套结构化真相"
      />
      <div className="content-card content-card--canvas">
        <div className="surface-state-stack">
          {hasSourceFile ? (
            <div className="surface-state-card surface-state-card--info">
              <div className="card-title">已锁定当前源电路文件</div>
              <div className="muted-text">后端文档生成与写回都严格基于这个本地 SPICE 文件，不额外猜测其它文件。</div>
              <div className="muted-text">{sourceFilePath}</div>
            </div>
          ) : (
            <div className="surface-state-card surface-state-card--empty">
              <div className="card-title">暂无可用电路文件</div>
              <div className="muted-text">当前结果缺少有效 `file_path`，电路页不会猜路径，也不会推断其它文件。</div>
            </div>
          )}
          {latestWriteFailed ? (
            <div className="surface-state-card surface-state-card--warning">
              <div className="card-title">最近一次写回未成功</div>
              <div className="muted-text">{schematicWriteResult.error_message}</div>
            </div>
          ) : null}
          {hasSchematic ? (
            <div className="surface-state-card surface-state-card--info">
              <div className="card-title">已收到权威电路文档</div>
              <div className="muted-text">文档 ID：{schematicDocument.document_id}</div>
              <div className="muted-text">Revision：{schematicDocument.revision}</div>
              <div className="muted-text">元件数：{schematicDocument.components.length}，网络数：{schematicDocument.nets.length}，子电路数：{schematicDocument.subcircuits.length}</div>
              {schematicDocument.readonly_reasons.length > 0 ? (
                <div className="muted-text">只读原因：{schematicDocument.readonly_reasons.join('；')}</div>
              ) : null}
            </div>
          ) : null}
          {schematicDocument.parse_errors.length > 0 ? (
            <div className="surface-state-card surface-state-card--warning">
              <div className="card-title">解析阶段发现问题</div>
              {schematicDocument.parse_errors.map((item, index) => (
                <div className="muted-text" key={`${item.source_file}-${item.line_index}-${index}`}>
                  {item.message}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
