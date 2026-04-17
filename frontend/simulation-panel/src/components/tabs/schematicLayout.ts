import type { SchematicDocumentState, SchematicPinState } from '../../types/state'
import { getSchematicSymbolDefinition, type SchematicPinSide } from './symbolRegistry'
import { normalizeSchematicDocument } from './schematicDocumentNormalizer'
import type {
  SchematicSemanticModel,
  SemanticComponent,
} from './schematicSemanticModel'
import { classifySchematicNetRoles } from './schematicNetRoles'
import type { SchematicNetRoleMap } from './schematicNetRoles'
import {
  computeSchematicElkLayout,
  type SchematicElkLayout,
} from './schematicElkLayout'
import type {
  SchematicCanvasViewState,
  SchematicLayoutBounds,
  SchematicLayoutComponent,
  SchematicLayoutGroup,
  SchematicLayoutNet,
  SchematicLayoutPin,
  SchematicLayoutPinStub,
  SchematicLayoutPoint,
  SchematicLayoutRect,
  SchematicLayoutResult,
} from './schematicLayoutTypes'
import { routeSchematicNets } from './schematicOrthogonalConnectorRouter'
import {
  rotateLayoutClockwise90,
  shouldRotateLayoutToHorizontal,
} from './schematicLayoutRotation'
import { alignNetPins } from './schematicPinAlignment'
import { RAIL_STUB_LENGTH, computeRailStubBounds } from './schematicRailStub'
import {
  SCHEMATIC_COMPONENT_LABEL_HEIGHT,
  SCHEMATIC_NET_LABEL_HEIGHT,
  computeSchematicLabelRect,
  getSchematicComponentLabelWidth,
  getSchematicNetLabelWidth,
  planSchematicComponentLabels,
  planSchematicNetLabels,
} from './schematicLabelPlanner'

export type {
  SchematicCanvasViewState,
  SchematicLayoutBounds,
  SchematicLayoutComponent,
  SchematicLayoutGroup,
  SchematicLayoutLabel,
  SchematicLayoutNet,
  SchematicLayoutNetSegment,
  SchematicLayoutPin,
  SchematicLayoutPoint,
  SchematicLayoutRect,
  SchematicLayoutResult,
} from './schematicLayoutTypes'

interface ResolvedPinAnchor {
  portId: string
  pin: SchematicPinState
  side: SchematicPinSide
  anchorX: number
  anchorY: number
}

const FIT_PADDING = 56
const MIN_SCALE = 0.35
const MAX_SCALE = 2.6

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function includePoint(bounds: SchematicLayoutBounds | null, point: SchematicLayoutPoint): SchematicLayoutBounds {
  if (bounds === null) {
    return {
      minX: point.x,
      minY: point.y,
      maxX: point.x,
      maxY: point.y,
    }
  }
  return {
    minX: Math.min(bounds.minX, point.x),
    minY: Math.min(bounds.minY, point.y),
    maxX: Math.max(bounds.maxX, point.x),
    maxY: Math.max(bounds.maxY, point.y),
  }
}

function includeRect(bounds: SchematicLayoutBounds | null, x: number, y: number, width: number, height: number): SchematicLayoutBounds {
  let nextBounds = includePoint(bounds, { x, y })
  nextBounds = includePoint(nextBounds, { x: x + width, y: y + height })
  return nextBounds
}

function getBoundsWidth(bounds: SchematicLayoutBounds): number {
  return Math.max(1, bounds.maxX - bounds.minX)
}

function getBoundsHeight(bounds: SchematicLayoutBounds): number {
  return Math.max(1, bounds.maxY - bounds.minY)
}

function buildPortId(componentId: string, pinName: string): string {
  return `port:${componentId}:${pinName}`
}

function buildRequestKey(documentId: string, revision: string): string {
  return `${documentId}::${revision}`
}

// Keep this in lock-step with the `GRID_SNAP` constant in
// `schematicOrthogonalConnectorRouter.ts`. The router snaps every polyline
// point to this grid; snapping pin coordinates here ensures terminals and
// route endpoints land on the same lattice so the orthogonal visibility
// graph does not manufacture near-duplicate columns / rows.
const PIN_GRID_SNAP = 4

function snapPinCoordinate(value: number): number {
  return Math.round(value / PIN_GRID_SNAP) * PIN_GRID_SNAP
}

function resolvePinAnchors(semanticComponent: SemanticComponent): ResolvedPinAnchor[] {
  const component = semanticComponent.component
  const definition = getSchematicSymbolDefinition(component.symbol_kind)
  return semanticComponent.pins.map((semanticPin) => {
    const anchor = definition.getPinAnchor(component, semanticPin.pin, semanticPin.index)
    return {
      portId: buildPortId(component.id, semanticPin.pin.name),
      pin: semanticPin.pin,
      side: anchor.side,
      anchorX: anchor.x,
      anchorY: anchor.y,
    }
  })
}

