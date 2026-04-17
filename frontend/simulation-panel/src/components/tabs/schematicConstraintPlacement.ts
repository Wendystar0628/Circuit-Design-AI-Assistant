import { Layout } from 'webcola'
import type { Group as ColaGroup, InputNode as ColaInputNode, Link as ColaLink, Node as ColaNode } from 'webcola'

import type { SchematicLayoutOrientation, SchematicLayoutRect } from './schematicLayoutTypes'
import type {
  SchematicSemanticModel,
  SemanticScopeGroup,
} from './schematicSemanticModel'
import type { SchematicSkeleton } from './schematicSkeletonModel'
import { getOrientedSymbolDimensions, getSchematicSymbolDefinition } from './symbolRegistry'

export interface CoarseComponentPosition {
  componentId: string
  clusterId: string
  scopeGroupId: string
  box: SchematicLayoutRect
  symbolBox: SchematicLayoutRect
}

export interface CoarseGroupBounds {
  scopeGroupId: string
  bounds: SchematicLayoutRect
  depth: number
  label: string
  componentIds: string[]
}

export interface CoarseClusterBounds {
  clusterId: string
  bounds: SchematicLayoutRect
}

export interface SchematicCoarsePlacement {
  componentPositions: CoarseComponentPosition[]
  componentsById: Map<string, CoarseComponentPosition>
  scopeGroupBounds: CoarseGroupBounds[]
  scopeGroupBoundsById: Map<string, CoarseGroupBounds>
  clusterBounds: CoarseClusterBounds[]
  overallBounds: SchematicLayoutRect | null
}

const NODE_PADDING_X = 24
const NODE_PADDING_Y = 28
const SCOPE_GROUP_OUTER_PADDING_X = 24
const SCOPE_GROUP_OUTER_PADDING_Y = 32
const SCOPE_GROUP_INNER_PADDING = 28

const LINK_LENGTH_SIGNAL = 150
const LINK_LENGTH_BIAS = 130
const LINK_LENGTH_POWER = 110
const LINK_LENGTH_GROUND = 110
const LINK_LENGTH_DEFAULT = 140

const LINK_WEIGHT_SIGNAL = 1
const LINK_WEIGHT_RAIL = 1.4

const POWER_RAIL_SEED_Y = 60
const GROUND_RAIL_SEED_Y = 520
const MAIN_BAND_SEED_Y = 290
const RAIL_MIN_SEPARATION = 320

const RESIDUAL_ROW_HEIGHT = 60
const RESIDUAL_ROW_GAP = 10
const GRID_SNAP = 4

const ITERATIONS_UNCONSTRAINED = 30
const ITERATIONS_USER = 60
const ITERATIONS_ALL = 220

interface PlacementNode extends ColaNode {
  index: number
  width: number
  height: number
  componentId: string
  scopeGroupId: string
  clusterId: string
  symbolWidth: number
  symbolHeight: number
  paddingX: number
  paddingY: number
  rank: number
}

interface PlacementLink extends ColaLink<number> {
  category: string
}

interface AlignmentConstraint {
  type: 'alignment'
  axis: 'x' | 'y'
  offsets: Array<{ node: number; offset: number }>
}

interface SeparationConstraint {
  axis: 'x' | 'y'
  left: number
  right: number
  gap: number
  equality?: boolean
}

type PlacementConstraint = AlignmentConstraint | SeparationConstraint

function resolveLinkLengthForCategory(category: string): number {
  switch (category) {
    case 'power':
      return LINK_LENGTH_POWER
    case 'ground':
      return LINK_LENGTH_GROUND
    case 'bias':
      return LINK_LENGTH_BIAS
    case 'signal':
      return LINK_LENGTH_SIGNAL
    default:
      return LINK_LENGTH_DEFAULT
  }
}

function resolveLinkWeightForCategory(category: string): number {
  return category === 'power' || category === 'ground' ? LINK_WEIGHT_RAIL : LINK_WEIGHT_SIGNAL
}

function collectRailMembership(semantic: SchematicSemanticModel): {
  touchesPower: Set<string>
  touchesGround: Set<string>
} {
  const touchesPower = new Set<string>()
  const touchesGround = new Set<string>()
  for (const net of semantic.nets) {
    if (net.category === 'power') {
      for (const id of net.componentIds) {
        touchesPower.add(id)
      }
    } else if (net.category === 'ground') {
      for (const id of net.componentIds) {
        touchesGround.add(id)
      }
    }
  }
  return { touchesPower, touchesGround }
}

