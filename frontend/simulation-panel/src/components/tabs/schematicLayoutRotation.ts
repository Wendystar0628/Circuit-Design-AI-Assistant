import type {
  SchematicLayoutBounds,
  SchematicLayoutComponent,
  SchematicLayoutGroup,
  SchematicLayoutNet,
  SchematicLayoutPin,
  SchematicLayoutPinStub,
  SchematicLayoutPoint,
  SchematicLayoutRect,
  SchematicPinSide,
} from './schematicLayoutTypes'

// ============================================================================
// Global "rotate-to-horizontal" pass.
//
// The ELK-driven placement pipeline always emits a drawing whose signal flow
// runs left-to-right in its own coordinate system. For a circuit whose
// natural signal graph is short and deep (e.g. a single-stage common-emitter
// amplifier: source → coupling cap → base → collector → load), ELK correctly
// produces a tall, narrow diagram. That is faithful to the topology but
// wastes the horizontal canvas we actually have.
//
// This module is a *post-processing* pass: after the whole layout (components,
// pins, stubs, labels, net segments, group bounds) has been finalized, we
// measure the finished bounding box. If it is substantially taller than it
// is wide, we rotate the entire drawing 90° clockwise around its top-left
// corner. Every single coordinate is transformed uniformly; the renderer
// then reads an already-horizontal layout and applies a local symbol
// rotation so that each individual symbol glyph also rotates with the rest
// of the drawing.
//
// What this pass does NOT do:
//   - It never reshuffles components, net topology, label slots, or any
//     other structural decision the upstream pipeline made. Rotation is
//     a rigid whole-drawing operation, so the schematic remains exactly
//     as clear as it was pre-rotation — just in a different orientation.
//   - It never rotates text runs. Labels keep their baseline horizontal so
//     the user can still read "10k", "Vin", "Q1", etc. without tilting
//     their head. Only the symbols, pin positions, stubs, and wire
//     segments move.
// ============================================================================

/**
 * Aspect threshold that decides whether rotation is worth doing. Interpreted
 * as "height must exceed width by at least this factor to trigger rotation".
 * Values between 1.0 and 1.2 are effectively "already-square" layouts that
 * stay put; the 1.2 cutoff keeps jitter away from the decision boundary so
 * two semantically similar circuits do not flip orientation based on a few
 * pixels of label overflow.
 */
const ROTATION_ASPECT_THRESHOLD = 1.2

export function shouldRotateLayoutToHorizontal(bounds: SchematicLayoutBounds | null): boolean {
  if (bounds === null) return false
  const width = bounds.maxX - bounds.minX
  const height = bounds.maxY - bounds.minY
  if (width <= 0 || height <= 0) return false
  return height > width * ROTATION_ASPECT_THRESHOLD
}

// ---------------------------------------------------------------------------
// Primitive CW90 transforms.
//
// Conceptually we rotate the local space `[minX..maxX] × [minY..maxY]` by
// 90° clockwise around the bounding-box origin `(minX, minY)`. With the
// local origin normalized away, the rotation is simply:
//
//     (lx, ly) → (H - ly, lx)
//
// where `H = maxY - minY`. We then re-anchor the result back to the original
// `(minX, minY)` so the post-rotation drawing sits in the same region of
// world space the pre-rotation drawing did, avoiding surprise viewport
// jumps in the canvas `<svg>` viewBox.
// ---------------------------------------------------------------------------

interface Cw90Transform {
  point(p: SchematicLayoutPoint): SchematicLayoutPoint
  rect(r: SchematicLayoutRect): SchematicLayoutRect
}

function buildCw90Transform(bounds: SchematicLayoutBounds): Cw90Transform {
  const dx = bounds.minX
  const dy = bounds.minY
  const maxY = bounds.maxY
  return {
    point(p: SchematicLayoutPoint): SchematicLayoutPoint {
      return {
        x: dx + (maxY - p.y),
        y: dy + (p.x - dx),
      }
    },
    rect(r: SchematicLayoutRect): SchematicLayoutRect {
      return {
        x: dx + (maxY - r.y - r.height),
        y: dy + (r.x - dx),
        width: r.height,
        height: r.width,
      }
    },
  }
}

const SIDE_CW90: Record<SchematicPinSide, SchematicPinSide> = {
  left: 'top',
  top: 'right',
  right: 'bottom',
  bottom: 'left',
}

