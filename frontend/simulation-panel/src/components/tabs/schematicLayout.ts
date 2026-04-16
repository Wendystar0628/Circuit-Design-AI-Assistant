import type { SchematicComponentState, SchematicDocumentState, SchematicPinState } from '../../types/state'
import { getSchematicSymbolDefinition, type SchematicPinSide } from './symbolRegistry'
import { normalizeSchematicDocument } from './schematicDocumentNormalizer'
import type {
  SchematicSemanticModel,
  SemanticComponent,
} from './schematicSemanticModel'
import { analyzeSchematicSkeleton } from './schematicSkeletonAnalyzer'
import type { SchematicSkeleton } from './schematicSkeletonModel'
import { computeSchematicCoarsePlacement } from './schematicCoarsePlacement'
import type { SchematicCoarsePlacement } from './schematicCoarsePlacement'
import type {
  SchematicCanvasViewState,
  SchematicLayoutBounds,
  SchematicLayoutComponent,
  SchematicLayoutGroup,
  SchematicLayoutLabel,
  SchematicLayoutNet,
  SchematicLayoutNetSegment,
  SchematicLayoutOrientation,
  SchematicLayoutPin,
  SchematicLayoutPoint,
  SchematicLayoutRect,
  SchematicLayoutResult,
  SchematicLayoutSegmentAxis,
} from './schematicLayoutTypes'

export type {
  SchematicCanvasViewState,
  SchematicLayoutBounds,
  SchematicLayoutComponent,
  SchematicLayoutGroup,
  SchematicLayoutLabel,
  SchematicLayoutNet,
  SchematicLayoutNetSegment,
  SchematicLayoutOrientation,
  SchematicLayoutPin,
  SchematicLayoutPoint,
  SchematicLayoutRect,
  SchematicLayoutResult,
} from './schematicLayoutTypes'

type LayoutRect = SchematicLayoutRect

interface LabelPosition {
  slot: string
  text: string
}

interface ResolvedPinAnchor {
  portId: string
  pin: SchematicPinState
  side: SchematicPinSide
  anchorX: number
  anchorY: number
}

const FIT_PADDING = 56
const MIN_SCALE = 0.35
const MAX_SCALE = 2.6
const NET_STUB_LENGTH = 28
const INSTANCE_LABEL_FONT_SIZE = 16.5
const SECONDARY_LABEL_FONT_SIZE = 15
const COMPONENT_LABEL_MIN_WIDTH = 36
const COMPONENT_LABEL_HORIZONTAL_PADDING = 8
const COMPONENT_LABEL_HEIGHT = 24
const NET_LABEL_MIN_WIDTH = 54
const NET_LABEL_HORIZONTAL_PADDING = 18
export const SCHEMATIC_NET_LABEL_HEIGHT = 26
const NET_LABEL_WIRE_CLEARANCE = 4
const NET_LABEL_COMPONENT_CLEARANCE = 8

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function estimateTextWidth(text: string, fontSize: number, minWidth: number, horizontalPadding: number): number {
  return Math.max(minWidth, Math.ceil(text.length * fontSize * 0.62 + horizontalPadding))
}

export function getSchematicNetLabelWidth(text: string): number {
  return estimateTextWidth(text, SECONDARY_LABEL_FONT_SIZE, NET_LABEL_MIN_WIDTH, NET_LABEL_HORIZONTAL_PADDING)
}

function includePoint(bounds: SchematicLayoutBounds | null, point: SchematicLayoutPoint): SchematicLayoutBounds {
  if (bounds === null) {
    return {
      minX: point.x,
      minY: point.y,
      maxX: point.x,
      maxY: point.y,
    }
  }
  return {
    minX: Math.min(bounds.minX, point.x),
    minY: Math.min(bounds.minY, point.y),
    maxX: Math.max(bounds.maxX, point.x),
    maxY: Math.max(bounds.maxY, point.y),
  }
}