function buildComponentLayouts(
  semantic: SchematicSemanticModel,
  placement: SchematicElkLayout,
  portMap: Map<string, SchematicLayoutPin>,
): { components: SchematicLayoutComponent[]; groups: SchematicLayoutGroup[] } {
  const components: SchematicLayoutComponent[] = []
  for (const position of placement.componentPositions) {
    const semanticComponent = semantic.componentsById.get(position.componentId)
    if (!semanticComponent) {
      continue
    }
    const pinAnchors = resolvePinAnchors(semanticComponent)
    const pins: SchematicLayoutPin[] = pinAnchors.map((anchor) => {
      // Snap each pin's world coordinates to the router's grid so that
      // sub-grid offsets carried by `anchor.x/y` (e.g. passive pins at
      // y=30 when GRID_SNAP=4 → residual 2 px off-grid) never leak into
      // the orthogonal visibility graph as near-duplicate candidate
      // lines. Without this, two terminals that *should* share a column
      // can end up 2 px apart and force a spurious micro-jog segment.
      const pin: SchematicLayoutPin = {
        id: anchor.portId,
        componentId: position.componentId,
        pin: anchor.pin,
        side: anchor.side,
        x: snapPinCoordinate(position.symbolBox.x + anchor.anchorX),
        y: snapPinCoordinate(position.symbolBox.y + anchor.anchorY),
        stub: null,
      }
      portMap.set(anchor.portId, pin)
      return pin
    })
    const layoutComponent: SchematicLayoutComponent = {
      component: semanticComponent.component,
      // Layout defaults to unrotated; the global rotate-to-horizontal pass
      // at the end of `computeSchematicLayout` may flip this to 90 for
      // every component if the finished drawing is too tall.
      rotation: 0,
      bounds: { ...position.box },
      symbolBounds: { ...position.symbolBox },
      pins,
      nameLabel: null,
      valueLabel: null,
    }
    components.push(layoutComponent)
  }
  const groups: SchematicLayoutGroup[] = placement.scopeGroupBounds.map((entry) => ({
    id: entry.scopeGroupId,
    label: entry.label,
    depth: entry.depth,
    bounds: { ...entry.bounds },
  }))
  return { components, groups }
}

// ---------------------------------------------------------------------------
// Rail pin stubs.
//
// Ground and power-rail nets are not drawn as wires. Instead every pin on
// such a net is terminated locally by a GND / VCC / VEE glyph (a "stub").
// This is the industry-standard way to express supply connectivity: each
// pin says where it goes by its symbol, and the shared node is implicit.
//
// Stub placement is done purely from pin geometry here so the router has a
// single, stable input downstream (it just skips rail nets entirely).
// ---------------------------------------------------------------------------

