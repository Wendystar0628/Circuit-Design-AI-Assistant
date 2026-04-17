import type {
  SchematicLayoutComponent,
  SchematicLayoutNetSegment,
  SchematicLayoutPin,
  SchematicLayoutPoint,
  SchematicLayoutSegmentAxis,
  SchematicLayoutSegmentKind,
  SchematicPinSide,
} from './schematicLayoutTypes'
import type { SchematicSemanticModel } from './schematicSemanticModel'
import type { SchematicNetRoleMap } from './schematicNetRoles'

// ============================================================================
// Orthogonal Connector Routing
// ----------------------------------------------------------------------------
// Authoritative pin-to-pin wire router backed by:
//
//   Layer 1 — Obstacle model
//     each SchematicLayoutComponent.symbolBounds becomes an axis-aligned
//     obstacle, inflated by OBSTACLE_CLEARANCE on every side. Pin vertices
//     inherit their component's id so that edges incident to a pin are
//     allowed to pass through the owning component's own obstacle.
//
//   Layer 2 — Orthogonal visibility graph (OVG)
//     coordinates are collected from obstacle edges and pin/attachment
//     positions. The Cartesian product of the X and Y coordinate lists
//     gives candidate vertices; those strictly inside any obstacle are
//     rejected unless they correspond to a pin anchor. Horizontal and
//     vertical edges are drawn between adjacent vertices on the same row
//     or column iff the segment does not cross any obstacle's interior.
//
//   Layer 3 — Port constraints
//     each pin has an attachment vertex offset by STUB_LENGTH in pin.side.
//     The pin vertex's adjacency is then restricted to that single
//     attachment edge, forcing A* to exit every pin along its correct
//     side. No other mechanism — pattern templates, "shift once" hacks,
//     directional heuristics — is permitted.
//
//   Layer 4 — Single-pair A* and Kou-style Steiner tree growth
//     2-pin nets use A* on the OVG with Manhattan heuristic and a bend
//     penalty. Multi-pin nets grow a Steiner-like tree by running
//     multi-source A* from the current tree to the next unreached
//     terminal; edges already in the tree carry a strong bonus so the
//     tree reuses its trunk rather than drawing parallel copies.
//
//   Layer 5 — Nudging
//     parallel segments that share a row/column and overlap are separated
//     using a local 1-D separation sweep (VPSC-equivalent for our feasibility
//     needs) — no external constraint-solver dependency is required.
//
//   Layer 6 — Polyline marshaling
//     tree edges are contracted through degree-2 colinear vertices and
//     emitted as SchematicLayoutNetSegment instances. Redundant length-0
//     segments are dropped; coordinates are snapped to GRID_SNAP so they
//     align with Phase-2 placement.
//
// This module is the single authority for wire routing. There is no
// fallback, no pattern-based shortcut, no straight-line bypass.
// ============================================================================

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const OBSTACLE_CLEARANCE = 14
const STUB_LENGTH = 28
const OUTER_MARGIN = STUB_LENGTH * 2
const BEND_PENALTY_COST = 24
const WIRE_OVERLAP_PENALTY_COST = 36
const TREE_REUSE_BONUS_FACTOR = 0.05
const WIRE_MIN_GAP = 10
const GRID_SNAP = 4
const EPSILON = 1e-6

// ---------------------------------------------------------------------------
// Obstacle model (Layer 1)
// ---------------------------------------------------------------------------

interface Obstacle {
  id: number
  left: number
  right: number
  top: number
  bottom: number
  ownerComponentId: string
}

function buildObstacles(components: SchematicLayoutComponent[]): Obstacle[] {
  const obstacles: Obstacle[] = []
  for (let index = 0; index < components.length; index += 1) {
    const component = components[index]
    const bounds = component.symbolBounds
    obstacles.push({
      id: index,
      left: bounds.x - OBSTACLE_CLEARANCE,
      right: bounds.x + bounds.width + OBSTACLE_CLEARANCE,
      top: bounds.y - OBSTACLE_CLEARANCE,
      bottom: bounds.y + bounds.height + OBSTACLE_CLEARANCE,
      ownerComponentId: component.component.id,
    })
  }
  return obstacles
}