function includeRect(bounds: SchematicLayoutBounds | null, x: number, y: number, width: number, height: number): SchematicLayoutBounds {
  let nextBounds = includePoint(bounds, { x, y })
  nextBounds = includePoint(nextBounds, { x: x + width, y: y + height })
  return nextBounds
}

function getBoundsWidth(bounds: SchematicLayoutBounds): number {
  return Math.max(1, bounds.maxX - bounds.minX)
}

function getBoundsHeight(bounds: SchematicLayoutBounds): number {
  return Math.max(1, bounds.maxY - bounds.minY)
}

function buildPortId(componentId: string, pinName: string): string {
  return `port:${componentId}:${pinName}`
}

function buildRequestKey(documentId: string, revision: string): string {
  return `${documentId}::${revision}`
}

function resolveLabelSlot(rawSlot: string, fallback: string): string {
  const normalized = rawSlot.trim().toLowerCase()
  if (normalized === 'top' || normalized === 'bottom' || normalized === 'left' || normalized === 'right' || normalized === 'top-left' || normalized === 'bottom-right') {
    return normalized
  }
  return fallback
}

function resolveComponentOrientation(semanticComponent: SemanticComponent): SchematicLayoutOrientation {
  return semanticComponent.orientationPreference === 'vertical' ? 'down' : 'right'
}

function resolveLabel(component: SchematicComponentState, kind: 'name' | 'value'): LabelPosition | null {
  if (kind === 'name') {
    const text = component.instance_name || component.display_name || component.id
    if (!text) {
      return null
    }
    return {
      slot: resolveLabelSlot(component.label_slots.name || 'top', 'top'),
      text,
    }
  }
  const text = component.display_value
  if (!text) {
    return null
  }
  return {
    slot: resolveLabelSlot(component.label_slots.value || 'bottom', 'bottom'),
    text,
  }
}

function makeLabelPosition(label: LabelPosition | null, symbolBounds: SchematicLayoutRect): SchematicLayoutLabel | null {
  if (label === null) {
    return null
  }
  const symbolLeft = symbolBounds.x
  const symbolTop = symbolBounds.y
  const symbolRight = symbolLeft + symbolBounds.width
  const symbolBottom = symbolTop + symbolBounds.height
  const symbolCenterX = symbolLeft + symbolBounds.width / 2
  if (label.slot === 'bottom') {
    return {
      text: label.text,
      x: symbolCenterX,
      y: symbolBottom + 14,
      textAnchor: 'middle',
    }
  }
  if (label.slot === 'left') {
    return {
      text: label.text,
      x: symbolLeft - 6,
      y: symbolTop + 16,
      textAnchor: 'end',
    }
  }
  if (label.slot === 'right') {
    return {
      text: label.text,
      x: symbolRight + 6,
      y: symbolBottom - 6,
      textAnchor: 'start',
    }
  }
  if (label.slot === 'top-left') {
    return {
      text: label.text,
      x: symbolLeft,
      y: symbolTop - 6,
      textAnchor: 'start',
    }
  }
  if (label.slot === 'bottom-right') {
    return {
      text: label.text,
      x: symbolRight,
      y: symbolBottom + 14,
      textAnchor: 'end',
    }
  }
  return {
    text: label.text,
    x: symbolCenterX,
    y: symbolTop - 6,
    textAnchor: 'middle',
  }
}

function buildOrthogonalFallback(startPoint: SchematicLayoutPoint, endPoint: SchematicLayoutPoint): SchematicLayoutPoint[] {
  if (Math.abs(startPoint.x - endPoint.x) >= Math.abs(startPoint.y - endPoint.y)) {
    const middleX = (startPoint.x + endPoint.x) / 2
    return [
      startPoint,
      { x: middleX, y: startPoint.y },
      { x: middleX, y: endPoint.y },
      endPoint,
    ]
  }
  const middleY = (startPoint.y + endPoint.y) / 2
  return [
    startPoint,
    { x: startPoint.x, y: middleY },
    { x: endPoint.x, y: middleY },
    endPoint,
  ]
}

