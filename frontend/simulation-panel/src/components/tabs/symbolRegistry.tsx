import type { ReactNode } from 'react'

import type { SchematicComponentState, SchematicPinState } from '../../types/state'
import type {
  SchematicLayoutPinStub,
  SchematicPinSide,
} from './schematicLayoutTypes'

export type { SchematicPinSide } from './schematicLayoutTypes'

export interface SchematicSymbolAnchor {
  x: number
  y: number
  side: SchematicPinSide
}

export interface SchematicSymbolAppearance {
  stroke: string
  fill: string
  accent: string
  text: string
  pinFill: string
  readonly: boolean
}

export interface RenderSchematicSymbolProps {
  component: SchematicComponentState
  width: number
  height: number
  appearance: SchematicSymbolAppearance
}

export interface SchematicSymbolDimensions {
  width: number
  height: number
}

/**
 * Symbol definitions expose their outer bounding-box size as a function of
 * the component rather than as a constant. Most symbols (op-amp, BJT, MOS,
 * source, etc.) still return fixed numbers — the dynamic form exists so
 * that two-port passives (R / C / L / D) can flip between a horizontal
 * 108×60 footprint and a vertical 60×108 footprint depending on whether
 * they terminate on a power / ground rail. This matters because when a
 * passive has one terminal on a rail, forcing it horizontal pushes the
 * rail stub out of a left/right pin and then the router has no choice but
 * to U-turn that stub 180° up to the top / bottom rail trunk. Letting the
 * passive be vertical in that case places the stub directly on the
 * top / bottom face, which the router can connect with a straight short
 * segment.
 */
export interface SchematicSymbolDefinition {
  getDimensions(component: SchematicComponentState): SchematicSymbolDimensions
  getPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor
  render(props: RenderSchematicSymbolProps): ReactNode
}

const PASSIVE_WIDTH = 108
const PASSIVE_HEIGHT = 60
const BLOCK_WIDTH = 132
const BLOCK_HEIGHT = 82
const SOURCE_SIZE = 76
const TRIANGLE_WIDTH = 110
const TRIANGLE_HEIGHT = 82
const TRANSISTOR_WIDTH = 94
const TRANSISTOR_HEIGHT = 90

function isSide(value: string): value is SchematicPinSide {
  return value === 'left' || value === 'right' || value === 'top' || value === 'bottom'
}

export function isSchematicComponentReadonly(component: SchematicComponentState): boolean {
  if (!component.editable_fields.length) {
    return true
  }
  return component.editable_fields.every((field) => !field.editable)
}

const schematicComponentTypeLabels: Record<string, string> = {
  r: '电阻',
  resistor: '电阻',
  c: '电容',
  capacitor: '电容',
  l: '电感',
  inductor: '电感',
  d: '二极管',
  diode: '二极管',
  v: '电压源',
  voltage_source: '电压源',
  i: '电流源',
  current_source: '电流源',
  gnd: '接地',
  ground: '接地',
  x: '子电路',
  subckt: '子电路',
  subckt_block: '子电路',
  controlled_source: '受控源',
  e: '受控源',
  f: '受控源',
  g: '受控源',
  h: '受控源',
  u: '运算放大器',
  opamp: '运算放大器',
  q: '三极管',
  bjt: '三极管',
  m: 'MOS 管',
  mos: 'MOS 管',
  j: '结型场效应管',
  jfet: '结型场效应管',
  unknown: '未知元件',
}

function normalizeSchematicComponentTypeKey(value: string): string {
  return value.trim().toLowerCase()
}

export function getSchematicComponentTypeLabel(component: SchematicComponentState): string {
  const candidates = [component.symbol_kind, component.kind, component.display_name].filter((value) => Boolean(value))
  for (const candidate of candidates) {
    const label = schematicComponentTypeLabels[normalizeSchematicComponentTypeKey(candidate)]
    if (label) {
      return label
    }
  }
  return component.display_name || component.kind || component.symbol_kind || '--'
}

function renderLeadLine(x1: number, y1: number, x2: number, y2: number, stroke: string): ReactNode {
  return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke} strokeWidth={2.2} strokeLinecap="round" />
}

function resolvePinSide(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicPinSide {
  const hintedSide = component.port_side_hints[pin.name]
  if (isSide(hintedSide)) {
    return hintedSide
  }
  if (pin.role === 'ground') {
    return 'bottom'
  }
  if (pin.role === 'power') {
    return 'top'
  }
  if (pin.role === 'output') {
    return 'right'
  }
  if (pin.role === 'input') {
    return 'left'
  }
  if (component.pins.length <= 1) {
    return 'top'
  }
  if (component.pins.length === 2) {
    return index === 0 ? 'left' : 'right'
  }
  return index % 2 === 0 ? 'left' : 'right'
}

function resolveSideOrder(component: SchematicComponentState, side: SchematicPinSide, index: number): { order: number; total: number } {
  const sameSideIndices = component.pins
    .map((pin, pinIndex) => ({ pinIndex, side: resolvePinSide(component, pin, pinIndex) }))
    .filter((item) => item.side === side)
    .map((item) => item.pinIndex)
  return {
    order: Math.max(0, sameSideIndices.indexOf(index)),
    total: Math.max(1, sameSideIndices.length),
  }
}

function distributeAlongSide(side: SchematicPinSide, order: number, total: number, width: number, height: number): SchematicSymbolAnchor {
  if (side === 'left') {
    return { x: 0, y: height * (order + 1) / (total + 1), side }
  }
  if (side === 'right') {
    return { x: width, y: height * (order + 1) / (total + 1), side }
  }
  if (side === 'top') {
    return { x: width * (order + 1) / (total + 1), y: 0, side }
  }
  return { x: width * (order + 1) / (total + 1), y: height, side }
}

function resolveRectPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number, width: number, height: number): SchematicSymbolAnchor {
  const side = resolvePinSide(component, pin, index)
  const placement = resolveSideOrder(component, side, index)
  return distributeAlongSide(side, placement.order, placement.total, width, height)
}