function segmentCrossesObstacleInterior(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  obstacle: Obstacle,
  excludedOwners: Set<string>,
): boolean {
  if (excludedOwners.has(obstacle.ownerComponentId)) {
    return false
  }
  const minX = Math.min(x1, x2)
  const maxX = Math.max(x1, x2)
  const minY = Math.min(y1, y2)
  const maxY = Math.max(y1, y2)
  if (maxX <= obstacle.left + EPSILON) return false
  if (minX >= obstacle.right - EPSILON) return false
  if (maxY <= obstacle.top + EPSILON) return false
  if (minY >= obstacle.bottom - EPSILON) return false
  return true
}

function pointStrictlyInside(x: number, y: number, obstacle: Obstacle): boolean {
  return (
    x > obstacle.left + EPSILON &&
    x < obstacle.right - EPSILON &&
    y > obstacle.top + EPSILON &&
    y < obstacle.bottom - EPSILON
  )
}

// ---------------------------------------------------------------------------
// Orthogonal Visibility Graph (Layer 2 + Layer 3)
// ---------------------------------------------------------------------------

type EdgeAxis = 'horizontal' | 'vertical'

interface OVGVertex {
  id: number
  x: number
  y: number
  /**
   * Identity of the component that owns this vertex, used purely to relax
   * obstacle collision checks: edges incident to this vertex may cross the
   * owning component's own obstacle (otherwise pins, which sit on the symbol
   * boundary, would be trapped inside their clearance rectangle).
   */
  ownedBy: string | null
}

interface OVGEdge {
  index: number
  from: number
  to: number
  axis: EdgeAxis
  length: number
}

interface OVGNeighbor {
  to: number
  edge: OVGEdge
}

interface OVG {
  vertices: OVGVertex[]
  edges: OVGEdge[]
  adjacency: Map<number, OVGNeighbor[]>
}

interface PinEndpointBinding {
  pinId: string
  pinVertexId: number
  attachmentVertexId: number
}

function directionVector(side: SchematicPinSide): { dx: number; dy: number } {
  switch (side) {
    case 'left':
      return { dx: -1, dy: 0 }
    case 'right':
      return { dx: 1, dy: 0 }
    case 'top':
      return { dx: 0, dy: -1 }
    case 'bottom':
      return { dx: 0, dy: 1 }
  }
}

