import type { ELK, ElkNode, ElkPort, ElkExtendedEdge, LayoutOptions } from 'elkjs/lib/elk-api'

import type {
  SchematicLayoutOrientation,
  SchematicLayoutRect,
  SchematicPinSide,
} from './schematicLayoutTypes'
import type {
  SchematicSemanticModel,
  SemanticComponent,
  SemanticNet,
  SemanticScopeGroup,
} from './schematicSemanticModel'
import type { SchematicNetRoleMap } from './schematicNetRoles'
import { getSchematicSymbolDefinition } from './symbolRegistry'

// ---------------------------------------------------------------------------
// Public output model consumed by schematicLayout.ts
// ---------------------------------------------------------------------------

export interface SchematicElkComponentPosition {
  componentId: string
  scopeGroupId: string
  orientation: SchematicLayoutOrientation
  box: SchematicLayoutRect
  symbolBox: SchematicLayoutRect
}

export interface SchematicElkScopeGroupBounds {
  scopeGroupId: string
  depth: number
  label: string
  bounds: SchematicLayoutRect
  componentIds: string[]
}

export interface SchematicElkLayout {
  componentPositions: SchematicElkComponentPosition[]
  componentsById: Map<string, SchematicElkComponentPosition>
  scopeGroupBounds: SchematicElkScopeGroupBounds[]
  scopeGroupBoundsById: Map<string, SchematicElkScopeGroupBounds>
  overallBounds: SchematicLayoutRect | null
}

// ---------------------------------------------------------------------------
// ELK instance (lazily imported so the worker bundle is only loaded on demand)
// ---------------------------------------------------------------------------

let elkInstancePromise: Promise<ELK> | null = null

async function getElkInstance(): Promise<ELK> {
  if (elkInstancePromise === null) {
    elkInstancePromise = import('elkjs/lib/elk.bundled.js').then((module) => new module.default())
  }
  return elkInstancePromise
}

// ---------------------------------------------------------------------------
// Layout tuning constants
// ---------------------------------------------------------------------------

const NODE_PADDING_X = 20
const NODE_PADDING_Y = 22
const SCOPE_OUTER_PADDING_X = 28
const SCOPE_OUTER_PADDING_Y = 34
const SCOPE_INNER_PADDING = '[top=28,left=28,bottom=28,right=28]'
const ROOT_PADDING = '[top=40,left=40,bottom=40,right=40]'

const RAIL_TRUNK_CLEARANCE_Y = 120
const RAIL_COMPONENT_SPACING_X = 112
const RAIL_COMPONENT_MIN_MARGIN_X = 32

// Virtual hub nodes materialize N-pin nets as star edges with a tiny anchor
// at the Steiner center. Keep the hub small so it barely perturbs spacing but
// not zero-sized (ELK refuses degenerate geometry in some layout phases).
const VIRTUAL_HUB_SIZE = 2
const VIRTUAL_HUB_ID_PREFIX = 'hub:'

const GRID_SNAP = 4

const ROOT_LAYOUT_OPTIONS: LayoutOptions = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
  'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
  'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
  'elk.layered.cycleBreaking.strategy': 'GREEDY',
  'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
  'elk.layered.spacing.nodeNodeBetweenLayers': '72',
  'elk.layered.spacing.edgeNodeBetweenLayers': '24',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '16',
  'elk.layered.thoroughness': '12',
  'elk.spacing.nodeNode': '52',
  'elk.spacing.edgeNode': '18',
  'elk.spacing.edgeEdge': '12',
  'elk.spacing.portPort': '16',
  'elk.padding': ROOT_PADDING,
  'elk.separateConnectedComponents': 'true',
  'elk.layered.considerModelOrder.strategy': 'PREFER_EDGES',
}

const SCOPE_NODE_LAYOUT_OPTIONS: LayoutOptions = {
  'elk.padding': SCOPE_INNER_PADDING,
}

const COMPONENT_NODE_LAYOUT_OPTIONS: LayoutOptions = {
  'elk.portConstraints': 'FIXED_SIDE',
}

// ---------------------------------------------------------------------------
// Rail extraction: pure supply / ground pads do not flow through the ELK
// layered graph. They are laid out post-placement along dedicated trunks above
// and below the main signal band so the ELK result stays focused on signal
// topology (which is what Sugiyama is good at).
// ---------------------------------------------------------------------------

