import type {
  SchematicLayoutComponent,
  SchematicLayoutPin,
  SchematicLayoutRect,
} from './schematicLayoutTypes'
import type { SchematicNetRoleMap } from './schematicNetRoles'

// ============================================================================
// Post-ELK pin alignment
//
// ELK places each component to balance signal-flow layering and aesthetic
// spacing, but it has no awareness that two terminals of different-width
// components should share an x (or y) coordinate just because the net
// connecting them is "supposed to" look like a clean T-junction. The cost
// function it optimizes over is node-centered; a 108 px horizontal resistor
// and a 60 px vertical resistor will therefore have their *pins* offset by
// as much as ±40 px even when their node centers are perfectly aligned.
//
// The orthogonal router that runs downstream cannot fix this on its own. It
// routes around obstacles between the exact pin coordinates it is handed,
// so whenever two pins on the same net are "almost" aligned it is forced
// to emit a Z-shaped jog: two long parallel segments joined by a short
// perpendicular bridge. That bridge is the visual artifact the user
// reports as "不必要的错位".
//
// This pass closes the loop: after ELK but before the router, we walk each
// signal net, decide which axis the pins naturally want to share (based on
// each pin's `side`), pick an anchor pin, and slide every other component
// by `delta = anchor.coord − pin.coord` so that the pins end up exactly
// co-linear. A conservative clearance check rejects any shift that would
// overlap another component, and a bounded `MAX_SHIFT_DISTANCE` keeps the
// pass from undoing ELK's layering on pins that are far apart for a real
// reason (different layers, different scope groups, etc.).
//
// Outcome:
//   - 2- and 3-pin signal nets route as clean T or straight lines.
//   - Rail nets are untouched (they are rendered as per-pin stubs, not
//     routed as wires, so pin x/y alignment across rail components would
//     serve no visual purpose and risks dislodging rail components from
//     their ELK-allocated trunk cells).
//   - Component shifts are bounded and obstacle-checked, so ELK's overall
//     placement grid is preserved within a ±MAX_SHIFT_DISTANCE tolerance.
//
// The pass is O(nets × pins × components) per iteration, which in practice
// is far below the router's A* + Steiner cost; it never exceeds a handful
// of milliseconds even on large schematics.
// ============================================================================

/**
 * Maximum single-axis displacement a component may receive. Chosen to be
 * roughly half a typical passive's body width — large enough to absorb the
 * 50-60 px pin offset caused by mixing horizontal and vertical passives in
 * the same net, but small enough that we never slide a component across a
 * neighbor's layer.
 */
const MAX_SHIFT_DISTANCE = 60

/**
 * Treat two pins as already-aligned if their shared coordinate differs by
 * less than this. `buildComponentLayouts` snaps every pin to a 4 px grid
 * so a 0.5 px tolerance is ample; it only exists to sidestep floating
 * point round-trip noise from earlier rotation / translation passes.
 */
const ALIGN_TOLERANCE = 0.5

/**
 * Extra padding applied to each component's symbol bounds when testing for
 * post-shift overlaps. This mirrors the router's `OBSTACLE_CLEARANCE` so
 * an aligned shift never places two components closer than the router
 * would allow wires to pass between — otherwise we would "fix" an aligned
 * jog only to create an un-routable pinch point.
 */
const COMPONENT_CLEARANCE = 14

/**
 * Net roles that participate in pin alignment. Rails are drawn with local
 * glyphs (no inter-component wires), and dangling nets have no partner to
 * align with. Every other role is a genuine signal edge and benefits from
 * T-junction / straight-line cleanup.
 */
const ALIGNABLE_ROLES = new Set<string>([
  'signal_trunk',
  'branch',
])

function rectsOverlap(a: SchematicLayoutRect, b: SchematicLayoutRect): boolean {
  return !(
    a.x + a.width <= b.x ||
    b.x + b.width <= a.x ||
    a.y + a.height <= b.y ||
    b.y + b.height <= a.y
  )
}

/**
 * True when shifting `target` by `(dx, dy)` would cause its clearance
 * rectangle to collide with any other component's clearance rectangle.
 * Components other than `target` are treated as immovable — the pass is
 * intentionally conservative: if any single check fails, the whole shift
 * is rejected so we never stack corrective shifts on top of each other
 * and accidentally slide a component across a scope-group boundary.
 */
function canShiftSafely(
  target: SchematicLayoutComponent,
  dx: number,
  dy: number,
  components: SchematicLayoutComponent[],
): boolean {
  // Use `bounds` (which unions symbol + rail-stub glyph rectangles) for
  // both the moving component and its neighbors. Checking against
  // `symbolBounds` alone would let us slide a component into the space
  // occupied by a neighbor's GND / VCC stub, recreating the overlap the
  // stub-aware obstacle model was meant to prevent.
  const shiftedRect: SchematicLayoutRect = {
    x: target.bounds.x + dx - COMPONENT_CLEARANCE,
    y: target.bounds.y + dy - COMPONENT_CLEARANCE,
    width: target.bounds.width + COMPONENT_CLEARANCE * 2,
    height: target.bounds.height + COMPONENT_CLEARANCE * 2,
  }
  for (const other of components) {
    if (other === target) continue
    if (rectsOverlap(shiftedRect, other.bounds)) {
      return false
    }
  }
  return true
}

