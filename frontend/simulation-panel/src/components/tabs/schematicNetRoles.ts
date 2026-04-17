import type { SchematicSemanticModel, SemanticNet } from './schematicSemanticModel'

/**
 * Net role classification used by the orthogonal router to select the
 * appropriate routing strategy for each net. Classification is a pure function
 * of the semantic model; it does not carry any placement or geometric state.
 *
 * - `ground_rail`  : shared ground node (category === 'ground')
 * - `power_rail`   : shared supply node (category === 'power')
 * - `signal_trunk` : high-fanout signal net (>= 3 pins)
 * - `branch`       : ordinary 2-pin signal/bias net
 * - `dangling`     : net reaching at most one pin (no routing required)
 */
export type SchematicNetRole =
  | 'ground_rail'
  | 'power_rail'
  | 'signal_trunk'
  | 'branch'
  | 'dangling'

export type SchematicNetRoleMap = ReadonlyMap<string, SchematicNetRole>

const SIGNAL_TRUNK_FANOUT_THRESHOLD = 3

export function classifySchematicNetRoles(semantic: SchematicSemanticModel): Map<string, SchematicNetRole> {
  const roles = new Map<string, SchematicNetRole>()
  for (const net of semantic.nets) {
    roles.set(net.net.id, classifyOneNet(net))
  }
  return roles
}

function classifyOneNet(net: SemanticNet): SchematicNetRole {
  if (net.pinCount <= 1) {
    return 'dangling'
  }
  if (net.category === 'ground') {
    return 'ground_rail'
  }
  if (net.category === 'power') {
    return 'power_rail'
  }
  if (net.pinCount >= SIGNAL_TRUNK_FANOUT_THRESHOLD) {
    return 'signal_trunk'
  }
  return 'branch'
}