interface RailPartition {
  mainComponents: SemanticComponent[]
  powerRailOnly: SemanticComponent[]
  groundRailOnly: SemanticComponent[]
}

function partitionByRailRole(semantic: SchematicSemanticModel): RailPartition {
  const mainComponents: SemanticComponent[] = []
  const powerRailOnly: SemanticComponent[] = []
  const groundRailOnly: SemanticComponent[] = []
  for (const component of semantic.components) {
    if (component.role === 'supply') {
      powerRailOnly.push(component)
    } else if (component.role === 'ground') {
      groundRailOnly.push(component)
    } else {
      mainComponents.push(component)
    }
  }
  return { mainComponents, powerRailOnly, groundRailOnly }
}

// ---------------------------------------------------------------------------
// ELK graph construction
// ---------------------------------------------------------------------------

function buildPortId(componentId: string, pinName: string): string {
  return `port:${componentId}:${pinName}`
}

function mapPinSideToElkSide(side: SchematicPinSide): string {
  switch (side) {
    case 'left':
      return 'WEST'
    case 'right':
      return 'EAST'
    case 'top':
      return 'NORTH'
    case 'bottom':
      return 'SOUTH'
  }
}

function buildComponentElkNode(component: SemanticComponent): ElkNode {
  const definition = getSchematicSymbolDefinition(component.component.symbol_kind)
  const ports: ElkPort[] = component.pins.map((semanticPin) => {
    const anchor = definition.getPinAnchor(component.component, semanticPin.pin, semanticPin.index)
    return {
      id: buildPortId(component.component.id, semanticPin.pin.name),
      width: 0,
      height: 0,
      layoutOptions: {
        'elk.port.side': mapPinSideToElkSide(anchor.side),
      },
    }
  })
  return {
    id: component.component.id,
    width: definition.width + NODE_PADDING_X * 2,
    height: definition.height + NODE_PADDING_Y * 2,
    ports,
    layoutOptions: { ...COMPONENT_NODE_LAYOUT_OPTIONS },
  }
}

interface ScopeBuildContext {
  semantic: SchematicSemanticModel
  mainComponentIds: Set<string>
  componentNodesById: Map<string, ElkNode>
}

function buildScopeHierarchy(scope: SemanticScopeGroup, context: ScopeBuildContext): ElkNode | null {
  const children: ElkNode[] = []
  for (const childId of scope.childGroupIds) {
    const childScope = context.semantic.scopeGroupsById.get(childId)
    if (!childScope) continue
    const childNode = buildScopeHierarchy(childScope, context)
    if (childNode) {
      children.push(childNode)
    }
  }
  for (const componentId of scope.componentIds) {
    if (!context.mainComponentIds.has(componentId)) continue
    const node = context.componentNodesById.get(componentId)
    if (node) {
      children.push(node)
    }
  }
  if (children.length === 0 && scope.depth > 0) {
    return null
  }
  return {
    id: scope.depth === 0 ? 'schematic-root' : `scope:${scope.id}`,
    children,
    layoutOptions:
      scope.depth === 0
        ? { ...ROOT_LAYOUT_OPTIONS }
        : { ...SCOPE_NODE_LAYOUT_OPTIONS },
  }
}

interface ElkEdgeBuild {
  edges: ElkExtendedEdge[]
  virtualHubNodes: ElkNode[]
}

/**
 * ELK's `layered` algorithm does not accept true hyperedges (edges with more
 * than two endpoints). To express N-pin nets correctly we use the ELK-approved
 * technique of inserting a zero-semantic "virtual hub" node per multi-pin net
 * and connecting every pin to the hub with an ordinary 2-endpoint edge.
 *
 * Properties of this encoding:
 *   - 2-pin nets degenerate to a single direct edge (no hub allocated).
 *   - N-pin nets produce exactly N spoke edges + 1 virtual hub node, i.e.
 *     linear in the pin count. This matches the cost of a spanning chain
 *     while avoiding its order-dependence and its "flatten into N layers"
 *     visual pathology.
 *   - The hub converges to the geometric center of its connected components
 *     under Sugiyama, approximating the Steiner center of the net — which is
 *     exactly the aesthetic we want for fan-out branches and feedback webs.
 *   - Hub nodes use `VIRTUAL_HUB_ID_PREFIX` so downstream position collection
 *     skips them trivially; they never surface in `SchematicLayoutResult`.
 */