/**
 * A two-port passive is drawn vertically (60×108) whenever at least one
 * of its terminals is explicitly hinted toward a `top` / `bottom` side
 * by the normalizer — this happens when that terminal lands on a power
 * or ground net, because such a terminal must face the rail trunk above
 * or below the main band. All other passives stay horizontal (108×60)
 * so they read naturally along a left-to-right signal chain.
 */
function isPassiveVertical(component: SchematicComponentState): boolean {
  if (component.pins.length !== 2) return false
  for (const pin of component.pins) {
    const hint = component.port_side_hints[pin.name]
    if (hint === 'top' || hint === 'bottom') {
      return true
    }
  }
  return false
}

function getPassiveDimensions(component: SchematicComponentState): SchematicSymbolDimensions {
  if (isPassiveVertical(component)) {
    return { width: PASSIVE_HEIGHT, height: PASSIVE_WIDTH }
  }
  return { width: PASSIVE_WIDTH, height: PASSIVE_HEIGHT }
}

function resolvePassivePinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const { width, height } = getPassiveDimensions(component)
  if (component.pins.length <= 1) {
    return { x: width / 2, y: 0, side: 'top' }
  }
  // Two-terminal passives always sit on opposite faces: a left/right pair
  // for horizontal components, a top/bottom pair for vertical ones. The
  // general `resolveRectPinAnchor` — which reads `port_side_hints` for
  // each pin and otherwise falls back to index-based left/right — produces
  // exactly that pattern once the normalizer has set the hints.
  return resolveRectPinAnchor(component, pin, index, width, height)
}

/**
 * Body of a passive symbol drawn in its native horizontal orientation
 * (`width` > `height`). Every individual passive reuses
 * `renderPassiveBody` to adapt to a vertical bounding box by rotating the
 * whole body 90° in a single place, so each symbol author only describes
 * the horizontal silhouette.
 */
function renderPassiveBody(
  width: number,
  height: number,
  draw: (w: number, h: number) => ReactNode,
): ReactNode {
  if (height > width) {
    // Vertical layout: draw the horizontal silhouette on a swapped canvas
    // of size (height × width), then rotate it 90° clockwise about the
    // origin and slide right by `width` so it lands back inside the
    // vertical bounding box (0..width, 0..height).
    return <g transform={`translate(${width} 0) rotate(90)`}>{draw(height, width)}</g>
  }
  return draw(width, height)
}

