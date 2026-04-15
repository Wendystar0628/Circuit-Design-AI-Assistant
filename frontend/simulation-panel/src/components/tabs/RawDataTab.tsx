import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react'

import type { SimulationBridge } from '../../bridge/bridge'
import type { RawDataCopyResultState, RawDataDocumentState, RawDataViewportState } from '../../types/state'

const FALLBACK_ROW_HEIGHT_PX = 28
const FALLBACK_COLUMN_HEADER_HEIGHT_PX = 32
const FALLBACK_ROW_HEADER_WIDTH_PX = 64
const MIN_COLUMN_WIDTH_PX = 96
const ROW_OVERSCAN = 20
const COLUMN_OVERSCAN = 4

interface GridCellPosition {
  row: number
  col: number
}

interface GridSelectionState {
  anchor: GridCellPosition
  focus: GridCellPosition
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) {
    return min
  }
  if (value > max) {
    return max
  }
  return value
}

function findColumnIndexAtOffset(offset: number, boundaries: number[]): number {
  if (boundaries.length <= 1) {
    return 0
  }
  const maxIndex = boundaries.length - 2
  const normalizedOffset = Math.max(0, offset)
  let low = 0
  let high = maxIndex
  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const start = boundaries[mid]
    const end = boundaries[mid + 1]
    if (normalizedOffset < start) {
      high = mid - 1
      continue
    }
    if (normalizedOffset >= end) {
      low = mid + 1
      continue
    }
    return mid
  }
  return clamp(low, 0, maxIndex)
}

function normalizeSelection(selection: GridSelectionState | null) {
  if (!selection) {
    return null
  }
  return {
    startRow: Math.min(selection.anchor.row, selection.focus.row),
    endRow: Math.max(selection.anchor.row, selection.focus.row),
    startCol: Math.min(selection.anchor.col, selection.focus.col),
    endCol: Math.max(selection.anchor.col, selection.focus.col),
  }
}

interface RawDataTabProps {
  rawDataCopyResult: RawDataCopyResultState
  rawDataDocument: RawDataDocumentState
  rawDataViewport: RawDataViewportState
  bridge: SimulationBridge | null
}

