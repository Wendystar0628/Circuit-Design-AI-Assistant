import type {
  SchematicLayoutComponent,
  SchematicLayoutLabel,
  SchematicLayoutNet,
  SchematicLayoutNetSegment,
  SchematicLayoutPoint,
  SchematicLayoutRect,
} from './schematicLayoutTypes'

const INSTANCE_LABEL_FONT_SIZE = 16.5
const SECONDARY_LABEL_FONT_SIZE = 15
const COMPONENT_LABEL_MIN_WIDTH = 36
const COMPONENT_LABEL_HORIZONTAL_PADDING = 8
const NET_LABEL_MIN_WIDTH = 54
const NET_LABEL_HORIZONTAL_PADDING = 18
const NET_LABEL_WIRE_CLEARANCE = 4
const NET_LABEL_COMPONENT_CLEARANCE = 8
const NET_LABEL_TO_LABEL_CLEARANCE = 4
const COMPONENT_LABEL_EDGE_OFFSET_TOP = 6
const COMPONENT_LABEL_EDGE_OFFSET_BOTTOM = 14
const COMPONENT_LABEL_EDGE_OFFSET_SIDE = 6
const MIN_CANDIDATE_SEGMENT_LENGTH = 18

export const SCHEMATIC_NET_LABEL_HEIGHT = 26
export const SCHEMATIC_COMPONENT_LABEL_HEIGHT = 24

export function estimateSchematicTextWidth(
  text: string,
  fontSize: number,
  minWidth: number,
  horizontalPadding: number,
): number {
  return Math.max(minWidth, Math.ceil(text.length * fontSize * 0.62 + horizontalPadding))
}

export function getSchematicNetLabelWidth(text: string): number {
  return estimateSchematicTextWidth(text, SECONDARY_LABEL_FONT_SIZE, NET_LABEL_MIN_WIDTH, NET_LABEL_HORIZONTAL_PADDING)
}

export function getSchematicComponentLabelWidth(text: string, kind: 'name' | 'value'): number {
  const fontSize = kind === 'name' ? INSTANCE_LABEL_FONT_SIZE : SECONDARY_LABEL_FONT_SIZE
  return estimateSchematicTextWidth(text, fontSize, COMPONENT_LABEL_MIN_WIDTH, COMPONENT_LABEL_HORIZONTAL_PADDING)
}

export function computeSchematicLabelRect(
  label: SchematicLayoutLabel,
  width: number,
  height: number,
  verticalMode: 'baseline' | 'middle',
): SchematicLayoutRect {
  const x = label.textAnchor === 'middle'
    ? label.x - width / 2
    : label.textAnchor === 'end'
      ? label.x - width
      : label.x
  const y = verticalMode === 'middle' ? label.y - height / 2 : label.y - height * 0.78
  return { x, y, width, height }
}

function rectsOverlap(a: SchematicLayoutRect, b: SchematicLayoutRect): boolean {
  return a.x < b.x + b.width
    && a.x + a.width > b.x
    && a.y < b.y + b.height
    && a.y + a.height > b.y
}

function inflateRect(rect: SchematicLayoutRect, padding: number): SchematicLayoutRect {
  return {
    x: rect.x - padding,
    y: rect.y - padding,
    width: rect.width + padding * 2,
    height: rect.height + padding * 2,
  }
}

function segmentToRect(a: SchematicLayoutPoint, b: SchematicLayoutPoint, padding: number): SchematicLayoutRect {
  return {
    x: Math.min(a.x, b.x) - padding,
    y: Math.min(a.y, b.y) - padding,
    width: Math.abs(a.x - b.x) + padding * 2,
    height: Math.abs(a.y - b.y) + padding * 2,
  }
}

type ComponentLabelSlot = 'top' | 'bottom' | 'left' | 'right'

function pickComponentSlots(component: SchematicLayoutComponent): { name: ComponentLabelSlot; value: ComponentLabelSlot } {
  const symbolKind = component.component.symbol_kind
  const orientation = component.orientation
  if (symbolKind === 'opamp' || symbolKind === 'subckt_block' || symbolKind === 'controlled_source') {
    return { name: 'top', value: 'bottom' }
  }
  if (symbolKind === 'ground') {
    return { name: 'bottom', value: 'bottom' }
  }
  if (symbolKind === 'bjt' || symbolKind === 'mos') {
    return { name: 'top', value: 'bottom' }
  }
  if (symbolKind === 'voltage_source' || symbolKind === 'current_source') {
    return { name: 'right', value: 'left' }
  }
  if (orientation === 'up' || orientation === 'down') {
    return { name: 'right', value: 'left' }
  }
  return { name: 'top', value: 'bottom' }
}