function buildElkEdges(
  semantic: SchematicSemanticModel,
  netRoles: SchematicNetRoleMap,
  mainComponentIds: Set<string>,
): ElkEdgeBuild {
  const edges: ElkExtendedEdge[] = []
  const virtualHubNodes: ElkNode[] = []
  for (const semanticNet of semantic.nets) {
    const role = netRoles.get(semanticNet.net.id) ?? 'branch'
    // Rails are handled outside ELK; skip them so they don't distort the
    // signal-flow layering.
    if (role === 'power_rail' || role === 'ground_rail' || role === 'dangling') {
      continue
    }
    const connections = collectConnectionsWithinMainGraph(semanticNet, mainComponentIds)
    if (connections.length < 2) {
      continue
    }
    const edgeOptions = edgeLayoutOptionsForRole(role)
    if (connections.length === 2) {
      edges.push({
        id: `edge:${semanticNet.net.id}`,
        sources: [connections[0].portId],
        targets: [connections[1].portId],
        layoutOptions: edgeOptions,
      })
      continue
    }
    const hubId = `${VIRTUAL_HUB_ID_PREFIX}${semanticNet.net.id}`
    virtualHubNodes.push({
      id: hubId,
      width: VIRTUAL_HUB_SIZE,
      height: VIRTUAL_HUB_SIZE,
      layoutOptions: {
        'elk.portConstraints': 'FREE',
      },
    })
    connections.forEach((connection, index) => {
      edges.push({
        id: `edge:${semanticNet.net.id}:${index}`,
        sources: [connection.portId],
        targets: [hubId],
        layoutOptions: edgeOptions,
      })
    })
  }
  return { edges, virtualHubNodes }
}

interface ConnectionEndpoint {
  portId: string
}

function collectConnectionsWithinMainGraph(
  semanticNet: SemanticNet,
  mainComponentIds: Set<string>,
): ConnectionEndpoint[] {
  const result: ConnectionEndpoint[] = []
  for (const connection of semanticNet.net.connections) {
    if (!mainComponentIds.has(connection.component_id)) continue
    result.push({ portId: buildPortId(connection.component_id, connection.pin_name) })
  }
  return result
}

function edgeLayoutOptionsForRole(role: string): LayoutOptions {
  if (role === 'signal_trunk') {
    return {
      'elk.layered.priority.shortness': '10',
      'elk.layered.priority.straightness': '10',
    }
  }
  return {
    'elk.layered.priority.shortness': '1',
    'elk.layered.priority.straightness': '5',
  }
}

// ---------------------------------------------------------------------------
// Post-processing: recover per-component positions and orientations
// ---------------------------------------------------------------------------

function snapToGrid(value: number): number {
  return Math.round(value / GRID_SNAP) * GRID_SNAP
}

interface AbsolutePositionedNode {
  node: ElkNode
  absX: number
  absY: number
}

function collectAbsoluteComponentPositions(
  root: ElkNode,
  componentIdSet: Set<string>,
): Map<string, AbsolutePositionedNode> {
  const result = new Map<string, AbsolutePositionedNode>()
  function walk(node: ElkNode, parentX: number, parentY: number): void {
    const absX = parentX + (node.x ?? 0)
    const absY = parentY + (node.y ?? 0)
    if (componentIdSet.has(node.id)) {
      result.set(node.id, { node, absX, absY })
      return
    }
    if (node.children) {
      for (const child of node.children) {
        walk(child, absX, absY)
      }
    }
  }
  walk(root, 0, 0)
  return result
}

function collectAbsoluteScopeBounds(
  root: ElkNode,
  semantic: SchematicSemanticModel,
): Map<string, SchematicLayoutRect> {
  const result = new Map<string, SchematicLayoutRect>()
  const scopePrefix = 'scope:'
  function walk(node: ElkNode, parentX: number, parentY: number): void {
    const absX = parentX + (node.x ?? 0)
    const absY = parentY + (node.y ?? 0)
    if (node.id.startsWith(scopePrefix)) {
      const scopeId = node.id.slice(scopePrefix.length)
      const scope = semantic.scopeGroupsById.get(scopeId)
      if (scope) {
        result.set(scopeId, {
          x: absX,
          y: absY,
          width: node.width ?? 0,
          height: node.height ?? 0,
        })
      }
    }
    if (node.children) {
      for (const child of node.children) {
        walk(child, absX, absY)
      }
    }
  }
  walk(root, 0, 0)
  return result
}

