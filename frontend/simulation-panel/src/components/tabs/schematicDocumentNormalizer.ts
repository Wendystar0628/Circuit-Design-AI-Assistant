import type {
  SchematicComponentState,
  SchematicDocumentState,
  SchematicNetState,
  SchematicPinState,
  SchematicSubcircuitState,
} from '../../types/state'
import {
  ROOT_SCOPE_GROUP_ID,
  type SchematicSemanticModel,
  type SemanticComponent,
  type SemanticComponentRole,
  type SemanticNet,
  type SemanticNetCategory,
  type SemanticPin,
  type SemanticPinHintedSide,
  type SemanticPinRole,
  type SemanticScopeGroup,
} from './schematicSemanticModel'
import {
  PRIMITIVE_SYMBOL_KIND,
  classifySchematicPrimitiveSubckts,
  type SchematicPrimitiveSubcktInfo,
  type SchematicPrimitiveSubcktMap,
} from './schematicSubcktClassifier'

const POWER_NET_PATTERN = /^(vcc|vdd|vee|vss|vbb|vaa|vdda|vssa|vbus|vsupply|v_supply|v_rail|v\+|v-)$/
const GROUND_NET_PATTERN = /^(0|gnd|agnd|dgnd|ground)$/
const BIAS_NET_PATTERN = /^(vbias|vref|vcm|bias|ref|v_bias|v_ref|v_cm)/

function normalizeNetName(name: string): string {
  return name.trim().toLowerCase()
}

function scopePathKey(path: string[]): string {
  return path.join(' / ')
}

function scopeGroupId(path: string[]): string {
  return `${ROOT_SCOPE_GROUP_ID}${scopePathKey(path)}`
}

function resolveComponentRole(component: SchematicComponentState): SemanticComponentRole {
  switch (component.symbol_kind) {
    case 'ground':
      return 'ground'
    case 'voltage_source':
    case 'current_source':
      return 'supply'
    case 'resistor':
    case 'capacitor':
    case 'inductor':
    case 'diode':
      return 'passive'
    case 'bjt':
    case 'mos':
      return 'active'
    case 'opamp':
      return 'amplifier'
    case 'controlled_source':
      return 'controlled_source'
    case 'subckt_block':
      return 'block'
    default:
      return 'unknown'
  }
}

function resolvePinRole(pin: SchematicPinState): SemanticPinRole {
  const normalized = pin.role.trim().toLowerCase()
  if (normalized === 'input' || normalized === 'in') {
    return 'input'
  }
  if (normalized === 'output' || normalized === 'out') {
    return 'output'
  }
  if (normalized === 'power' || normalized === 'vdd' || normalized === 'vcc') {
    return 'power'
  }
  if (normalized === 'ground' || normalized === 'gnd' || normalized === 'vss') {
    return 'ground'
  }
  if (
    normalized === 'passive' ||
    normalized === 'anode' ||
    normalized === 'cathode' ||
    normalized === 'plus' ||
    normalized === 'minus' ||
    normalized === '+' ||
    normalized === '-'
  ) {
    return 'passive'
  }
  return 'unknown'
}

function normalizeHintedSide(value: string | undefined): SemanticPinHintedSide {
  if (value === 'left' || value === 'right' || value === 'top' || value === 'bottom') {
    return value
  }
  return null
}

function buildSemanticPins(component: SchematicComponentState): SemanticPin[] {
  return component.pins.map((pin, index) => ({
    pin,
    index,
    role: resolvePinRole(pin),
    hintedSide: normalizeHintedSide(component.port_side_hints[pin.name]),
  }))
}

function resolvePlacementPriority(role: SemanticComponentRole, pins: SemanticPin[]): number {
  if (role === 'ground') {
    return 90
  }
  if (role === 'supply') {
    return 10
  }
  const hasInput = pins.some((pin) => pin.role === 'input')
  const hasOutput = pins.some((pin) => pin.role === 'output')
  if (hasInput && !hasOutput) {
    return 20
  }
  if (hasOutput && !hasInput) {
    return 80
  }
  return 50
}

function buildSubcircuitLabelMap(subcircuits: SchematicSubcircuitState[]): Map<string, string> {
  const labels = new Map<string, string>()
  for (const item of subcircuits) {
    const path = [...item.scope_path, item.name]
    labels.set(scopePathKey(path), item.name)
  }
  return labels
}

function resolveScopeGroupLabel(path: string[], labelMap: Map<string, string>): string {
  if (path.length === 0) {
    return ''
  }
  const candidate = labelMap.get(scopePathKey(path))
  if (candidate) {
    return candidate
  }
  return path[path.length - 1]
}

