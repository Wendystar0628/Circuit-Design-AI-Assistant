import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SchematicComponentState, SchematicDocumentState, SchematicEditableFieldState, SchematicWriteResultState } from '../../types/state'
import { ResponsivePane } from '../layout/ResponsivePane'
import { SchematicCanvas } from './SchematicCanvasSurface'
import { SchematicPropertyPanel } from './SchematicPropertyPanel'
import { computeSchematicLayout, createEmptySchematicViewState, fitSchematicViewToBounds } from './schematicLayout'
import type { SchematicLayoutResult } from './schematicLayoutTypes'

interface SchematicTabProps {
  bridge: SimulationBridge | null
  schematicDocument: SchematicDocumentState
  schematicWriteResult: SchematicWriteResultState
}

function getDraftKey(componentId: string, fieldKey: string): string {
  return `${componentId}::${fieldKey}`
}

interface SchematicLayoutState {
  result: SchematicLayoutResult | null
  pending: boolean
  error: string
}

interface ViewportSize {
  width: number
  height: number
}

interface PendingSchematicWriteRequest {
  requestId: string
  documentId: string
  revision: string
  componentId: string
  fieldKey: string
}

function createEmptyLayoutState(): SchematicLayoutState {
  return {
    result: null,
    pending: false,
    error: '',
  }
}

function createEmptyViewportSize(): ViewportSize {
  return {
    width: 0,
    height: 0,
  }
}

function buildLayoutRequestKey(documentId: string, revision: string): string {
  return `${documentId}::${revision}`
}

function getPendingWriteKey(componentId: string, fieldKey: string): string {
  return `${componentId}::${fieldKey}`
}