function rotatePinStub(stub: SchematicLayoutPinStub, transform: Cw90Transform): SchematicLayoutPinStub {
  const rotated = transform.point({ x: stub.x, y: stub.y })
  return {
    kind: stub.kind,
    label: stub.label,
    side: SIDE_CW90[stub.side],
    x: rotated.x,
    y: rotated.y,
    length: stub.length,
  }
}

function rotatePin(pin: SchematicLayoutPin, transform: Cw90Transform): SchematicLayoutPin {
  const rotated = transform.point({ x: pin.x, y: pin.y })
  return {
    id: pin.id,
    componentId: pin.componentId,
    pin: pin.pin,
    side: SIDE_CW90[pin.side],
    x: rotated.x,
    y: rotated.y,
    stub: pin.stub ? rotatePinStub(pin.stub, transform) : null,
  }
}

function rotateComponent(component: SchematicLayoutComponent, transform: Cw90Transform): SchematicLayoutComponent {
  return {
    component: component.component,
    // Every component rotates uniformly; `0 → 90` is the only transition
    // this pass performs (it is never composed with itself).
    rotation: 90,
    bounds: transform.rect(component.bounds),
    symbolBounds: transform.rect(component.symbolBounds),
    pins: component.pins.map((pin) => rotatePin(pin, transform)),
    // Label anchor coordinates rotate with the rest of the drawing, but
    // `text` and `textAnchor` stay untouched so the label continues to
    // render as a horizontal text run (the rotation only moves *where*
    // the text sits, not *how* it reads).
    nameLabel: component.nameLabel
      ? { ...component.nameLabel, ...transform.point({ x: component.nameLabel.x, y: component.nameLabel.y }) }
      : null,
    valueLabel: component.valueLabel
      ? { ...component.valueLabel, ...transform.point({ x: component.valueLabel.x, y: component.valueLabel.y }) }
      : null,
  }
}

function rotateGroup(group: SchematicLayoutGroup, transform: Cw90Transform): SchematicLayoutGroup {
  return {
    id: group.id,
    label: group.label,
    depth: group.depth,
    bounds: transform.rect(group.bounds),
  }
}

function rotateNet(net: SchematicLayoutNet, transform: Cw90Transform): SchematicLayoutNet {
  return {
    net: net.net,
    segments: net.segments.map((segment) => ({
      key: segment.key,
      // Rotated horizontal segments become vertical and vice versa; we
      // recompute the axis from the new points rather than trying to map
      // the old label, to keep one source of truth for downstream axis
      // classification (e.g. the label planner).
      axis:
        segment.axis === 'horizontal'
          ? 'vertical'
          : segment.axis === 'vertical'
            ? 'horizontal'
            : segment.axis,
      points: segment.points.map((point) => transform.point(point)),
    })),
    label: net.label
      ? { ...net.label, ...transform.point({ x: net.label.x, y: net.label.y }) }
      : null,
  }
}

function rotateBounds(bounds: SchematicLayoutBounds, transform: Cw90Transform): SchematicLayoutBounds {
  // Rotating a rectangle swaps its width and height. We compute the two
  // transformed corners explicitly instead of "swap w/h in place" so the
  // bounds anchor stays at (minX, minY), matching the anchor used by the
  // point/rect transforms above.
  const topLeft = transform.point({ x: bounds.minX, y: bounds.minY })
  const bottomRight = transform.point({ x: bounds.maxX, y: bounds.maxY })
  return {
    minX: Math.min(topLeft.x, bottomRight.x),
    minY: Math.min(topLeft.y, bottomRight.y),
    maxX: Math.max(topLeft.x, bottomRight.x),
    maxY: Math.max(topLeft.y, bottomRight.y),
  }
}

export interface RotatableLayout {
  components: SchematicLayoutComponent[]
  nets: SchematicLayoutNet[]
  groups: SchematicLayoutGroup[]
  bounds: SchematicLayoutBounds | null
}

/**
 * Rotate an entire finished layout 90° clockwise in place of returning a new
 * structure, so the caller can keep their existing object identity. Every
 * downstream consumer (renderer, view-fit, label planner output) already
 * reads through the same fields we mutate here.
 */
export function rotateLayoutClockwise90<T extends RotatableLayout>(layout: T): T {
  if (layout.bounds === null) return layout
  const transform = buildCw90Transform(layout.bounds)
  return {
    ...layout,
    components: layout.components.map((component) => rotateComponent(component, transform)),
    groups: layout.groups.map((group) => rotateGroup(group, transform)),
    nets: layout.nets.map((net) => rotateNet(net, transform)),
    bounds: rotateBounds(layout.bounds, transform),
  }
}
