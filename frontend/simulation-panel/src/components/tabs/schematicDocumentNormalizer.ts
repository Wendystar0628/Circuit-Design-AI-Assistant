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
import { getSchematicComponentDisplayName } from './schematicComponentName'

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
  if (component.primitive_kind === 'opamp') {
    return 'amplifier'
  }
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
    case 'jfet':
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
  if (normalized === 'input' || normalized === 'in' || normalized === 'input_plus' || normalized === 'input_minus') {
    return 'input'
  }
  if (normalized === 'output' || normalized === 'out') {
    return 'output'
  }
  if (normalized === 'power' || normalized === 'vdd' || normalized === 'vcc' || normalized === 'power_positive' || normalized === 'power_negative') {
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
    const leftName = getSchematicComponentDisplayName(left.component)
    const rightName = getSchematicComponentDisplayName(right.component)
    const nameDelta = leftName.localeCompare(rightName)
    if (nameDelta !== 0) {
      return nameDelta
    }
    return left.component.id.localeCompare(right.component.id)
  })
}

const PASSIVE_SYMBOL_KINDS: ReadonlySet<string> = new Set([
  'resistor',
  'capacitor',
  'inductor',
  'diode',
])

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

function buildPinToNetCategoryMap(
  document: SchematicDocumentState,
): Map<string, SemanticNetCategory> {
  const map = new Map<string, SemanticNetCategory>()
  for (const rawNet of document.nets) {
    const category = resolveNetCategory(rawNet, rawNet.connections.length)
    for (const connection of rawNet.connections) {
      map.set(buildPinToNetKey(connection.component_id, connection.pin_name), category)
    }
  }
  return map
}

function buildPinToNetKey(componentId: string, pinName: string): string {
  return `${componentId}::${pinName}`
}

function buildVisiblePinNames(components: SemanticComponent[]): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>()
  for (const entry of components) {
    map.set(entry.component.id, new Set(entry.component.pins.map((pin) => pin.name)))
  }
  return map
}

const MOS_VISIBLE_PIN_COUNT = 3

function hideMosBulkPin(component: SchematicComponentState): SchematicComponentState {
  if (component.symbol_kind !== 'mos') return component
  if (component.pins.length <= MOS_VISIBLE_PIN_COUNT) return component
  const hiddenPin = component.pins[MOS_VISIBLE_PIN_COUNT]
  const visiblePins = component.pins.slice(0, MOS_VISIBLE_PIN_COUNT)
  const nextPortSideHints = { ...component.port_side_hints }
  delete nextPortSideHints[hiddenPin.name]
  return {
    ...component,
    pins: visiblePins,
    port_side_hints: nextPortSideHints,
  }
}

export function normalizeSchematicDocument(document: SchematicDocumentState): SchematicSemanticModel {
  const labelMap = buildSubcircuitLabelMap(document.subcircuits)
  const scopeGroupsById = new Map<string, SemanticScopeGroup>()
  ensureScopeGroupChain(scopeGroupsById, [], labelMap)

  const pinToNetCategory = buildPinToNetCategoryMap(document)

  const componentsById = new Map<string, SemanticComponent>()
  const rawComponents: SemanticComponent[] = []

  for (const rawComponent of document.components) {
    const railHinted = applyPassivePortSideHints(rawComponent, pinToNetCategory)
    // Strip the MOSFET body pin so downstream layout / routing / render
    // all see a 3-terminal MOS (textbook convention) while the backend
    // still emits the full 4-node `M` card for SPICE simulation.
    const effectiveComponent = hideMosBulkPin(railHinted)
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

  // Drop any net connection whose pin was removed by a prior
  // normalization step (most notably the MOSFET body pin). Without
  // this scrubbing the body net would still reference a phantom pin
  // and the router would fail to match the pin id during stub
  // routing, generating layout errors.
  const visiblePinNames = buildVisiblePinNames(rawComponents)

  for (const rawNet of document.nets) {
    const validConnections = rawNet.connections.filter((connection) => {
      if (!componentsById.has(connection.component_id)) return false
      const pinSet = visiblePinNames.get(connection.component_id)
      if (!pinSet) return false
      return pinSet.has(connection.pin_name)
    })
    const componentIds = Array.from(new Set(validConnections.map((connection) => connection.component_id)))
    const pinCount = validConnections.length
    const category = resolveNetCategory(rawNet, pinCount)
    const netGroup = ensureScopeGroupChain(scopeGroupsById, rawNet.scope_path, labelMap)
    // Replace `rawNet.connections` with the filtered list at the
    // SemanticNet boundary so downstream consumers that walk
    // `semanticNet.net.connections` directly (e.g. ELK edge builders,
    // rail-stub padding, pin-per-net maps) never see a connection
    // pointing at a hidden pin. Spreading over `rawNet` preserves id,
    // name, scope_path, and every other raw field untouched.
    const scrubbedNet = {
      ...rawNet,
      connections: validConnections,
    }
    const semanticNet: SemanticNet = {
      net: scrubbedNet,
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
