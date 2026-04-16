import type { SchematicLayoutOrientation, SchematicLayoutRect } from './schematicLayoutTypes'
import type { SchematicSemanticModel, SemanticComponent, SemanticScopeGroup } from './schematicSemanticModel'
import type { SchematicSkeleton, SkeletonCluster } from './schematicSkeletonModel'
import { getOrientedSymbolDimensions, getSchematicSymbolDefinition } from './symbolRegistry'

const H_STEP = 176
const V_STEP = 132
const SUPPLY_LANE_OFFSET = 0
const MAIN_LANE_OFFSET = V_STEP * 1.4
const GROUND_LANE_OFFSET = V_STEP * 2.8
const BRANCH_LANE_OFFSET = V_STEP * 4.0
const ISOLATED_LANE_OFFSET = V_STEP * 5.4
const CLUSTER_GAP_Y = V_STEP * 1.6
const NODE_PADDING_X = 24
const NODE_PADDING_Y = 28
const SCOPE_GROUP_PADDING_X = 24
const SCOPE_GROUP_PADDING_Y = 32

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

function makeBox(width: number, height: number, x: number, y: number): SchematicLayoutRect {
  return { x, y, width, height }
}

function unionBounds(existing: SchematicLayoutRect | null, next: SchematicLayoutRect): SchematicLayoutRect {
  if (existing === null) {
    return { ...next }
  }
  const minX = Math.min(existing.x, next.x)
  const minY = Math.min(existing.y, next.y)
  const maxX = Math.max(existing.x + existing.width, next.x + next.width)
  const maxY = Math.max(existing.y + existing.height, next.y + next.height)
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

function resolveOrientedSymbolSize(
  semanticComponent: SemanticComponent,
  orientation: SchematicLayoutOrientation,
): { symbolWidth: number; symbolHeight: number } {
  const definition = getSchematicSymbolDefinition(semanticComponent.component.symbol_kind)
  const oriented = getOrientedSymbolDimensions(definition.width, definition.height, orientation)
  return { symbolWidth: oriented.width, symbolHeight: oriented.height }
}

function buildComponentPosition(
  semanticComponent: SemanticComponent,
  orientation: SchematicLayoutOrientation,
  clusterId: string,
  x: number,
  y: number,
): CoarseComponentPosition {
  const { symbolWidth, symbolHeight } = resolveOrientedSymbolSize(semanticComponent, orientation)
  const width = symbolWidth + NODE_PADDING_X * 2
  const height = symbolHeight + NODE_PADDING_Y * 2
  return {
    componentId: semanticComponent.component.id,
    clusterId,
    scopeGroupId: semanticComponent.scopeGroupId,
    box: makeBox(width, height, x, y),
    symbolBox: makeBox(symbolWidth, symbolHeight, x + NODE_PADDING_X, y + NODE_PADDING_Y),
  }
}

function findMainPathNeighborX(
  componentId: string,
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  mainPathCenterX: Map<string, number>,
): number | null {
  for (const semanticNet of semantic.nets) {
    if (!semanticNet.componentIds.includes(componentId)) {
      continue
    }
    const skeletonNet = skeleton.netsById.get(semanticNet.net.id)
    if (!skeletonNet) {
      continue
    }
    if (skeletonNet.role === 'ground_rail' || skeletonNet.role === 'power_rail' || skeletonNet.role === 'dangling') {
      continue
    }
    for (const otherId of semanticNet.componentIds) {
      if (otherId === componentId) {
        continue
      }
      const centerX = mainPathCenterX.get(otherId)
      if (centerX !== undefined) {
        return centerX
      }
    }
  }
  return null
}

function placeCluster(
  cluster: SkeletonCluster,
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  orientationsById: Map<string, SchematicLayoutOrientation>,
  topY: number,
  sink: CoarseComponentPosition[],
): number {
  const mainRowY = topY + MAIN_LANE_OFFSET
  const supplyRowY = topY + SUPPLY_LANE_OFFSET
  const groundRowY = topY + GROUND_LANE_OFFSET
  const branchRowY = topY + BRANCH_LANE_OFFSET
  const isolatedRowY = topY + ISOLATED_LANE_OFFSET

  const mainPathCenterX = new Map<string, number>()
  const clusterComponents: CoarseComponentPosition[] = []

  function orientationFor(componentId: string): SchematicLayoutOrientation {
    return orientationsById.get(componentId) ?? 'right'
  }

  let mainCursor = 0
  for (const componentId of cluster.mainPath.componentIds) {
    const semanticComponent = semantic.componentsById.get(componentId)
    if (!semanticComponent) {
      continue
    }
    const position = buildComponentPosition(semanticComponent, orientationFor(componentId), cluster.id, mainCursor, mainRowY)
    mainPathCenterX.set(componentId, position.box.x + position.box.width / 2)
    clusterComponents.push(position)
    mainCursor = position.box.x + position.box.width + (H_STEP - position.box.width)
  }

  let supplyCursor = 0
  let groundCursor = 0
  for (const componentId of cluster.railComponentIds) {
    const semanticComponent = semantic.componentsById.get(componentId)
    if (!semanticComponent) {
      continue
    }
    const orientation = orientationFor(componentId)
    const neighborX = findMainPathNeighborX(componentId, semantic, skeleton, mainPathCenterX)
    const isSupply = semanticComponent.role === 'supply'
    const laneY = isSupply ? supplyRowY : groundRowY
    const fallbackCursor = isSupply ? supplyCursor : groundCursor
    const { symbolWidth } = resolveOrientedSymbolSize(semanticComponent, orientation)
    const width = symbolWidth + NODE_PADDING_X * 2
    const x = neighborX !== null ? neighborX - width / 2 : fallbackCursor
    const position = buildComponentPosition(semanticComponent, orientation, cluster.id, x, laneY)
    clusterComponents.push(position)
    if (neighborX === null) {
      const nextCursor = position.box.x + position.box.width + (H_STEP - position.box.width)
      if (isSupply) {
        supplyCursor = nextCursor
      } else {
        groundCursor = nextCursor
      }
    }
  }

  let branchCursor = 0
  for (const componentId of cluster.branchComponentIds) {
    const semanticComponent = semantic.componentsById.get(componentId)
    if (!semanticComponent) {
      continue
    }
    const orientation = orientationFor(componentId)
    const neighborX = findMainPathNeighborX(componentId, semantic, skeleton, mainPathCenterX)
    const { symbolWidth } = resolveOrientedSymbolSize(semanticComponent, orientation)
    const width = symbolWidth + NODE_PADDING_X * 2
    const x = neighborX !== null ? neighborX - width / 2 : branchCursor
    const position = buildComponentPosition(semanticComponent, orientation, cluster.id, x, branchRowY)
    clusterComponents.push(position)
    if (neighborX === null) {
      branchCursor = position.box.x + position.box.width + (H_STEP - position.box.width)
    }
  }

  let isolatedCursor = 0
  for (const componentId of cluster.isolatedComponentIds) {
    const semanticComponent = semantic.componentsById.get(componentId)
    if (!semanticComponent) {
      continue
    }
    const position = buildComponentPosition(semanticComponent, orientationFor(componentId), cluster.id, isolatedCursor, isolatedRowY)
    clusterComponents.push(position)
    isolatedCursor = position.box.x + position.box.width + (H_STEP - position.box.width)
  }

  resolveLocalOverlaps(clusterComponents)

  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const position of clusterComponents) {
    minX = Math.min(minX, position.box.x)
    minY = Math.min(minY, position.box.y)
    maxX = Math.max(maxX, position.box.x + position.box.width)
    maxY = Math.max(maxY, position.box.y + position.box.height)
    sink.push(position)
  }

  if (!isFinite(minX)) {
    return topY
  }
  return maxY + CLUSTER_GAP_Y
}

