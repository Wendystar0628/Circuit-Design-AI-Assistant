import type { ELK as ElkApi, ElkEdgeSection, ElkExtendedEdge, ElkNode, ElkPort } from 'elkjs/lib/elk-api'

import type { SchematicComponentState, SchematicDocumentState, SchematicNetState, SchematicPinState } from '../../types/state'
import { getSchematicSymbolDefinition, type SchematicPinSide } from './symbolRegistry'
import { normalizeSchematicDocument } from './schematicDocumentNormalizer'
import type {
  SchematicSemanticModel,
  SemanticComponent,
  SemanticScopeGroup,
} from './schematicSemanticModel'
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

interface Padding {
  top: number
  right: number
  bottom: number
  left: number
}

interface LabelPosition {
  slot: string
  text: string
}

interface ComponentBlueprint {
  component: SchematicComponentState
  orientation: SchematicLayoutOrientation
  nodeId: string
  width: number
  height: number
  symbolX: number
  symbolY: number
  symbolWidth: number
  symbolHeight: number
  pins: Array<{
    portId: string
    pin: SchematicPinState
    side: SchematicPinSide
    x: number
    y: number
  }>
}

interface PositionedComponentBox extends ComponentBlueprint {
  x: number
  y: number
}

interface EdgeBlueprint {
  edgeId: string
  net: SchematicNetState
  sourcePortId: string
  targetPortId: string
}

interface GroupBlueprint {
  id: string
  label: string
  depth: number
}

let elkInstancePromise: Promise<ElkApi> | null = null

async function getElkInstance(): Promise<ElkApi> {
  if (elkInstancePromise === null) {
    elkInstancePromise = import('elkjs/lib/elk.bundled.js').then((module) => new module.default())
  }
  return elkInstancePromise
}

const ROOT_PADDING: Padding = {
  top: 64,
  right: 64,
  bottom: 64,
  left: 64,
}

const GROUP_PADDING: Padding = {
  top: 44,
  right: 24,
  bottom: 24,
  left: 24,
}