function buildOrthogonalVisibilityGraph(
  obstacles: Obstacle[],
  pins: SchematicLayoutPin[],
): {
  ovg: OVG
  endpointsByPinId: Map<string, PinEndpointBinding>
} {
  const xCoords = new Set<number>()
  const yCoords = new Set<number>()

  for (const obstacle of obstacles) {
    xCoords.add(obstacle.left)
    xCoords.add(obstacle.right)
    yCoords.add(obstacle.top)
    yCoords.add(obstacle.bottom)
  }

  for (const pin of pins) {
    xCoords.add(pin.x)
    yCoords.add(pin.y)
    const direction = directionVector(pin.side)
    xCoords.add(pin.x + direction.dx * STUB_LENGTH)
    yCoords.add(pin.y + direction.dy * STUB_LENGTH)
  }

  const sortedX = [...xCoords].sort((left, right) => left - right)
  const sortedY = [...yCoords].sort((left, right) => left - right)

  if (sortedX.length > 0) {
    xCoords.add(sortedX[0] - OUTER_MARGIN)
    xCoords.add(sortedX[sortedX.length - 1] + OUTER_MARGIN)
  }
  if (sortedY.length > 0) {
    yCoords.add(sortedY[0] - OUTER_MARGIN)
    yCoords.add(sortedY[sortedY.length - 1] + OUTER_MARGIN)
  }

  const xs = [...xCoords].sort((left, right) => left - right)
  const ys = [...yCoords].sort((left, right) => left - right)

  const vertices: OVGVertex[] = []
  const vertexByKey = new Map<string, number>()

  function keyOf(x: number, y: number): string {
    return `${x}|${y}`
  }

  function ensureVertex(x: number, y: number, ownedBy: string | null): number {
    const key = keyOf(x, y)
    const existing = vertexByKey.get(key)
    if (existing !== undefined) {
      if (ownedBy === null && vertices[existing].ownedBy !== null) {
        // Promote to un-owned so non-pin paths can reuse this grid vertex.
        vertices[existing].ownedBy = null
      }
      return existing
    }
    const id = vertices.length
    vertices.push({ id, x, y, ownedBy })
    vertexByKey.set(key, id)
    return id
  }

  // Add pin vertices (sit on or inside the owning component's clearance rectangle).
  const endpointsByPinId = new Map<string, PinEndpointBinding>()
  for (const pin of pins) {
    const pinVertexId = ensureVertex(pin.x, pin.y, pin.componentId)
    const direction = directionVector(pin.side)
    const attachmentX = pin.x + direction.dx * STUB_LENGTH
    const attachmentY = pin.y + direction.dy * STUB_LENGTH
    const attachmentVertexId = ensureVertex(attachmentX, attachmentY, null)
    endpointsByPinId.set(pin.id, {
      pinId: pin.id,
      pinVertexId,
      attachmentVertexId,
    })
  }

  // Add remaining grid vertices, skipping those strictly inside any obstacle.
  for (const x of xs) {
    for (const y of ys) {
      if (vertexByKey.has(keyOf(x, y))) {
        continue
      }
      let blocked = false
      for (const obstacle of obstacles) {
        if (pointStrictlyInside(x, y, obstacle)) {
          blocked = true
          break
        }
      }
      if (!blocked) {
        ensureVertex(x, y, null)
      }
    }
  }

  // Bucket vertices by row (y) and column (x) so adjacent-pair edges can be
  // emitted without a full O(V^2) scan.
  const byRow = new Map<number, number[]>()
  const byColumn = new Map<number, number[]>()
  for (const vertex of vertices) {
    let row = byRow.get(vertex.y)
    if (!row) {
      row = []
      byRow.set(vertex.y, row)
    }
    row.push(vertex.id)
    let column = byColumn.get(vertex.x)
    if (!column) {
      column = []
      byColumn.set(vertex.x, column)
    }
    column.push(vertex.id)
  }

  const edges: OVGEdge[] = []
  const adjacency = new Map<number, OVGNeighbor[]>()

  function attachEdge(edge: OVGEdge): void {
    let fromList = adjacency.get(edge.from)
    if (!fromList) {
      fromList = []
      adjacency.set(edge.from, fromList)
    }
    fromList.push({ to: edge.to, edge })
    let toList = adjacency.get(edge.to)
    if (!toList) {
      toList = []
      adjacency.set(edge.to, toList)
    }
    toList.push({ to: edge.from, edge })
  }

  function tryAddEdge(fromId: number, toId: number, axis: EdgeAxis): void {
    const fromVertex = vertices[fromId]
    const toVertex = vertices[toId]
    const length = axis === 'horizontal'
      ? Math.abs(toVertex.x - fromVertex.x)
      : Math.abs(toVertex.y - fromVertex.y)
    if (length <= EPSILON) {
      return
    }
    const excludedOwners = new Set<string>()
    if (fromVertex.ownedBy !== null) excludedOwners.add(fromVertex.ownedBy)
    if (toVertex.ownedBy !== null) excludedOwners.add(toVertex.ownedBy)
    for (const obstacle of obstacles) {
      if (segmentCrossesObstacleInterior(fromVertex.x, fromVertex.y, toVertex.x, toVertex.y, obstacle, excludedOwners)) {
        return
      }
    }
    const edge: OVGEdge = {
      index: edges.length,
      from: fromId,
      to: toId,
      axis,
      length,
    }
    edges.push(edge)
    attachEdge(edge)
  }

  for (const row of byRow.values()) {
    row.sort((a, b) => vertices[a].x - vertices[b].x)
    for (let i = 1; i < row.length; i += 1) {
      tryAddEdge(row[i - 1], row[i], 'horizontal')
    }
  }
  for (const column of byColumn.values()) {
    column.sort((a, b) => vertices[a].y - vertices[b].y)
    for (let i = 1; i < column.length; i += 1) {
      tryAddEdge(column[i - 1], column[i], 'vertical')
    }
  }

  return {
    ovg: { vertices, edges, adjacency },
    endpointsByPinId,
  }
}

function enforcePinDirectionConstraints(
  ovg: OVG,
  pins: SchematicLayoutPin[],
  endpointsByPinId: Map<string, PinEndpointBinding>,
): void {
  for (const pin of pins) {
    const binding = endpointsByPinId.get(pin.id)
    if (!binding) {
      continue
    }
    const neighbors = ovg.adjacency.get(binding.pinVertexId)
    if (!neighbors) {
      continue
    }
    const pinVertex = ovg.vertices[binding.pinVertexId]
    const direction = directionVector(pin.side)
    const allowed: OVGNeighbor[] = []
    const disallowed: number[] = []
    for (const entry of neighbors) {
      const neighbor = ovg.vertices[entry.to]
      let inDirection = false
      if (direction.dx !== 0) {
        if (neighbor.y === pinVertex.y) {
          inDirection = direction.dx > 0 ? neighbor.x > pinVertex.x : neighbor.x < pinVertex.x
        }
      } else if (neighbor.x === pinVertex.x) {
        inDirection = direction.dy > 0 ? neighbor.y > pinVertex.y : neighbor.y < pinVertex.y
      }
      if (inDirection) {
        allowed.push(entry)
      } else {
        disallowed.push(entry.to)
      }
    }
    ovg.adjacency.set(binding.pinVertexId, allowed)
    for (const neighborId of disallowed) {
      const list = ovg.adjacency.get(neighborId)
      if (!list) continue
      ovg.adjacency.set(
        neighborId,
        list.filter((other) => other.to !== binding.pinVertexId),
      )
    }
  }
}