function resolveLocalOverlaps(positions: CoarseComponentPosition[]): void {
  const lanes = new Map<number, CoarseComponentPosition[]>()
  for (const position of positions) {
    const laneKey = Math.round(position.box.y)
    const bucket = lanes.get(laneKey)
    if (bucket) {
      bucket.push(position)
    } else {
      lanes.set(laneKey, [position])
    }
  }
  for (const bucket of lanes.values()) {
    bucket.sort((left, right) => left.box.x - right.box.x)
    for (let index = 1; index < bucket.length; index += 1) {
      const prev = bucket[index - 1]
      const current = bucket[index]
      const prevRight = prev.box.x + prev.box.width
      if (current.box.x < prevRight + 8) {
        const shift = prevRight + 8 - current.box.x
        current.box.x += shift
        current.symbolBox.x += shift
      }
    }
  }
}

function computeScopeGroupBounds(
  positions: CoarseComponentPosition[],
  semantic: SchematicSemanticModel,
): Map<string, CoarseGroupBounds> {
  const map = new Map<string, CoarseGroupBounds>()
  for (const position of positions) {
    let scopeGroup: SemanticScopeGroup | undefined = semantic.scopeGroupsById.get(position.scopeGroupId)
    while (scopeGroup) {
      if (scopeGroup.depth === 0) {
        break
      }
      const existing = map.get(scopeGroup.id)
      if (existing) {
        existing.bounds = unionBounds(existing.bounds, position.box)
        existing.componentIds.push(position.componentId)
      } else {
        map.set(scopeGroup.id, {
          scopeGroupId: scopeGroup.id,
          bounds: { ...position.box },
          depth: scopeGroup.depth,
          label: scopeGroup.label,
          componentIds: [position.componentId],
        })
      }
      scopeGroup = scopeGroup.parentId ? semantic.scopeGroupsById.get(scopeGroup.parentId) : undefined
    }
  }
  for (const entry of map.values()) {
    entry.bounds = {
      x: entry.bounds.x - SCOPE_GROUP_PADDING_X,
      y: entry.bounds.y - SCOPE_GROUP_PADDING_Y,
      width: entry.bounds.width + SCOPE_GROUP_PADDING_X * 2,
      height: entry.bounds.height + SCOPE_GROUP_PADDING_Y * 2,
    }
  }
  return map
}