function seedYForComponent(componentId: string, touchesPower: Set<string>, touchesGround: Set<string>): number {
  const onPower = touchesPower.has(componentId)
  const onGround = touchesGround.has(componentId)
  if (onPower && !onGround) {
    return POWER_RAIL_SEED_Y
  }
  if (onGround && !onPower) {
    return GROUND_RAIL_SEED_Y
  }
  return MAIN_BAND_SEED_Y
}

function buildPlacementNodes(
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  orientationsById: Map<string, SchematicLayoutOrientation>,
  touchesPower: Set<string>,
  touchesGround: Set<string>,
): { nodes: PlacementNode[]; nodeByComponent: Map<string, PlacementNode> } {
  const nodes: PlacementNode[] = []
  const nodeByComponent = new Map<string, PlacementNode>()
  semantic.components.forEach((semanticComponent, index) => {
    const orientation = orientationsById.get(semanticComponent.component.id) ?? 'right'
    const definition = getSchematicSymbolDefinition(semanticComponent.component.symbol_kind)
    const oriented = getOrientedSymbolDimensions(definition.width, definition.height, orientation)
    const width = oriented.width + NODE_PADDING_X * 2
    const height = oriented.height + NODE_PADDING_Y * 2
    const skeletonEntry = skeleton.componentsById.get(semanticComponent.component.id)
    const rank = skeletonEntry?.mainPathRank ?? index
    const seedX = 120 + index * 90
    const seedY = seedYForComponent(semanticComponent.component.id, touchesPower, touchesGround)
    const node: PlacementNode = {
      index,
      componentId: semanticComponent.component.id,
      scopeGroupId: semanticComponent.scopeGroupId,
      clusterId: skeletonEntry?.clusterId ?? '',
      symbolWidth: oriented.width,
      symbolHeight: oriented.height,
      paddingX: NODE_PADDING_X,
      paddingY: NODE_PADDING_Y,
      rank,
      x: seedX,
      y: seedY,
      width,
      height,
    }
    nodes.push(node)
    nodeByComponent.set(node.componentId, node)
  })
  return { nodes, nodeByComponent }
}

function buildPlacementLinks(
  semantic: SchematicSemanticModel,
  nodeByComponent: Map<string, PlacementNode>,
): PlacementLink[] {
  const links: PlacementLink[] = []
  const seenPairs = new Set<string>()
  for (const semanticNet of semantic.nets) {
    if (semanticNet.category === 'dangling') {
      continue
    }
    if (semanticNet.componentIds.length < 2) {
      continue
    }
    const length = resolveLinkLengthForCategory(semanticNet.category)
    const weight = resolveLinkWeightForCategory(semanticNet.category)
    const hubNode = nodeByComponent.get(semanticNet.componentIds[0])
    if (!hubNode) {
      continue
    }
    for (let i = 1; i < semanticNet.componentIds.length; i += 1) {
      const otherNode = nodeByComponent.get(semanticNet.componentIds[i])
      if (!otherNode) {
        continue
      }
      const smaller = Math.min(hubNode.index, otherNode.index)
      const larger = Math.max(hubNode.index, otherNode.index)
      const pairKey = `${smaller}:${larger}`
      if (seenPairs.has(pairKey)) {
        continue
      }
      seenPairs.add(pairKey)
      links.push({
        source: hubNode.index,
        target: otherNode.index,
        length,
        weight,
        category: semanticNet.category,
      })
    }
  }
  return links
}

function buildRailConstraints(
  nodes: PlacementNode[],
  touchesPower: Set<string>,
  touchesGround: Set<string>,
): PlacementConstraint[] {
  const constraints: PlacementConstraint[] = []
  const powerOnlyIndices: number[] = []
  const groundOnlyIndices: number[] = []
  for (const node of nodes) {
    const onPower = touchesPower.has(node.componentId)
    const onGround = touchesGround.has(node.componentId)
    if (onPower && !onGround) {
      powerOnlyIndices.push(node.index)
    }
    if (onGround && !onPower) {
      groundOnlyIndices.push(node.index)
    }
  }
  if (powerOnlyIndices.length >= 2) {
    constraints.push({
      type: 'alignment',
      axis: 'y',
      offsets: powerOnlyIndices.map((idx) => ({ node: idx, offset: 0 })),
    })
  }
  if (groundOnlyIndices.length >= 2) {
    constraints.push({
      type: 'alignment',
      axis: 'y',
      offsets: groundOnlyIndices.map((idx) => ({ node: idx, offset: 0 })),
    })
  }
  if (powerOnlyIndices.length >= 1 && groundOnlyIndices.length >= 1) {
    constraints.push({
      axis: 'y',
      left: powerOnlyIndices[0],
      right: groundOnlyIndices[0],
      gap: RAIL_MIN_SEPARATION,
    })
  }
  return constraints
}

