import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { SchematicComponentState, SchematicDocumentState, SchematicEditableFieldState, SchematicWriteResultState } from '../../types/state'
import { getUiText, type UiTextMap } from '../../uiText'
import { ResponsivePane } from '../layout/ResponsivePane'
import { SchematicCanvas } from './SchematicCanvasSurface'
import { SchematicPropertyPanel } from './SchematicPropertyPanel'
import { computeSchematicLayout, createEmptySchematicViewState, fitSchematicViewToBounds } from './schematicLayout'
import type { SchematicLayoutResult } from './schematicLayoutTypes'

interface SchematicTabProps {
  bridge: SimulationBridge | null
  schematicDocument: SchematicDocumentState
  schematicWriteResult: SchematicWriteResultState
  uiText: UiTextMap
}

function getDraftKey(componentId: string, fieldKey: string): string {
  return `${componentId}::${fieldKey}`
}

interface SchematicLayoutState {
  result: SchematicLayoutResult | null
  pending: boolean
  error: string
  fallbackErrorKey: string
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
    fallbackErrorKey: '',
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

export function SchematicTab({ bridge, schematicDocument, schematicWriteResult, uiText }: SchematicTabProps) {
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(null)
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, string>>({})
  const [pendingWriteRequests, setPendingWriteRequests] = useState<Record<string, PendingSchematicWriteRequest>>({})
  const [hasStaleDraftNotice, setHasStaleDraftNotice] = useState(false)
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
      setHasStaleDraftNotice(true)
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
      fallbackErrorKey: '',
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
          fallbackErrorKey: '',
        })
      })
      .catch((error: unknown) => {
        if (disposed || latestLayoutRequestKeyRef.current !== requestKey) {
          return
        }
        setLayoutState((current) => ({
          result: current.result,
          pending: false,
          error: error instanceof Error ? error.message : '',
          fallbackErrorKey: error instanceof Error ? '' : 'simulation.schematic.layout_failed',
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
    setHasStaleDraftNotice(false)
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
    setHasStaleDraftNotice(false)
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
  const staleDraftNotice = hasStaleDraftNotice
    ? getUiText(uiText, 'simulation.schematic.stale_draft_notice', 'The authoritative document was refreshed and local drafts for the old revision were discarded.')
    : ''
  const layoutErrorMessage = layoutState.error || (layoutState.fallbackErrorKey
    ? getUiText(uiText, layoutState.fallbackErrorKey, 'Failed to compute the schematic layout.')
    : '')

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
            uiText={uiText}
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
              layoutError={layoutErrorMessage}
              selectedComponentId={selectedComponentId}
              uiText={uiText}
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
