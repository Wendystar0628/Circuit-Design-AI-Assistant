import type { SchematicDocumentState, SchematicPinState } from '../../types/state'
import { getSchematicSymbolDefinition, transformSchematicSymbolAnchor, type SchematicPinSide } from './symbolRegistry'
import { normalizeSchematicDocument } from './schematicDocumentNormalizer'
import type {
  SchematicSemanticModel,
  SemanticComponent,
} from './schematicSemanticModel'
import { analyzeSchematicSkeleton } from './schematicSkeletonAnalyzer'
import type { SchematicSkeleton } from './schematicSkeletonModel'
import { computeSchematicCoarsePlacement } from './schematicConstraintPlacement'
import type { SchematicCoarsePlacement } from './schematicConstraintPlacement'
import { decideSchematicComponentOrientations } from './schematicOrientationDecision'
import type {
  SchematicCanvasViewState,
  SchematicLayoutBounds,
  SchematicLayoutComponent,
  SchematicLayoutGroup,
  SchematicLayoutNet,
  SchematicLayoutOrientation,
  SchematicLayoutPin,
  SchematicLayoutPoint,
  SchematicLayoutResult,
} from './schematicLayoutTypes'
import { routeSchematicNets } from './schematicOrthogonalConnectorRouter'
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
  SchematicLayoutOrientation,
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

function resolveOrientedPinAnchors(
  semanticComponent: SemanticComponent,
  orientation: SchematicLayoutOrientation,
): ResolvedPinAnchor[] {
  const component = semanticComponent.component
  const definition = getSchematicSymbolDefinition(component.symbol_kind)
  return semanticComponent.pins.map((semanticPin) => {
    const baseAnchor = definition.getPinAnchor(component, semanticPin.pin, semanticPin.index)
    const orientedAnchor = transformSchematicSymbolAnchor(baseAnchor, orientation, definition.width, definition.height)
    return {
      portId: buildPortId(component.id, semanticPin.pin.name),
      pin: semanticPin.pin,
      side: orientedAnchor.side,
      anchorX: orientedAnchor.x,
      anchorY: orientedAnchor.y,
    }
  })
}

function buildComponentLayouts(
  semantic: SchematicSemanticModel,
  placement: SchematicCoarsePlacement,
  orientationsById: Map<string, SchematicLayoutOrientation>,
  portMap: Map<string, SchematicLayoutPin>,
): { components: SchematicLayoutComponent[]; groups: SchematicLayoutGroup[] } {
  const components: SchematicLayoutComponent[] = []
  for (const position of placement.componentPositions) {
    const semanticComponent = semantic.componentsById.get(position.componentId)
    if (!semanticComponent) {
      continue
    }
    const orientation = orientationsById.get(position.componentId) ?? 'right'
    const pinAnchors = resolveOrientedPinAnchors(semanticComponent, orientation)
    const pins: SchematicLayoutPin[] = pinAnchors.map((anchor) => {
      const pin: SchematicLayoutPin = {
        id: anchor.portId,
        componentId: position.componentId,
        pin: anchor.pin,
        side: anchor.side,
        x: position.symbolBox.x + anchor.anchorX,
        y: position.symbolBox.y + anchor.anchorY,
      }
      portMap.set(anchor.portId, pin)
      return pin
    })
    const layoutComponent: SchematicLayoutComponent = {
      component: semanticComponent.component,
      orientation,
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
  skeleton: SchematicSkeleton,
  portMap: Map<string, SchematicLayoutPin>,
  components: SchematicLayoutComponent[],
): SchematicLayoutNet[] {
  const pinsByNet = buildPinsByNet(semantic, portMap)
  const routedSegments = routeSchematicNets(semantic, skeleton, pinsByNet, components)
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
  const skeleton = analyzeSchematicSkeleton(semantic)
  const orientationsById = decideSchematicComponentOrientations(semantic, skeleton)
  const placement = computeSchematicCoarsePlacement(semantic, skeleton, orientationsById)
  const portMap = new Map<string, SchematicLayoutPin>()
  const { components, groups } = buildComponentLayouts(semantic, placement, orientationsById, portMap)
  const nets = buildNetLayouts(semantic, skeleton, portMap, components)
  applySchematicLabelPlans(components, nets)
  const bounds = buildBounds(components, groups, nets)

  return {
    requestKey,
    documentId: document.document_id,
    revision: document.revision,
    components,
    nets,
    groups,
    bounds,
  }
}