export const RawDataTab = memo(function RawDataTab({ rawDataCopyResult, rawDataDocument, rawDataViewport, bridge }: RawDataTabProps) {
  const bodyScrollRef = useRef<HTMLDivElement | null>(null)
  const [bodySize, setBodySize] = useState({ width: 0, height: 0 })
  const [scrollLeft, setScrollLeft] = useState(0)
  const [scrollTop, setScrollTop] = useState(0)
  const [selection, setSelection] = useState<GridSelectionState | null>(null)
  const [dragging, setDragging] = useState(false)
  const [copyFeedback, setCopyFeedback] = useState('')
  const [pendingCopySequence, setPendingCopySequence] = useState(0)

  const rowCount = rawDataDocument.row_count
  const columns = rawDataDocument.columns
  const columnCount = columns.length
  const rowHeight = Math.max(rawDataDocument.row_height_px || FALLBACK_ROW_HEIGHT_PX, 20)
  const columnHeaderHeight = Math.max(rawDataDocument.column_header_height_px || FALLBACK_COLUMN_HEADER_HEIGHT_PX, 24)
  const rowHeaderWidth = Math.max(rawDataDocument.row_header_width_px || FALLBACK_ROW_HEADER_WIDTH_PX, 52)

  const columnWidths = useMemo(
    () => columns.map((column) => Math.max(column.width_px || 0, MIN_COLUMN_WIDTH_PX)),
    [columns],
  )

  const columnBoundaries = useMemo(() => {
    const boundaries = [0]
    for (const width of columnWidths) {
      boundaries.push(boundaries[boundaries.length - 1] + width)
    }
    return boundaries
  }, [columnWidths])

  const totalWidth = columnBoundaries[columnBoundaries.length - 1] || 0
  const totalHeight = rowCount * rowHeight
  const viewportMatchesDocument = rawDataViewport.dataset_id === rawDataDocument.dataset_id && rawDataViewport.version === rawDataDocument.version

  useEffect(() => {
    const element = bodyScrollRef.current
    if (!element) {
      return
    }
    const updateSize = () => {
      setBodySize({ width: element.clientWidth, height: element.clientHeight })
    }
    updateSize()
    const observer = new ResizeObserver(updateSize)
    observer.observe(element)
    return () => {
      observer.disconnect()
    }
  }, [])

  useEffect(() => {
    const scroller = bodyScrollRef.current
    if (scroller) {
      scroller.scrollTo({ left: 0, top: 0 })
    }
    setScrollLeft(0)
    setScrollTop(0)
    setPendingCopySequence(0)
    setCopyFeedback('')
    if (rawDataDocument.has_data && rowCount > 0 && columnCount > 0) {
      setSelection({ anchor: { row: 0, col: 0 }, focus: { row: 0, col: 0 } })
      return
    }
    setSelection(null)
  }, [rawDataDocument.dataset_id, rawDataDocument.version, rawDataDocument.has_data, rowCount, columnCount])

  useEffect(() => {
    if (!copyFeedback) {
      return
    }
    const handle = window.setTimeout(() => {
      setCopyFeedback('')
    }, 1200)
    return () => {
      window.clearTimeout(handle)
    }
  }, [copyFeedback])

  useEffect(() => {
    if (!pendingCopySequence) {
      return
    }
    if (rawDataCopyResult.sequence < pendingCopySequence) {
      return
    }
    if (rawDataCopyResult.dataset_id !== rawDataDocument.dataset_id || rawDataCopyResult.version !== rawDataDocument.version) {
      return
    }
    setPendingCopySequence(0)
    if (!rawDataCopyResult.success) {
      setCopyFeedback('复制失败')
      return
    }
    const rowCountLabel = Math.max(rawDataCopyResult.row_count, 0)
    const colCountLabel = Math.max(rawDataCopyResult.col_count, 0)
    setCopyFeedback(`已复制 ${rowCountLabel} × ${colCountLabel}`)
  }, [pendingCopySequence, rawDataCopyResult, rawDataDocument.dataset_id, rawDataDocument.version])

  const viewportRowMap = useMemo(() => {
    const map = new Map<number, string[]>()
    if (!viewportMatchesDocument) {
      return map
    }
    for (const row of rawDataViewport.rows) {
      map.set(row.row_index, row.values)
    }
    return map
  }, [viewportMatchesDocument, rawDataViewport.rows])

  const visibleRowStart = Math.min(rowCount, Math.max(0, Math.floor(scrollTop / rowHeight)))
  const visibleRowEnd = Math.min(
    rowCount,
    Math.max(visibleRowStart, Math.ceil((scrollTop + Math.max(bodySize.height, 1)) / rowHeight)),
  )

  const visibleColStart = columnCount > 0
    ? clamp(findColumnIndexAtOffset(scrollLeft, columnBoundaries), 0, columnCount - 1)
    : 0
  const visibleColEnd = columnCount > 0
    ? Math.min(
      columnCount,
      Math.max(
        visibleColStart + 1,
        findColumnIndexAtOffset(scrollLeft + Math.max(bodySize.width - 1, 0), columnBoundaries) + 1,
      ),
    )
    : 0

  const requestedRange = useMemo(() => {
    if (!rawDataDocument.has_data || rowCount <= 0 || columnCount <= 0 || bodySize.width <= 0 || bodySize.height <= 0) {
      return null
    }
    return {
      rowStart: Math.max(0, visibleRowStart - ROW_OVERSCAN),
      rowEnd: Math.min(rowCount, visibleRowEnd + ROW_OVERSCAN),
      colStart: Math.max(0, visibleColStart - COLUMN_OVERSCAN),
      colEnd: Math.min(columnCount, visibleColEnd + COLUMN_OVERSCAN),
    }
  }, [bodySize.height, bodySize.width, columnCount, rawDataDocument.has_data, rowCount, visibleColEnd, visibleColStart, visibleRowEnd, visibleRowStart])

  useEffect(() => {
    if (!bridge || !requestedRange || !rawDataDocument.has_data) {
      return
    }
    bridge.requestRawDataViewport({
      datasetId: rawDataDocument.dataset_id,
      version: rawDataDocument.version,
      rowStart: requestedRange.rowStart,
      rowEnd: requestedRange.rowEnd,
      colStart: requestedRange.colStart,
      colEnd: requestedRange.colEnd,
    })
  }, [
    bridge,
    rawDataDocument.dataset_id,
    rawDataDocument.has_data,
    rawDataDocument.version,
    requestedRange,
  ])

  const getCellValue = useCallback((row: number, col: number) => {
    if (!viewportMatchesDocument) {
      return ''
    }
    if (row < rawDataViewport.row_start || row >= rawDataViewport.row_end) {
      return ''
    }
    if (col < rawDataViewport.col_start || col >= rawDataViewport.col_end) {
      return ''
    }
    const rowValues = viewportRowMap.get(row)
    if (!rowValues) {
      return ''
    }
    return rowValues[col - rawDataViewport.col_start] || ''
  }, [rawDataViewport.col_end, rawDataViewport.col_start, rawDataViewport.row_end, rawDataViewport.row_start, viewportMatchesDocument, viewportRowMap])

  const selectionRange = useMemo(() => normalizeSelection(selection), [selection])
  const selectionLabel = selectionRange
    ? `${selectionRange.endRow - selectionRange.startRow + 1} × ${selectionRange.endCol - selectionRange.startCol + 1}`
    : ''

  const getCellFromClientPoint = useCallback((clientX: number, clientY: number): GridCellPosition | null => {
    if (!rawDataDocument.has_data || rowCount <= 0 || columnCount <= 0) {
      return null
    }
    const scroller = bodyScrollRef.current
    if (!scroller) {
      return null
    }
    const rect = scroller.getBoundingClientRect()
    const offsetX = scrollLeft + clientX - rect.left
    const offsetY = scrollTop + clientY - rect.top
    if (offsetX < 0 || offsetY < 0) {
      return null
    }
    const row = clamp(Math.floor(offsetY / rowHeight), 0, rowCount - 1)
    const col = clamp(findColumnIndexAtOffset(offsetX, columnBoundaries), 0, columnCount - 1)
    return { row, col }
  }, [columnBoundaries, columnCount, rawDataDocument.has_data, rowCount, rowHeight, scrollLeft, scrollTop])

  useEffect(() => {
    if (!dragging) {
      return
    }
    const handleMouseMove = (event: MouseEvent) => {
      const cell = getCellFromClientPoint(event.clientX, event.clientY)
      if (!cell) {
        return
      }
      setSelection((previous) => previous ? { anchor: previous.anchor, focus: cell } : { anchor: cell, focus: cell })
    }
    const handleMouseUp = () => {
      setDragging(false)
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [dragging, getCellFromClientPoint])

  const ensureCellVisible = useCallback((cell: GridCellPosition) => {
    const scroller = bodyScrollRef.current
    if (!scroller) {
      return
    }
    const cellLeft = columnBoundaries[cell.col] || 0
    const cellRight = columnBoundaries[cell.col + 1] || cellLeft
    const cellTop = cell.row * rowHeight
    const cellBottom = cellTop + rowHeight
    let nextLeft = scroller.scrollLeft
    let nextTop = scroller.scrollTop
    if (cellLeft < nextLeft) {
      nextLeft = cellLeft
    } else if (cellRight > nextLeft + scroller.clientWidth) {
      nextLeft = cellRight - scroller.clientWidth
    }
    if (cellTop < nextTop) {
      nextTop = cellTop
    } else if (cellBottom > nextTop + scroller.clientHeight) {
      nextTop = cellBottom - scroller.clientHeight
    }
    if (nextLeft !== scroller.scrollLeft || nextTop !== scroller.scrollTop) {
      scroller.scrollTo({ left: nextLeft, top: nextTop })
    }
  }, [columnBoundaries, rowHeight])

  const updateSelectionToCell = useCallback((cell: GridCellPosition, extend: boolean) => {
    setSelection((previous) => {
      if (extend && previous) {
        return { anchor: previous.anchor, focus: cell }
      }
      return { anchor: cell, focus: cell }
    })
    ensureCellVisible(cell)
  }, [ensureCellVisible])

  const copySelection = useCallback((includeHeaders = false) => {
    if (!bridge || !selectionRange || !rawDataDocument.has_data) {
      return
    }
    setPendingCopySequence(rawDataCopyResult.sequence + 1)
    bridge.copyRawDataRange({
      datasetId: rawDataDocument.dataset_id,
      version: rawDataDocument.version,
      rowStart: selectionRange.startRow,
      rowEnd: selectionRange.endRow + 1,
      colStart: selectionRange.startCol,
      colEnd: selectionRange.endCol + 1,
      includeHeaders,
    })
    setCopyFeedback(selectionLabel ? `正在复制 ${selectionLabel}` : '正在复制')
  }, [bridge, rawDataCopyResult.sequence, rawDataDocument.dataset_id, rawDataDocument.has_data, rawDataDocument.version, selectionLabel, selectionRange])

  const handleBodyScroll = useCallback(() => {
    const scroller = bodyScrollRef.current
    if (!scroller) {
      return
    }
    setScrollLeft(scroller.scrollLeft)
    setScrollTop(scroller.scrollTop)
  }, [])

  const handleBodyMouseDown = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    const cell = getCellFromClientPoint(event.clientX, event.clientY)
    if (!cell) {
      return
    }
    bodyScrollRef.current?.focus()
    setSelection((previous) => {
      if (event.shiftKey && previous) {
        return { anchor: previous.anchor, focus: cell }
      }
      return { anchor: cell, focus: cell }
    })
    setDragging(true)
    event.preventDefault()
  }, [getCellFromClientPoint])

  const handleBodyKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!rawDataDocument.has_data || rowCount <= 0 || columnCount <= 0) {
      return
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'c') {
      event.preventDefault()
      copySelection(false)
      return
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
      event.preventDefault()
      setSelection({
        anchor: { row: 0, col: 0 },
        focus: { row: rowCount - 1, col: columnCount - 1 },
      })
      return
    }
    const focusCell = selection?.focus ?? { row: 0, col: 0 }
    let nextCell: GridCellPosition | null = null
    if (event.key === 'ArrowUp') {
      nextCell = { row: clamp(focusCell.row - 1, 0, rowCount - 1), col: focusCell.col }
    } else if (event.key === 'ArrowDown') {
      nextCell = { row: clamp(focusCell.row + 1, 0, rowCount - 1), col: focusCell.col }
    } else if (event.key === 'ArrowLeft') {
      nextCell = { row: focusCell.row, col: clamp(focusCell.col - 1, 0, columnCount - 1) }
    } else if (event.key === 'ArrowRight') {
      nextCell = { row: focusCell.row, col: clamp(focusCell.col + 1, 0, columnCount - 1) }
    } else if (event.key === 'Home') {
      nextCell = { row: focusCell.row, col: 0 }
    } else if (event.key === 'End') {
      nextCell = { row: focusCell.row, col: columnCount - 1 }
    }
    if (!nextCell) {
      return
    }
    event.preventDefault()
    updateSelectionToCell(nextCell, event.shiftKey)
  }, [columnCount, copySelection, rawDataDocument.has_data, rowCount, selection, updateSelectionToCell])

  const renderRowStart = requestedRange ? requestedRange.rowStart : 0
  const renderRowEnd = requestedRange ? requestedRange.rowEnd : 0
  const renderColStart = requestedRange ? requestedRange.colStart : 0
  const renderColEnd = requestedRange ? requestedRange.colEnd : 0

  const bodyCells = useMemo(() => {
    const items = []
    for (let rowIndex = renderRowStart; rowIndex < renderRowEnd; rowIndex += 1) {
      for (let colIndex = renderColStart; colIndex < renderColEnd; colIndex += 1) {
        const isSelected = Boolean(
          selectionRange
          && rowIndex >= selectionRange.startRow
          && rowIndex <= selectionRange.endRow
          && colIndex >= selectionRange.startCol
          && colIndex <= selectionRange.endCol,
        )
        items.push(
          <div
            key={`${rowIndex}:${colIndex}`}
            className={isSelected ? 'raw-data-grid__cell raw-data-grid__cell--selected' : 'raw-data-grid__cell'}
            style={{
              left: `${columnBoundaries[colIndex] || 0}px`,
              top: `${rowIndex * rowHeight}px`,
              width: `${columnWidths[colIndex] || MIN_COLUMN_WIDTH_PX}px`,
              height: `${rowHeight}px`,
            }}
          >
            {getCellValue(rowIndex, colIndex) || '…'}
          </div>,
        )
      }
    }
    return items
  }, [columnBoundaries, columnWidths, getCellValue, renderColEnd, renderColStart, renderRowEnd, renderRowStart, rowHeight, selectionRange])

  const columnHeaderCells = useMemo(() => {
    const items = []
    for (let colIndex = visibleColStart; colIndex < visibleColEnd; colIndex += 1) {
      const isSelected = Boolean(selectionRange && colIndex >= selectionRange.startCol && colIndex <= selectionRange.endCol)
      items.push(
        <div
          key={columns[colIndex]?.key || `column-${colIndex}`}
          className={isSelected ? 'raw-data-grid__header-cell raw-data-grid__header-cell--selected' : 'raw-data-grid__header-cell'}
          style={{
            left: `${(columnBoundaries[colIndex] || 0) - scrollLeft}px`,
            width: `${columnWidths[colIndex] || MIN_COLUMN_WIDTH_PX}px`,
            height: `${columnHeaderHeight}px`,
          }}
        >
          {columns[colIndex]?.label || ''}
        </div>,
      )
    }
    return items
  }, [columnBoundaries, columnHeaderHeight, columnWidths, columns, scrollLeft, selectionRange, visibleColEnd, visibleColStart])

  const rowHeaderCells = useMemo(() => {
    const items = []
    for (let rowIndex = visibleRowStart; rowIndex < visibleRowEnd; rowIndex += 1) {
      const isSelected = Boolean(selectionRange && rowIndex >= selectionRange.startRow && rowIndex <= selectionRange.endRow)
      items.push(
        <div
          key={`row-${rowIndex}`}
          className={isSelected ? 'raw-data-grid__row-header-cell raw-data-grid__row-header-cell--selected' : 'raw-data-grid__row-header-cell'}
          style={{
            top: `${rowIndex * rowHeight - scrollTop}px`,
            width: `${rowHeaderWidth}px`,
            height: `${rowHeight}px`,
          }}
        >
          {rowIndex + 1}
        </div>,
      )
    }
    return items
  }, [rowHeaderWidth, rowHeight, scrollTop, selectionRange, visibleRowEnd, visibleRowStart])

  const selectionOverlay = selectionRange ? (
    <div
      className="raw-data-grid__selection"
      style={{
        left: `${columnBoundaries[selectionRange.startCol] || 0}px`,
        top: `${selectionRange.startRow * rowHeight}px`,
        width: `${(columnBoundaries[selectionRange.endCol + 1] || 0) - (columnBoundaries[selectionRange.startCol] || 0)}px`,
        height: `${(selectionRange.endRow - selectionRange.startRow + 1) * rowHeight}px`,
      }}
    />
  ) : null

  return (
    <div className="tab-surface">
      <div className="raw-data-grid-shell">
        <div className="raw-data-grid__statusbar">
          <span>{rawDataDocument.has_data ? `共 ${rowCount} 行 · ${columnCount} 列` : '当前没有可展示的原始数据。'}</span>
          <span>{copyFeedback || (rawDataDocument.has_data ? 'Ctrl/Cmd + C 复制选区，Ctrl/Cmd + A 全选。' : '')}</span>
        </div>
        {rawDataDocument.has_data ? (
          <div className="raw-data-grid__viewport-shell" style={{ gridTemplateColumns: `${rowHeaderWidth}px minmax(0, 1fr)`, gridTemplateRows: `${columnHeaderHeight}px minmax(0, 1fr)` }}>
            <div className="raw-data-grid__corner">#</div>
            <div className="raw-data-grid__column-headers">{columnHeaderCells}</div>
            <div className="raw-data-grid__row-headers">{rowHeaderCells}</div>
            <div
              ref={bodyScrollRef}
              className="raw-data-grid__body-scroll"
              onKeyDown={handleBodyKeyDown}
              onScroll={handleBodyScroll}
              tabIndex={0}
            >
              <div className="raw-data-grid__body-content" onMouseDown={handleBodyMouseDown} style={{ width: `${Math.max(totalWidth, bodySize.width)}px`, height: `${Math.max(totalHeight, bodySize.height)}px` }}>
                {bodyCells}
                {selectionOverlay}
              </div>
            </div>
          </div>
        ) : (
          <div className="muted-text">当前没有可展示的原始数据。</div>
        )}
      </div>
    </div>
  )
})