function resolveSegmentAxis(points: SchematicLayoutPoint[]): SchematicLayoutSegmentAxis {
  if (points.length < 2) {
    return 'mixed'
  }
  const hasHorizontalDelta = points.some((point, index) => index > 0 && point.x !== points[index - 1].x)
  const hasVerticalDelta = points.some((point, index) => index > 0 && point.y !== points[index - 1].y)
  if (hasHorizontalDelta && hasVerticalDelta) {
    return 'mixed'
  }
  if (hasHorizontalDelta) {
    return 'horizontal'
  }
  if (hasVerticalDelta) {
    return 'vertical'
  }
  return 'mixed'
}

function buildStubSegment(pin: SchematicLayoutPin): SchematicLayoutPoint[] {
  if (pin.side === 'left') {
    return [
      { x: pin.x - NET_STUB_LENGTH, y: pin.y },
      { x: pin.x, y: pin.y },
    ]
  }
  if (pin.side === 'right') {
    return [
      { x: pin.x, y: pin.y },
      { x: pin.x + NET_STUB_LENGTH, y: pin.y },
    ]
  }
  if (pin.side === 'top') {
    return [
      { x: pin.x, y: pin.y - NET_STUB_LENGTH },
      { x: pin.x, y: pin.y },
    ]
  }
  return [
    { x: pin.x, y: pin.y },
    { x: pin.x, y: pin.y + NET_STUB_LENGTH },
  ]
}

function buildTextLabelRect(label: SchematicLayoutLabel, width: number, height: number, verticalMode: 'baseline' | 'middle'): LayoutRect {
  const x = label.textAnchor === 'middle'
    ? label.x - width / 2
    : label.textAnchor === 'end'
      ? label.x - width
      : label.x
  const y = verticalMode === 'middle'
    ? label.y - height / 2
    : label.y - height * 0.78
  return {
    x,
    y,
    width,
    height,
  }
}

function rectsOverlap(left: LayoutRect, right: LayoutRect): boolean {
  return left.x < right.x + right.width
    && left.x + left.width > right.x
    && left.y < right.y + right.height
    && left.y + left.height > right.y
}

function buildComponentObstacleRect(component: SchematicLayoutComponent): LayoutRect {
  return {
    x: component.symbolBounds.x - NET_LABEL_COMPONENT_CLEARANCE,
    y: component.symbolBounds.y - NET_LABEL_COMPONENT_CLEARANCE,
    width: component.symbolBounds.width + NET_LABEL_COMPONENT_CLEARANCE * 2,
    height: component.symbolBounds.height + NET_LABEL_COMPONENT_CLEARANCE * 2,
  }
}

function buildSegmentObstacleRect(startPoint: SchematicLayoutPoint, endPoint: SchematicLayoutPoint, padding: number): LayoutRect {
  const minX = Math.min(startPoint.x, endPoint.x) - padding
  const minY = Math.min(startPoint.y, endPoint.y) - padding
  return {
    x: minX,
    y: minY,
    width: Math.abs(startPoint.x - endPoint.x) + padding * 2,
    height: Math.abs(startPoint.y - endPoint.y) + padding * 2,
  }
}

function doesRectOverlapComponents(rect: LayoutRect, components: SchematicLayoutComponent[]): boolean {
  return components.some((component) => rectsOverlap(rect, buildComponentObstacleRect(component)))
}

function doesRectOverlapSegments(rect: LayoutRect, segments: SchematicLayoutNetSegment[]): boolean {
  return segments.some((segment) => segment.points.some((point, index) => {
    if (index === 0) {
      return false
    }
    return rectsOverlap(rect, buildSegmentObstacleRect(segment.points[index - 1], point, 4))
  }))
}