// ---------------------------------------------------------------------------
// A* with bend and overlap penalty (Layer 4, single-pair)
// ---------------------------------------------------------------------------

type AxisState = EdgeAxis | 'none'

interface SearchEntry {
  stateKey: string
  vertexId: number
  lastAxis: AxisState
  gCost: number
  fCost: number
}

interface SearchFrame {
  prevStateKey: string | null
  edgeIndex: number | null
}

function manhattanDistance(a: OVGVertex, b: OVGVertex): number {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y)
}

function stateKey(vertexId: number, axis: AxisState): string {
  return `${vertexId}|${axis}`
}

function pushHeap(heap: SearchEntry[], entry: SearchEntry): void {
  heap.push(entry)
  let index = heap.length - 1
  while (index > 0) {
    const parent = (index - 1) >>> 1
    if (heap[parent].fCost <= heap[index].fCost) {
      break
    }
    const tmp = heap[parent]
    heap[parent] = heap[index]
    heap[index] = tmp
    index = parent
  }
}

function popHeap(heap: SearchEntry[]): SearchEntry {
  const top = heap[0]
  const last = heap.pop()
  if (heap.length > 0 && last !== undefined) {
    heap[0] = last
    let index = 0
    const size = heap.length
    while (true) {
      const left = 2 * index + 1
      const right = 2 * index + 2
      let smallest = index
      if (left < size && heap[left].fCost < heap[smallest].fCost) smallest = left
      if (right < size && heap[right].fCost < heap[smallest].fCost) smallest = right
      if (smallest === index) break
      const tmp = heap[index]
      heap[index] = heap[smallest]
      heap[smallest] = tmp
      index = smallest
    }
  }
  return top
}

interface AStarResult {
  vertexPath: number[]
  edgeIndices: number[]
  totalCost: number
}

function findShortestOrthogonalPath(
  ovg: OVG,
  sourceIds: Iterable<number>,
  targetId: number,
  reusedEdgeIndices: Set<number>,
  obstructionPenalty: Map<number, number>,
): AStarResult | null {
  const heap: SearchEntry[] = []
  const bestCost = new Map<string, number>()
  const frameOf = new Map<string, SearchFrame>()
  const target = ovg.vertices[targetId]

  for (const source of sourceIds) {
    const key = stateKey(source, 'none')
    if (bestCost.has(key)) continue
    bestCost.set(key, 0)
    frameOf.set(key, { prevStateKey: null, edgeIndex: null })
    pushHeap(heap, {
      stateKey: key,
      vertexId: source,
      lastAxis: 'none',
      gCost: 0,
      fCost: manhattanDistance(ovg.vertices[source], target),
    })
  }

  while (heap.length > 0) {
    const current = popHeap(heap)
    const recorded = bestCost.get(current.stateKey)
    if (recorded !== undefined && recorded < current.gCost - EPSILON) {
      continue
    }

    if (current.vertexId === targetId) {
      const vertexPath: number[] = []
      const edgeIndices: number[] = []
      let key: string | null = current.stateKey
      while (key !== null) {
        const vertexId = parseInt(key.split('|')[0], 10)
        vertexPath.push(vertexId)
        const frame = frameOf.get(key)
        if (!frame) break
        if (frame.edgeIndex !== null) {
          edgeIndices.push(frame.edgeIndex)
        }
        key = frame.prevStateKey
      }
      vertexPath.reverse()
      edgeIndices.reverse()
      return {
        vertexPath,
        edgeIndices,
        totalCost: current.gCost,
      }
    }

    const neighbors = ovg.adjacency.get(current.vertexId)
    if (!neighbors) continue

    for (const neighbor of neighbors) {
      const edge = neighbor.edge
      const nextAxis: AxisState = edge.axis
      const isBend = current.lastAxis !== 'none' && current.lastAxis !== nextAxis
      const reuseBonus = reusedEdgeIndices.has(edge.index) ? TREE_REUSE_BONUS_FACTOR : 1
      const overlapCount = obstructionPenalty.get(edge.index) ?? 0
      const stepCost =
        edge.length * reuseBonus +
        (isBend ? BEND_PENALTY_COST : 0) +
        overlapCount * WIRE_OVERLAP_PENALTY_COST

      const nextG = current.gCost + stepCost
      const nextKey = stateKey(neighbor.to, nextAxis)
      const existing = bestCost.get(nextKey)
      if (existing !== undefined && existing <= nextG + EPSILON) continue
      bestCost.set(nextKey, nextG)
      frameOf.set(nextKey, { prevStateKey: current.stateKey, edgeIndex: edge.index })
      const h = manhattanDistance(ovg.vertices[neighbor.to], target)
      pushHeap(heap, {
        stateKey: nextKey,
        vertexId: neighbor.to,
        lastAxis: nextAxis,
        gCost: nextG,
        fCost: nextG + h,
      })
    }
  }

  return null
}

