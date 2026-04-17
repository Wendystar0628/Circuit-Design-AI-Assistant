import type { SchematicSemanticModel, SemanticComponent, SemanticNet } from './schematicSemanticModel'

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

/**
 * Identify "local feedback" nets: a net that touches two or more distinct
 * pins of the same active amplifier component (typically an op-amp's output
 * fed back to one of its inputs via an RC network). Such nets should route
 * as a short U-turn next to the amplifier rather than flowing like a normal
 * left-to-right signal edge, so the ELK layout pipeline gives them higher
 * shortness / straightness priority and the feedback components converge
 * next to their amplifier rather than being scattered across the canvas.
 */
export function identifySchematicFeedbackNets(semantic: SchematicSemanticModel): Set<string> {
  const feedbackNetIds = new Set<string>()
  for (const net of semantic.nets) {
    if (net.pinCount < 2) continue
    const pinsPerComponent = new Map<string, number>()
    for (const connection of net.net.connections) {
      const count = pinsPerComponent.get(connection.component_id) ?? 0
      pinsPerComponent.set(connection.component_id, count + 1)
    }
    for (const [componentId, count] of pinsPerComponent) {
      if (count < 2) continue
      const component = semantic.componentsById.get(componentId)
      if (!component) continue
      if (isFeedbackAnchorComponent(component)) {
        feedbackNetIds.add(net.net.id)
        break
      }
    }
  }
  return feedbackNetIds
}

function isFeedbackAnchorComponent(component: SemanticComponent): boolean {
  // Only active amplifying components act as feedback anchors; a passive
  // component with two pins on the same net is simply shorted, not a
  // feedback loop.
  return component.role === 'amplifier' || component.role === 'active' || component.role === 'controlled_source'
}
