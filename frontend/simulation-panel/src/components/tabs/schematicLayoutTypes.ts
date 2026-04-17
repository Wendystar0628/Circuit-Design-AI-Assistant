import type { SchematicComponentState, SchematicNetState, SchematicPinState } from '../../types/state'

export type SchematicPinSide = 'left' | 'right' | 'top' | 'bottom'

export type SchematicLayoutOrientation = 'right' | 'left' | 'up' | 'down'

export type SchematicLayoutSegmentKind = 'route' | 'stub'

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

export interface SchematicLayoutComponent {
  component: SchematicComponentState
  orientation: SchematicLayoutOrientation
  bounds: SchematicLayoutRect
  symbolBounds: SchematicLayoutRect
  pins: SchematicLayoutPin[]
  nameLabel: SchematicLayoutLabel | null
  valueLabel: SchematicLayoutLabel | null
}

export interface SchematicLayoutNetSegment {
  key: string
  kind: SchematicLayoutSegmentKind
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
