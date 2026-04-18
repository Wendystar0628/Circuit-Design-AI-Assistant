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
 * Build an L-shaped two-segment polyline from a pin's anchor on the
 * symbol's outer bounding box to an electrode terminal point defined in
 * the symbol's interior. Which axis runs first is chosen to match the
 * pin's natural outgoing direction — horizontal pins (left / right) bend
 * vertically after the first horizontal run, and vertical pins
 * (top / bottom) bend horizontally after the first vertical run — so the
 * lead always leaves the pin along the pin's own side without a visible
 * diagonal artifact. Segments that are zero-length collapse into a plain
 * straight line.
 */
function leadPathPoints(
  anchor: SchematicSymbolAnchor,
  terminal: { x: number; y: number },
): string {
  if (anchor.side === 'left' || anchor.side === 'right') {
    return `${anchor.x},${anchor.y} ${terminal.x},${anchor.y} ${terminal.x},${terminal.y}`
  }
  return `${anchor.x},${anchor.y} ${anchor.x},${terminal.y} ${terminal.x},${terminal.y}`
}

/**
 * Classify a BJT pin as base / collector / emitter using the same rule
 * `resolveBjtPinAnchor` uses to position pins: pin role `input` (or the
 * first pin when no role is present) is the base, the next is the
 * collector, and the last is the emitter. Keeping the render and the
 * anchor resolver in lock-step is what guarantees each lead reaches the
 * electrode the pin is semantically wired to.
 */
function classifyBjtPin(pin: SchematicPinState, index: number): 'base' | 'collector' | 'emitter' {
  if (pin.role === 'input' || index === 0) return 'base'
  if (index === 1) return 'collector'
  return 'emitter'
}

function classifyMosPin(pin: SchematicPinState, index: number): 'gate' | 'drain' | 'source' | 'bulk' {
  if (pin.role === 'input' || index === 0) return 'gate'
  if (index === 1) return 'drain'
  if (index === 2) return 'source'
  return 'bulk'
}