// ---------------------------------------------------------------------------
// Steiner-like tree growth (Layer 4, multi-pin)
// ---------------------------------------------------------------------------

interface SteinerTree {
  vertexIds: Set<number>
  edgeIndices: Set<number>
}

function growSteinerLikeTree(
  ovg: OVG,
  terminalVertexIds: number[],
  globalOverlap: Map<number, number>,
): SteinerTree | null {
  if (terminalVertexIds.length === 0) {
    return null
  }
  const tree: SteinerTree = {
    vertexIds: new Set<number>([terminalVertexIds[0]]),
    edgeIndices: new Set<number>(),
  }
  const remaining = new Set<number>()
  for (let i = 1; i < terminalVertexIds.length; i += 1) {
    if (terminalVertexIds[i] !== terminalVertexIds[0]) {
      remaining.add(terminalVertexIds[i])
    }
  }
  while (remaining.size > 0) {
    let bestResult: { target: number; path: AStarResult } | null = null
    for (const target of remaining) {
      const result = findShortestOrthogonalPath(
        ovg,
        tree.vertexIds,
        target,
        tree.edgeIndices,
        globalOverlap,
      )
      if (!result) continue
      if (bestResult === null || result.totalCost < bestResult.path.totalCost) {
        bestResult = { target, path: result }
      }
    }
    if (bestResult === null) {
      return null
    }
    for (const vertexId of bestResult.path.vertexPath) {
      tree.vertexIds.add(vertexId)
    }
    for (const edgeIndex of bestResult.path.edgeIndices) {
      tree.edgeIndices.add(edgeIndex)
    }
    remaining.delete(bestResult.target)
  }
  return tree
}

// ---------------------------------------------------------------------------
// Polyline extraction (Layer 6, tree → segments)
// ---------------------------------------------------------------------------

interface PolylineChain {
  axis: SchematicLayoutSegmentAxis
  points: SchematicLayoutPoint[]
}

function buildTreeAdjacency(
  ovg: OVG,
  edgeIndices: Set<number>,
): Map<number, Array<{ to: number; edge: OVGEdge }>> {
  const adjacency = new Map<number, Array<{ to: number; edge: OVGEdge }>>()
  for (const edgeIndex of edgeIndices) {
    const edge = ovg.edges[edgeIndex]
    let fromList = adjacency.get(edge.from)
    if (!fromList) {
      fromList = []
      adjacency.set(edge.from, fromList)
    }
    fromList.push({ to: edge.to, edge })
    let toList = adjacency.get(edge.to)
    if (!toList) {
      toList = []
      adjacency.set(edge.to, toList)
    }
    toList.push({ to: edge.from, edge })
  }
  return adjacency
}

function classifyChainAxis(points: SchematicLayoutPoint[]): SchematicLayoutSegmentAxis {
  let hasHorizontal = false
  let hasVertical = false
  for (let i = 1; i < points.length; i += 1) {
    if (points[i].x !== points[i - 1].x) hasHorizontal = true
    if (points[i].y !== points[i - 1].y) hasVertical = true
  }
  if (hasHorizontal && hasVertical) return 'mixed'
  if (hasHorizontal) return 'horizontal'
  if (hasVertical) return 'vertical'
  return 'mixed'
}