function placeComponentLabel(
  text: string,
  slot: ComponentLabelSlot,
  symbolBounds: SchematicLayoutRect,
): SchematicLayoutLabel {
  const left = symbolBounds.x
  const right = symbolBounds.x + symbolBounds.width
  const top = symbolBounds.y
  const bottom = symbolBounds.y + symbolBounds.height
  const midX = left + symbolBounds.width / 2
  const midY = top + symbolBounds.height / 2
  switch (slot) {
    case 'top':
      return { text, x: midX, y: top - COMPONENT_LABEL_EDGE_OFFSET_TOP, textAnchor: 'middle' }
    case 'bottom':
      return { text, x: midX, y: bottom + COMPONENT_LABEL_EDGE_OFFSET_BOTTOM, textAnchor: 'middle' }
    case 'left':
      return { text, x: left - COMPONENT_LABEL_EDGE_OFFSET_SIDE, y: midY + 4, textAnchor: 'end' }
    case 'right':
      return { text, x: right + COMPONENT_LABEL_EDGE_OFFSET_SIDE, y: midY + 4, textAnchor: 'start' }
  }
}

export interface SchematicComponentLabelPlan {
  nameLabel: SchematicLayoutLabel | null
  valueLabel: SchematicLayoutLabel | null
}

export function planSchematicComponentLabels(
  components: SchematicLayoutComponent[],
): Map<string, SchematicComponentLabelPlan> {
  const result = new Map<string, SchematicComponentLabelPlan>()
  for (const component of components) {
    const slots = pickComponentSlots(component)
    const nameText = component.component.instance_name || component.component.display_name || component.component.id
    const valueText = component.component.display_value
    const nameLabel = nameText ? placeComponentLabel(nameText, slots.name, component.symbolBounds) : null
    const valueLabel = valueText ? placeComponentLabel(valueText, slots.value, component.symbolBounds) : null
    result.set(component.component.id, { nameLabel, valueLabel })
  }
  return result
}

interface NetLabelCandidate {
  x: number
  y: number
  orientation: 'horizontal' | 'vertical'
  length: number
  priority: number
}

function classifySegmentPriority(segment: SchematicLayoutNetSegment): number {
  if (segment.key.endsWith(':trunk')) return 4
  if (segment.key.endsWith(':direct')) return 3
  if (segment.key.includes(':tap:')) return 2
  if (segment.kind === 'stub') return 1
  return 1
}

function collectNetLabelCandidates(segments: SchematicLayoutNetSegment[]): NetLabelCandidate[] {
  const candidates: NetLabelCandidate[] = []
  for (const segment of segments) {
    const priority = classifySegmentPriority(segment)
    for (let i = 1; i < segment.points.length; i += 1) {
      const a = segment.points[i - 1]
      const b = segment.points[i]
      const dx = b.x - a.x
      const dy = b.y - a.y
      const length = Math.hypot(dx, dy)
      if (length < MIN_CANDIDATE_SEGMENT_LENGTH) continue
      candidates.push({
        x: (a.x + b.x) / 2,
        y: (a.y + b.y) / 2,
        orientation: Math.abs(dx) >= Math.abs(dy) ? 'horizontal' : 'vertical',
        length,
        priority,
      })
    }
  }
  candidates.sort((left, right) => right.priority - left.priority || right.length - left.length)
  return candidates
}

interface NetLabelContext {
  labelWidth: number
  componentObstacles: SchematicLayoutRect[]
  segmentObstacles: SchematicLayoutRect[]
  placedLabelRects: SchematicLayoutRect[]
}

function tryPlaceNetLabel(
  netName: string,
  candidate: NetLabelCandidate,
  ctx: NetLabelContext,
): SchematicLayoutLabel | null {
  const options: SchematicLayoutLabel[] = candidate.orientation === 'horizontal'
    ? [
        { text: netName, x: candidate.x, y: candidate.y - (SCHEMATIC_NET_LABEL_HEIGHT / 2 + NET_LABEL_WIRE_CLEARANCE), textAnchor: 'middle' },
        { text: netName, x: candidate.x, y: candidate.y + (SCHEMATIC_NET_LABEL_HEIGHT / 2 + NET_LABEL_WIRE_CLEARANCE), textAnchor: 'middle' },
      ]
    : [
        { text: netName, x: candidate.x + ctx.labelWidth / 2 + NET_LABEL_WIRE_CLEARANCE, y: candidate.y, textAnchor: 'middle' },
        { text: netName, x: candidate.x - ctx.labelWidth / 2 - NET_LABEL_WIRE_CLEARANCE, y: candidate.y, textAnchor: 'middle' },
      ]
  for (const option of options) {
    const rect = computeSchematicLabelRect(option, ctx.labelWidth, SCHEMATIC_NET_LABEL_HEIGHT, 'middle')
    if (ctx.componentObstacles.some((ob) => rectsOverlap(rect, ob))) continue
    if (ctx.segmentObstacles.some((ob) => rectsOverlap(rect, ob))) continue
    if (ctx.placedLabelRects.some((ob) => rectsOverlap(rect, ob))) continue
    return option
  }
  return null
}