function buildColaGroupHierarchy(
  semantic: SchematicSemanticModel,
  nodes: PlacementNode[],
): ColaGroup[] {
  const nonRootScopes = semantic.scopeGroups.filter((scope) => scope.depth > 0)
  if (nonRootScopes.length === 0) {
    return []
  }
  const nodesByScope = new Map<string, PlacementNode[]>()
  for (const node of nodes) {
    const bucket = nodesByScope.get(node.scopeGroupId)
    if (bucket) {
      bucket.push(node)
    } else {
      nodesByScope.set(node.scopeGroupId, [node])
    }
  }
  const deepestFirst = [...nonRootScopes].sort((a, b) => b.depth - a.depth)
  const colaByScope = new Map<string, ColaGroup>()
  const orderedGroups: ColaGroup[] = []
  for (const scope of deepestFirst) {
    const leafNodes = nodesByScope.get(scope.id) ?? []
    const childGroups: ColaGroup[] = []
    for (const childId of scope.childGroupIds) {
      const childGroup = colaByScope.get(childId)
      if (childGroup) {
        childGroups.push(childGroup)
      }
    }
    if (leafNodes.length === 0 && childGroups.length === 0) {
      continue
    }
    const group: ColaGroup = {
      leaves: leafNodes,
      padding: SCOPE_GROUP_INNER_PADDING,
    }
    if (childGroups.length > 0) {
      group.groups = childGroups
    }
    colaByScope.set(scope.id, group)
    orderedGroups.push(group)
  }
  return orderedGroups
}

function runConstraintLayout(
  nodes: PlacementNode[],
  links: PlacementLink[],
  constraints: PlacementConstraint[],
  groups: ColaGroup[],
): void {
  if (nodes.length === 0) {
    return
  }
  const canvasSpan = Math.max(600, 140 * Math.sqrt(nodes.length))
  const layout = new Layout()
    .size([canvasSpan, canvasSpan])
    .nodes(nodes as ColaInputNode[])
    .links(links as unknown as ColaLink<ColaNode | number>[])
    .constraints(constraints)
    .groups(groups)
    .linkDistance(LINK_LENGTH_DEFAULT)
    .avoidOverlaps(true)
    .handleDisconnected(true)
  layout.start(ITERATIONS_UNCONSTRAINED, ITERATIONS_USER, ITERATIONS_ALL, 0, false)
}

function snapToGrid(value: number): number {
  return Math.round(value / GRID_SNAP) * GRID_SNAP
}

function marshalComponentPositions(nodes: PlacementNode[]): CoarseComponentPosition[] {
  const positions: CoarseComponentPosition[] = []
  for (const node of nodes) {
    const boxX = snapToGrid(node.x - node.width / 2)
    const boxY = snapToGrid(node.y - node.height / 2)
    positions.push({
      componentId: node.componentId,
      clusterId: node.clusterId,
      scopeGroupId: node.scopeGroupId,
      box: { x: boxX, y: boxY, width: node.width, height: node.height },
      symbolBox: {
        x: boxX + node.paddingX,
        y: boxY + node.paddingY,
        width: node.symbolWidth,
        height: node.symbolHeight,
      },
    })
  }
  return positions
}

function resolveResidualOverlaps(positions: CoarseComponentPosition[]): void {
  if (positions.length < 2) {
    return
  }
  const byRow = new Map<number, CoarseComponentPosition[]>()
  for (const position of positions) {
    const rowKey = Math.round(position.box.y / RESIDUAL_ROW_HEIGHT)
    const bucket = byRow.get(rowKey)
    if (bucket) {
      bucket.push(position)
    } else {
      byRow.set(rowKey, [position])
    }
  }
  for (const bucket of byRow.values()) {
    bucket.sort((left, right) => left.box.x - right.box.x)
    for (let index = 1; index < bucket.length; index += 1) {
      const previous = bucket[index - 1]
      const current = bucket[index]
      const previousRight = previous.box.x + previous.box.width
      const minStart = previousRight + RESIDUAL_ROW_GAP
      if (current.box.x < minStart) {
        const shift = minStart - current.box.x
        current.box.x += shift
        current.symbolBox.x += shift
      }
    }
  }
}