function buildMainComponentPositions(
  mainComponents: SemanticComponent[],
  absoluteNodes: Map<string, AbsolutePositionedNode>,
): SchematicElkComponentPosition[] {
  const positions: SchematicElkComponentPosition[] = []
  for (const component of mainComponents) {
    const placed = absoluteNodes.get(component.component.id)
    if (!placed) continue
    const definition = getSchematicSymbolDefinition(component.component.symbol_kind)
    const boxX = snapToGrid(placed.absX)
    const boxY = snapToGrid(placed.absY)
    const boxWidth = placed.node.width ?? definition.width + NODE_PADDING_X * 2
    const boxHeight = placed.node.height ?? definition.height + NODE_PADDING_Y * 2
    positions.push({
      componentId: component.component.id,
      scopeGroupId: component.scopeGroupId,
      orientation: 'right',
      box: { x: boxX, y: boxY, width: boxWidth, height: boxHeight },
      symbolBox: {
        x: boxX + NODE_PADDING_X,
        y: boxY + NODE_PADDING_Y,
        width: definition.width,
        height: definition.height,
      },
    })
  }
  return positions
}

// ---------------------------------------------------------------------------
// Rail placement: dedicated horizontal trunks above (power) and below (ground)
// the main signal band. Rail components do not participate in ELK; we lay them
// out analytically so the rails stay as a clean single row each.
// ---------------------------------------------------------------------------

function layoutRailComponents(
  powerRailOnly: SemanticComponent[],
  groundRailOnly: SemanticComponent[],
  mainPositions: SchematicElkComponentPosition[],
  semantic: SchematicSemanticModel,
): SchematicElkComponentPosition[] {
  if (powerRailOnly.length === 0 && groundRailOnly.length === 0) {
    return []
  }
  const mainBounds = computeMainBounds(mainPositions)

  const result: SchematicElkComponentPosition[] = []

  const powerAnchors = computeRailAnchorsFromConnections(powerRailOnly, semantic, mainPositions)
  placeRailRow(
    powerRailOnly,
    powerAnchors,
    (mainBounds.y ?? 0) - RAIL_TRUNK_CLEARANCE_Y,
    mainBounds,
    'up',
    result,
  )

  const groundAnchors = computeRailAnchorsFromConnections(groundRailOnly, semantic, mainPositions)
  placeRailRow(
    groundRailOnly,
    groundAnchors,
    (mainBounds.y ?? 0) + (mainBounds.height ?? 0) + RAIL_TRUNK_CLEARANCE_Y,
    mainBounds,
    'down',
    result,
  )

  return result
}

interface MainBounds {
  x: number
  y: number
  width: number
  height: number
}