function ensureScopeGroupChain(
  scopeGroupsById: Map<string, SemanticScopeGroup>,
  path: string[],
  labelMap: Map<string, string>,
): SemanticScopeGroup {
  const id = scopeGroupId(path)
  const existing = scopeGroupsById.get(id)
  if (existing) {
    return existing
  }
  const group: SemanticScopeGroup = {
    id,
    path,
    label: resolveScopeGroupLabel(path, labelMap),
    depth: path.length,
    parentId: null,
    childGroupIds: [],
    componentIds: [],
  }
  scopeGroupsById.set(id, group)
  if (path.length > 0) {
    const parent = ensureScopeGroupChain(scopeGroupsById, path.slice(0, -1), labelMap)
    group.parentId = parent.id
    parent.childGroupIds.push(id)
  }
  return group
}

function resolveNetCategory(net: SchematicNetState, pinCount: number): SemanticNetCategory {
  if (pinCount <= 1) {
    return 'dangling'
  }
  const normalized = normalizeNetName(net.name)
  if (GROUND_NET_PATTERN.test(normalized)) {
    return 'ground'
  }
  if (POWER_NET_PATTERN.test(normalized)) {
    return 'power'
  }
  if (BIAS_NET_PATTERN.test(normalized)) {
    return 'bias'
  }
  return 'signal'
}

function sortSemanticComponents(components: SemanticComponent[]): SemanticComponent[] {
  return [...components].sort((left, right) => {
    const priorityDelta = left.placementPriority - right.placementPriority
    if (priorityDelta !== 0) {
      return priorityDelta
    }
    const scopeDelta = scopePathKey(left.component.scope_path).localeCompare(scopePathKey(right.component.scope_path))
    if (scopeDelta !== 0) {
      return scopeDelta
    }
    const leftName = left.component.instance_name || left.component.display_name
    const rightName = right.component.instance_name || right.component.display_name
    const nameDelta = leftName.localeCompare(rightName)
    if (nameDelta !== 0) {
      return nameDelta
    }
    return left.component.id.localeCompare(right.component.id)
  })
}

// ---------------------------------------------------------------------------
// Primitive subckt absorption.
//
// Analog primitives like op-amps are often modelled in SPICE as a `.subckt`
// containing a VCVS and a couple of resistors. Visually rendering those guts
// is the wrong abstraction — every reader expects a standard triangle. The
// normalizer therefore:
//
//   (a) Detects which subckts are primitives by name pattern
//       (see `schematicSubcktClassifier.ts`).
//   (b) For each primitive `.subckt`:
//         - Drops all components whose ids lie inside its body.
//         - Drops all nets whose `scope_path` sits under its scope.
//         - Removes the scope group itself so no dashed rectangle is drawn.
//   (c) For every top-level `X` instance that calls such a primitive:
//         - Rewrites `symbol_kind` to the primitive's canonical kind
//           (e.g. `'opamp'`).
//         - Forces port-side hints so the pin renderer places `+`, `−`,
//           `out` on the correct triangle sides regardless of the original
//           pin order coming from the SPICE parser.
//
// The rewrites happen purely inside the semantic layer; the raw
// `SchematicDocumentState` from the host is never mutated.
// ---------------------------------------------------------------------------

interface PrimitiveAbsorptionContext {
  primitives: SchematicPrimitiveSubcktMap
  internalComponentIds: Set<string>
  internalScopeKeys: Set<string>
  instanceByComponentId: Map<string, SchematicPrimitiveSubcktInfo>
}

function buildPrimitiveAbsorptionContext(
  document: SchematicDocumentState,
): PrimitiveAbsorptionContext {
  const primitives = classifySchematicPrimitiveSubckts(document.subcircuits)
  const internalComponentIds = new Set<string>()
  const internalScopeKeys = new Set<string>()
  for (const primitive of primitives.values()) {
    for (const id of primitive.componentIds) {
      internalComponentIds.add(id)
    }
    internalScopeKeys.add(primitive.scopePathKey)
  }
  const instanceByComponentId = new Map<string, SchematicPrimitiveSubcktInfo>()
  if (primitives.size > 0) {
    const primitivesByKey = new Map<string, SchematicPrimitiveSubcktInfo>()
    for (const primitive of primitives.values()) {
      const portKey = buildPortSignatureKey(primitive.portNames)
      primitivesByKey.set(portKey, primitive)
    }
    for (const component of document.components) {
      if (!isSubcktInstance(component)) continue
      if (internalComponentIds.has(component.id)) continue
      const pinNames = component.pins.map((pin) => pin.name)
      const portKey = buildPortSignatureKey(pinNames)
      const match = primitivesByKey.get(portKey)
      if (match) {
        instanceByComponentId.set(component.id, match)
      }
    }
  }
  return { primitives, internalComponentIds, internalScopeKeys, instanceByComponentId }
}

