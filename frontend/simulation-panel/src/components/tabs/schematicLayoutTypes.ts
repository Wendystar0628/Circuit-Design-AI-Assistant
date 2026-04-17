import type { SchematicComponentState, SchematicNetState, SchematicPinState } from '../../types/state'

export type SchematicPinSide = 'left' | 'right' | 'top' | 'bottom'

export type SchematicLayoutSegmentAxis = 'horizontal' | 'vertical' | 'mixed'

export interface SchematicLayoutPoint {
  x: number
  y: number
}

export interface SchematicLayoutRect {
  x: number
  y: number
  width: number
  height: number
}

export interface SchematicLayoutBounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export interface SchematicCanvasViewState {
  scale: number
  offsetX: number
  offsetY: number
}

export interface SchematicLayoutLabel {
  text: string
  x: number
  y: number
  textAnchor: 'start' | 'middle' | 'end'
}

/**
 * Virtual stub symbol anchored to a pin. Used when a net should terminate
 * locally at the pin with a GND / VCC / VEE glyph instead of running a long
 * wire back to a shared node label. The stub carries everything the renderer
 * needs (glyph kind, tip position along the pin's outward direction, display
 * label) so the layout layer owns placement while the render layer owns
 * pure drawing.
 */
export type SchematicLayoutPinStubKind = 'ground' | 'power'

export interface SchematicLayoutPinStub {
  kind: SchematicLayoutPinStubKind
  /** Net name to display next to the glyph (e.g. "VCC", "VEE"). Empty for GND. */
  label: string
  /** Direction the glyph extends from the pin anchor. Mirrors `pin.side`. */
  side: SchematicPinSide
  /** Anchor point on the pin itself; the glyph is drawn out from here. */
  x: number
  y: number
  /** How far the glyph extends away from the pin along `side`. */
  length: number
}

export interface SchematicLayoutPin {
  id: string
  componentId: string
  pin: SchematicPinState
  side: SchematicPinSide
  x: number
  y: number
  /** Present when this pin is terminated by a local rail/ground glyph. */
  stub: SchematicLayoutPinStub | null
}

/**
 * Per-component rotation applied by the global "rotate-to-horizontal" pass.
 *
 * This is NOT a per-component layout degree of freedom that the placer
 * chooses — it is strictly a uniform flag that is either `0` for every
 * component or `90` (clockwise) for every component, depending on whether
 * the finished drawing was too tall for the canvas and therefore got
 * rotated as a whole. Keeping it on each component (rather than on the
 * `SchematicLayoutResult`) lets the renderer apply the matching symbol
 * transform locally without needing to pipe a separate rotation flag
 * through every render site.
 */
export type SchematicLayoutComponentRotation = 0 | 90

export interface SchematicLayoutComponent {
  component: SchematicComponentState
  rotation: SchematicLayoutComponentRotation
  bounds: SchematicLayoutRect
  symbolBounds: SchematicLayoutRect
  pins: SchematicLayoutPin[]
  nameLabel: SchematicLayoutLabel | null
  valueLabel: SchematicLayoutLabel | null
}

export interface SchematicLayoutNetSegment {
  key: string
  axis: SchematicLayoutSegmentAxis
  points: SchematicLayoutPoint[]
}

export interface SchematicLayoutNet {
  net: SchematicNetState
  segments: SchematicLayoutNetSegment[]
  label: SchematicLayoutLabel | null
}

export interface SchematicLayoutGroup {
  id: string
  label: string
  depth: number
  bounds: SchematicLayoutRect
}

export interface SchematicLayoutResult {
  requestKey: string
  documentId: string
  revision: string
  components: SchematicLayoutComponent[]
  nets: SchematicLayoutNet[]
  groups: SchematicLayoutGroup[]
  bounds: SchematicLayoutBounds | null
}
