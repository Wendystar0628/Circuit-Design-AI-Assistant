import type { ELK as ElkApi, ElkEdgeSection, ElkExtendedEdge, ElkNode, ElkPort } from 'elkjs/lib/elk-api'

import type { SchematicComponentState, SchematicDocumentState, SchematicNetState, SchematicPinState, SchematicSubcircuitState } from '../../types/state'
import { getSchematicSymbolDefinition, type SchematicPinSide } from './symbolRegistry'

export interface SchematicLayoutPoint {
  x: number
  y: number
}

export interface SchematicLayoutBounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export interface SchematicCanvasViewState {
  scale: number
  offsetX: number
  offsetY: number
}

export interface SchematicLayoutLabel {
  text: string
  x: number
  y: number
  textAnchor: 'start' | 'middle' | 'end'
}

export interface SchematicLayoutPin {
  id: string
  pin: SchematicPinState
  side: SchematicPinSide
  x: number
  y: number
}

export interface SchematicLayoutComponent {
  component: SchematicComponentState
  x: number
  y: number
  width: number
  height: number
  symbolX: number
  symbolY: number
  symbolWidth: number
  symbolHeight: number
  pins: SchematicLayoutPin[]
  nameLabel: SchematicLayoutLabel | null
  valueLabel: SchematicLayoutLabel | null
}

export interface SchematicLayoutNetSegment {
  key: string
  points: SchematicLayoutPoint[]
}

export interface SchematicLayoutNet {
  net: SchematicNetState
  segments: SchematicLayoutNetSegment[]
  label: SchematicLayoutLabel | null
}

export interface SchematicLayoutGroup {
  id: string
  label: string
  depth: number
  x: number
  y: number
  width: number
  height: number
}

export interface SchematicLayoutResult {
  requestKey: string
  documentId: string
  revision: string
  relayoutNonce: number
  components: SchematicLayoutComponent[]
  nets: SchematicLayoutNet[]
  groups: SchematicLayoutGroup[]
  bounds: SchematicLayoutBounds | null
}

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