function collectNetLabelCandidates(segments: SchematicLayoutNetSegment[]): Array<{ x: number; y: number; horizontal: boolean; length: number }> {
  const candidates: Array<{ x: number; y: number; horizontal: boolean; length: number }> = []
  for (const segment of segments) {
    for (let index = 1; index < segment.points.length; index += 1) {
      const startPoint = segment.points[index - 1]
      const endPoint = segment.points[index]
      const dx = endPoint.x - startPoint.x
      const dy = endPoint.y - startPoint.y
      const length = Math.hypot(dx, dy)
      if (length < 18) {
        continue
      }
      candidates.push({
        x: (startPoint.x + endPoint.x) / 2,
        y: (startPoint.y + endPoint.y) / 2,
        horizontal: Math.abs(dx) >= Math.abs(dy),
        length,
      })
    }
  }
  return candidates.sort((left, right) => right.length - left.length)
}

function resolveNetLabelPosition(netName: string, segments: SchematicLayoutNetSegment[], components: SchematicLayoutComponent[]): SchematicLayoutLabel | null {
  if (!netName) {
    return null
  }
  const labelWidth = getSchematicNetLabelWidth(netName)
  const candidates = collectNetLabelCandidates(segments)
  for (const candidate of candidates) {
    const labelOptions: SchematicLayoutLabel[] = candidate.horizontal
      ? [
          {
            text: netName,
            x: candidate.x,
            y: candidate.y - (SCHEMATIC_NET_LABEL_HEIGHT / 2 + NET_LABEL_WIRE_CLEARANCE),
            textAnchor: 'middle',
          },
          {
            text: netName,
            x: candidate.x,
            y: candidate.y + (SCHEMATIC_NET_LABEL_HEIGHT / 2 + NET_LABEL_WIRE_CLEARANCE),
            textAnchor: 'middle',
          },
        ]
      : [
          {
            text: netName,
            x: candidate.x + labelWidth / 2 + NET_LABEL_WIRE_CLEARANCE,
            y: candidate.y,
            textAnchor: 'middle',
          },
          {
            text: netName,
            x: candidate.x - labelWidth / 2 - NET_LABEL_WIRE_CLEARANCE,
            y: candidate.y,
            textAnchor: 'middle',
          },
        ]
    for (const option of labelOptions) {
      const rect = buildTextLabelRect(option, labelWidth, SCHEMATIC_NET_LABEL_HEIGHT, 'middle')
      if (doesRectOverlapComponents(rect, components)) {
        continue
      }
      if (doesRectOverlapSegments(rect, segments)) {
        continue
      }
      return option
    }
  }
  const fallback = candidates[0]
  if (!fallback) {
    return null
  }
  return fallback.horizontal
    ? {
        text: netName,
        x: fallback.x,
        y: fallback.y - (SCHEMATIC_NET_LABEL_HEIGHT / 2 + NET_LABEL_WIRE_CLEARANCE),
        textAnchor: 'middle',
      }
    : {
        text: netName,
        x: fallback.x + labelWidth / 2 + NET_LABEL_WIRE_CLEARANCE,
        y: fallback.y,
        textAnchor: 'middle',
      }
}

function resolvePinAnchors(semanticComponent: SemanticComponent): ResolvedPinAnchor[] {
  const component = semanticComponent.component
  const definition = getSchematicSymbolDefinition(component.symbol_kind)
  return semanticComponent.pins.map((semanticPin) => {
    const anchor = definition.getPinAnchor(component, semanticPin.pin, semanticPin.index)
    return {
      portId: buildPortId(component.id, semanticPin.pin.name),
      pin: semanticPin.pin,
      side: anchor.side,
      anchorX: anchor.x,
      anchorY: anchor.y,
    }
  })
}