function computeMainBounds(positions: SchematicElkComponentPosition[]): MainBounds {
  if (positions.length === 0) {
    return { x: 0, y: 0, width: 0, height: 0 }
  }
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const position of positions) {
    minX = Math.min(minX, position.box.x)
    minY = Math.min(minY, position.box.y)
    maxX = Math.max(maxX, position.box.x + position.box.width)
    maxY = Math.max(maxY, position.box.y + position.box.height)
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

function computeRailAnchorsFromConnections(
  railComponents: SemanticComponent[],
  semantic: SchematicSemanticModel,
  mainPositions: SchematicElkComponentPosition[],
): Map<string, number> {
  const mainPositionsById = new Map<string, SchematicElkComponentPosition>()
  for (const position of mainPositions) {
    mainPositionsById.set(position.componentId, position)
  }
  const anchors = new Map<string, number>()
  for (const component of railComponents) {
    const neighborXs: number[] = []
    for (const semanticNet of semantic.nets) {
      if (!semanticNet.componentIds.includes(component.component.id)) continue
      for (const otherId of semanticNet.componentIds) {
        if (otherId === component.component.id) continue
        const other = mainPositionsById.get(otherId)
        if (other) {
          neighborXs.push(other.box.x + other.box.width / 2)
        }
      }
    }
    if (neighborXs.length > 0) {
      const sum = neighborXs.reduce((acc, value) => acc + value, 0)
      anchors.set(component.component.id, sum / neighborXs.length)
    }
  }
  return anchors
}

function placeRailRow(
  components: SemanticComponent[],
  anchors: Map<string, number>,
  centerY: number,
  mainBounds: MainBounds,
  direction: 'up' | 'down',
  output: SchematicElkComponentPosition[],
): void {
  if (components.length === 0) return
  const ordered = [...components].sort((left, right) => {
    const leftAnchor = anchors.get(left.component.id) ?? Number.POSITIVE_INFINITY
    const rightAnchor = anchors.get(right.component.id) ?? Number.POSITIVE_INFINITY
    if (leftAnchor !== rightAnchor) return leftAnchor - rightAnchor
    return left.component.id.localeCompare(right.component.id)
  })
  // Sweep a 1-D VPSC-like pass to satisfy minimum spacing while keeping
  // components close to their preferred anchors.
  const layout: Array<{ component: SemanticComponent; centerX: number; width: number; height: number }> = []
  let cursorX = mainBounds.x + RAIL_COMPONENT_MIN_MARGIN_X
  for (const component of ordered) {
    const definition = getSchematicSymbolDefinition(component.component.symbol_kind)
    const width = definition.width + NODE_PADDING_X * 2
    const height = definition.height + NODE_PADDING_Y * 2
    const preferred = anchors.get(component.component.id) ?? cursorX
    const centerX = Math.max(preferred, cursorX + width / 2)
    layout.push({ component, centerX, width, height })
    cursorX = centerX + width / 2 + (RAIL_COMPONENT_SPACING_X - width)
  }
  for (const entry of layout) {
    const definition = getSchematicSymbolDefinition(entry.component.component.symbol_kind)
    const boxX = snapToGrid(entry.centerX - entry.width / 2)
    const boxY = snapToGrid(direction === 'up' ? centerY - entry.height : centerY)
    output.push({
      componentId: entry.component.component.id,
      scopeGroupId: entry.component.scopeGroupId,
      orientation: 'right',
      box: { x: boxX, y: boxY, width: entry.width, height: entry.height },
      symbolBox: {
        x: boxX + NODE_PADDING_X,
        y: boxY + NODE_PADDING_Y,
        width: definition.width,
        height: definition.height,
      },
    })
  }
}

// ---------------------------------------------------------------------------
// Scope group bounds: union of children after rails are placed
// ---------------------------------------------------------------------------

function unionRect(existing: SchematicLayoutRect | null, next: SchematicLayoutRect): SchematicLayoutRect {
  if (existing === null) return { ...next }
  const minX = Math.min(existing.x, next.x)
  const minY = Math.min(existing.y, next.y)
  const maxX = Math.max(existing.x + existing.width, next.x + next.width)
  const maxY = Math.max(existing.y + existing.height, next.y + next.height)
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

function buildScopeGroupBounds(
  positions: SchematicElkComponentPosition[],
  semantic: SchematicSemanticModel,
  elkScopeBounds: Map<string, SchematicLayoutRect>,
): Map<string, SchematicElkScopeGroupBounds> {
  const result = new Map<string, SchematicElkScopeGroupBounds>()
  // Seed from ELK's own scope bounds so nested hierarchies stay consistent.
  for (const [scopeId, bounds] of elkScopeBounds) {
    const scope = semantic.scopeGroupsById.get(scopeId)
    if (!scope || scope.depth === 0) continue
    result.set(scopeId, {
      scopeGroupId: scopeId,
      depth: scope.depth,
      label: scope.label,
      bounds: { ...bounds },
      componentIds: [],
    })
  }
  // Expand each scope to also cover any post-placed rail components belonging
  // to it, and record the full component id list.
  for (const position of positions) {
    let scope: SemanticScopeGroup | undefined = semantic.scopeGroupsById.get(position.scopeGroupId)
    while (scope && scope.depth > 0) {
      const existing = result.get(scope.id)
      if (existing) {
        existing.bounds = unionRect(existing.bounds, position.box)
        existing.componentIds.push(position.componentId)
      } else {
        result.set(scope.id, {
          scopeGroupId: scope.id,
          depth: scope.depth,
          label: scope.label,
          bounds: { ...position.box },
          componentIds: [position.componentId],
        })
      }
      scope = scope.parentId ? semantic.scopeGroupsById.get(scope.parentId) : undefined
    }
  }
  for (const entry of result.values()) {
    entry.bounds = {
      x: entry.bounds.x - SCOPE_OUTER_PADDING_X,
      y: entry.bounds.y - SCOPE_OUTER_PADDING_Y,
      width: entry.bounds.width + SCOPE_OUTER_PADDING_X * 2,
      height: entry.bounds.height + SCOPE_OUTER_PADDING_Y * 2,
    }
  }
  return result
}

// ---------------------------------------------------------------------------
// Authoritative entry point
// ---------------------------------------------------------------------------

export async function computeSchematicElkLayout(
  semantic: SchematicSemanticModel,
  netRoles: SchematicNetRoleMap,
): Promise<SchematicElkLayout> {
  if (semantic.components.length === 0) {
    return {
      componentPositions: [],
      componentsById: new Map(),
      scopeGroupBounds: [],
      scopeGroupBoundsById: new Map(),
      overallBounds: null,
    }
  }

  const { mainComponents, powerRailOnly, groundRailOnly } = partitionByRailRole(semantic)
  const mainComponentIds = new Set(mainComponents.map((item) => item.component.id))

  let mainPositions: SchematicElkComponentPosition[]
  let elkScopeBounds: Map<string, SchematicLayoutRect>

  if (mainComponents.length > 0) {
    const componentNodesById = new Map<string, ElkNode>()
    for (const component of mainComponents) {
      componentNodesById.set(component.component.id, buildComponentElkNode(component))
    }
    const rootScope = semantic.scopeGroupsById.get(semantic.rootScopeGroupId)
    if (!rootScope) {
      throw new Error('[schematicElkLayout] Root scope group missing from semantic model')
    }
    const rootNode = buildScopeHierarchy(rootScope, {
      semantic,
      mainComponentIds,
      componentNodesById,
    })
    if (!rootNode) {
      throw new Error('[schematicElkLayout] Failed to build ELK root node')
    }
    const { edges, virtualHubNodes } = buildElkEdges(semantic, netRoles, mainComponentIds)
    rootNode.edges = edges
    if (virtualHubNodes.length > 0) {
      // Virtual hubs are attached flat under the root so cross-scope nets
      // resolve uniformly; `hierarchyHandling: INCLUDE_CHILDREN` in the root
      // layout options lets ELK route spoke edges into nested scope groups.
      rootNode.children = [...(rootNode.children ?? []), ...virtualHubNodes]
    }

    const elk = await getElkInstance()
    const laidOut = await elk.layout(rootNode)
    const absoluteNodes = collectAbsoluteComponentPositions(laidOut, mainComponentIds)
    mainPositions = buildMainComponentPositions(mainComponents, absoluteNodes)
    elkScopeBounds = collectAbsoluteScopeBounds(laidOut, semantic)
  } else {
    mainPositions = []
    elkScopeBounds = new Map()
  }

  const railPositions = layoutRailComponents(powerRailOnly, groundRailOnly, mainPositions, semantic)

  const componentPositions = [...mainPositions, ...railPositions]
  const componentsById = new Map<string, SchematicElkComponentPosition>()
  for (const position of componentPositions) {
    componentsById.set(position.componentId, position)
  }

  const scopeGroupBoundsById = buildScopeGroupBounds(componentPositions, semantic, elkScopeBounds)
  const scopeGroupBounds = Array.from(scopeGroupBoundsById.values()).sort(
    (left, right) => left.depth - right.depth,
  )

  let overallBounds: SchematicLayoutRect | null = null
  for (const position of componentPositions) {
    overallBounds = unionRect(overallBounds, position.box)
  }
  for (const entry of scopeGroupBounds) {
    overallBounds = unionRect(overallBounds, entry.bounds)
  }

  return {
    componentPositions,
    componentsById,
    scopeGroupBounds,
    scopeGroupBoundsById,
    overallBounds,
  }
}
