import type {
  SchematicLayoutComponent,
  SchematicLayoutNetSegment,
  SchematicLayoutPin,
  SchematicLayoutPoint,
  SchematicLayoutSegmentAxis,
  SchematicPinSide,
} from './schematicLayoutTypes'
import type { SchematicSemanticModel } from './schematicSemanticModel'
import type { SchematicSkeleton, SkeletonNet } from './schematicSkeletonModel'

const STUB_LENGTH = 28
const RAIL_CHANNEL_OFFSET = 44
const OBSTACLE_CLEARANCE = 10
const TRUNK_OBSTACLE_MARGIN = 14

interface ObstacleRect {
  x: number
  y: number
  width: number
  height: number
  ownerComponentId: string
}

function buildObstacles(components: SchematicLayoutComponent[]): ObstacleRect[] {
  return components.map((c) => ({
    x: c.symbolBounds.x - OBSTACLE_CLEARANCE,
    y: c.symbolBounds.y - OBSTACLE_CLEARANCE,
    width: c.symbolBounds.width + OBSTACLE_CLEARANCE * 2,
    height: c.symbolBounds.height + OBSTACLE_CLEARANCE * 2,
    ownerComponentId: c.component.id,
  }))
}

function resolveAxis(points: SchematicLayoutPoint[]): SchematicLayoutSegmentAxis {
  let hasHoriz = false
  let hasVert = false
  for (let i = 1; i < points.length; i += 1) {
    if (points[i].x !== points[i - 1].x) hasHoriz = true
    if (points[i].y !== points[i - 1].y) hasVert = true
  }
  if (hasHoriz && hasVert) return 'mixed'
  if (hasHoriz) return 'horizontal'
  if (hasVert) return 'vertical'
  return 'mixed'
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function stubTerminus(pin: SchematicLayoutPin): SchematicLayoutPoint {
  switch (pin.side) {
    case 'left': return { x: pin.x - STUB_LENGTH, y: pin.y }
    case 'right': return { x: pin.x + STUB_LENGTH, y: pin.y }
    case 'top': return { x: pin.x, y: pin.y - STUB_LENGTH }
    case 'bottom': return { x: pin.x, y: pin.y + STUB_LENGTH }
  }
}

function buildStubPoints(pin: SchematicLayoutPin): SchematicLayoutPoint[] {
  const term = stubTerminus(pin)
  if (pin.side === 'left' || pin.side === 'top') {
    return [term, { x: pin.x, y: pin.y }]
  }
  return [{ x: pin.x, y: pin.y }, term]
}

function isSideVertical(side: SchematicPinSide): boolean {
  return side === 'top' || side === 'bottom'
}

function route2Pin(a: SchematicLayoutPin, b: SchematicLayoutPin): SchematicLayoutPoint[] {
  const pa = { x: a.x, y: a.y }
  const pb = { x: b.x, y: b.y }
  if (pa.x === pb.x || pa.y === pb.y) {
    return [pa, pb]
  }
  const bend = isSideVertical(a.side)
    ? { x: pa.x, y: pb.y }
    : { x: pb.x, y: pa.y }
  return [pa, bend, pb]
}

interface TrunkPlan {
  axis: 'horizontal' | 'vertical'
  coord: number
}

function planTrunk(pins: SchematicLayoutPin[], skNet: SkeletonNet, obstacles: ObstacleRect[]): TrunkPlan {
  const xs = pins.map((p) => p.x)
  const ys = pins.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  if (skNet.role === 'ground_rail') {
    return { axis: 'horizontal', coord: maxY + RAIL_CHANNEL_OFFSET }
  }
  if (skNet.role === 'power_rail') {
    return { axis: 'horizontal', coord: minY - RAIL_CHANNEL_OFFSET }
  }
  const hSpread = maxX - minX
  const vSpread = maxY - minY
  if (hSpread >= vSpread) {
    return { axis: 'horizontal', coord: shiftTrunkClear('horizontal', median(ys), minX, maxX, obstacles) }
  }
  return { axis: 'vertical', coord: shiftTrunkClear('vertical', median(xs), minY, maxY, obstacles) }
}

function shiftTrunkClear(
  axis: 'horizontal' | 'vertical',
  initial: number,
  spanStart: number,
  spanEnd: number,
  obstacles: ObstacleRect[],
): number {
  let coord = initial
  for (const ob of obstacles) {
    if (axis === 'horizontal') {
      if (coord >= ob.y && coord <= ob.y + ob.height && spanEnd > ob.x && spanStart < ob.x + ob.width) {
        coord = ob.y + ob.height + TRUNK_OBSTACLE_MARGIN
      }
    } else if (coord >= ob.x && coord <= ob.x + ob.width && spanEnd > ob.y && spanStart < ob.y + ob.height) {
      coord = ob.x + ob.width + TRUNK_OBSTACLE_MARGIN
    }
  }
  return coord
}

function tapToHorizontalTrunk(pin: SchematicLayoutPin, trunkY: number): { points: SchematicLayoutPoint[]; tap: SchematicLayoutPoint } {
  if (isSideVertical(pin.side)) {
    const tap = { x: pin.x, y: trunkY }
    return { points: [{ x: pin.x, y: pin.y }, tap], tap }
  }
  const dx = pin.side === 'left' ? -STUB_LENGTH : STUB_LENGTH
  const intermediate = { x: pin.x + dx, y: pin.y }
  const tap = { x: pin.x + dx, y: trunkY }
  return { points: [{ x: pin.x, y: pin.y }, intermediate, tap], tap }
}

function tapToVerticalTrunk(pin: SchematicLayoutPin, trunkX: number): { points: SchematicLayoutPoint[]; tap: SchematicLayoutPoint } {
  if (!isSideVertical(pin.side)) {
    const tap = { x: trunkX, y: pin.y }
    return { points: [{ x: pin.x, y: pin.y }, tap], tap }
  }
  const dy = pin.side === 'top' ? -STUB_LENGTH : STUB_LENGTH
  const intermediate = { x: pin.x, y: pin.y + dy }
  const tap = { x: trunkX, y: pin.y + dy }
  return { points: [{ x: pin.x, y: pin.y }, intermediate, tap], tap }
}

function routeMultiPin(
  netId: string,
  pins: SchematicLayoutPin[],
  skNet: SkeletonNet,
  obstacles: ObstacleRect[],
): SchematicLayoutNetSegment[] {
  const plan = planTrunk(pins, skNet, obstacles)
  const segments: SchematicLayoutNetSegment[] = []
  const taps: SchematicLayoutPoint[] = []
  pins.forEach((pin, index) => {
    const hit = plan.axis === 'horizontal' ? tapToHorizontalTrunk(pin, plan.coord) : tapToVerticalTrunk(pin, plan.coord)
    taps.push(hit.tap)
    segments.push({
      key: `${netId}:tap:${index}`,
      kind: 'route',
      axis: resolveAxis(hit.points),
      points: hit.points,
    })
  })
  if (plan.axis === 'horizontal') {
    const txs = taps.map((p) => p.x)
    const start = { x: Math.min(...txs), y: plan.coord }
    const end = { x: Math.max(...txs), y: plan.coord }
    if (start.x !== end.x) {
      segments.push({ key: `${netId}:trunk`, kind: 'route', axis: 'horizontal', points: [start, end] })
    }
  } else {
    const tys = taps.map((p) => p.y)
    const start = { x: plan.coord, y: Math.min(...tys) }
    const end = { x: plan.coord, y: Math.max(...tys) }
    if (start.y !== end.y) {
      segments.push({ key: `${netId}:trunk`, kind: 'route', axis: 'vertical', points: [start, end] })
    }
  }
  return segments
}

export function routeSchematicNets(
  semantic: SchematicSemanticModel,
  skeleton: SchematicSkeleton,
  pinsByNetId: Map<string, SchematicLayoutPin[]>,
  components: SchematicLayoutComponent[],
): Map<string, SchematicLayoutNetSegment[]> {
  const obstacles = buildObstacles(components)
  const result = new Map<string, SchematicLayoutNetSegment[]>()
  for (const semanticNet of semantic.nets) {
    const netId = semanticNet.net.id
    const skNet = skeleton.netsById.get(netId)
    if (!skNet) continue
    const pins = pinsByNetId.get(netId) ?? []
    if (skNet.role === 'dangling') {
      if (pins.length === 1) {
        const points = buildStubPoints(pins[0])
        result.set(netId, [{
          key: `${netId}:stub`,
          kind: 'stub',
          axis: resolveAxis(points),
          points,
        }])
      }
      continue
    }
    if (pins.length < 2) continue
    if (pins.length === 2) {
      const points = route2Pin(pins[0], pins[1])
      result.set(netId, [{
        key: `${netId}:direct`,
        kind: 'route',
        axis: resolveAxis(points),
        points,
      }])
      continue
    }
    const segments = routeMultiPin(netId, pins, skNet, obstacles)
    if (segments.length > 0) {
      result.set(netId, segments)
    }
  }
  return result
}