function buildComponentLayouts(
  semantic: SchematicSemanticModel,
  placement: SchematicCoarsePlacement,
  portMap: Map<string, SchematicLayoutPin>,
): { components: SchematicLayoutComponent[]; groups: SchematicLayoutGroup[] } {
  const components: SchematicLayoutComponent[] = []
  for (const position of placement.componentPositions) {
    const semanticComponent = semantic.componentsById.get(position.componentId)
    if (!semanticComponent) {
      continue
    }
    const pinAnchors = resolvePinAnchors(semanticComponent)
    const pins: SchematicLayoutPin[] = pinAnchors.map((anchor) => {
      const pin: SchematicLayoutPin = {
        id: anchor.portId,
        componentId: position.componentId,
        pin: anchor.pin,
        side: anchor.side,
        x: position.symbolBox.x + anchor.anchorX,
        y: position.symbolBox.y + anchor.anchorY,
      }
      portMap.set(anchor.portId, pin)
      return pin
    })
    const orientation: SchematicLayoutOrientation = resolveComponentOrientation(semanticComponent)
    const layoutComponent: SchematicLayoutComponent = {
      component: semanticComponent.component,
      orientation,
      bounds: { ...position.box },
      symbolBounds: { ...position.symbolBox },
      pins,
      nameLabel: makeLabelPosition(resolveLabel(semanticComponent.component, 'name'), position.symbolBox),
      valueLabel: makeLabelPosition(resolveLabel(semanticComponent.component, 'value'), position.symbolBox),
    }
    components.push(layoutComponent)
  }
  const groups: SchematicLayoutGroup[] = placement.scopeGroupBounds.map((entry) => ({
    id: entry.scopeGroupId,
    label: entry.label,
    depth: entry.depth,
    bounds: { ...entry.bounds },
  }))
  return { components, groups }
}

function buildNetLayouts(
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  portMap: Map<string, SchematicLayoutPin>,
  components: SchematicLayoutComponent[],
): SchematicLayoutNet[] {
  const netsById = new Map<string, SchematicLayoutNet>()
  for (const semanticNet of semantic.nets) {
    netsById.set(semanticNet.net.id, {
      net: semanticNet.net,
      segments: [],
      label: null,
    })
  }

  for (const semanticNet of semantic.nets) {
    const skeletonNet = skeleton.netsById.get(semanticNet.net.id)
    const targetNet = netsById.get(semanticNet.net.id)
    if (!targetNet || !skeletonNet) {
      continue
    }
    if (skeletonNet.role === 'dangling') {
      if (semanticNet.net.connections.length === 1) {
        const onlyConnection = semanticNet.net.connections[0]
        const pin = portMap.get(buildPortId(onlyConnection.component_id, onlyConnection.pin_name))
        if (pin) {
          const stubPoints = buildStubSegment(pin)
          targetNet.segments.push({
            key: `${semanticNet.net.id}:stub`,
            kind: 'stub',
            axis: resolveSegmentAxis(stubPoints),
            points: stubPoints,
          })
        }
      }
      continue
    }
    const connections = semanticNet.net.connections.filter((connection) =>
      portMap.has(buildPortId(connection.component_id, connection.pin_name)),
    )
    if (connections.length < 2) {
      continue
    }
    const [firstConnection, ...otherConnections] = connections
    const sourcePortId = buildPortId(firstConnection.component_id, firstConnection.pin_name)
    const sourcePin = portMap.get(sourcePortId)
    if (!sourcePin) {
      continue
    }
    otherConnections.forEach((connection, index) => {
      const targetPortId = buildPortId(connection.component_id, connection.pin_name)
      const targetPin = portMap.get(targetPortId)
      if (!targetPin) {
        return
      }
      const points = buildOrthogonalFallback({ x: sourcePin.x, y: sourcePin.y }, { x: targetPin.x, y: targetPin.y })
      targetNet.segments.push({
        key: `${semanticNet.net.id}::${sourcePortId}::${targetPortId}::${index}`,
        kind: 'fallback',
        axis: resolveSegmentAxis(points),
        points,
      })
    })
  }

  for (const targetNet of netsById.values()) {
    targetNet.label = resolveNetLabelPosition(targetNet.net.name, targetNet.segments, components)
  }

  return [...netsById.values()].filter((item) => item.segments.length > 0)
}