export function SchematicTab({ bridge, schematicDocument, schematicWriteResult }: SchematicTabProps) {
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(null)
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, string>>({})
  const [pendingWriteRequests, setPendingWriteRequests] = useState<Record<string, PendingSchematicWriteRequest>>({})
  const [staleDraftNotice, setStaleDraftNotice] = useState('')
  const [layoutState, setLayoutState] = useState<SchematicLayoutState>(createEmptyLayoutState)
  const [viewState, setViewState] = useState(createEmptySchematicViewState)
  const [viewportSize, setViewportSize] = useState<ViewportSize>(createEmptyViewportSize)
  const requestSequenceRef = useRef(0)
  const latestLayoutRequestKeyRef = useRef('')
  const pendingAutoFitRequestKeyRef = useRef('')
  const latestDocumentKeyRef = useRef('')

  const selectedComponent = useMemo<SchematicComponentState | null>(() => {
    if (!selectedComponentId) {
      return null
    }
    return schematicDocument.components.find((item) => item.id === selectedComponentId) ?? null
  }, [schematicDocument.components, selectedComponentId])

  useEffect(() => {
    const nextDocumentKey = `${schematicDocument.document_id}::${schematicDocument.revision}`
    const hadUnsavedDrafts = Object.keys(fieldDrafts).length > 0
    const hadPendingWrites = Object.keys(pendingWriteRequests).length > 0
    if (latestDocumentKeyRef.current && latestDocumentKeyRef.current !== nextDocumentKey && hadUnsavedDrafts && !hadPendingWrites) {
      setStaleDraftNotice('检测到权威文档已刷新，旧 revision 的本地草稿已丢弃。')
    }
    latestDocumentKeyRef.current = nextDocumentKey
    setFieldDrafts({})
    setPendingWriteRequests({})
  }, [schematicDocument.document_id, schematicDocument.revision])

  useEffect(() => {
    if (!schematicWriteResult.request_id) {
      return
    }
    setPendingWriteRequests((current) => {
      const nextEntries = Object.entries(current).filter(([, item]) => item.requestId !== schematicWriteResult.request_id)
      if (nextEntries.length === Object.keys(current).length) {
        return current
      }
      return Object.fromEntries(nextEntries)
    })
  }, [schematicWriteResult.request_id])

  useEffect(() => {
    if (!selectedComponentId) {
      return
    }
    if (!schematicDocument.components.some((item) => item.id === selectedComponentId)) {
      setSelectedComponentId(null)
    }
  }, [schematicDocument.components, selectedComponentId])

  useEffect(() => {
    if (selectedComponentId) {
      return
    }
    if (!schematicDocument.has_schematic || schematicDocument.components.length === 0) {
      return
    }
    setSelectedComponentId(schematicDocument.components[0].id)
  }, [schematicDocument.components, schematicDocument.has_schematic, selectedComponentId])

  useEffect(() => {
    const requestKey = buildLayoutRequestKey(schematicDocument.document_id, schematicDocument.revision)
    latestLayoutRequestKeyRef.current = requestKey
    pendingAutoFitRequestKeyRef.current = requestKey
    setLayoutState((current) => ({
      result: current.result,
      pending: true,
      error: '',
    }))

    let disposed = false

    void computeSchematicLayout(schematicDocument)
      .then((result) => {
        if (disposed || latestLayoutRequestKeyRef.current !== result.requestKey) {
          return
        }
        setLayoutState({
          result,
          pending: false,
          error: '',
        })
      })
      .catch((error: unknown) => {
        if (disposed || latestLayoutRequestKeyRef.current !== requestKey) {
          return
        }
        setLayoutState((current) => ({
          result: current.result,
          pending: false,
          error: error instanceof Error ? error.message : '电路布局计算失败。',
        }))
      })

    return () => {
      disposed = true
    }
  }, [schematicDocument.document_id, schematicDocument.revision])

  useEffect(() => {
    const bounds = layoutState.result?.bounds
    if (!bounds || viewportSize.width <= 0 || viewportSize.height <= 0 || layoutState.result === null) {
      return
    }
    if (pendingAutoFitRequestKeyRef.current !== layoutState.result.requestKey) {
      return
    }
    pendingAutoFitRequestKeyRef.current = ''
    setViewState(fitSchematicViewToBounds(bounds, viewportSize.width, viewportSize.height))
  }, [layoutState.result, viewportSize.height, viewportSize.width])

  const handleViewStateChange = useCallback((nextViewState: typeof viewState) => {
    setViewState((current) => {
      if (current.scale === nextViewState.scale && current.offsetX === nextViewState.offsetX && current.offsetY === nextViewState.offsetY) {
        return current
      }
      return nextViewState
    })
  }, [])

  const handleViewportSizeChange = useCallback((nextSize: ViewportSize) => {
    setViewportSize((current) => {
      if (current.width === nextSize.width && current.height === nextSize.height) {
        return current
      }
      return nextSize
    })
  }, [])

  const selectedFieldDrafts = useMemo(() => {
    if (selectedComponent === null) {
      return {}
    }
    return Object.fromEntries(selectedComponent.editable_fields.filter((field) => field.field_key === 'value').map((field) => [
      field.field_key,
      fieldDrafts[getDraftKey(selectedComponent.id, field.field_key)] ?? field.raw_text,
    ]))
  }, [fieldDrafts, selectedComponent])

  const selectedPendingFieldRequestIds = useMemo(() => {
    if (selectedComponent === null) {
      return {}
    }
    return Object.fromEntries(
      Object.values(pendingWriteRequests)
        .filter((item) => item.componentId === selectedComponent.id)
        .map((item) => [item.fieldKey, item.requestId]),
    )
  }, [pendingWriteRequests, selectedComponent])

  const handleDraftChange = (fieldKey: string, nextValue: string) => {
    if (selectedComponent === null) {
      return
    }
    setStaleDraftNotice('')
    setFieldDrafts((current) => ({
      ...current,
      [getDraftKey(selectedComponent.id, fieldKey)]: nextValue,
    }))
  }

  const handleSubmitField = (field: SchematicEditableFieldState) => {
    if (selectedComponent === null || !field.editable || !bridge) {
      return
    }
    if (field.field_key !== 'value') {
      return
    }
    const draftKey = getDraftKey(selectedComponent.id, field.field_key)
    const nextText = fieldDrafts[draftKey] ?? field.raw_text
    if (nextText === field.raw_text) {
      return
    }
    if (pendingWriteRequests[getPendingWriteKey(selectedComponent.id, field.field_key)]) {
      return
    }
    setStaleDraftNotice('')
    requestSequenceRef.current += 1
    const requestId = `${Date.now()}-${requestSequenceRef.current}`
    setPendingWriteRequests((current) => ({
      ...current,
      [getPendingWriteKey(selectedComponent.id, field.field_key)]: {
        requestId,
        documentId: schematicDocument.document_id,
        revision: schematicDocument.revision,
        componentId: selectedComponent.id,
        fieldKey: field.field_key,
      },
    }))
    bridge.updateSchematicValue({
      documentId: schematicDocument.document_id,
      revision: schematicDocument.revision,
      componentId: selectedComponent.id,
      fieldKey: field.field_key,
      newText: nextText,
      requestId,
    })
  }

  return (
    <div className="tab-surface">
      <ResponsivePane
        sidebarConfig={{
          defaultSize: 320,
          minSize: 280,
          maxSize: 460,
          mainMinSize: 360,
          resizable: true,
        }}
        sidebar={(
          <SchematicPropertyPanel
            component={selectedComponent}
            schematicWriteResult={schematicWriteResult}
            fieldDrafts={selectedFieldDrafts}
            pendingFieldRequestIds={selectedPendingFieldRequestIds}
            staleDraftNotice={staleDraftNotice}
            onDraftChange={handleDraftChange}
            onSubmitField={handleSubmitField}
          />
        )}
        main={(
          <div className="content-card content-card--canvas">
            <SchematicCanvas
              schematicDocument={schematicDocument}
              layoutResult={layoutState.result}
              layoutPending={layoutState.pending}
              layoutError={layoutState.error}
              selectedComponentId={selectedComponentId}
              viewState={viewState}
              onViewStateChange={handleViewStateChange}
              onViewportSizeChange={handleViewportSizeChange}
              onSelectComponent={setSelectedComponentId}
            />
          </div>
        )}
      />
    </div>
  )
}