function extractPolylineChains(
  ovg: OVG,
  tree: SteinerTree,
): PolylineChain[] {
  const adjacency = buildTreeAdjacency(ovg, tree.edgeIndices)
  const consumedEdges = new Set<number>()
  const chains: PolylineChain[] = []

  // A "chain start" is any vertex that is NOT a degree-2 colinear passthrough.
  // Degree-2 colinear vertices are internal to a chain; all others anchor chain ends.
  function isColinearPassthrough(vertexId: number): boolean {
    const links = adjacency.get(vertexId)
    if (!links || links.length !== 2) return false
    return links[0].edge.axis === links[1].edge.axis
  }

  function walkChain(startVertexId: number, firstEdge: OVGEdge): PolylineChain {
    const points: SchematicLayoutPoint[] = []
    const startVertex = ovg.vertices[startVertexId]
    points.push({ x: startVertex.x, y: startVertex.y })

    let prevVertexId = startVertexId
    let currentEdge = firstEdge
    consumedEdges.add(currentEdge.index)
    let nextVertexId = currentEdge.from === startVertexId ? currentEdge.to : currentEdge.from
    let nextVertex = ovg.vertices[nextVertexId]
    points.push({ x: nextVertex.x, y: nextVertex.y })

    while (isColinearPassthrough(nextVertexId)) {
      const links = adjacency.get(nextVertexId)
      if (!links) break
      const forward = links.find((link) => link.edge.index !== currentEdge.index && !consumedEdges.has(link.edge.index))
      if (!forward) break
      consumedEdges.add(forward.edge.index)
      prevVertexId = nextVertexId
      currentEdge = forward.edge
      nextVertexId = forward.to
      nextVertex = ovg.vertices[nextVertexId]
      points.push({ x: nextVertex.x, y: nextVertex.y })
    }

    return {
      axis: classifyChainAxis(points),
      points,
    }
  }

  for (const vertexId of tree.vertexIds) {
    if (isColinearPassthrough(vertexId)) continue
    const links = adjacency.get(vertexId)
    if (!links) continue
    for (const link of links) {
      if (consumedEdges.has(link.edge.index)) continue
      chains.push(walkChain(vertexId, link.edge))
    }
  }

  return chains
}

// ---------------------------------------------------------------------------
// Nudging (Layer 5)
// ---------------------------------------------------------------------------

interface WireBundle {
  netId: string
  kind: SchematicLayoutSegmentKind
  chains: PolylineChain[]
}

interface SegmentLocator {
  bundleIndex: number
  chainIndex: number
  pointIndex: number
  axis: EdgeAxis
  constantCoord: number
  spanStart: number
  spanEnd: number
}

function gatherSegmentLocators(bundles: WireBundle[]): SegmentLocator[] {
  const locators: SegmentLocator[] = []
  for (let bundleIndex = 0; bundleIndex < bundles.length; bundleIndex += 1) {
    const bundle = bundles[bundleIndex]
    for (let chainIndex = 0; chainIndex < bundle.chains.length; chainIndex += 1) {
      const chain = bundle.chains[chainIndex]
      for (let pointIndex = 0; pointIndex + 1 < chain.points.length; pointIndex += 1) {
        const a = chain.points[pointIndex]
        const b = chain.points[pointIndex + 1]
        if (a.x === b.x && a.y === b.y) continue
        if (a.y === b.y) {
          locators.push({
            bundleIndex,
            chainIndex,
            pointIndex,
            axis: 'horizontal',
            constantCoord: a.y,
            spanStart: Math.min(a.x, b.x),
            spanEnd: Math.max(a.x, b.x),
          })
        } else if (a.x === b.x) {
          locators.push({
            bundleIndex,
            chainIndex,
            pointIndex,
            axis: 'vertical',
            constantCoord: a.x,
            spanStart: Math.min(a.y, b.y),
            spanEnd: Math.max(a.y, b.y),
          })
        }
      }
    }
  }
  return locators
}

function findOverlappingGroups(
  locators: SegmentLocator[],
  axis: EdgeAxis,
): SegmentLocator[][] {
  const filtered = locators.filter((s) => s.axis === axis)
  const byCoord = new Map<number, SegmentLocator[]>()
  for (const segment of filtered) {
    let bucket = byCoord.get(segment.constantCoord)
    if (!bucket) {
      bucket = []
      byCoord.set(segment.constantCoord, bucket)
    }
    bucket.push(segment)
  }
  const groups: SegmentLocator[][] = []
  for (const bucket of byCoord.values()) {
    if (bucket.length < 2) continue
    const sorted = [...bucket].sort((a, b) => a.spanStart - b.spanStart)
    let cluster: SegmentLocator[] = [sorted[0]]
    let clusterEnd = sorted[0].spanEnd
    for (let i = 1; i < sorted.length; i += 1) {
      const segment = sorted[i]
      if (segment.spanStart < clusterEnd - EPSILON) {
        cluster.push(segment)
        clusterEnd = Math.max(clusterEnd, segment.spanEnd)
      } else {
        if (cluster.length >= 2) groups.push(cluster)
        cluster = [segment]
        clusterEnd = segment.spanEnd
      }
    }
    if (cluster.length >= 2) groups.push(cluster)
  }
  return groups
}

