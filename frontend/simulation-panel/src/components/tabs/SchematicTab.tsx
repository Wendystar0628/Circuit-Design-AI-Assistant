import { useEffect, useMemo, useRef, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SchematicComponentState, SchematicDocumentState, SchematicEditableFieldState, SchematicWriteResultState } from '../../types/state'
import { ResponsivePane } from '../layout/ResponsivePane'
import { CompactToolbar } from '../layout/CompactToolbar'
import { SchematicCanvas } from './SchematicCanvas'
import { SchematicPropertyPanel } from './SchematicPropertyPanel'

interface SchematicTabProps {
  bridge: SimulationBridge | null
  schematicDocument: SchematicDocumentState
  schematicWriteResult: SchematicWriteResultState
}

function getDraftKey(componentId: string, fieldKey: string): string {
  return `${componentId}::${fieldKey}`
}

export function SchematicTab({ bridge, schematicDocument, schematicWriteResult }: SchematicTabProps) {
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(null)
  const [fitSignal, setFitSignal] = useState(0)
  const [relayoutSignal, setRelayoutSignal] = useState(0)
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, string>>({})
  const requestSequenceRef = useRef(0)

  const selectedComponent = useMemo<SchematicComponentState | null>(() => {
    if (!selectedComponentId) {
      return null
    }
    return schematicDocument.components.find((item) => item.id === selectedComponentId) ?? null
  }, [schematicDocument.components, selectedComponentId])

  useEffect(() => {
    setFieldDrafts({})
    setFitSignal((current) => current + 1)
  }, [schematicDocument.document_id, schematicDocument.revision])

  useEffect(() => {
    if (!selectedComponentId) {
      return
    }
    if (!schematicDocument.components.some((item) => item.id === selectedComponentId)) {
      setSelectedComponentId(null)
    }
  }, [schematicDocument.components, selectedComponentId])

  const selectedFieldDrafts = useMemo(() => {
    if (selectedComponent === null) {
      return {}
    }
    return Object.fromEntries(selectedComponent.editable_fields.map((field) => [
      field.field_key,
      fieldDrafts[getDraftKey(selectedComponent.id, field.field_key)] ?? field.raw_text,
    ]))
  }, [fieldDrafts, selectedComponent])

  const handleDraftChange = (fieldKey: string, nextValue: string) => {
    if (selectedComponent === null) {
      return
    }
    setFieldDrafts((current) => ({
      ...current,
      [getDraftKey(selectedComponent.id, fieldKey)]: nextValue,
    }))
  }

  const handleSubmitField = (field: SchematicEditableFieldState) => {
    if (selectedComponent === null || !field.editable || !bridge) {
      return
    }
    const draftKey = getDraftKey(selectedComponent.id, field.field_key)
    const nextText = fieldDrafts[draftKey] ?? field.raw_text
    if (nextText === field.raw_text) {
      return
    }
    requestSequenceRef.current += 1
    bridge.updateSchematicValue({
      documentId: schematicDocument.document_id,
      revision: schematicDocument.revision,
      componentId: selectedComponent.id,
      fieldKey: field.field_key,
      newText: nextText,
      requestId: `${Date.now()}-${requestSequenceRef.current}`,
    })
  }

  const toolbarActions = (
    <>
      <button
        type="button"
        className="chart-header-button"
        disabled={!schematicDocument.has_schematic}
        onClick={() => setFitSignal((current) => current + 1)}
      >
        Fit
      </button>
      <button
        type="button"
        className="chart-header-button chart-header-button--accent"
        disabled={!schematicDocument.has_schematic}
        onClick={() => {
          setRelayoutSignal((current) => current + 1)
          setFitSignal((current) => current + 1)
        }}
      >
        重新布局
      </button>
    </>
  )

  return (
    <div className="tab-surface">
      <CompactToolbar title={schematicDocument.title || '电路'} actions={toolbarActions} />
      <ResponsivePane
        sidebarConfig={{
          defaultSize: 320,
          minSize: 280,
          maxSize: 460,
          mainMinSize: 360,
          resizable: true,
        }}
        sidebar={selectedComponent ? (
          <SchematicPropertyPanel
            component={selectedComponent}
            schematicDocument={schematicDocument}
            schematicWriteResult={schematicWriteResult}
            fieldDrafts={selectedFieldDrafts}
            onDraftChange={handleDraftChange}
            onSubmitField={handleSubmitField}
          />
        ) : undefined}
        main={(
          <div className="content-card content-card--canvas">
            <SchematicCanvas
              schematicDocument={schematicDocument}
              selectedComponentId={selectedComponentId}
              fitSignal={fitSignal}
              relayoutSignal={relayoutSignal}
              onSelectComponent={setSelectedComponentId}
            />
          </div>
        )}
      />
    </div>
  )
}