/**
 * Apply a rigid `(dx, dy)` translation to a component and every piece of
 * geometry it owns. Labels are typically `null` at this stage (they are
 * populated by `applySchematicLabelPlans` downstream), but we guard them
 * anyway so the function is safe to reuse later if the call order ever
 * changes.
 */
function shiftComponent(component: SchematicLayoutComponent, dx: number, dy: number): void {
  component.bounds.x += dx
  component.bounds.y += dy
  component.symbolBounds.x += dx
  component.symbolBounds.y += dy
  for (const pin of component.pins) {
    pin.x += dx
    pin.y += dy
    if (pin.stub) {
      pin.stub.x += dx
      pin.stub.y += dy
    }
  }
  if (component.nameLabel) {
    component.nameLabel.x += dx
    component.nameLabel.y += dy
  }
  if (component.valueLabel) {
    component.valueLabel.x += dx
    component.valueLabel.y += dy
  }
}

/**
 * Given the pins of a net, decide whether an x- or y-alignment would be
 * a meaningful improvement. A majority of `top`/`bottom` pins wants its
 * pin column shared (x-alignment); a majority of `left`/`right` pins
 * wants its pin row shared (y-alignment). Mixed nets where the two
 * categories tie are skipped — there is no obvious axis on which
 * enforcing alignment produces a cleaner schematic, and a wrong guess
 * would shuffle components for no visual gain.
 */
function chooseAlignmentAxis(pins: SchematicLayoutPin[]): 'x' | 'y' | null {
  let verticalPinCount = 0
  let horizontalPinCount = 0
  for (const pin of pins) {
    if (pin.side === 'top' || pin.side === 'bottom') {
      verticalPinCount += 1
    } else if (pin.side === 'left' || pin.side === 'right') {
      horizontalPinCount += 1
    }
  }
  if (verticalPinCount === 0 && horizontalPinCount === 0) return null
  if (verticalPinCount > horizontalPinCount) return 'x'
  if (horizontalPinCount > verticalPinCount) return 'y'
  return null
}

/**
 * Pick the pin whose component will define the target coordinate that
 * every other component's pin is slid onto. Preference order:
 *
 *   1. A pin whose component is already locked by a prior, higher-priority
 *      net. This guarantees we never un-align a decision made earlier.
 *   2. The pin whose coordinate is the median of the candidate axis. Using
 *      the median (rather than the first listed pin) minimizes the total
 *      displacement and, for 3-pin nets, avoids the pathological case of
 *      anchoring on an outlier and shifting two components by 50 px each
 *      when a 25 px shift of a single outlier would have sufficed.
 */
function pickAnchorPin(
  pins: SchematicLayoutPin[],
  axis: 'x' | 'y',
  lockedComponents: Set<string>,
): SchematicLayoutPin {
  const lockedPin = pins.find((pin) => lockedComponents.has(pin.componentId))
  if (lockedPin) return lockedPin
  const sorted = [...pins].sort((left, right) => {
    const leftCoord = axis === 'x' ? left.x : left.y
    const rightCoord = axis === 'x' ? right.x : right.y
    return leftCoord - rightCoord
  })
  return sorted[Math.floor(sorted.length / 2)]
}

export function alignNetPins(
  components: SchematicLayoutComponent[],
  pinsByNetId: Map<string, SchematicLayoutPin[]>,
  netRoles: SchematicNetRoleMap,
): void {
  if (components.length === 0) return

  const lockedComponents = new Set<string>()

  // Process nets from highest-priority (fewest pins but still ≥2) up to
  // 4-pin nets. Nets with more than 4 pins are skipped because a single
  // shared axis is rarely meaningful for fan-out buses and the greedy
  // anchor heuristic starts to pessimize in that regime. Order within
  // the priority tier is by pin count ascending: 2-pin nets first so
  // their unambiguous alignments become anchors for subsequent 3-pin
  // nets, reducing the chance of cascading conflicts.
  const candidates = Array.from(pinsByNetId.entries())
    .filter(([netId, pins]) => {
      if (pins.length < 2 || pins.length > 4) return false
      const role = netRoles.get(netId)
      return role !== undefined && ALIGNABLE_ROLES.has(role)
    })
    .sort(([, aPins], [, bPins]) => aPins.length - bPins.length)

  for (const [, pins] of candidates) {
    const axis = chooseAlignmentAxis(pins)
    if (axis === null) continue
    const anchorPin = pickAnchorPin(pins, axis, lockedComponents)
    const anchorCoord = axis === 'x' ? anchorPin.x : anchorPin.y
    // The anchor's component is considered locked regardless of whether
    // it was already locked before: once a net's target is derived from
    // it, any subsequent net must respect that target to stay consistent.
    lockedComponents.add(anchorPin.componentId)

    for (const pin of pins) {
      if (pin === anchorPin) continue
      if (lockedComponents.has(pin.componentId)) continue
      const currentCoord = axis === 'x' ? pin.x : pin.y
      const delta = anchorCoord - currentCoord
      if (Math.abs(delta) < ALIGN_TOLERANCE) {
        lockedComponents.add(pin.componentId)
        continue
      }
      if (Math.abs(delta) > MAX_SHIFT_DISTANCE) continue
      const target = components.find((c) => c.component.id === pin.componentId)
      if (!target) continue
      const dx = axis === 'x' ? delta : 0
      const dy = axis === 'y' ? delta : 0
      if (!canShiftSafely(target, dx, dy, components)) continue
      shiftComponent(target, dx, dy)
      lockedComponents.add(pin.componentId)
    }
  }
}