function buildForcedNetLabel(
  netName: string,
  candidate: NetLabelCandidate,
  labelWidth: number,
): SchematicLayoutLabel {
  if (candidate.orientation === 'horizontal') {
    return {
      text: netName,
      x: candidate.x,
      y: candidate.y - (SCHEMATIC_NET_LABEL_HEIGHT / 2 + NET_LABEL_WIRE_CLEARANCE),
      textAnchor: 'middle',
    }
  }
  return {
    text: netName,
    x: candidate.x + labelWidth / 2 + NET_LABEL_WIRE_CLEARANCE,
    y: candidate.y,
    textAnchor: 'middle',
  }
}

function collectComponentObstacles(components: SchematicLayoutComponent[]): SchematicLayoutRect[] {
  return components.map((component) => inflateRect(component.symbolBounds, NET_LABEL_COMPONENT_CLEARANCE))
}

function collectSegmentObstacles(nets: SchematicLayoutNet[]): SchematicLayoutRect[] {
  const result: SchematicLayoutRect[] = []
  for (const net of nets) {
    for (const segment of net.segments) {
      for (let i = 1; i < segment.points.length; i += 1) {
        result.push(segmentToRect(segment.points[i - 1], segment.points[i], NET_LABEL_WIRE_CLEARANCE))
      }
    }
  }
  return result
}

function collectComponentLabelObstacles(components: SchematicLayoutComponent[]): SchematicLayoutRect[] {
  const result: SchematicLayoutRect[] = []
  for (const component of components) {
    if (component.nameLabel) {
      const width = getSchematicComponentLabelWidth(component.nameLabel.text, 'name')
      result.push(inflateRect(
        computeSchematicLabelRect(component.nameLabel, width, SCHEMATIC_COMPONENT_LABEL_HEIGHT, 'baseline'),
        NET_LABEL_TO_LABEL_CLEARANCE,
      ))
    }
    if (component.valueLabel) {
      const width = getSchematicComponentLabelWidth(component.valueLabel.text, 'value')
      result.push(inflateRect(
        computeSchematicLabelRect(component.valueLabel, width, SCHEMATIC_COMPONENT_LABEL_HEIGHT, 'baseline'),
        NET_LABEL_TO_LABEL_CLEARANCE,
      ))
    }
  }
  return result
}

export function planSchematicNetLabels(
  nets: SchematicLayoutNet[],
  components: SchematicLayoutComponent[],
): Map<string, SchematicLayoutLabel | null> {
  const result = new Map<string, SchematicLayoutLabel | null>()
  const componentObstacles = collectComponentObstacles(components)
  const segmentObstacles = collectSegmentObstacles(nets)
  const placedLabelRects: SchematicLayoutRect[] = collectComponentLabelObstacles(components)

  const prioritized = [...nets].sort((left, right) => {
    const leftTrunk = left.segments.some((s) => s.key.endsWith(':trunk')) ? 1 : 0
    const rightTrunk = right.segments.some((s) => s.key.endsWith(':trunk')) ? 1 : 0
    if (leftTrunk !== rightTrunk) return rightTrunk - leftTrunk
    const leftDirect = left.segments.some((s) => s.key.endsWith(':direct')) ? 1 : 0
    const rightDirect = right.segments.some((s) => s.key.endsWith(':direct')) ? 1 : 0
    return rightDirect - leftDirect
  })

  for (const net of prioritized) {
    if (!net.net.name) {
      result.set(net.net.id, null)
      continue
    }
    const labelWidth = getSchematicNetLabelWidth(net.net.name)
    const candidates = collectNetLabelCandidates(net.segments)
    if (candidates.length === 0) {
      result.set(net.net.id, null)
      continue
    }
    const ctx: NetLabelContext = { labelWidth, componentObstacles, segmentObstacles, placedLabelRects }
    let label: SchematicLayoutLabel | null = null
    for (const candidate of candidates) {
      label = tryPlaceNetLabel(net.net.name, candidate, ctx)
      if (label) break
    }
    if (!label) {
      label = buildForcedNetLabel(net.net.name, candidates[0], labelWidth)
    }
    placedLabelRects.push(computeSchematicLabelRect(label, labelWidth, SCHEMATIC_NET_LABEL_HEIGHT, 'middle'))
    result.set(net.net.id, label)
  }

  return result
}