function renderResistor({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return renderPassiveBody(width, height, (w, h) => {
    const y = h / 2
    return (
      <g>
        {renderLeadLine(0, y, 18, y, appearance.stroke)}
        <polyline
          points={`18,${y} 28,${y - 10} 38,${y + 10} 48,${y - 10} 58,${y + 10} 68,${y - 10} 78,${y + 10} 90,${y}`}
          fill="none"
          stroke={appearance.stroke}
          strokeWidth={2.2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {renderLeadLine(90, y, w, y, appearance.stroke)}
      </g>
    )
  })
}

function renderCapacitor({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return renderPassiveBody(width, height, (w, h) => {
    const y = h / 2
    return (
      <g>
        {renderLeadLine(0, y, 34, y, appearance.stroke)}
        <line x1={38} y1={12} x2={38} y2={h - 12} stroke={appearance.stroke} strokeWidth={2.2} />
        <line x1={70} y1={12} x2={70} y2={h - 12} stroke={appearance.stroke} strokeWidth={2.2} />
        {renderLeadLine(74, y, w, y, appearance.stroke)}
      </g>
    )
  })
}

function renderInductor({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return renderPassiveBody(width, height, (w, h) => {
    const y = h / 2
    return (
      <g>
        {renderLeadLine(0, y, 20, y, appearance.stroke)}
        <path
          d={`M20 ${y} C26 ${y - 15}, 34 ${y - 15}, 40 ${y} C46 ${y - 15}, 54 ${y - 15}, 60 ${y} C66 ${y - 15}, 74 ${y - 15}, 80 ${y} C86 ${y - 15}, 94 ${y - 15}, 100 ${y}`}
          fill="none"
          stroke={appearance.stroke}
          strokeWidth={2.2}
          strokeLinecap="round"
        />
        {renderLeadLine(100, y, w, y, appearance.stroke)}
      </g>
    )
  })
}

function renderDiode({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return renderPassiveBody(width, height, (w, h) => {
    const y = h / 2
    return (
      <g>
        {renderLeadLine(0, y, 24, y, appearance.stroke)}
        <polygon points={`24,12 24,${h - 12} 66,${y}`} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
        <line x1={72} y1={10} x2={72} y2={h - 10} stroke={appearance.stroke} strokeWidth={2.2} />
        {renderLeadLine(72, y, w, y, appearance.stroke)}
      </g>
    )
  })
}

function renderVoltageSource({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const center = SOURCE_SIZE / 2
  return (
    <g>
      {renderLeadLine(center, 0, center, 14, appearance.stroke)}
      <circle cx={center} cy={center} r={24} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center - 7} y1={center - 8} x2={center + 7} y2={center - 8} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={center} y1={center - 14} x2={center} y2={center - 2} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={center - 7} y1={center + 10} x2={center + 7} y2={center + 10} stroke={appearance.stroke} strokeWidth={2} />
      {renderLeadLine(center, SOURCE_SIZE - 14, center, SOURCE_SIZE, appearance.stroke)}
    </g>
  )
}

function renderCurrentSource({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const center = SOURCE_SIZE / 2
  return (
    <g>
      {renderLeadLine(center, 0, center, 14, appearance.stroke)}
      <circle cx={center} cy={center} r={24} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center} y1={center + 12} x2={center} y2={center - 8} stroke={appearance.stroke} strokeWidth={2} />
      <polyline
        points={`${center - 6},${center - 2} ${center},${center - 10} ${center + 6},${center - 2}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {renderLeadLine(center, SOURCE_SIZE - 14, center, SOURCE_SIZE, appearance.stroke)}
    </g>
  )
}

function renderGround({ appearance }: RenderSchematicSymbolProps): ReactNode {
  const center = SOURCE_SIZE / 2
  return (
    <g>
      {renderLeadLine(center, 0, center, 22, appearance.stroke)}
      <line x1={center - 16} y1={26} x2={center + 16} y2={26} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center - 10} y1={34} x2={center + 10} y2={34} stroke={appearance.stroke} strokeWidth={2.2} />
      <line x1={center - 4} y1={42} x2={center + 4} y2={42} stroke={appearance.stroke} strokeWidth={2.2} />
    </g>
  )
}

function renderBlock({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return <rect x={10} y={10} width={width - 20} height={height - 20} rx={12} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
}

function renderControlledSource({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  const centerX = width / 2
  const centerY = height / 2
  return (
    <g>
      <polygon
        points={`${centerX},8 ${width - 8},${centerY} ${centerX},${height - 8} 8,${centerY}`}
        fill={appearance.fill}
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
    </g>
  )
}

function renderOpamp({ appearance }: RenderSchematicSymbolProps): ReactNode {
  return (
    <g>
      <polygon
        points={`14,8 ${TRIANGLE_WIDTH - 12},${TRIANGLE_HEIGHT / 2} 14,${TRIANGLE_HEIGHT - 8}`}
        fill={appearance.fill}
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
      <line x1={22} y1={TRIANGLE_HEIGHT * 0.34} x2={34} y2={TRIANGLE_HEIGHT * 0.34} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={28} y1={TRIANGLE_HEIGHT * 0.28} x2={28} y2={TRIANGLE_HEIGHT * 0.4} stroke={appearance.stroke} strokeWidth={2} />
      <line x1={22} y1={TRIANGLE_HEIGHT * 0.66} x2={34} y2={TRIANGLE_HEIGHT * 0.66} stroke={appearance.stroke} strokeWidth={2} />
    </g>
  )
}

/**
 * Resolve a BJT pin to its canonical electrode role. The parser tags
 * pins from SPICE `Q` cards with `collector` / `base` / `emitter`, and
 * we trust those tags first; otherwise we fall back to the SPICE `Q`
 * positional order (C B E) so stubbed netlists without role hints
 * still land on the correct electrode.
 */
function canonicalBjtRole(role: string, index: number): 'collector' | 'base' | 'emitter' {
  if (role === 'collector' || role === 'base' || role === 'emitter') return role
  if (index === 1) return 'base'
  if (index === 2) return 'emitter'
  return 'collector'
}

/**
 * Resolve a FET pin (MOSFET or JFET) to its canonical electrode role.
 * Both SPICE `M` and `J` cards share the `drain gate source` ordering
 * for the first three nodes, and the parser tags the rendering-layer
 * pins with matching `drain` / `gate` / `source` role strings (the
 * MOS body pin has already been stripped by `hideMosBulkPin`). We
 * trust those tags first and fall back to positional order only for
 * stubbed netlists that arrive without role hints.
 */
function canonicalFetRole(role: string, index: number): 'drain' | 'gate' | 'source' {
  if (role === 'drain' || role === 'gate' || role === 'source') return role
  if (index === 1) return 'gate'
  if (index === 2) return 'source'
  return 'drain'
}

/**
 * Canonical MOS variant tag supplied by the backend. Parser fills this
 * from the `.model` lookup (`NMOS` / `PMOS`); the fallback `"mos"` only
 * appears when no matching `.model` card exists, in which case we
 * render the generic (NMOS-style) silhouette.
 */
type MosChannelVariant = 'nmos' | 'pmos'

function resolveMosVariant(component: SchematicComponentState): MosChannelVariant {
  return component.symbol_variant === 'pmos' ? 'pmos' : 'nmos'
}

type BjtChannelVariant = 'npn' | 'pnp'

function resolveBjtVariant(component: SchematicComponentState): BjtChannelVariant {
  return component.symbol_variant === 'pnp' ? 'pnp' : 'npn'
}

/**
 * JFET channel variant tag supplied by the backend parser from the
 * `.model` lookup (`NJF` → `'njf'` / `PJF` → `'pjf'`). The only visual
 * difference between the two is the direction of the gate-to-channel
 * arrow; everything else in the symbol is identical. When no `.model`
 * card resolves the referenced model name the parser emits the
 * neutral sentinel `'jfet'`, which we normalise to `'njf'` here since
 * the NJF silhouette is the conventional default.
 */
type JfetChannelVariant = 'njf' | 'pjf'

function resolveJfetVariant(component: SchematicComponentState): JfetChannelVariant {
  return component.symbol_variant === 'pjf' ? 'pjf' : 'njf'
}

// --- BJT symbol geometry (single source of truth) ----------------------
// The pin anchors returned by `resolveBjtPinAnchor` coincide exactly
// with the outer ends of the electrode leads drawn by `renderBjt`, so
// every pin connects to its electrode with a single straight stroke
// and no L-shaped jumper compensation is ever required.
const BJT_CX = TRANSISTOR_WIDTH * 0.56
const BJT_CY = TRANSISTOR_HEIGHT / 2
const BJT_RADIUS = 22
const BJT_BASE_BAR_X = BJT_CX - 10
const BJT_BASE_INNER_X = BJT_CX - BJT_RADIUS
const BJT_ELECTRODE_X = BJT_CX + 14
const BJT_COLLECTOR_Y = BJT_CY - 17
const BJT_EMITTER_Y = BJT_CY + 17
const BJT_EMITTER_SLANT_START_Y = BJT_CY + 8

/**
 * Three-vertex solid-filled emitter arrow. For NPN the tip sits at the
 * emitter electrode point (conventional current flowing out of the
 * emitter); for PNP the tip sits near the base-bar end of the slant
 * (current flowing into the emitter). The triangle is oriented
 * perpendicular to the slant so it reads as a consistent arrowhead
 * regardless of the slant angle.
 */
function bjtEmitterArrowPoints(variant: BjtChannelVariant): string {
  const slantStartX = BJT_BASE_BAR_X
  const slantStartY = BJT_EMITTER_SLANT_START_Y
  const slantEndX = BJT_ELECTRODE_X
  const slantEndY = BJT_EMITTER_Y
  const dx = slantEndX - slantStartX
  const dy = slantEndY - slantStartY
  const len = Math.sqrt(dx * dx + dy * dy) || 1
  const ux = dx / len
  const uy = dy / len
  const perpX = -uy
  const perpY = ux
  const arrowLength = 10
  const arrowHalfWidth = 4
  const tipX = variant === 'npn' ? slantEndX : slantStartX + ux * 4
  const tipY = variant === 'npn' ? slantEndY : slantStartY + uy * 4
  const backDirection = variant === 'npn' ? -1 : 1
  const baseCenterX = tipX + backDirection * ux * arrowLength
  const baseCenterY = tipY + backDirection * uy * arrowLength
  const wing1X = baseCenterX + perpX * arrowHalfWidth
  const wing1Y = baseCenterY + perpY * arrowHalfWidth
  const wing2X = baseCenterX - perpX * arrowHalfWidth
  const wing2Y = baseCenterY - perpY * arrowHalfWidth
  return `${tipX},${tipY} ${wing1X},${wing1Y} ${wing2X},${wing2Y}`
}

function renderBjt({ component, appearance }: RenderSchematicSymbolProps): ReactNode {
  // Textbook BJT: a circle envelope, a vertical base bar inside the
  // circle on its left, and two internal slanted leads that run from
  // the base bar to the collector / emitter electrode points on the
  // right half of the circle. Each electrode extends out to its pin
  // anchor on the outer bounding box with a single straight segment
  // so the anchor *is* the stroke endpoint — there is never any
  // L-shaped jumper. NPN vs PNP is carried solely by the emitter
  // arrow's direction.
  const variant = resolveBjtVariant(component)
  const stroke = appearance.stroke
  return (
    <g>
      {/* Base lead: left-edge pin → circle left edge */}
      <line x1={0} y1={BJT_CY} x2={BJT_BASE_INNER_X} y2={BJT_CY} stroke={stroke} strokeWidth={2.2} />
      {/* Collector lead: inner electrode point → right-edge pin */}
      <line x1={BJT_ELECTRODE_X} y1={BJT_COLLECTOR_Y} x2={TRANSISTOR_WIDTH} y2={BJT_COLLECTOR_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Emitter lead: inner electrode point → right-edge pin */}
      <line x1={BJT_ELECTRODE_X} y1={BJT_EMITTER_Y} x2={TRANSISTOR_WIDTH} y2={BJT_EMITTER_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Circle envelope */}
      <circle cx={BJT_CX} cy={BJT_CY} r={BJT_RADIUS} fill={appearance.fill} stroke={stroke} strokeWidth={2.2} />
      {/* Vertical base bar */}
      <line x1={BJT_BASE_BAR_X} y1={BJT_CY - 12} x2={BJT_BASE_BAR_X} y2={BJT_CY + 12} stroke={stroke} strokeWidth={2.4} />
      {/* Internal collector slant: base bar → collector electrode point */}
      <line x1={BJT_BASE_BAR_X} y1={BJT_CY - 8} x2={BJT_ELECTRODE_X} y2={BJT_COLLECTOR_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Internal emitter slant: base bar → emitter electrode point */}
      <line x1={BJT_BASE_BAR_X} y1={BJT_EMITTER_SLANT_START_Y} x2={BJT_ELECTRODE_X} y2={BJT_EMITTER_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Emitter arrow (NPN tip at emitter point, PNP tip near base bar) */}
      <polygon
        points={bjtEmitterArrowPoints(variant)}
        fill={stroke}
        stroke={stroke}
        strokeWidth={1}
        strokeLinejoin="round"
      />
    </g>
  )
}

// --- MOS symbol geometry (single source of truth) ----------------------
// Pin anchors returned by `resolveMosPinAnchor` are the exact outer
// endpoints of the electrode leads drawn by `renderMos`, mirroring the
// same single-stroke design used for BJT and JFET.
const MOS_CHANNEL_X = TRANSISTOR_WIDTH * 0.58
const MOS_GATE_BAR_X = MOS_CHANNEL_X - 12
const MOS_GATE_LEAD_INNER_X = MOS_GATE_BAR_X - 8
const MOS_GATE_Y = TRANSISTOR_HEIGHT / 2
const MOS_TOP_Y = 20
const MOS_BOTTOM_Y = TRANSISTOR_HEIGHT - 20
const MOS_CHANNEL_TOP = 16
const MOS_CHANNEL_BOTTOM = TRANSISTOR_HEIGHT - 16

/**
 * Three-vertex source arrow. The tip points into the channel for both
 * NMOS and PMOS — the variant distinction is carried purely by the
 * vertical position of the source lead (bottom for NMOS, top for PMOS),
 * resolved by `resolveMosPinAnchor`.
 */
function mosSourceArrowPoints(sourceY: number): string {
  const tipX = MOS_CHANNEL_X + 6
  const baseX = MOS_CHANNEL_X + 14
  const halfHeight = 4
  return `${tipX},${sourceY} ${baseX},${sourceY - halfHeight} ${baseX},${sourceY + halfHeight}`
}

function renderMos({ component, appearance }: RenderSchematicSymbolProps): ReactNode {
  // Textbook 3-terminal MOSFET (body pin already stripped upstream by
  // `hideMosBulkPin`). Layout is gate-on-the-left: gate lead from the
  // left edge → insulator gap → gate bar → channel bar on the right
  // → drain / source leads running straight out of the channel to the
  // right-edge pin anchors. NMOS places source at the bottom (pulls
  // current down to GND); PMOS places source at the top (pulls up to
  // VDD). The source arrow always points into the channel; its
  // vertical position alone encodes NMOS vs PMOS.
  const variant = resolveMosVariant(component)
  const stroke = appearance.stroke
  const sourceAtBottom = variant !== 'pmos'
  const drainY = sourceAtBottom ? MOS_TOP_Y : MOS_BOTTOM_Y
  const sourceY = sourceAtBottom ? MOS_BOTTOM_Y : MOS_TOP_Y
  return (
    <g>
      {/* Gate lead: left-edge pin → gate bar (stops before the insulator gap) */}
      <line x1={0} y1={MOS_GATE_Y} x2={MOS_GATE_LEAD_INNER_X} y2={MOS_GATE_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Gate bar (vertical, separated from the channel by the insulator gap) */}
      <line x1={MOS_GATE_BAR_X} y1={MOS_CHANNEL_TOP + 2} x2={MOS_GATE_BAR_X} y2={MOS_CHANNEL_BOTTOM - 2} stroke={stroke} strokeWidth={2.2} />
      {/* Channel bar */}
      <line x1={MOS_CHANNEL_X} y1={MOS_CHANNEL_TOP} x2={MOS_CHANNEL_X} y2={MOS_CHANNEL_BOTTOM} stroke={stroke} strokeWidth={2.2} />
      {/* Drain lead: channel → right-edge drain pin */}
      <line x1={MOS_CHANNEL_X} y1={drainY} x2={TRANSISTOR_WIDTH} y2={drainY} stroke={stroke} strokeWidth={2.2} />
      {/* Source lead: channel → right-edge source pin */}
      <line x1={MOS_CHANNEL_X} y1={sourceY} x2={TRANSISTOR_WIDTH} y2={sourceY} stroke={stroke} strokeWidth={2.2} />
      {/* Source arrow (tip into the channel) */}
      <polygon
        points={mosSourceArrowPoints(sourceY)}
        fill={stroke}
        stroke={stroke}
        strokeWidth={1}
        strokeLinejoin="round"
      />
    </g>
  )
}

// --- JFET symbol geometry (single source of truth) ---------------------
// The pin anchors returned by `resolveJfetPinAnchor` coincide exactly
// with the electrode line endpoints drawn by `renderJfet`, so every
// pin is a single straight stroke from the channel bar to the pin
// without any L-shaped jumper compensation.
const JFET_CHANNEL_X = TRANSISTOR_WIDTH * 0.58
const JFET_GATE_Y = TRANSISTOR_HEIGHT / 2
const JFET_DRAIN_Y = 20
const JFET_SOURCE_Y = TRANSISTOR_HEIGHT - 20
const JFET_CHANNEL_TOP = JFET_DRAIN_Y - 4
const JFET_CHANNEL_BOTTOM = JFET_SOURCE_Y + 4

/**
 * Three-vertex gate-to-channel arrow that encodes NJF vs PJF:
 *
 *   - **NJF** (p-type gate, n-type channel): tip points **into** the
 *     channel (rightward) indicating conventional current flowing
 *     from gate into channel.
 *   - **PJF** (n-type gate, p-type channel): tip points **out toward**
 *     the gate lead (leftward).
 *
 * The arrow sits flush against the channel bar so the junction
 * indication is visible independently of gate-lead length.
 */
function jfetGateArrowPoints(variant: JfetChannelVariant): string {
  const halfHeight = 4
  const baseOffset = 10
  if (variant === 'njf') {
    const tipX = JFET_CHANNEL_X - 2
    const baseX = tipX - baseOffset
    return `${tipX},${JFET_GATE_Y} ${baseX},${JFET_GATE_Y - halfHeight} ${baseX},${JFET_GATE_Y + halfHeight}`
  }
  const baseX = JFET_CHANNEL_X - 2
  const tipX = baseX - baseOffset
  return `${tipX},${JFET_GATE_Y} ${baseX},${JFET_GATE_Y - halfHeight} ${baseX},${JFET_GATE_Y + halfHeight}`
}

function renderJfet({ component, appearance }: RenderSchematicSymbolProps): ReactNode {
  // Textbook 3-terminal JFET: a vertical channel bar with the gate
  // lead entering from the left and making direct (non-capacitive)
  // contact with the channel — the missing insulator gap is what
  // visually distinguishes a JFET from a MOSFET. Drain and source
  // leads run from the channel ends straight out to the right-edge
  // pin anchors. NJF vs PJF is carried exclusively by the arrow on
  // the gate lead.
  const variant = resolveJfetVariant(component)
  const stroke = appearance.stroke
  return (
    <g>
      {/* Gate lead: left-edge pin → channel (no insulator gap) */}
      <line x1={0} y1={JFET_GATE_Y} x2={JFET_CHANNEL_X} y2={JFET_GATE_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Vertical channel bar */}
      <line x1={JFET_CHANNEL_X} y1={JFET_CHANNEL_TOP} x2={JFET_CHANNEL_X} y2={JFET_CHANNEL_BOTTOM} stroke={stroke} strokeWidth={2.2} />
      {/* Drain lead: channel top → right-edge drain pin */}
      <line x1={JFET_CHANNEL_X} y1={JFET_DRAIN_Y} x2={TRANSISTOR_WIDTH} y2={JFET_DRAIN_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Source lead: channel bottom → right-edge source pin */}
      <line x1={JFET_CHANNEL_X} y1={JFET_SOURCE_Y} x2={TRANSISTOR_WIDTH} y2={JFET_SOURCE_Y} stroke={stroke} strokeWidth={2.2} />
      {/* Channel-type arrow on the gate lead */}
      <polygon
        points={jfetGateArrowPoints(variant)}
        fill={stroke}
        stroke={stroke}
        strokeWidth={1}
        strokeLinejoin="round"
      />
    </g>
  )
}

function renderUnknown({ width, height, appearance }: RenderSchematicSymbolProps): ReactNode {
  return (
    <g>
      <rect
        x={10}
        y={10}
        width={width - 20}
        height={height - 20}
        rx={12}
        fill={appearance.fill}
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeDasharray="6 4"
      />
      <text x={width / 2} y={height / 2 + 6} textAnchor="middle" fontSize={24} fontWeight={700} fill={appearance.accent}>
        ?
      </text>
    </g>
  )
}

function resolveOpampPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const sideHint = component.port_side_hints[pin.name]
  if (isSide(sideHint)) {
    const placement = resolveSideOrder(component, sideHint, index)
    return distributeAlongSide(sideHint, placement.order, placement.total, TRIANGLE_WIDTH, TRIANGLE_HEIGHT)
  }
  if (pin.role === 'output' || index === component.pins.length - 1) {
    return { x: TRIANGLE_WIDTH, y: TRIANGLE_HEIGHT / 2, side: 'right' }
  }
  if (index === 0) {
    return { x: 0, y: TRIANGLE_HEIGHT * 0.34, side: 'left' }
  }
  if (index === 1) {
    return { x: 0, y: TRIANGLE_HEIGHT * 0.66, side: 'left' }
  }
  return resolveRectPinAnchor(component, pin, index, TRIANGLE_WIDTH, TRIANGLE_HEIGHT)
}

/**
 * Pin-anchor resolver for BJTs. The SPICE `Q` card orders nodes as
 * `collector base emitter`, so pin[0] is collector (right-top),
 * pin[1] is base (left-center), and pin[2] is emitter (right-bottom).
 * The returned anchors are also the exact endpoints that `renderBjt`
 * draws its electrode leads to, so each pin reaches its electrode
 * with a single straight stroke and no jumper is ever needed.
 * `port_side_hints` is deliberately ignored: the BJT silhouette is
 * topologically fixed (base-on-left, collector/emitter-on-right) and
 * any layout-engine request to move a pin onto another face would
 * only desynchronise the anchor from the drawn lead.
 */
function resolveBjtPinAnchor(_component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const role = canonicalBjtRole(pin.role, index)
  if (role === 'base') return { x: 0, y: BJT_CY, side: 'left' }
  if (role === 'emitter') return { x: TRANSISTOR_WIDTH, y: BJT_EMITTER_Y, side: 'right' }
  return { x: TRANSISTOR_WIDTH, y: BJT_COLLECTOR_Y, side: 'right' }
}

/**
 * Pin-anchor resolver for JFETs. The SPICE `J` card orders nodes as
 * `drain gate source`, so pin[0] is drain (right-top), pin[1] gate
 * (left-center), pin[2] source (right-bottom). The returned anchors
 * are also the exact endpoints that `renderJfet` draws its electrode
 * lines to, so the three pins are connected to the channel by single
 * straight strokes with no jumper. JFETs are electrically symmetric
 * between drain and source and the channel-type distinction rides on
 * the gate arrow, so we deliberately do not mirror D/S between NJF
 * and PJF. We also deliberately ignore `port_side_hints`: the JFET
 * silhouette is fixed (gate-on-left, drain/source-on-right) and any
 * layout-engine request to move a pin onto a different face would
 * only desynchronise the anchor from the drawn electrode line.
 */
function resolveJfetPinAnchor(_component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const role = canonicalFetRole(pin.role, index)
  if (role === 'gate') return { x: 0, y: JFET_GATE_Y, side: 'left' }
  if (role === 'source') return { x: TRANSISTOR_WIDTH, y: JFET_SOURCE_Y, side: 'right' }
  return { x: TRANSISTOR_WIDTH, y: JFET_DRAIN_Y, side: 'right' }
}

/**
 * Pin-anchor resolver for MOSFETs. The SPICE `M` card orders nodes as
 * `drain gate source body`; `body` has already been stripped by
 * `hideMosBulkPin` upstream, so the rendering layer sees pin[0]=drain,
 * pin[1]=gate, pin[2]=source. The returned anchors coincide with the
 * exact endpoints `renderMos` draws its electrode leads to, so each
 * pin lands on the channel (or gate bar) with a single straight
 * stroke and no jumper compensation is ever needed. NMOS places the
 * source at the bottom (current pulls down to GND) and PMOS at the
 * top (current pulls up to VDD), so the drain / source anchor y's
 * are mirrored on the channel-type axis. `port_side_hints` is
 * deliberately ignored: the MOS silhouette is topologically fixed
 * (gate-on-left, D/S-on-right).
 */
function resolveMosPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const role = canonicalFetRole(pin.role, index)
  if (role === 'gate') {
    return { x: 0, y: MOS_GATE_Y, side: 'left' }
  }
  const sourceAtBottom = resolveMosVariant(component) !== 'pmos'
  if (role === 'source') {
    return { x: TRANSISTOR_WIDTH, y: sourceAtBottom ? MOS_BOTTOM_Y : MOS_TOP_Y, side: 'right' }
  }
  return { x: TRANSISTOR_WIDTH, y: sourceAtBottom ? MOS_TOP_Y : MOS_BOTTOM_Y, side: 'right' }
}

const passiveDefinition: SchematicSymbolDefinition = {
  getDimensions(component) {
    return getPassiveDimensions(component)
  },
  getPinAnchor(component, pin, index) {
    return resolvePassivePinAnchor(component, pin, index)
  },
  render: renderResistor,
}

const sourceDimensions: SchematicSymbolDimensions = { width: SOURCE_SIZE, height: SOURCE_SIZE }
const blockDimensions: SchematicSymbolDimensions = { width: BLOCK_WIDTH, height: BLOCK_HEIGHT }
const triangleDimensions: SchematicSymbolDimensions = { width: TRIANGLE_WIDTH, height: TRIANGLE_HEIGHT }
const transistorDimensions: SchematicSymbolDimensions = { width: TRANSISTOR_WIDTH, height: TRANSISTOR_HEIGHT }

const symbolDefinitions: Record<string, SchematicSymbolDefinition> = {
  resistor: {
    ...passiveDefinition,
    render: renderResistor,
  },
  capacitor: {
    ...passiveDefinition,
    render: renderCapacitor,
  },
  inductor: {
    ...passiveDefinition,
    render: renderInductor,
  },
  diode: {
    ...passiveDefinition,
    render: renderDiode,
  },
  voltage_source: {
    getDimensions: () => sourceDimensions,
    getPinAnchor(component, pin, index) {
      if (index === 0) {
        return { x: SOURCE_SIZE / 2, y: 0, side: 'top' }
      }
      if (index === 1) {
        return { x: SOURCE_SIZE / 2, y: SOURCE_SIZE, side: 'bottom' }
      }
      return resolveRectPinAnchor(component, pin, index, SOURCE_SIZE, SOURCE_SIZE)
    },
    render: renderVoltageSource,
  },
  current_source: {
    getDimensions: () => sourceDimensions,
    getPinAnchor(component, pin, index) {
      if (index === 0) {
        return { x: SOURCE_SIZE / 2, y: 0, side: 'top' }
      }
      if (index === 1) {
        return { x: SOURCE_SIZE / 2, y: SOURCE_SIZE, side: 'bottom' }
      }
      return resolveRectPinAnchor(component, pin, index, SOURCE_SIZE, SOURCE_SIZE)
    },
    render: renderCurrentSource,
  },
  ground: {
    getDimensions: () => sourceDimensions,
    getPinAnchor() {
      return { x: SOURCE_SIZE / 2, y: 0, side: 'top' }
    },
    render: renderGround,
  },
  subckt_block: {
    getDimensions: () => blockDimensions,
    getPinAnchor(component, pin, index) {
      return resolveRectPinAnchor(component, pin, index, BLOCK_WIDTH, BLOCK_HEIGHT)
    },
    render: renderBlock,
  },
  controlled_source: {
    getDimensions: () => blockDimensions,
    getPinAnchor(component, pin, index) {
      return resolveRectPinAnchor(component, pin, index, BLOCK_WIDTH, BLOCK_HEIGHT)
    },
    render: renderControlledSource,
  },
  opamp: {
    getDimensions: () => triangleDimensions,
    getPinAnchor(component, pin, index) {
      return resolveOpampPinAnchor(component, pin, index)
    },
    render: renderOpamp,
  },
  bjt: {
    getDimensions: () => transistorDimensions,
    getPinAnchor(component, pin, index) {
      return resolveBjtPinAnchor(component, pin, index)
    },
    render: renderBjt,
  },
  mos: {
    getDimensions: () => transistorDimensions,
    getPinAnchor(component, pin, index) {
      return resolveMosPinAnchor(component, pin, index)
    },
    render: renderMos,
  },
  jfet: {
    getDimensions: () => transistorDimensions,
    getPinAnchor(component, pin, index) {
      return resolveJfetPinAnchor(component, pin, index)
    },
    render: renderJfet,
  },
  unknown: {
    getDimensions: () => blockDimensions,
    getPinAnchor(component, pin, index) {
      return resolveRectPinAnchor(component, pin, index, BLOCK_WIDTH, BLOCK_HEIGHT)
    },
    render: renderUnknown,
  },
}

export function getSchematicSymbolDefinition(kind: string): SchematicSymbolDefinition {
  return symbolDefinitions[kind] ?? symbolDefinitions.unknown
}

// ---------------------------------------------------------------------------
// Pin stub glyphs (GND / VCC / VEE).
//
// Stubs are the industry-standard way to express "this pin connects to a
// shared rail" without drawing a long wire across the canvas. A stub is a
// short line leaving the pin in its outward direction, capped by a small
// symbol (three decreasing bars for GND, a triangle for power) plus an
// optional text label for named rails.
//
// The glyph is a pure geometric function of the stub descriptor (`side`,
// `x`, `y`, `length`, `label`). No placement is decided here — the layout
// layer has already pinned the anchor point in world coordinates.
// ---------------------------------------------------------------------------

export interface SchematicPinStubAppearance {
  stroke: string
  fill: string
  text: string
}

interface StubAxes {
  dx: number
  dy: number
  perpX: number
  perpY: number
}

function resolveStubAxes(side: SchematicPinSide): StubAxes {
  switch (side) {
    case 'top':
      return { dx: 0, dy: -1, perpX: 1, perpY: 0 }
    case 'bottom':
      return { dx: 0, dy: 1, perpX: 1, perpY: 0 }
    case 'left':
      return { dx: -1, dy: 0, perpX: 0, perpY: 1 }
    case 'right':
      return { dx: 1, dy: 0, perpX: 0, perpY: 1 }
  }
}

const GND_BAR_WIDTHS: readonly number[] = [18, 12, 6]
const GND_BAR_SPACING = 3.5
const GND_STROKE_WIDTH = 1.8

function renderGroundStubGlyph(stub: SchematicLayoutPinStub, axes: StubAxes, appearance: SchematicPinStubAppearance): ReactNode {
  const tipX = stub.x + axes.dx * stub.length
  const tipY = stub.y + axes.dy * stub.length
  return (
    <g stroke={appearance.stroke} strokeWidth={GND_STROKE_WIDTH} strokeLinecap="round" fill="none">
      <line x1={stub.x} y1={stub.y} x2={tipX} y2={tipY} />
      {GND_BAR_WIDTHS.map((width, index) => {
        const offsetAlong = index * GND_BAR_SPACING
        const cx = tipX + axes.dx * offsetAlong
        const cy = tipY + axes.dy * offsetAlong
        const halfWidth = width / 2
        return (
          <line
            key={index}
            x1={cx + axes.perpX * halfWidth}
            y1={cy + axes.perpY * halfWidth}
            x2={cx - axes.perpX * halfWidth}
            y2={cy - axes.perpY * halfWidth}
          />
        )
      })}
    </g>
  )
}

const POWER_CAP_SIZE = 8
const POWER_LABEL_OFFSET = 10
const POWER_FONT_SIZE = 12
const POWER_STROKE_WIDTH = 1.8

function powerLabelAnchor(side: SchematicPinSide): 'start' | 'middle' | 'end' {
  if (side === 'left') return 'end'
  if (side === 'right') return 'start'
  return 'middle'
}

function renderPowerStubGlyph(stub: SchematicLayoutPinStub, axes: StubAxes, appearance: SchematicPinStubAppearance): ReactNode {
  const tipX = stub.x + axes.dx * stub.length
  const tipY = stub.y + axes.dy * stub.length
  // Triangle cap points outward along the stub axis.
  const apexX = tipX + axes.dx * POWER_CAP_SIZE
  const apexY = tipY + axes.dy * POWER_CAP_SIZE
  const leftBaseX = tipX + axes.perpX * (POWER_CAP_SIZE / 2)
  const leftBaseY = tipY + axes.perpY * (POWER_CAP_SIZE / 2)
  const rightBaseX = tipX - axes.perpX * (POWER_CAP_SIZE / 2)
  const rightBaseY = tipY - axes.perpY * (POWER_CAP_SIZE / 2)
  const labelX = apexX + axes.dx * POWER_LABEL_OFFSET
  const labelY = apexY + axes.dy * POWER_LABEL_OFFSET
  return (
    <g>
      <line
        x1={stub.x}
        y1={stub.y}
        x2={tipX}
        y2={tipY}
        stroke={appearance.stroke}
        strokeWidth={POWER_STROKE_WIDTH}
        strokeLinecap="round"
      />
      <polygon
        points={`${apexX},${apexY} ${leftBaseX},${leftBaseY} ${rightBaseX},${rightBaseY}`}
        fill={appearance.fill}
        stroke={appearance.stroke}
        strokeWidth={POWER_STROKE_WIDTH}
        strokeLinejoin="round"
      />
      {stub.label ? (
        <text
          x={labelX}
          y={labelY + (axes.dy > 0 ? POWER_FONT_SIZE : 0)}
          textAnchor={powerLabelAnchor(stub.side)}
          fontSize={POWER_FONT_SIZE}
          fontWeight={600}
          fill={appearance.text}
        >
          {stub.label}
        </text>
      ) : null}
    </g>
  )
}

export function renderSchematicPinStub(stub: SchematicLayoutPinStub, appearance: SchematicPinStubAppearance): ReactNode {
  const axes = resolveStubAxes(stub.side)
  if (stub.kind === 'ground') {
    return renderGroundStubGlyph(stub, axes, appearance)
  }
  return renderPowerStubGlyph(stub, axes, appearance)
}