function isSubcktInstance(component: SchematicComponentState): boolean {
  const kind = component.kind.trim().toUpperCase()
  return kind === 'X' || component.symbol_kind === 'subckt_block'
}

function buildPortSignatureKey(names: readonly string[]): string {
  return [...names].map((name) => name.trim().toLowerCase()).sort().join('|')
}

function applyPrimitiveOverrides(
  component: SchematicComponentState,
  primitive: SchematicPrimitiveSubcktInfo,
): SchematicComponentState {
  const overriddenPortSideHints: Record<string, string> = { ...component.port_side_hints }
  for (const pin of component.pins) {
    const roleHint = primitive.portRoleHints[pin.name]
    if (roleHint === 'output') {
      overriddenPortSideHints[pin.name] = 'right'
    } else if (roleHint === 'input_plus' || roleHint === 'input_minus') {
      overriddenPortSideHints[pin.name] = 'left'
    }
  }
  return {
    ...component,
    symbol_kind: PRIMITIVE_SYMBOL_KIND,
    port_side_hints: overriddenPortSideHints,
  }
}

/**
 * Pre-compute a `(componentId, pinName) → SemanticNetCategory` lookup so
 * the component-normalization pass can decide a passive's intrinsic
 * orientation (horizontal vs vertical) based purely on local pin-to-net
 * information, without needing to re-walk `document.nets` per component.
 */
function buildPinToNetCategoryMap(
  document: SchematicDocumentState,
  absorption: PrimitiveAbsorptionContext,
): Map<string, SemanticNetCategory> {
  const map = new Map<string, SemanticNetCategory>()
  for (const rawNet of document.nets) {
    const scopeKey = scopePathKey(rawNet.scope_path)
    if (absorption.internalScopeKeys.has(scopeKey)) continue
    const validConnections = rawNet.connections.filter(
      (connection) => !absorption.internalComponentIds.has(connection.component_id),
    )
    const category = resolveNetCategory(rawNet, validConnections.length)
    for (const connection of validConnections) {
      map.set(buildPinToNetKey(connection.component_id, connection.pin_name), category)
    }
  }
  return map
}

function buildPinToNetKey(componentId: string, pinName: string): string {
  return `${componentId}::${pinName}`
}

const PASSIVE_SYMBOL_KINDS: ReadonlySet<string> = new Set([
  'resistor',
  'capacitor',
  'inductor',
  'diode',
])

/**
 * Force the port-side hints on a two-terminal passive so that any pin
 * sitting on a power / ground rail faces the corresponding trunk:
 *
 *   - `power` net  → hint `top`    (reaches the top power trunk)
 *   - `ground` net → hint `bottom` (reaches the bottom ground trunk)
 *
 * The opposite terminal is hinted to the opposite face, which triggers
 * `symbolRegistry.getPassiveDimensions` to return a vertical
 * (60×108) footprint and the renderer to draw a vertical silhouette.
 * Passives with no rail terminal (pure signal-chain couplers like a
 * bypass capacitor between two biasing nodes) are left untouched so
 * they stay horizontal along the left-to-right signal flow.
 *
 * This is a *pre-layout* authority: the finalized hints flow into every
 * downstream stage — `getPinAnchor().side` sets `elk.port.side`, which
 * in turn makes ELK pack the component vertically, which in turn makes
 * the router attach the rail stub on a straight short segment instead
 * of a U-turn around the component body.
 */
function applyPassivePortSideHints(
  component: SchematicComponentState,
  pinToNetCategory: Map<string, SemanticNetCategory>,
): SchematicComponentState {
  if (!PASSIVE_SYMBOL_KINDS.has(component.symbol_kind)) {
    return component
  }
  if (component.pins.length !== 2) {
    return component
  }
  const pin0 = component.pins[0]
  const pin1 = component.pins[1]
  const category0 = pinToNetCategory.get(buildPinToNetKey(component.id, pin0.name))
  const category1 = pinToNetCategory.get(buildPinToNetKey(component.id, pin1.name))

  let side0: 'top' | 'bottom' | null = null
  let side1: 'top' | 'bottom' | null = null
  // Power takes precedence over ground on the *same* pin (a pin on
  // a power net is forced to `top`), and power/ground on pin 0 takes
  // precedence over pin 1's rail for choosing which terminal sits
  // where. Non-rail terminals always take the opposite face.
  if (category0 === 'power') {
    side0 = 'top'
    side1 = 'bottom'
  } else if (category0 === 'ground') {
    side0 = 'bottom'
    side1 = 'top'
  } else if (category1 === 'power') {
    side1 = 'top'
    side0 = 'bottom'
  } else if (category1 === 'ground') {
    side1 = 'bottom'
    side0 = 'top'
  }
  if (side0 === null || side1 === null) {
    return component
  }
  return {
    ...component,
    port_side_hints: {
      ...component.port_side_hints,
      [pin0.name]: side0,
      [pin1.name]: side1,
    },
  }
}