interface ScopeGroupBuilder {
  path: string[]
  children: ScopeGroupBuilder[]
  components: SchematicComponentState[]
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

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
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

function buildScopePathKey(scopePath: string[]): string {
  return scopePath.join(' / ')
}

function buildGroupId(scopePath: string[]): string {
  return `scope:${buildScopePathKey(scopePath)}`
}

function buildPortId(componentId: string, pinName: string): string {
  return `port:${componentId}:${pinName}`
}

function buildRequestKey(documentId: string, revision: string, relayoutNonce: number): string {
  return `${documentId}::${revision}::${relayoutNonce}`
}

function getComponentSortKey(component: SchematicComponentState): string {
  return [component.scope_path.join('/'), component.instance_name, component.display_name, component.id].join('|')
}

function getComponentPriority(component: SchematicComponentState): number {
  const pinRoles = Object.values(component.pin_roles)
  const hasGround = pinRoles.includes('ground') || component.symbol_kind === 'ground'
  if (hasGround) {
    return 90
  }
  const hasPower = pinRoles.includes('power') || component.symbol_kind === 'voltage_source' || component.symbol_kind === 'current_source'
  if (hasPower) {
    return 10
  }
  const hasInput = pinRoles.includes('input')
  const hasOutput = pinRoles.includes('output')
  if (hasInput && !hasOutput) {
    return 20
  }
  if (hasOutput && !hasInput) {
    return 80
  }
  return 50
}

function sortComponents(components: SchematicComponentState[]): SchematicComponentState[] {
  return [...components].sort((left, right) => {
    const priorityDelta = getComponentPriority(left) - getComponentPriority(right)
    if (priorityDelta !== 0) {
      return priorityDelta
    }
    return getComponentSortKey(left).localeCompare(getComponentSortKey(right))
  })
}

function ensureScopeGroup(root: ScopeGroupBuilder, scopePath: string[]): ScopeGroupBuilder {
  let current = root
  for (let index = 0; index < scopePath.length; index += 1) {
    const nextPath = scopePath.slice(0, index + 1)
    const existing = current.children.find((item) => item.path.length === nextPath.length && item.path.every((segment, segmentIndex) => segment === nextPath[segmentIndex]))
    if (existing) {
      current = existing
      continue
    }
    const created: ScopeGroupBuilder = {
      path: nextPath,
      children: [],
      components: [],
    }
    current.children.push(created)
    current = created
  }
  return current
}

function buildSubcircuitLabelMap(subcircuits: SchematicSubcircuitState[]): Map<string, string> {
  const labels = new Map<string, string>()
  for (const item of subcircuits) {
    const path = [...item.scope_path, item.name]
    labels.set(buildScopePathKey(path), item.name)
  }
  return labels
}

function resolveScopeLabel(scopePath: string[], labelMap: Map<string, string>): string {
  const key = buildScopePathKey(scopePath)
  return labelMap.get(key) || scopePath[scopePath.length - 1] || 'scope'
}

function resolveLabelSlot(rawSlot: string, fallback: string): string {
  const normalized = rawSlot.trim().toLowerCase()
  if (normalized === 'top' || normalized === 'bottom' || normalized === 'left' || normalized === 'right' || normalized === 'top-left' || normalized === 'bottom-right') {
    return normalized
  }
  return fallback
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
      y: symbolBottom + 18,
      textAnchor: 'middle',
    }
  }
  if (label.slot === 'left') {
    return {
      text: label.text,
      x: symbolLeft - 8,
      y: symbolTop + 12,
      textAnchor: 'end',
    }
  }
  if (label.slot === 'right') {
    return {
      text: label.text,
      x: symbolRight + 8,
      y: symbolBottom - 8,
      textAnchor: 'start',
    }
  }
  if (label.slot === 'top-left') {
    return {
      text: label.text,
      x: symbolLeft,
      y: symbolTop - 10,
      textAnchor: 'start',
    }
  }
  if (label.slot === 'bottom-right') {
    return {
      text: label.text,
      x: symbolRight,
      y: symbolBottom + 18,
      textAnchor: 'end',
    }
  }
  return {
    text: label.text,
    x: symbolLeft + componentBox.symbolWidth / 2,
    y: symbolTop - 10,
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

function buildGraph(document: SchematicDocumentState, relayoutNonce: number) {
  const subcircuitLabelMap = buildSubcircuitLabelMap(document.subcircuits)
  const rootGroup: ScopeGroupBuilder = {
    path: [],
    children: [],
    components: [],
  }

  for (const component of sortComponents(document.components)) {
    const group = ensureScopeGroup(rootGroup, component.scope_path)
    group.components.push(component)
  }

  const componentBlueprints = new Map<string, ComponentBlueprint>()
  const groupBlueprints = new Map<string, GroupBlueprint>()
  const edgeBlueprints = new Map<string, EdgeBlueprint>()
  const portOwnerMap = new Map<string, string>()

  function buildComponentNode(component: SchematicComponentState): ElkNode {
    const definition = getSchematicSymbolDefinition(component.symbol_kind)
    const width = definition.width + NODE_PADDING.left + NODE_PADDING.right
    const height = definition.height + NODE_PADDING.top + NODE_PADDING.bottom
    const pins = component.pins.map((pin, index) => {
      const anchor = definition.getPinAnchor(component, pin, index)
      const portId = buildPortId(component.id, pin.name)
      portOwnerMap.set(portId, component.id)
      return {
        portId,
        pin,
        side: anchor.side,
        x: NODE_PADDING.left + anchor.x,
        y: NODE_PADDING.top + anchor.y,
      }
    })
    componentBlueprints.set(component.id, {
      component,
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

  function buildGroupNode(group: ScopeGroupBuilder): ElkNode {
    const childNodes = [
      ...group.children.map((item) => buildGroupNode(item)),
      ...group.components.map((component) => buildComponentNode(component)),
    ]
    const depth = group.path.length
    const id = buildGroupId(group.path)
    const label = resolveScopeLabel(group.path, subcircuitLabelMap)
    groupBlueprints.set(id, { id, label, depth })
    return {
      id,
      children: childNodes,
      layoutOptions: {
        'elk.padding': toPaddingValue(GROUP_PADDING),
      },
    }
  }

  const rootChildren = [
    ...rootGroup.children.map((item) => buildGroupNode(item)),
    ...rootGroup.components.map((component) => buildComponentNode(component)),
  ]

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

  for (const net of document.nets) {
    const connections = net.connections.filter((connection) => portOwnerMap.has(buildPortId(connection.component_id, connection.pin_name)))
    if (connections.length < 2) {
      continue
    }
    const [firstConnection, ...otherConnections] = connections
    const sourcePortId = buildPortId(firstConnection.component_id, firstConnection.pin_name)
    otherConnections.forEach((connection, index) => {
      const targetPortId = buildPortId(connection.component_id, connection.pin_name)
      const edgeId = `${net.id}::${relayoutNonce}::${index}`
      edgeBlueprints.set(edgeId, {
        edgeId,
        net,
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
      x: currentX,
      y: currentY,
      width: componentBlueprint.width,
      height: componentBlueprint.height,
      symbolX: componentBlueprint.symbolX,
      symbolY: componentBlueprint.symbolY,
      symbolWidth: componentBlueprint.symbolWidth,
      symbolHeight: componentBlueprint.symbolHeight,
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
        x: currentX,
        y: currentY,
        width: node.width ?? 0,
        height: node.height ?? 0,
      })
    }
    for (const child of node.children ?? []) {
      collectComponentLayouts(child, currentX, currentY, componentBlueprints, groupBlueprints, components, groups, portMap)
    }
  }
}

function buildNetLayouts(document: SchematicDocumentState, edges: ElkExtendedEdge[] | undefined, edgeBlueprints: Map<string, EdgeBlueprint>, portMap: Map<string, SchematicLayoutPin>): SchematicLayoutNet[] {
  const netsById = new Map<string, SchematicLayoutNet>()
  for (const net of document.nets) {
    netsById.set(net.id, {
      net,
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
          points,
        })
        if (targetNet.label === null && blueprint.net.name) {
          const middlePoint = points[Math.max(0, Math.floor(points.length / 2) - 1)] ?? points[0]
          targetNet.label = {
            text: blueprint.net.name,
            x: middlePoint.x + 8,
            y: middlePoint.y - 10,
            textAnchor: 'start',
          }
        }
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
      points: fallbackPoints,
    })
    if (targetNet.label === null && blueprint.net.name) {
      const anchorPoint = fallbackPoints[Math.floor(fallbackPoints.length / 2)] ?? fallbackPoints[0]
      targetNet.label = {
        text: blueprint.net.name,
        x: anchorPoint.x + 8,
        y: anchorPoint.y - 10,
        textAnchor: 'start',
      }
    }
  }

  for (const targetNet of netsById.values()) {
    if (targetNet.net.connections.length === 1) {
      const onlyConnection = targetNet.net.connections[0]
      const pin = portMap.get(buildPortId(onlyConnection.component_id, onlyConnection.pin_name))
      if (pin) {
        targetNet.segments.push({
          key: `${targetNet.net.id}:stub`,
          points: buildStubSegment(pin),
        })
        if (targetNet.label === null && targetNet.net.name) {
          targetNet.label = {
            text: targetNet.net.name,
            x: pin.x + 8,
            y: pin.y - 10,
            textAnchor: 'start',
          }
        }
      }
    }
  }

  return [...netsById.values()].filter((item) => item.segments.length > 0)
}

function buildBounds(components: SchematicLayoutComponent[], groups: SchematicLayoutGroup[], nets: SchematicLayoutNet[]): SchematicLayoutBounds | null {
  let bounds: SchematicLayoutBounds | null = null
  for (const group of groups) {
    bounds = includeRect(bounds, group.x, group.y, group.width, group.height)
  }
  for (const component of components) {
    bounds = includeRect(bounds, component.x, component.y, component.width, component.height)
    if (component.nameLabel) {
      bounds = includeRect(bounds, component.nameLabel.x - 48, component.nameLabel.y - 18, 96, 22)
    }
    if (component.valueLabel) {
      bounds = includeRect(bounds, component.valueLabel.x - 48, component.valueLabel.y - 18, 96, 22)
    }
  }
  for (const net of nets) {
    for (const segment of net.segments) {
      for (const point of segment.points) {
        bounds = includePoint(bounds, point)
      }
    }
    if (net.label) {
      bounds = includeRect(bounds, net.label.x - 8, net.label.y - 14, Math.max(42, net.label.text.length * 8 + 12), 20)
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

export async function computeSchematicLayout(document: SchematicDocumentState, relayoutNonce: number): Promise<SchematicLayoutResult> {
  const requestKey = buildRequestKey(document.document_id, document.revision, relayoutNonce)
  if (!document.has_schematic || document.components.length === 0) {
    return {
      requestKey,
      documentId: document.document_id,
      revision: document.revision,
      relayoutNonce,
      components: [],
      nets: [],
      groups: [],
      bounds: null,
    }
  }

  const { graph, componentBlueprints, groupBlueprints, edgeBlueprints } = buildGraph(document, relayoutNonce)
  const elk = await getElkInstance()
  const laidOutGraph = await elk.layout(graph)
  const components: SchematicLayoutComponent[] = []
  const groups: SchematicLayoutGroup[] = []
  const portMap = new Map<string, SchematicLayoutPin>()

  for (const child of laidOutGraph.children ?? []) {
    collectComponentLayouts(child, laidOutGraph.x ?? 0, laidOutGraph.y ?? 0, componentBlueprints, groupBlueprints, components, groups, portMap)
  }

  const nets = buildNetLayouts(document, laidOutGraph.edges, edgeBlueprints, portMap)
  const bounds = buildBounds(components, groups, nets)

  return {
    requestKey,
    documentId: document.document_id,
    revision: document.revision,
    relayoutNonce,
    components,
    nets,
    groups,
    bounds,
  }
}