function unionLayoutRect(a: SchematicLayoutRect, b: SchematicLayoutRect): SchematicLayoutRect {
  const minX = Math.min(a.x, b.x)
  const minY = Math.min(a.y, b.y)
  const maxX = Math.max(a.x + a.width, b.x + b.width)
  const maxY = Math.max(a.y + a.height, b.y + b.height)
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

/**
 * Expand each component's `bounds` to include any rail stub rectangles
 * attached to its pins. `bounds` is the canonical "occupied area" used by
 * every downstream pass — the orthogonal router's obstacle builder, the
 * pin-alignment pass's overlap check, and the final layout bounds. By
 * folding the stub rectangles into it here, right after the stubs are
 * attached, all those passes inherit stub-aware collision detection for
 * free.
 */
function expandComponentBoundsForStubs(components: SchematicLayoutComponent[]): void {
  for (const component of components) {
    for (const pin of component.pins) {
      const stubRect = computeRailStubBounds(pin)
      if (!stubRect) continue
      component.bounds = unionLayoutRect(component.bounds, stubRect)
    }
  }
}

function attachRailPinStubs(
  semantic: SchematicSemanticModel,
  netRoles: SchematicNetRoleMap,
  portMap: Map<string, SchematicLayoutPin>,
): void {
  for (const semanticNet of semantic.nets) {
    const role = netRoles.get(semanticNet.net.id)
    if (role !== 'ground_rail' && role !== 'power_rail') {
      continue
    }
    const stubKind: SchematicLayoutPinStub['kind'] = role === 'ground_rail' ? 'ground' : 'power'
    // Ground symbols carry no text; power rails carry their normalized net
    // name (e.g. "VCC"). Trimming mirrors the host's lower-case storage.
    const label = role === 'power_rail' ? semanticNet.net.name.toUpperCase() : ''
    for (const connection of semanticNet.net.connections) {
      const portId = buildPortId(connection.component_id, connection.pin_name)
      const pin = portMap.get(portId)
      if (!pin) continue
      // Do not stub pins on the supply / ground component itself — those
      // nodes are the source of the rail, not a consumer of it, and the
      // ELK rail-trunk placement already represents them structurally.
      const owner = semantic.componentsById.get(pin.componentId)
      if (owner && (owner.role === 'supply' || owner.role === 'ground')) {
        continue
      }
      pin.stub = {
        kind: stubKind,
        label,
        side: pin.side,
        x: pin.x,
        y: pin.y,
        length: RAIL_STUB_LENGTH,
      }
    }
  }
}

function buildPinsByNet(
  semantic: SchematicSemanticModel,
  portMap: Map<string, SchematicLayoutPin>,
): Map<string, SchematicLayoutPin[]> {
  const pinsByNet = new Map<string, SchematicLayoutPin[]>()
  for (const semanticNet of semantic.nets) {
    const pins: SchematicLayoutPin[] = []
    for (const connection of semanticNet.net.connections) {
      const pin = portMap.get(buildPortId(connection.component_id, connection.pin_name))
      if (pin) {
        pins.push(pin)
      }
    }
    pinsByNet.set(semanticNet.net.id, pins)
  }
  return pinsByNet
}

function buildNetLayouts(
  semantic: SchematicSemanticModel,
  netRoles: SchematicNetRoleMap,
  portMap: Map<string, SchematicLayoutPin>,
  components: SchematicLayoutComponent[],
): SchematicLayoutNet[] {
  const pinsByNet = buildPinsByNet(semantic, portMap)
  const routedSegments = routeSchematicNets(semantic, netRoles, pinsByNet, components)
  const nets: SchematicLayoutNet[] = []
  for (const semanticNet of semantic.nets) {
    const segments = routedSegments.get(semanticNet.net.id) ?? []
    if (segments.length === 0) {
      continue
    }
    nets.push({
      net: semanticNet.net,
      segments,
      label: null,
    })
  }
  return nets
}

function applySchematicLabelPlans(
  components: SchematicLayoutComponent[],
  nets: SchematicLayoutNet[],
): void {
  const componentPlan = planSchematicComponentLabels(components)
  for (const component of components) {
    const plan = componentPlan.get(component.component.id)
    if (plan) {
      component.nameLabel = plan.nameLabel
      component.valueLabel = plan.valueLabel
    }
  }
  const netPlan = planSchematicNetLabels(nets, components)
  for (const net of nets) {
    net.label = netPlan.get(net.net.id) ?? null
  }
}

function buildBounds(components: SchematicLayoutComponent[], groups: SchematicLayoutGroup[], nets: SchematicLayoutNet[]): SchematicLayoutBounds | null {
  let bounds: SchematicLayoutBounds | null = null
  for (const group of groups) {
    bounds = includeRect(bounds, group.bounds.x, group.bounds.y, group.bounds.width, group.bounds.height)
  }
  for (const component of components) {
    bounds = includeRect(bounds, component.bounds.x, component.bounds.y, component.bounds.width, component.bounds.height)
    if (component.nameLabel) {
      const nameBounds = computeSchematicLabelRect(
        component.nameLabel,
        getSchematicComponentLabelWidth(component.nameLabel.text, 'name'),
        SCHEMATIC_COMPONENT_LABEL_HEIGHT,
        'baseline',
      )
      bounds = includeRect(bounds, nameBounds.x, nameBounds.y, nameBounds.width, nameBounds.height)
    }
    if (component.valueLabel) {
      const valueBounds = computeSchematicLabelRect(
        component.valueLabel,
        getSchematicComponentLabelWidth(component.valueLabel.text, 'value'),
        SCHEMATIC_COMPONENT_LABEL_HEIGHT,
        'baseline',
      )
      bounds = includeRect(bounds, valueBounds.x, valueBounds.y, valueBounds.width, valueBounds.height)
    }
  }
  for (const net of nets) {
    for (const segment of net.segments) {
      for (const point of segment.points) {
        bounds = includePoint(bounds, point)
      }
    }
    if (net.label) {
      const labelBounds = computeSchematicLabelRect(
        net.label,
        getSchematicNetLabelWidth(net.label.text),
        SCHEMATIC_NET_LABEL_HEIGHT,
        'middle',
      )
      bounds = includeRect(bounds, labelBounds.x, labelBounds.y, labelBounds.width, labelBounds.height)
    }
  }
  return bounds
}

export function createEmptySchematicViewState(): SchematicCanvasViewState {
  return {
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  }
}

export function fitSchematicViewToBounds(bounds: SchematicLayoutBounds, width: number, height: number): SchematicCanvasViewState {
  const paddedWidth = Math.max(1, width - FIT_PADDING * 2)
  const paddedHeight = Math.max(1, height - FIT_PADDING * 2)
  const scale = clamp(Math.min(paddedWidth / getBoundsWidth(bounds), paddedHeight / getBoundsHeight(bounds)), MIN_SCALE, MAX_SCALE)
  const centerX = (bounds.minX + bounds.maxX) / 2
  const centerY = (bounds.minY + bounds.maxY) / 2
  return {
    scale,
    offsetX: width / 2 - centerX * scale,
    offsetY: height / 2 - centerY * scale,
  }
}

export function makeViewTargetWorldPoint(clientX: number, clientY: number, rect: DOMRect, viewState: SchematicCanvasViewState): SchematicLayoutPoint {
  return {
    x: (clientX - rect.left - viewState.offsetX) / viewState.scale,
    y: (clientY - rect.top - viewState.offsetY) / viewState.scale,
  }
}

/**
 * Authoritative schematic layout pipeline.
 *
 * 1. Normalize the document into a stable `SchematicSemanticModel`.
 * 2. Classify each net's role (ground / power / signal trunk / branch / dangling).
 * 3. Run ELK (`computeSchematicElkLayout`) to place components along a
 *    left-to-right signal flow, emitting rail components into dedicated
 *    top/bottom trunks that do not distort the main layered graph.
 * 4. Build the final component + group layout geometry from ELK's output.
 * 5. Route nets through the orthogonal-visibility-graph + A* + nudging
 *    pipeline (`routeSchematicNets`).
 * 6. Plan component and net labels, then compute overall bounds.
 *
 * There is a single authority at every stage — no fallbacks, no alternative
 * placement strategies, no pre-placement orientation guessing.
 */
export async function computeSchematicLayout(document: SchematicDocumentState): Promise<SchematicLayoutResult> {
  const requestKey = buildRequestKey(document.document_id, document.revision)
  if (!document.has_schematic || document.components.length === 0) {
    return {
      requestKey,
      documentId: document.document_id,
      revision: document.revision,
      components: [],
      nets: [],
      groups: [],
      bounds: null,
    }
  }

  const semantic = normalizeSchematicDocument(document)
  const netRoles = classifySchematicNetRoles(semantic)
  const placement = await computeSchematicElkLayout(semantic, netRoles)
  const portMap = new Map<string, SchematicLayoutPin>()
  const { components, groups } = buildComponentLayouts(semantic, placement, portMap)
  // Snap signal-net pins onto a shared axis before rail stubs or routing
  // run. This is the authoritative fix for "Z-jog" artifacts between
  // near-aligned terminals: the downstream router will draw clean straight
  // lines / T-junctions because its inputs are already co-linear. See
  // `schematicPinAlignment.ts` for the full rationale.
  const pinsByNet = buildPinsByNet(semantic, portMap)
  alignNetPins(components, pinsByNet, netRoles)
  attachRailPinStubs(semantic, netRoles, portMap)
  // Fold the rail-stub glyph rectangles into each component's `bounds`
  // so the router's obstacle builder and the final bounds computation
  // treat the stub as part of the component's occupied area. Must run
  // after `attachRailPinStubs` (the stub records are the input) and
  // before `buildNetLayouts` (the router reads these bounds).
  expandComponentBoundsForStubs(components)
  const nets = buildNetLayouts(semantic, netRoles, portMap, components)
  applySchematicLabelPlans(components, nets)
  const bounds = buildBounds(components, groups, nets)

  // Final global orientation pass: if the finished drawing is substantially
  // taller than it is wide (a common outcome for short/deep signal chains
  // such as a single-stage amplifier), rotate the whole layout 90° clockwise
  // so it fills the canvas horizontally. The pass is rigid — it moves every
  // coordinate uniformly and flips a single per-component `rotation` flag,
  // leaving topology, label slots, routing, and group hierarchy untouched.
  const baseLayout = { components, nets, groups, bounds }
  const finalLayout = shouldRotateLayoutToHorizontal(bounds) ? rotateLayoutClockwise90(baseLayout) : baseLayout

  return {
    requestKey,
    documentId: document.document_id,
    revision: document.revision,
    components: finalLayout.components,
    nets: finalLayout.nets,
    groups: finalLayout.groups,
    bounds: finalLayout.bounds,
  }
}
