import type {
  SchematicSemanticModel,
  SemanticComponent,
  SemanticNet,
} from './schematicSemanticModel'
import type {
  SchematicSkeleton,
  SkeletonCluster,
  SkeletonComponent,
  SkeletonComponentRole,
  SkeletonMainPath,
  SkeletonNet,
  SkeletonNetRole,
} from './schematicSkeletonModel'

const SIGNAL_TRUNK_FANOUT_THRESHOLD = 3

function classifyBaseNetRole(net: SemanticNet): SkeletonNetRole {
  if (net.pinCount <= 1) {
    return 'dangling'
  }
  if (net.category === 'ground') {
    return 'ground_rail'
  }
  if (net.category === 'power') {
    return 'power_rail'
  }
  return 'branch'
}

function detectCrossesScopes(net: SemanticNet, semantic: SchematicSemanticModel): boolean {
  if (net.componentIds.length < 2) {
    return false
  }
  const scopes = new Set<string>()
  for (const componentId of net.componentIds) {
    const component = semantic.componentsById.get(componentId)
    if (!component) {
      continue
    }
    scopes.add(component.scopeGroupId)
    if (scopes.size >= 2) {
      return true
    }
  }
  return false
}

function computeNetImportance(net: SemanticNet, crossesScopes: boolean): number {
  let score = net.pinCount
  if (crossesScopes) {
    score += 2
  }
  if (net.category === 'bias') {
    score += 1
  }
  return score
}

function isDirectionalComponent(component: SemanticComponent): boolean {
  return (
    component.role === 'active' ||
    component.role === 'amplifier' ||
    component.role === 'controlled_source' ||
    component.role === 'block'
  )
}

function classifyMainPathCandidate(component: SemanticComponent, nonRailDegree: number): SkeletonComponentRole {
  if (component.isolated) {
    return 'isolated'
  }
  if (component.role === 'ground') {
    return 'ground_rail'
  }
  if (component.role === 'supply') {
    return 'supply_rail'
  }
  if (isDirectionalComponent(component)) {
    return 'main_path'
  }
  if (nonRailDegree >= 2) {
    return 'main_path'
  }
  return 'branch'
}

function orderMainPath(candidates: SemanticComponent[]): string[] {
  return [...candidates]
    .sort((left, right) => {
      const priorityDelta = left.placementPriority - right.placementPriority
      if (priorityDelta !== 0) {
        return priorityDelta
      }
      const leftName = left.component.instance_name || left.component.display_name || left.component.id
      const rightName = right.component.instance_name || right.component.display_name || right.component.id
      const nameDelta = leftName.localeCompare(rightName)
      if (nameDelta !== 0) {
        return nameDelta
      }
      return left.component.id.localeCompare(right.component.id)
    })
    .map((component) => component.component.id)
}

export function analyzeSchematicSkeleton(semantic: SchematicSemanticModel): SchematicSkeleton {
  const netsById = new Map<string, SkeletonNet>()
  const nonRailDegree = new Map<string, number>()

  for (const semanticNet of semantic.nets) {
    const crossesScopes = detectCrossesScopes(semanticNet, semantic)
    let role = classifyBaseNetRole(semanticNet)
    if (role === 'branch' && (semanticNet.pinCount >= SIGNAL_TRUNK_FANOUT_THRESHOLD || crossesScopes)) {
      role = 'signal_trunk'
    }
    netsById.set(semanticNet.net.id, {
      netId: semanticNet.net.id,
      clusterId: semanticNet.connectedComponentId,
      role,
      fanout: semanticNet.pinCount,
      crossesScopes,
      importance: computeNetImportance(semanticNet, crossesScopes),
    })
    if (role === 'signal_trunk' || role === 'branch') {
      for (const componentId of semanticNet.componentIds) {
        nonRailDegree.set(componentId, (nonRailDegree.get(componentId) ?? 0) + 1)
      }
    }
  }

  const nets = Array.from(netsById.values())

  const clusters: SkeletonCluster[] = []
  const clustersById = new Map<string, SkeletonCluster>()
  const componentsById = new Map<string, SkeletonComponent>()

  for (const semanticCluster of semantic.connectedComponents) {
    const clusterComponents = semanticCluster.componentIds
      .map((id) => semantic.componentsById.get(id))
      .filter((item): item is SemanticComponent => item !== undefined)

    const mainPathCandidates: SemanticComponent[] = []
    const railComponentIds: string[] = []
    const branchComponentIds: string[] = []
    const isolatedComponentIds: string[] = []
    const componentClassification = new Map<string, SkeletonComponentRole>()

    for (const component of clusterComponents) {
      const degree = nonRailDegree.get(component.component.id) ?? 0
      const classification = classifyMainPathCandidate(component, degree)
      componentClassification.set(component.component.id, classification)
      if (classification === 'main_path') {
        mainPathCandidates.push(component)
      } else if (classification === 'supply_rail' || classification === 'ground_rail') {
        railComponentIds.push(component.component.id)
      } else if (classification === 'branch') {
        branchComponentIds.push(component.component.id)
      } else {
        isolatedComponentIds.push(component.component.id)
      }
    }

    const mainPath: SkeletonMainPath = {
      componentIds: orderMainPath(mainPathCandidates),
    }
    const mainPathRankById = new Map<string, number>()
    mainPath.componentIds.forEach((id, index) => {
      mainPathRankById.set(id, index)
    })

    const trunkNetIds: string[] = []
    const branchNetIds: string[] = []
    const railNetIds: string[] = []
    for (const skeletonNet of nets) {
      if (skeletonNet.clusterId !== semanticCluster.id) {
        continue
      }
      if (skeletonNet.role === 'ground_rail' || skeletonNet.role === 'power_rail') {
        railNetIds.push(skeletonNet.netId)
      } else if (skeletonNet.role === 'signal_trunk') {
        trunkNetIds.push(skeletonNet.netId)
      } else if (skeletonNet.role === 'branch') {
        branchNetIds.push(skeletonNet.netId)
      }
    }

    const cluster: SkeletonCluster = {
      id: semanticCluster.id,
      readingDirection: 'left_to_right',
      mainPath,
      railComponentIds,
      branchComponentIds,
      isolatedComponentIds,
      trunkNetIds,
      branchNetIds,
      railNetIds,
    }
    clusters.push(cluster)
    clustersById.set(cluster.id, cluster)

    for (const component of clusterComponents) {
      const role = componentClassification.get(component.component.id) ?? 'branch'
      const skeletonComponent: SkeletonComponent = {
        componentId: component.component.id,
        clusterId: cluster.id,
        role,
        mainPathRank: mainPathRankById.get(component.component.id) ?? -1,
        nonRailDegree: nonRailDegree.get(component.component.id) ?? 0,
      }
      componentsById.set(component.component.id, skeletonComponent)
    }
  }

  const components = Array.from(componentsById.values())

  return {
    clusters,
    clustersById,
    nets,
    netsById,
    components,
    componentsById,
  }
}
