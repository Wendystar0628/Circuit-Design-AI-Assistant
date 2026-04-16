export type SkeletonReadingDirection =
  | 'left_to_right'
  | 'right_to_left'
  | 'top_to_bottom'
  | 'bottom_to_top'

export type SkeletonNetRole =
  | 'ground_rail'
  | 'power_rail'
  | 'signal_trunk'
  | 'branch'
  | 'dangling'

export type SkeletonComponentRole =
  | 'main_path'
  | 'supply_rail'
  | 'ground_rail'
  | 'branch'
  | 'isolated'

export interface SkeletonNet {
  netId: string
  clusterId: string
  role: SkeletonNetRole
  fanout: number
  crossesScopes: boolean
  importance: number
}

export interface SkeletonComponent {
  componentId: string
  clusterId: string
  role: SkeletonComponentRole
  mainPathRank: number
  nonRailDegree: number
}

export interface SkeletonMainPath {
  componentIds: string[]
}

export interface SkeletonCluster {
  id: string
  readingDirection: SkeletonReadingDirection
  mainPath: SkeletonMainPath
  railComponentIds: string[]
  branchComponentIds: string[]
  isolatedComponentIds: string[]
  trunkNetIds: string[]
  branchNetIds: string[]
  railNetIds: string[]
}

export interface SchematicSkeleton {
  clusters: SkeletonCluster[]
  clustersById: Map<string, SkeletonCluster>
  nets: SkeletonNet[]
  netsById: Map<string, SkeletonNet>
  components: SkeletonComponent[]
  componentsById: Map<string, SkeletonComponent>
}
