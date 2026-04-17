import type { SchematicComponentState, SchematicNetState, SchematicPinState } from '../../types/state'

export const ROOT_SCOPE_GROUP_ID = 'scope:'

export type SemanticComponentRole =
  | 'ground'
  | 'supply'
  | 'passive'
  | 'active'
  | 'amplifier'
  | 'controlled_source'
  | 'block'
  | 'unknown'

export type SemanticPinRole =
  | 'input'
  | 'output'
  | 'power'
  | 'ground'
  | 'passive'
  | 'unknown'

export type SemanticPinHintedSide = 'left' | 'right' | 'top' | 'bottom' | null

export type SemanticNetCategory =
  | 'ground'
  | 'power'
  | 'bias'
  | 'signal'
  | 'dangling'

export interface SemanticPin {
  pin: SchematicPinState
  index: number
  role: SemanticPinRole
  hintedSide: SemanticPinHintedSide
}

export interface SemanticComponent {
  component: SchematicComponentState
  role: SemanticComponentRole
  pins: SemanticPin[]
  scopeGroupId: string
  placementPriority: number
}

export interface SemanticNet {
  net: SchematicNetState
  category: SemanticNetCategory
  pinCount: number
  componentIds: string[]
  scopeGroupId: string
}

export interface SemanticScopeGroup {
  id: string
  path: string[]
  label: string
  depth: number
  parentId: string | null
  childGroupIds: string[]
  componentIds: string[]
}

export interface SchematicSemanticModel {
  components: SemanticComponent[]
  componentsById: Map<string, SemanticComponent>
  nets: SemanticNet[]
  netsById: Map<string, SemanticNet>
  scopeGroups: SemanticScopeGroup[]
  scopeGroupsById: Map<string, SemanticScopeGroup>
  rootScopeGroupId: string
}