function unionRect(existing: SchematicLayoutRect | null, next: SchematicLayoutRect): SchematicLayoutRect {
  if (existing === null) {
    return { ...next }
  }
  const minX = Math.min(existing.x, next.x)
  const minY = Math.min(existing.y, next.y)
  const maxX = Math.max(existing.x + existing.width, next.x + next.width)
  const maxY = Math.max(existing.y + existing.height, next.y + next.height)
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

function computeScopeGroupBounds(
  positions: CoarseComponentPosition[],
  semantic: SchematicSemanticModel,
): Map<string, CoarseGroupBounds> {
  const map = new Map<string, CoarseGroupBounds>()
  for (const position of positions) {
    let scope: SemanticScopeGroup | undefined = semantic.scopeGroupsById.get(position.scopeGroupId)
    while (scope) {
      if (scope.depth === 0) {
        break
      }
      const existing = map.get(scope.id)
      if (existing) {
        existing.bounds = unionRect(existing.bounds, position.box)
        existing.componentIds.push(position.componentId)
      } else {
        map.set(scope.id, {
          scopeGroupId: scope.id,
          bounds: { ...position.box },
          depth: scope.depth,
          label: scope.label,
          componentIds: [position.componentId],
        })
      }
      scope = scope.parentId ? semantic.scopeGroupsById.get(scope.parentId) : undefined
    }
  }
  for (const entry of map.values()) {
    entry.bounds = {
      x: entry.bounds.x - SCOPE_GROUP_OUTER_PADDING_X,
      y: entry.bounds.y - SCOPE_GROUP_OUTER_PADDING_Y,
      width: entry.bounds.width + SCOPE_GROUP_OUTER_PADDING_X * 2,
      height: entry.bounds.height + SCOPE_GROUP_OUTER_PADDING_Y * 2,
    }
  }
  return map
}

function computeClusterBounds(
  positions: CoarseComponentPosition[],
  skeleton: SchematicSkeleton,
): CoarseClusterBounds[] {
  const boundsByCluster = new Map<string, SchematicLayoutRect>()
  for (const position of positions) {
    if (!position.clusterId) {
      continue
    }
    const existing = boundsByCluster.get(position.clusterId)
    boundsByCluster.set(
      position.clusterId,
      existing ? unionRect(existing, position.box) : { ...position.box },
    )
  }
  const result: CoarseClusterBounds[] = []
  for (const cluster of skeleton.clusters) {
    const bounds = boundsByCluster.get(cluster.id)
    if (bounds) {
      result.push({ clusterId: cluster.id, bounds })
    }
  }
  return result
}

export function computeSchematicCoarsePlacement(
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  orientationsById: Map<string, SchematicLayoutOrientation>,
): SchematicCoarsePlacement {
  if (semantic.components.length === 0) {
    return {
      componentPositions: [],
      componentsById: new Map(),
      scopeGroupBounds: [],
      scopeGroupBoundsById: new Map(),
      clusterBounds: [],
      overallBounds: null,
    }
  }

  const { touchesPower, touchesGround } = collectRailMembership(semantic)
  const { nodes, nodeByComponent } = buildPlacementNodes(
    semantic,
    skeleton,
    orientationsById,
    touchesPower,
    touchesGround,
  )
  const links = buildPlacementLinks(semantic, nodeByComponent)
  const constraints = buildRailConstraints(nodes, touchesPower, touchesGround)
  const groups = buildColaGroupHierarchy(semantic, nodes)

  runConstraintLayout(nodes, links, constraints, groups)

  const componentPositions = marshalComponentPositions(nodes)
  resolveResidualOverlaps(componentPositions)

  const componentsById = new Map<string, CoarseComponentPosition>()
  for (const position of componentPositions) {
    componentsById.set(position.componentId, position)
  }

  const scopeGroupBoundsById = computeScopeGroupBounds(componentPositions, semantic)
  const scopeGroupBounds = Array.from(scopeGroupBoundsById.values()).sort(
    (left, right) => left.depth - right.depth,
  )
  const clusterBounds = computeClusterBounds(componentPositions, skeleton)

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
    clusterBounds,
    overallBounds,
  }
}