function renderBjt({ component, appearance }: RenderSchematicSymbolProps): ReactNode {
  // Textbook NPN layout: a circle envelope, a vertical base bar inside
  // the circle on its left, and two slanted leads going from the ends
  // of the base bar to the upper-right and lower-right of the circle
  // (the collector and emitter electrode terminals). Pin leads are then
  // drawn from each pin's anchor on the bounding box to whichever of
  // the three interior terminals the pin is semantically connected to,
  // so the symbol is always visibly continuous with the terminal dots.
  const cx = TRANSISTOR_WIDTH * 0.56
  const cy = TRANSISTOR_HEIGHT / 2
  const r = 22
  const baseBarX = cx - 10
  const baseTerminal = { x: cx - r, y: cy }
  const collectorTerminal = { x: cx + 14, y: cy - 17 }
  const emitterTerminal = { x: cx + 14, y: cy + 17 }
  const leads = component.pins.map((pin, index) => {
    const anchor = resolveBjtPinAnchor(component, pin, index)
    const role = classifyBjtPin(pin, index)
    const terminal =
      role === 'base' ? baseTerminal : role === 'collector' ? collectorTerminal : emitterTerminal
    return (
      <polyline
        key={`lead-${pin.name}`}
        points={leadPathPoints(anchor, terminal)}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
    )
  })
  return (
    <g>
      {leads}
      <circle cx={cx} cy={cy} r={r} fill={appearance.fill} stroke={appearance.stroke} strokeWidth={2.2} />
      {/* Vertical base bar inside the circle */}
      <line x1={baseBarX} y1={cy - 12} x2={baseBarX} y2={cy + 12} stroke={appearance.stroke} strokeWidth={2.4} />
      {/* Collector slant: from upper end of base bar to upper-right terminal */}
      <line
        x1={baseBarX}
        y1={cy - 8}
        x2={collectorTerminal.x}
        y2={collectorTerminal.y}
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
      {/* Emitter slant: from lower end of base bar to lower-right terminal */}
      <line
        x1={baseBarX}
        y1={cy + 8}
        x2={emitterTerminal.x}
        y2={emitterTerminal.y}
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
      {/* NPN arrow on the emitter slant, tip at the emitter terminal */}
      <polyline
        points={`${cx + 3},${cy + 10} ${emitterTerminal.x},${emitterTerminal.y} ${cx + 2},${cy + 20}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
  )
}

function renderMos({ component, appearance }: RenderSchematicSymbolProps): ReactNode {
  // Textbook enhancement-mode MOSFET layout, rotated so gate enters from
  // the left: horizontal gate lead stub → small insulator gap → vertical
  // gate bar → channel bar to its right → drain stub (upper) and source
  // stub (lower) jutting right out of the channel. Per-pin L-shaped
  // leads connect each pin anchor to its electrode terminal so the
  // terminal dots are never visually detached from the symbol.
  const cy = TRANSISTOR_HEIGHT / 2
  const channelX = TRANSISTOR_WIDTH * 0.58
  const gateBarX = channelX - 12
  const gateLeadInnerX = gateBarX - 8
  const channelTop = 16
  const channelBottom = TRANSISTOR_HEIGHT - 16
  const drainStubY = 20
  const sourceStubY = TRANSISTOR_HEIGHT - 20
  const stubEndX = channelX + 18
  const gateTerminal = { x: 16, y: cy }
  const drainTerminal = { x: stubEndX, y: drainStubY }
  const sourceTerminal = { x: stubEndX, y: sourceStubY }
  const bulkTerminal = { x: channelX, y: cy }
  const leads = component.pins.map((pin, index) => {
    const anchor = resolveMosPinAnchor(component, pin, index)
    const role = classifyMosPin(pin, index)
    const terminal =
      role === 'gate'
        ? gateTerminal
        : role === 'drain'
          ? drainTerminal
          : role === 'source'
            ? sourceTerminal
            : bulkTerminal
    return (
      <polyline
        key={`lead-${pin.name}`}
        points={leadPathPoints(anchor, terminal)}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
      />
    )
  })
  return (
    <g>
      {leads}
      {/* Gate lead inside the symbol (horizontal), stops short of gate bar to leave insulator gap */}
      <line x1={gateTerminal.x} y1={cy} x2={gateLeadInnerX} y2={cy} stroke={appearance.stroke} strokeWidth={2.2} />
      {/* Vertical gate bar (separated from channel by the insulator gap) */}
      <line x1={gateBarX} y1={channelTop + 2} x2={gateBarX} y2={channelBottom - 2} stroke={appearance.stroke} strokeWidth={2.2} />
      {/* Vertical channel bar */}
      <line x1={channelX} y1={channelTop} x2={channelX} y2={channelBottom} stroke={appearance.stroke} strokeWidth={2.2} />
      {/* Drain stub (upper) */}
      <line x1={channelX} y1={drainStubY} x2={stubEndX} y2={drainStubY} stroke={appearance.stroke} strokeWidth={2.2} />
      {/* Source stub (lower) */}
      <line x1={channelX} y1={sourceStubY} x2={stubEndX} y2={sourceStubY} stroke={appearance.stroke} strokeWidth={2.2} />
      {/* Source arrow: open chevron pointing out along the source stub */}
      <polyline
        points={`${channelX + 8},${sourceStubY - 10} ${stubEndX},${sourceStubY} ${channelX + 5},${sourceStubY + 4}`}
        fill="none"
        stroke={appearance.stroke}
        strokeWidth={2.2}
        strokeLinecap="round"
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

function resolveBjtPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const sideHint = component.port_side_hints[pin.name]
  if (isSide(sideHint)) {
    const placement = resolveSideOrder(component, sideHint, index)
    return distributeAlongSide(sideHint, placement.order, placement.total, TRANSISTOR_WIDTH, TRANSISTOR_HEIGHT)
  }
  if (pin.role === 'input' || index === 0) {
    return { x: 0, y: TRANSISTOR_HEIGHT / 2, side: 'left' }
  }
  if (index === 1) {
    return { x: TRANSISTOR_WIDTH, y: 12, side: 'right' }
  }
  return { x: TRANSISTOR_WIDTH, y: TRANSISTOR_HEIGHT - 12, side: 'right' }
}

function resolveMosPinAnchor(component: SchematicComponentState, pin: SchematicPinState, index: number): SchematicSymbolAnchor {
  const sideHint = component.port_side_hints[pin.name]
  if (isSide(sideHint)) {
    const placement = resolveSideOrder(component, sideHint, index)
    return distributeAlongSide(sideHint, placement.order, placement.total, TRANSISTOR_WIDTH, TRANSISTOR_HEIGHT)
  }
  if (pin.role === 'input' || index === 0) {
    return { x: 0, y: TRANSISTOR_HEIGHT / 2, side: 'left' }
  }
  if (index === 1) {
    return { x: TRANSISTOR_WIDTH, y: 12, side: 'right' }
  }
  if (index === 2) {
    return { x: TRANSISTOR_WIDTH, y: TRANSISTOR_HEIGHT - 12, side: 'right' }
  }
  return { x: TRANSISTOR_WIDTH / 2, y: TRANSISTOR_HEIGHT, side: 'bottom' }
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