/**
 * 1-D non-overlap resolver equivalent to a single-dimension VPSC feasibility
 * solve: given unit spans with preferred centers within `[lo, hi]`, return a
 * set of centers that (a) respect each span's size so intervals do not
 * overlap, (b) stay inside the bounds, and (c) stay close to the preferred
 * centers. A forward sweep followed by a backward clamp is sufficient: it
 * produces the unique feasible assignment that minimizes the lexicographic
 * deviation ordering, which matches the nudging need (push wires apart just
 * enough to break overlaps while staying near original routes).
 */
function resolveOneDimensionalOverlap(
  spans: Array<{ size: number; desiredCenter: number }>,
  lo: number,
  hi: number,
): { newCenters: number[] } {
  const count = spans.length
  if (count === 0) return { newCenters: [] }
  const indexed = spans.map((span, index) => ({
    index,
    size: span.size,
    desiredCenter: span.desiredCenter,
  }))
  indexed.sort((left, right) => left.desiredCenter - right.desiredCenter)
  const centers = new Array<number>(count)
  let prevRight = lo
  for (const item of indexed) {
    const minCenter = prevRight + item.size / 2
    const center = Math.max(item.desiredCenter, minCenter)
    centers[item.index] = center
    prevRight = center + item.size / 2
  }
  let nextLeft = hi
  for (let k = indexed.length - 1; k >= 0; k -= 1) {
    const item = indexed[k]
    const maxCenter = nextLeft - item.size / 2
    if (centers[item.index] > maxCenter) {
      centers[item.index] = maxCenter
    }
    nextLeft = centers[item.index] - item.size / 2
  }
  return { newCenters: centers }
}

