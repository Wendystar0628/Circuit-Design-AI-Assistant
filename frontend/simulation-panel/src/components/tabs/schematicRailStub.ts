import type {
  SchematicLayoutPin,
  SchematicLayoutRect,
} from './schematicLayoutTypes'

// ============================================================================
// Rail stub geometry (single source of truth)
// ----------------------------------------------------------------------------
// The layout pipeline and the orthogonal connector router both need the
// axis-aligned rectangle occupied by a GND / VCC glyph:
//
//   - schematicLayout.ts uses it to fold the stub area into
//     `SchematicLayoutComponent.bounds` so the final canvas bounds and any
//     bounds-based overlap checks see the glyph.
//   - schematicOrthogonalConnectorRouter.ts uses it to emit a *separate*
//     obstacle per rail stub so wires routed for other nets cannot cross
//     a stub's three-bar glyph or power triangle.
//
// Keeping the length and glyph half-width here — rather than duplicating
// them across files — guarantees the "render size", the "bounds size", and
// the "obstacle size" all stay in sync, which is the invariant that makes
// the stub-aware obstacle model work.
// ============================================================================

/**
 * How far the stub glyph extends from the pin anchor along the pin's
 * outward direction. Matches the `length` written into every
 * `SchematicLayoutPinStub` by `attachRailPinStubs` and consumed by
 * `renderSchematicPinStub` at draw time.
 */
export const RAIL_STUB_LENGTH = 26

/**
 * Half-width of the stub glyph perpendicular to its axis. Sized to cover
 * both the widest ground bar (≈ 14 px across) and the power cap +
 * adjacent label (e.g. "VCC" / "VDD"). A tighter value would let the
 * router skim wires under the label text; a looser value wastes canvas.
 */
export const RAIL_STUB_HALF_WIDTH = 12

/**
 * Axis-aligned rectangle that a rail stub glyph + label occupies in
 * world space. Returns `null` for pins without a stub so call sites can
 * iterate uniformly over every pin without branching on role.
 */
export function computeRailStubBounds(pin: SchematicLayoutPin): SchematicLayoutRect | null {
  if (!pin.stub) return null
  const { x, y, side, length } = pin.stub
  const halfWidth = RAIL_STUB_HALF_WIDTH
  switch (side) {
    case 'top':
      return { x: x - halfWidth, y: y - length, width: halfWidth * 2, height: length }
    case 'bottom':
      return { x: x - halfWidth, y, width: halfWidth * 2, height: length }
    case 'left':
      return { x: x - length, y: y - halfWidth, width: length, height: halfWidth * 2 }
    case 'right':
      return { x, y: y - halfWidth, width: length, height: halfWidth * 2 }
  }
}
