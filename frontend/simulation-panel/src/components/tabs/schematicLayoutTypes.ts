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

export interface SchematicLayoutPin {
  id: string
  componentId: string
  pin: SchematicPinState
  side: SchematicPinSide
  x: number
  y: number
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