function nudgeParallelSegments(bundles: WireBundle[]): void {
  // Horizontal conflicts (equal y, overlapping x) → shift y.
  // Vertical conflicts (equal x, overlapping y) → shift x.
  for (const axis of ['horizontal', 'vertical'] as const) {
    const locators = gatherSegmentLocators(bundles)
    const groups = findOverlappingGroups(locators, axis)
    for (const group of groups) {
      const spans = group.map((segment) => ({
        size: WIRE_MIN_GAP,
        desiredCenter: segment.constantCoord,
      }))
      const lowerBound = Math.min(...group.map((segment) => segment.constantCoord)) - WIRE_MIN_GAP * group.length
      const upperBound = Math.max(...group.map((segment) => segment.constantCoord)) + WIRE_MIN_GAP * group.length
      const { newCenters } = resolveOneDimensionalOverlap(spans, lowerBound, upperBound)
      for (let i = 0; i < group.length; i += 1) {
        const segment = group[i]
        const newCoord = newCenters[i]
        if (Math.abs(newCoord - segment.constantCoord) <= EPSILON) continue
        const chain = bundles[segment.bundleIndex].chains[segment.chainIndex]
        const a = chain.points[segment.pointIndex]
        const b = chain.points[segment.pointIndex + 1]
        if (axis === 'horizontal') {
          a.y = newCoord
          b.y = newCoord
        } else {
          a.x = newCoord
          b.x = newCoord
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Snap, segment emission, and stubs
// ---------------------------------------------------------------------------

function snapToGrid(value: number): number {
  return Math.round(value / GRID_SNAP) * GRID_SNAP
}

function snapChainPoints(chains: PolylineChain[]): void {
  for (const chain of chains) {
    for (const point of chain.points) {
      point.x = snapToGrid(point.x)
      point.y = snapToGrid(point.y)
    }
  }
}

function chainsToNetSegments(
  netId: string,
  chains: PolylineChain[],
  kind: SchematicLayoutSegmentKind,
): SchematicLayoutNetSegment[] {
  const segments: SchematicLayoutNetSegment[] = []
  for (let index = 0; index < chains.length; index += 1) {
    const chain = chains[index]
    const pruned = removeCollinearRedundancy(chain.points)
    if (pruned.length < 2) continue
    segments.push({
      key: `${netId}:${kind}:${index}`,
      kind,
      axis: classifyChainAxis(pruned),
      points: pruned,
    })
  }
  return segments
}

function removeCollinearRedundancy(points: SchematicLayoutPoint[]): SchematicLayoutPoint[] {
  if (points.length <= 2) return points.slice()
  const result: SchematicLayoutPoint[] = [points[0]]
  for (let i = 1; i < points.length - 1; i += 1) {
    const prev = result[result.length - 1]
    const current = points[i]
    const next = points[i + 1]
    const isColinearHoriz = prev.y === current.y && current.y === next.y
    const isColinearVert = prev.x === current.x && current.x === next.x
    if (isColinearHoriz || isColinearVert) {
      continue
    }
    result.push(current)
  }
  result.push(points[points.length - 1])
  // Drop exact duplicate consecutive points (can appear after snap).
  const deduped: SchematicLayoutPoint[] = [result[0]]
  for (let i = 1; i < result.length; i += 1) {
    const prev = deduped[deduped.length - 1]
    const current = result[i]
    if (prev.x === current.x && prev.y === current.y) continue
    deduped.push(current)
  }
  return deduped
}

function buildDanglingStubChain(pin: SchematicLayoutPin): PolylineChain {
  const direction = directionVector(pin.side)
  const tip = {
    x: pin.x + direction.dx * STUB_LENGTH,
    y: pin.y + direction.dy * STUB_LENGTH,
  }
  return {
    axis: direction.dx !== 0 ? 'horizontal' : 'vertical',
    points: [{ x: pin.x, y: pin.y }, tip],
  }
}

// ---------------------------------------------------------------------------
// Authoritative entry point
// ---------------------------------------------------------------------------

export function routeSchematicNets(
  semantic: SchematicSemanticModel,
  netRoles: SchematicNetRoleMap,
  pinsByNetId: Map<string, SchematicLayoutPin[]>,
  components: SchematicLayoutComponent[],
): Map<string, SchematicLayoutNetSegment[]> {
  const result = new Map<string, SchematicLayoutNetSegment[]>()
  if (components.length === 0) {
    return result
  }

  const obstacles = buildObstacles(components)
  const allPins: SchematicLayoutPin[] = []
  for (const pinList of pinsByNetId.values()) {
    for (const pin of pinList) {
      allPins.push(pin)
    }
  }
  if (allPins.length === 0) {
    return result
  }

  const { ovg, endpointsByPinId } = buildOrthogonalVisibilityGraph(obstacles, allPins)
  enforcePinDirectionConstraints(ovg, allPins, endpointsByPinId)

  const routedBundles: WireBundle[] = []
  const globalOverlap = new Map<number, number>()

  for (const semanticNet of semantic.nets) {
    const netId = semanticNet.net.id
    const role = netRoles.get(netId)
    if (!role) continue
    const pins = pinsByNetId.get(netId) ?? []

    if (role === 'dangling') {
      if (pins.length === 1) {
        const chain = buildDanglingStubChain(pins[0])
        routedBundles.push({ netId, kind: 'stub', chains: [chain] })
      }
      continue
    }

    if (pins.length < 2) continue

    const terminalIds: number[] = []
    for (const pin of pins) {
      const binding = endpointsByPinId.get(pin.id)
      if (binding) terminalIds.push(binding.pinVertexId)
    }
    if (terminalIds.length < 2) continue

    const tree = growSteinerLikeTree(ovg, terminalIds, globalOverlap)
    if (!tree || tree.edgeIndices.size === 0) {
      // Unreachable under current obstacle/port configuration. Skipping so the
      // net is visible-as-missing; this is by design — no fallback straight line
      // may hide a real routability problem.
      continue
    }
    for (const edgeIndex of tree.edgeIndices) {
      globalOverlap.set(edgeIndex, (globalOverlap.get(edgeIndex) ?? 0) + 1)
    }

    const chains = extractPolylineChains(ovg, tree)
    routedBundles.push({ netId, kind: 'route', chains })
  }

  nudgeParallelSegments(routedBundles)
  for (const bundle of routedBundles) {
    snapChainPoints(bundle.chains)
  }

  for (const bundle of routedBundles) {
    const segments = chainsToNetSegments(bundle.netId, bundle.chains, bundle.kind)
    if (segments.length > 0) {
      result.set(bundle.netId, segments)
    }
  }

  return result
}