const NODE_PADDING: Padding = {
  top: 28,
  right: 24,
  bottom: 30,
  left: 24,
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

function toPaddingValue(padding: Padding): string {
  return `[top=${padding.top},left=${padding.left},bottom=${padding.bottom},right=${padding.right}]`
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

function makeLabelPosition(label: LabelPosition | null, componentBox: PositionedComponentBox): SchematicLayoutLabel | null {
  if (label === null) {
    return null
  }
  const left = componentBox.x
  const top = componentBox.y
  const symbolLeft = left + componentBox.symbolX
  const symbolTop = top + componentBox.symbolY
  const symbolRight = symbolLeft + componentBox.symbolWidth
  const symbolBottom = symbolTop + componentBox.symbolHeight
  if (label.slot === 'bottom') {
    return {
      text: label.text,
      x: symbolLeft + componentBox.symbolWidth / 2,
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
    x: symbolLeft + componentBox.symbolWidth / 2,
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

function extractSectionPoints(section: ElkEdgeSection): SchematicLayoutPoint[] {
  return [
    section.startPoint,
    ...(section.bendPoints ?? []),
    section.endPoint,
  ].map((item) => ({ x: item.x, y: item.y }))
}

function findElkPort(node: ElkNode, portId: string): ElkPort | null {
  return node.ports?.find((item) => item.id === portId) ?? null
}

function buildGraph(semantic: SchematicSemanticModel) {
  const componentBlueprints = new Map<string, ComponentBlueprint>()
  const groupBlueprints = new Map<string, GroupBlueprint>()
  const edgeBlueprints = new Map<string, EdgeBlueprint>()
  const portOwnerMap = new Map<string, string>()

  const priorityOrder = new Map(semantic.components.map((item, index) => [item.component.id, index]))

  function orderScopedComponentIds(componentIds: string[]): string[] {
    return [...componentIds].sort((left, right) => {
      const leftRank = priorityOrder.get(left) ?? Number.MAX_SAFE_INTEGER
      const rightRank = priorityOrder.get(right) ?? Number.MAX_SAFE_INTEGER
      return leftRank - rightRank
    })
  }

  function requireScopeGroup(scopeGroupId: string): SemanticScopeGroup {
    const group = semantic.scopeGroupsById.get(scopeGroupId)
    if (!group) {
      throw new Error(`[schematicLayout] Semantic scope group missing: ${scopeGroupId}`)
    }
    return group
  }

  function requireSemanticComponent(componentId: string): SemanticComponent {
    const semanticComponent = semantic.componentsById.get(componentId)
    if (!semanticComponent) {
      throw new Error(`[schematicLayout] Semantic component missing: ${componentId}`)
    }
    return semanticComponent
  }

  function buildComponentNode(semanticComponent: SemanticComponent): ElkNode {
    const component = semanticComponent.component
    const definition = getSchematicSymbolDefinition(component.symbol_kind)
    const width = definition.width + NODE_PADDING.left + NODE_PADDING.right
    const height = definition.height + NODE_PADDING.top + NODE_PADDING.bottom
    const pins = semanticComponent.pins.map((semanticPin) => {
      const anchor = definition.getPinAnchor(component, semanticPin.pin, semanticPin.index)
      const portId = buildPortId(component.id, semanticPin.pin.name)
      portOwnerMap.set(portId, component.id)
      return {
        portId,
        pin: semanticPin.pin,
        side: anchor.side,
        x: NODE_PADDING.left + anchor.x,
        y: NODE_PADDING.top + anchor.y,
      }
    })
    componentBlueprints.set(component.id, {
      component,
      orientation: resolveComponentOrientation(semanticComponent),
      nodeId: component.id,
      width,
      height,
      symbolX: NODE_PADDING.left,
      symbolY: NODE_PADDING.top,
      symbolWidth: definition.width,
      symbolHeight: definition.height,
      pins,
    })
    return {
      id: component.id,
      width,
      height,
      layoutOptions: {
        'elk.portConstraints': 'FIXED_POS',
      },
      ports: pins.map((pin) => ({
        id: pin.portId,
        width: 8,
        height: 8,
        x: pin.x - 4,
        y: pin.y - 4,
      })),
    }
  }

  function buildScopeGroupNode(scopeGroup: SemanticScopeGroup): ElkNode {
    const childNodes: ElkNode[] = []
    for (const childGroupId of scopeGroup.childGroupIds) {
      childNodes.push(buildScopeGroupNode(requireScopeGroup(childGroupId)))
    }
    for (const componentId of orderScopedComponentIds(scopeGroup.componentIds)) {
      childNodes.push(buildComponentNode(requireSemanticComponent(componentId)))
    }
    groupBlueprints.set(scopeGroup.id, { id: scopeGroup.id, label: scopeGroup.label, depth: scopeGroup.depth })
    return {
      id: scopeGroup.id,
      children: childNodes,
      layoutOptions: {
        'elk.padding': toPaddingValue(GROUP_PADDING),
      },
    }
  }

  const rootScopeGroup = requireScopeGroup(semantic.rootScopeGroupId)
  const rootChildren: ElkNode[] = []
  for (const childGroupId of rootScopeGroup.childGroupIds) {
    rootChildren.push(buildScopeGroupNode(requireScopeGroup(childGroupId)))
  }
  for (const componentId of orderScopedComponentIds(rootScopeGroup.componentIds)) {
    rootChildren.push(buildComponentNode(requireSemanticComponent(componentId)))
  }

  const graph: ElkNode = {
    id: 'schematic-root',
    children: rootChildren,
    edges: [],
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      'elk.padding': toPaddingValue(ROOT_PADDING),
      'elk.spacing.nodeNode': '42',
      'elk.layered.spacing.nodeNodeBetweenLayers': '84',
      'elk.layered.spacing.edgeNodeBetweenLayers': '24',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    },
  }

  for (const semanticNet of semantic.nets) {
    if (semanticNet.pinCount < 2) {
      continue
    }
    const connections = semanticNet.net.connections.filter((connection) => portOwnerMap.has(buildPortId(connection.component_id, connection.pin_name)))
    if (connections.length < 2) {
      continue
    }
    const [firstConnection, ...otherConnections] = connections
    const sourcePortId = buildPortId(firstConnection.component_id, firstConnection.pin_name)
    otherConnections.forEach((connection, index) => {
      const targetPortId = buildPortId(connection.component_id, connection.pin_name)
      const edgeId = `${semanticNet.net.id}::${sourcePortId}::${targetPortId}::${index}`
      edgeBlueprints.set(edgeId, {
        edgeId,
        net: semanticNet.net,
        sourcePortId,
        targetPortId,
      })
      graph.edges?.push({
        id: edgeId,
        sources: [sourcePortId],
        targets: [targetPortId],
      })
    })
  }

  return {
    graph,
    componentBlueprints,
    groupBlueprints,
    edgeBlueprints,
  }
}

function collectComponentLayouts(node: ElkNode, parentX: number, parentY: number, componentBlueprints: Map<string, ComponentBlueprint>, groupBlueprints: Map<string, GroupBlueprint>, components: SchematicLayoutComponent[], groups: SchematicLayoutGroup[], portMap: Map<string, SchematicLayoutPin>) {
  const currentX = parentX + (node.x ?? 0)
  const currentY = parentY + (node.y ?? 0)
  const componentBlueprint = componentBlueprints.get(node.id)
  if (componentBlueprint) {
    const pins = componentBlueprint.pins.map((item) => {
      const port = findElkPort(node, item.portId)
      const pin: SchematicLayoutPin = {
        id: item.portId,
        componentId: componentBlueprint.component.id,
        pin: item.pin,
        side: item.side,
        x: currentX + ((port?.x ?? item.x - 4) + 4),
        y: currentY + ((port?.y ?? item.y - 4) + 4),
      }
      portMap.set(item.portId, pin)
      return pin
    })
    const componentBox: ComponentBlueprint = {
      ...componentBlueprint,
      pins: componentBlueprint.pins,
    }
    const layoutComponent: SchematicLayoutComponent = {
      component: componentBlueprint.component,
      orientation: componentBlueprint.orientation,
      bounds: {
        x: currentX,
        y: currentY,
        width: componentBlueprint.width,
        height: componentBlueprint.height,
      },
      symbolBounds: {
        x: currentX + componentBlueprint.symbolX,
        y: currentY + componentBlueprint.symbolY,
        width: componentBlueprint.symbolWidth,
        height: componentBlueprint.symbolHeight,
      },
      pins,
      nameLabel: null,
      valueLabel: null,
    }
    const labelComponentBox = {
      ...componentBox,
      x: currentX,
      y: currentY,
    }
    layoutComponent.nameLabel = makeLabelPosition(resolveLabel(componentBlueprint.component, 'name'), labelComponentBox)
    layoutComponent.valueLabel = makeLabelPosition(resolveLabel(componentBlueprint.component, 'value'), labelComponentBox)
    components.push(layoutComponent)
  } else {
    const groupBlueprint = groupBlueprints.get(node.id)
    if (groupBlueprint) {
      groups.push({
        id: groupBlueprint.id,
        label: groupBlueprint.label,
        depth: groupBlueprint.depth,
        bounds: {
          x: currentX,
          y: currentY,
          width: node.width ?? 0,
          height: node.height ?? 0,
        },
      })
    }
    for (const child of node.children ?? []) {
      collectComponentLayouts(child, currentX, currentY, componentBlueprints, groupBlueprints, components, groups, portMap)
    }
  }
}

function buildNetLayouts(semantic: SchematicSemanticModel, edges: ElkExtendedEdge[] | undefined, edgeBlueprints: Map<string, EdgeBlueprint>, portMap: Map<string, SchematicLayoutPin>, components: SchematicLayoutComponent[]): SchematicLayoutNet[] {
  const netsById = new Map<string, SchematicLayoutNet>()
  for (const semanticNet of semantic.nets) {
    netsById.set(semanticNet.net.id, {
      net: semanticNet.net,
      segments: [],
      label: null,
    })
  }

  for (const edge of edges ?? []) {
    const blueprint = edgeBlueprints.get(edge.id || '')
    if (!blueprint) {
      continue
    }
    const targetNet = netsById.get(blueprint.net.id)
    if (!targetNet) {
      continue
    }
    const sections = edge.sections ?? []
    if (sections.length > 0) {
      sections.forEach((section, index) => {
        const points = extractSectionPoints(section)
        targetNet.segments.push({
          key: `${edge.id}:${section.id || index}`,
          kind: 'route',
          axis: resolveSegmentAxis(points),
          points,
        })
      })
      continue
    }
    const sourcePin = portMap.get(blueprint.sourcePortId)
    const targetPin = portMap.get(blueprint.targetPortId)
    if (!sourcePin || !targetPin) {
      continue
    }
    const fallbackPoints = buildOrthogonalFallback({ x: sourcePin.x, y: sourcePin.y }, { x: targetPin.x, y: targetPin.y })
    targetNet.segments.push({
      key: `${edge.id}:fallback`,
      kind: 'fallback',
      axis: resolveSegmentAxis(fallbackPoints),
      points: fallbackPoints,
    })
  }

  for (const targetNet of netsById.values()) {
    const semanticNet = semantic.netsById.get(targetNet.net.id)
    if (semanticNet && semanticNet.pinCount === 1) {
      const onlyConnection = targetNet.net.connections[0]
      const pin = portMap.get(buildPortId(onlyConnection.component_id, onlyConnection.pin_name))
      if (pin) {
        const stubPoints = buildStubSegment(pin)
        targetNet.segments.push({
          key: `${targetNet.net.id}:stub`,
          kind: 'stub',
          axis: resolveSegmentAxis(stubPoints),
          points: stubPoints,
        })
      }
    }
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
  const { graph, componentBlueprints, groupBlueprints, edgeBlueprints } = buildGraph(semantic)
  const elk = await getElkInstance()
  const laidOutGraph = await elk.layout(graph)
  const components: SchematicLayoutComponent[] = []
  const groups: SchematicLayoutGroup[] = []
  const portMap = new Map<string, SchematicLayoutPin>()

  for (const child of laidOutGraph.children ?? []) {
    collectComponentLayouts(child, laidOutGraph.x ?? 0, laidOutGraph.y ?? 0, componentBlueprints, groupBlueprints, components, groups, portMap)
  }

  const nets = buildNetLayouts(semantic, laidOutGraph.edges, edgeBlueprints, portMap, components)
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