export function computeSchematicCoarsePlacement(
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  orientationsById: Map<string, SchematicLayoutOrientation>,
): SchematicCoarsePlacement {
  const componentPositions: CoarseComponentPosition[] = []
  const clusterBounds: CoarseClusterBounds[] = []

  let currentTop = 0
  for (const cluster of skeleton.clusters) {
    const clusterStart = componentPositions.length
    const nextTop = placeCluster(cluster, semantic, skeleton, orientationsById, currentTop, componentPositions)
    const placed = componentPositions.slice(clusterStart)
    if (placed.length > 0) {
      let minX = Infinity
      let minY = Infinity
      let maxX = -Infinity
      let maxY = -Infinity
      for (const position of placed) {
        minX = Math.min(minX, position.box.x)
        minY = Math.min(minY, position.box.y)
        maxX = Math.max(maxX, position.box.x + position.box.width)
        maxY = Math.max(maxY, position.box.y + position.box.height)
      }
      clusterBounds.push({
        clusterId: cluster.id,
        bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
      })
    }
    currentTop = nextTop
  }

  const componentsById = new Map<string, CoarseComponentPosition>()
  for (const position of componentPositions) {
    componentsById.set(position.componentId, position)
  }

  const scopeGroupBoundsById = computeScopeGroupBounds(componentPositions, semantic)
  const scopeGroupBounds = Array.from(scopeGroupBoundsById.values()).sort((left, right) => left.depth - right.depth)

  let overallBounds: SchematicLayoutRect | null = null
  for (const position of componentPositions) {
    overallBounds = unionBounds(overallBounds, position.box)
  }
  for (const entry of scopeGroupBounds) {
    overallBounds = unionBounds(overallBounds, entry.bounds)
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