function sortPinsForPrimitive(
  component: SchematicComponentState,
  primitive: SchematicPrimitiveSubcktInfo,
): SchematicComponentState {
  // Op-amp pin-anchor resolution uses index order as the tie-breaker
  // (index 0 → +, index 1 → −, index N-1 → output). Reorder the pins so
  // that convention always holds regardless of the original SPICE ordering.
  const roleOrder: Record<string, number> = {
    input_plus: 0,
    input_minus: 1,
    output: 2,
    ground: 3,
  }
  const enriched = component.pins.map((pin, originalIndex) => {
    const role = primitive.portRoleHints[pin.name]
    const order = role !== undefined ? roleOrder[role] : 10 + originalIndex
    return { pin, order, originalIndex }
  })
  enriched.sort((a, b) => {
    if (a.order !== b.order) return a.order - b.order
    return a.originalIndex - b.originalIndex
  })
  return {
    ...component,
    pins: enriched.map((entry) => entry.pin),
  }
}

export function normalizeSchematicDocument(document: SchematicDocumentState): SchematicSemanticModel {
  const labelMap = buildSubcircuitLabelMap(document.subcircuits)
  const scopeGroupsById = new Map<string, SemanticScopeGroup>()
  ensureScopeGroupChain(scopeGroupsById, [], labelMap)

  const absorption = buildPrimitiveAbsorptionContext(document)
  // Pre-compute the pin→net-category lookup once; it stays valid for the
  // whole pass since neither `document.nets` nor `absorption` mutate.
  const pinToNetCategory = buildPinToNetCategoryMap(document, absorption)

  const componentsById = new Map<string, SemanticComponent>()
  const rawComponents: SemanticComponent[] = []

  for (const rawComponent of document.components) {
    if (absorption.internalComponentIds.has(rawComponent.id)) {
      continue
    }
    const primitive = absorption.instanceByComponentId.get(rawComponent.id)
    const primitiveOverridden = primitive
      ? applyPrimitiveOverrides(sortPinsForPrimitive(rawComponent, primitive), primitive)
      : rawComponent
    // Force rail-facing hints on two-terminal passives so that a pin on
    // VCC/GND naturally faces the corresponding trunk. Applied after any
    // primitive override so that op-amp / BJT / MOS hints (which come
    // from the primitive classifier) are never clobbered by this pass.
    const effectiveComponent = applyPassivePortSideHints(primitiveOverridden, pinToNetCategory)
    const role = resolveComponentRole(effectiveComponent)
    const pins = buildSemanticPins(effectiveComponent)
    const group = ensureScopeGroupChain(scopeGroupsById, effectiveComponent.scope_path, labelMap)
    const semanticComponent: SemanticComponent = {
      component: effectiveComponent,
      role,
      pins,
      scopeGroupId: group.id,
      placementPriority: resolvePlacementPriority(role, pins),
    }
    componentsById.set(effectiveComponent.id, semanticComponent)
    rawComponents.push(semanticComponent)
    group.componentIds.push(effectiveComponent.id)
  }

  const netsById = new Map<string, SemanticNet>()
  const rawNets: SemanticNet[] = []

  for (const rawNet of document.nets) {
    const netScopeKey = scopePathKey(rawNet.scope_path)
    if (absorption.internalScopeKeys.has(netScopeKey)) {
      // Internal net of a primitive subckt — dropped along with its body.
      continue
    }
    const validConnections = rawNet.connections.filter((connection) => componentsById.has(connection.component_id))
    const componentIds = Array.from(new Set(validConnections.map((connection) => connection.component_id)))
    const pinCount = validConnections.length
    const category = resolveNetCategory(rawNet, pinCount)
    const netGroup = ensureScopeGroupChain(scopeGroupsById, rawNet.scope_path, labelMap)
    const semanticNet: SemanticNet = {
      net: rawNet,
      category,
      pinCount,
      componentIds,
      scopeGroupId: netGroup.id,
    }
    netsById.set(rawNet.id, semanticNet)
    rawNets.push(semanticNet)
  }

  const sortedComponents = sortSemanticComponents(rawComponents)
  const scopeGroups = Array.from(scopeGroupsById.values())

  return {
    components: sortedComponents,
    componentsById,
    nets: rawNets,
    netsById,
    scopeGroups,
    scopeGroupsById,
    rootScopeGroupId: ROOT_SCOPE_GROUP_ID,
  }
}