function buildBounds(components: SchematicLayoutComponent[], groups: SchematicLayoutGroup[], nets: SchematicLayoutNet[]): SchematicLayoutBounds | null {
  let bounds: SchematicLayoutBounds | null = null
  for (const group of groups) {
    bounds = includeRect(bounds, group.bounds.x, group.bounds.y, group.bounds.width, group.bounds.height)
  }
  for (const component of components) {
    bounds = includeRect(bounds, component.bounds.x, component.bounds.y, component.bounds.width, component.bounds.height)
    if (component.nameLabel) {
      const nameBounds = buildTextLabelRect(
        component.nameLabel,
        estimateTextWidth(component.nameLabel.text, INSTANCE_LABEL_FONT_SIZE, COMPONENT_LABEL_MIN_WIDTH, COMPONENT_LABEL_HORIZONTAL_PADDING),
        COMPONENT_LABEL_HEIGHT,
        'baseline',
      )
      bounds = includeRect(bounds, nameBounds.x, nameBounds.y, nameBounds.width, nameBounds.height)
    }
    if (component.valueLabel) {
      const valueBounds = buildTextLabelRect(
        component.valueLabel,
        estimateTextWidth(component.valueLabel.text, SECONDARY_LABEL_FONT_SIZE, COMPONENT_LABEL_MIN_WIDTH, COMPONENT_LABEL_HORIZONTAL_PADDING),
        COMPONENT_LABEL_HEIGHT,
        'baseline',
      )
      bounds = includeRect(bounds, valueBounds.x, valueBounds.y, valueBounds.width, valueBounds.height)
    }
  }
  for (const net of nets) {
    for (const segment of net.segments) {
      for (const point of segment.points) {
        bounds = includePoint(bounds, point)
      }
    }
    if (net.label) {
      const labelBounds = buildTextLabelRect(net.label, getSchematicNetLabelWidth(net.label.text), SCHEMATIC_NET_LABEL_HEIGHT, 'middle')
      bounds = includeRect(bounds, labelBounds.x, labelBounds.y, labelBounds.width, labelBounds.height)
    }
  }
  return bounds
}

export function createEmptySchematicViewState(): SchematicCanvasViewState {
  return {
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  }
}

export function fitSchematicViewToBounds(bounds: SchematicLayoutBounds, width: number, height: number): SchematicCanvasViewState {
  const paddedWidth = Math.max(1, width - FIT_PADDING * 2)
  const paddedHeight = Math.max(1, height - FIT_PADDING * 2)
  const scale = clamp(Math.min(paddedWidth / getBoundsWidth(bounds), paddedHeight / getBoundsHeight(bounds)), MIN_SCALE, MAX_SCALE)
  const centerX = (bounds.minX + bounds.maxX) / 2
  const centerY = (bounds.minY + bounds.maxY) / 2
  return {
    scale,
    offsetX: width / 2 - centerX * scale,
    offsetY: height / 2 - centerY * scale,
  }
}

export function makeViewTargetWorldPoint(clientX: number, clientY: number, rect: DOMRect, viewState: SchematicCanvasViewState): SchematicLayoutPoint {
  return {
    x: (clientX - rect.left - viewState.offsetX) / viewState.scale,
    y: (clientY - rect.top - viewState.offsetY) / viewState.scale,
  }
}

export async function computeSchematicLayout(document: SchematicDocumentState): Promise<SchematicLayoutResult> {
  const requestKey = buildRequestKey(document.document_id, document.revision)
  if (!document.has_schematic || document.components.length === 0) {
    return {
      requestKey,
      documentId: document.document_id,
      revision: document.revision,
      components: [],
      nets: [],
      groups: [],
      bounds: null,
    }
  }

  const semantic = normalizeSchematicDocument(document)
  const skeleton = analyzeSchematicSkeleton(semantic)
  const placement = computeSchematicCoarsePlacement(semantic, skeleton)
  const portMap = new Map<string, SchematicLayoutPin>()
  const { components, groups } = buildComponentLayouts(semantic, placement, portMap)
  const nets = buildNetLayouts(semantic, skeleton, portMap, components)
  const bounds = buildBounds(components, groups, nets)

  return {
    requestKey,
    documentId: document.document_id,
    revision: document.revision,
    components,
    nets,
    groups,
    bounds,
  }
}
